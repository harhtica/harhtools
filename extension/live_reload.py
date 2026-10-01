"""Reload an installed Harhtools update while leaving the current file open.

This is a code watcher, not a remote command bridge. Only this extension's
installed Python package is imported. The watcher must already be registered
in the running Blender session; installing it cannot bootstrap an older session.
"""
import hashlib
import importlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys
import time
import tomllib

import bpy
from bpy.props import BoolProperty, StringProperty

_INTERVAL = 2.0
_DEBOUNCE = 2.0
_ROOT_NAME = __package__
_DIRECTORY = Path(__file__).resolve().parent
_loaded_version = ''
_candidate = None
_candidate_since = 0.0
_failed_version = ''
_requested = False
_reloading = False
_message = ''
_PROPERTIES = ('harhtools_live_reload_enabled', 'harhtools_live_reload_status',
               'harhtools_live_reload_version')
_SKIP_SETTINGS = {'harhtools_shape_assets', 'harhtools_shape_drag',
                  'harhtools_shape_preview_index', *_PROPERTIES[1:]}


def _manifest():
    return tomllib.loads((_DIRECTORY / 'blender_manifest.toml').read_text(encoding='utf8'))


def _set_status(message):
    global _message
    _message = message
    # Blender intentionally exposes _RestrictData during Preferences enable.
    # Register RNA/timers there, then publish UI status on the first idle tick.
    managers = getattr(bpy.data, 'window_managers', ())
    for wm in managers:
        if hasattr(wm, _PROPERTIES[1]):
            wm.harhtools_live_reload_status = message
            wm.harhtools_live_reload_version = _loaded_version
    for wm in managers:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()


def status():
    """Human-readable current status for the settings panel."""
    return _message


def request_reload():
    """Retry the installed version once, using the same idle/stability guards."""
    global _requested, _failed_version, _candidate
    _requested = True
    _failed_version = ''
    _candidate = None
    _set_status('Reload requested; waiting for an idle moment')


def _busy_reason(context=None):
    context = context or bpy.context
    if getattr(context, 'mode', 'OBJECT') != 'OBJECT':
        return 'finish Edit/Sculpt mode'
    wm = getattr(context, 'window_manager', None)
    if wm is None or getattr(wm, 'is_interface_locked', False):
        return 'Blender is busy'
    keys = {'arch_tools_shape_builder', 'harhtools_array_preview',
            'harhtools_shape_library_drag', 'harhtools_shortcut_capture',
            'harhtools_section_drag', 'harhtools_outline_preview', 'harhtools_outline', 'harhtools_arc_preview'}
    for name, module in tuple(sys.modules.items()):
        if module is not None and name.startswith(_ROOT_NAME + '.'):
            for attribute in ('_STATE_KEY', 'STATE_KEY', '_DRAG_KEY', '_CAPTURE_KEY', '_SECTION_DRAG_KEY'):
                key = vars(module).get(attribute)
                if isinstance(key, str):
                    keys.add(key)
    if any(bpy.app.driver_namespace.get(key) for key in keys):
        return 'finish the active Harhtools tool'
    library = sys.modules.get(_ROOT_NAME + '.shape_library')
    if library is not None and getattr(library, '_pending_drag', None) is not None:
        return 'finish shape placement'
    for manager in bpy.data.window_managers:
        for window in manager.windows:
            active = window.view_layer.objects.active
            if active is not None and active.mode != 'OBJECT':
                return 'finish Edit/Sculpt mode'
            if window.screen.is_animation_playing:
                return 'stop animation playback'
            if not hasattr(window, 'modal_operators'):
                return 'restart Blender (this version cannot inspect active tools)'
            if len(window.modal_operators):
                return 'finish the active interaction'
    for job in ('RENDER', 'COMPOSITE', 'OBJECT_BAKE'):
        try:
            if bpy.app.is_job_running(job):
                return 'wait for the running job'
        except (TypeError, ValueError):
            pass  # Job identifiers differ across supported Blender versions.
    return ''


def _source_snapshot():
    """Read an immutable package snapshot; never use stale pyc."""
    digest = hashlib.sha256()
    sources = {}
    paths = sorted(_DIRECTORY.rglob('*.py'))
    for path in paths:
        if '__pycache__' in path.parts:
            continue
        if not path.resolve().is_relative_to(_DIRECTORY):
            raise ValueError('An extension source file points outside its installation')
        relative = path.relative_to(_DIRECTORY)
        source = path.read_bytes()
        digest.update(relative.as_posix().encode('utf8'))
        digest.update(b'\0' + source)
        parts = relative.with_suffix('').parts
        package = parts[-1] == '__init__'
        suffix = parts[:-1] if package else parts
        name = '.'.join((_ROOT_NAME, *suffix))
        sources[name] = (str(path), source, package)
    if _ROOT_NAME not in sources:
        raise ValueError('The installed extension has no __init__.py')
    return digest.hexdigest(), sources


def _compile_snapshot(sources):
    return {name: (filename, compile(source, filename, 'exec'), package)
            for name, (filename, source, package) in sources.items()}


class _SourceLoader(importlib.abc.Loader):
    def __init__(self, code):
        self.code = code

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(self.code, module.__dict__)


class _SnapshotFinder(importlib.abc.MetaPathFinder):
    def __init__(self, sources):
        self.sources = sources

    def find_spec(self, fullname, path=None, target=None):
        item = self.sources.get(fullname)
        if item is None:
            if fullname == _ROOT_NAME or fullname.startswith(_ROOT_NAME + '.'):
                raise ImportError('Module is absent from the verified extension snapshot: ' + fullname)
            return None
        filename, code, package = item
        return importlib.util.spec_from_file_location(
            fullname, filename, loader=_SourceLoader(code),
            submodule_search_locations=[str(Path(filename).parent)] if package else None)


def _rna_snapshot(owner, only_tools=False):
    values = {}
    for prop in owner.bl_rna.properties:
        name = prop.identifier
        if name == 'rna_type' or prop.is_readonly or prop.type == 'COLLECTION':
            continue
        if only_tools and (not name.startswith(('harhtools_', 'arch_shape_builder_'))
                           or name.startswith('harhtools_grip_') or name in _SKIP_SETTINGS):
            continue
        value = getattr(owner, name)
        if prop.type == 'POINTER' and isinstance(value, bpy.types.PropertyGroup):
            values[name] = ('GROUP', _rna_snapshot(value))
        else:
            if getattr(prop, 'is_array', False):
                value = tuple(value)
            elif prop.type == 'ENUM' and getattr(prop, 'is_enum_flag', False):
                value = set(value)
            values[name] = ('VALUE', value)
    return values


def _restore_rna(owner, values):
    # Restore profile presets before their explicitly saved detail controls.
    for name, (kind, value) in sorted(values.items(),key=lambda row:row[0]!='bevel_profile'):
        prop = owner.bl_rna.properties.get(name)
        if prop is None or prop.is_readonly:
            continue
        try:
            if kind == 'GROUP':
                _restore_rna(getattr(owner, name), value)
            else:
                setattr(owner, name, value)
        except (AttributeError, TypeError, ValueError, ReferenceError):
            # A newer release may intentionally remove/change a setting.
            continue


def _snapshot_settings():
    addon = bpy.context.preferences.addons.get(_ROOT_NAME)
    return {
        'windows': [(wm, _rna_snapshot(wm, only_tools=True)) for wm in bpy.data.window_managers],
        'scenes': [(scene, _rna_snapshot(scene.harhtools_shape_placement))
                   for scene in bpy.data.scenes if hasattr(scene, 'harhtools_shape_placement')],
        'preferences': _rna_snapshot(addon.preferences) if addon is not None and addon.preferences is not None else None,
    }


def _restore_settings(snapshot):
    shortcuts = sys.modules.get(_ROOT_NAME + '.shortcuts')
    previous_updating = getattr(shortcuts, '_updating', False)
    if shortcuts is not None:
        shortcuts._updating = True
    try:
        for wm, values in snapshot['windows']:
            _restore_rna(wm, values)
        for scene, values in snapshot['scenes']:
            if hasattr(scene, 'harhtools_shape_placement'):
                _restore_rna(scene.harhtools_shape_placement, values)
        addon = bpy.context.preferences.addons.get(_ROOT_NAME)
        if addon is not None and addon.preferences is not None and snapshot['preferences'] is not None:
            _restore_rna(addon.preferences, snapshot['preferences'])
    finally:
        if shortcuts is not None:
            shortcuts._updating = previous_updating
    if shortcuts is not None:
        shortcuts.apply_toggle(shortcuts.settings())
        shortcuts.refresh_theme(shortcuts.settings(), bpy.context)


def _remove_package_modules():
    for name in list(sys.modules):
        if name == _ROOT_NAME or name.startswith(_ROOT_NAME + '.'):
            del sys.modules[name]


def _restore_parent(module):
    parent_name, _, child = _ROOT_NAME.rpartition('.')
    if parent_name and parent_name in sys.modules:
        setattr(sys.modules[parent_name], child, module)


def _reload_package(version, sources):
    """Swap only this package; keep old module objects for registration rollback."""
    global _reloading, _failed_version, _requested, _loaded_version
    old_modules = {name: module for name, module in sys.modules.items()
                   if name == _ROOT_NAME or name.startswith(_ROOT_NAME + '.')}
    old_root = old_modules[_ROOT_NAME]
    snapshot = _snapshot_settings()
    old_version = _loaded_version
    old_metadata = {key: vars(old_root)[key] for key in
                    ('__addon_enabled__', '__addon_persistent__', '__time__') if key in vars(old_root)}
    finder = _SnapshotFinder(sources)
    new_root = None
    _reloading = True
    try:
        old_root.unregister()
        # A one-time Scripting-tab bootstrap can attach this watcher to an old
        # release whose package unregister() does not yet know about it.
        unregister()
        _remove_package_modules()
        sys.meta_path.insert(0, finder)
        try:
            new_root = importlib.import_module(_ROOT_NAME)
            # Include lazily imported helpers, so future tool invocations cannot
            # pick up an old timestamp-based pyc from the previous release.
            for name in sorted(sources):
                importlib.import_module(name)
            new_root.register()
        finally:
            sys.meta_path.remove(finder)
        for key, value in old_metadata.items():
            setattr(new_root, key, value)
        _restore_settings(snapshot)
        watcher = sys.modules[_ROOT_NAME + '.live_reload']
        watcher._loaded_version = version
        watcher._requested = False
        watcher._failed_version = ''
        watcher._set_status('Updated to ' + version + '; current file kept open')
        print('harhtools: code updated to', version, 'without reloading the current file')
        return True
    except Exception as exc:
        if new_root is not None:
            try:
                new_root.unregister()
            except Exception:
                pass
        _remove_package_modules()
        sys.modules.update(old_modules)
        _restore_parent(old_root)
        try:
            old_root.register()
            if not bpy.app.timers.is_registered(_poll):
                register()
            _restore_settings(snapshot)
            for key, value in old_metadata.items():
                setattr(old_root, key, value)
        except Exception as rollback_error:
            _set_status('Reload failed; restart Blender to restore the extension')
            print('harhtools: reload rollback failed:', rollback_error)
        else:
            _loaded_version = old_version
            _set_status('Update ' + version + ' failed; previous code restored: ' + str(exc))
        _failed_version = version
        _requested = False
        print('harhtools: could not load update', version, ':', exc)
        return False
    finally:
        _reloading = False


def _poll():
    global _candidate, _candidate_since, _failed_version
    if _reloading:
        return _INTERVAL
    wm = getattr(bpy.context, 'window_manager', None)
    if wm is None:
        return _INTERVAL
    if getattr(wm, 'harhtools_live_reload_version', '') != _loaded_version:
        _set_status(_message)
    if not getattr(wm, 'harhtools_live_reload_enabled', True) and not _requested:
        _set_status('Automatic code reload is off')
        return _INTERVAL
    version = ''
    try:
        version = str(_manifest()['version'])
        if version == _failed_version:
            return _INTERVAL
        if version == _loaded_version and not _requested:
            _candidate = None
            return _INTERVAL
        fingerprint, sources = _source_snapshot()
        if str(_manifest()['version']) != version:
            _candidate = None
            return _INTERVAL
        candidate = (version, fingerprint)
        if candidate != _candidate:
            _candidate = candidate
            _candidate_since = time.monotonic()
            _set_status('Update ' + version + ' detected; waiting for files to settle')
            return _INTERVAL
        if time.monotonic() - _candidate_since < _DEBOUNCE:
            return _INTERVAL
        reason = _busy_reason()
        if reason:
            _set_status('Update ' + version + ' pending: ' + reason)
            return _INTERVAL
        # Parse only after stability: a half-copied file must not poison a version.
        sources = _compile_snapshot(sources)
        # Success registers the new module's timer. Failure restores this one.
        return None if _reload_package(version, sources) else _INTERVAL
    except Exception as exc:
        if version:
            _failed_version = version
        _set_status('Update not loaded: ' + str(exc))
        print('harhtools: update preflight failed:', exc)
        return _INTERVAL


def register():
    global _loaded_version, _candidate, _requested, _failed_version
    _loaded_version = str(_manifest().get('version', 'unknown'))
    _candidate = None
    _requested = False
    _failed_version = ''
    if not hasattr(bpy.types.WindowManager, _PROPERTIES[0]):
        bpy.types.WindowManager.harhtools_live_reload_enabled = BoolProperty(
            name='Reload Installed Updates', default=True,
            description='Load newly installed Harhtools code when idle, keeping the current file open')
    if not hasattr(bpy.types.WindowManager, _PROPERTIES[1]):
        bpy.types.WindowManager.harhtools_live_reload_status = StringProperty(options={'SKIP_SAVE'})
        bpy.types.WindowManager.harhtools_live_reload_version = StringProperty(options={'SKIP_SAVE'})
    _set_status('Loaded ' + _loaded_version + '; watching installed updates')
    if not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll, first_interval=_INTERVAL, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)
    for name in _PROPERTIES:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
