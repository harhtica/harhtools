"""Run once in Blender's Scripting workspace after installing Harhtools updates.

Finish active tools, return to Object Mode, then open this file in the Text Editor
and press Run Script. An enabled older release gets the new code watcher and
reloads after a short idle wait. A unique disabled/orphaned installation left by
a failed Preferences enable is repaired from its installed source immediately.
The current blend file is neither saved nor reopened. No other add-on is reloaded.
Progress prints to Blender's console; the loaded version/status appears in the
Harhtools Settings panel after recovery or reload succeeds.
"""
import importlib
import importlib.util
from pathlib import Path
import sys
import tomllib

import bpy
import addon_utils


def _is_harhtools(directory):
    try:
        return tomllib.loads((directory / 'blender_manifest.toml').read_text(encoding='utf8')).get('id') == 'harhtools'
    except (OSError, ValueError):
        return False


def _enabled_harhtools():
    matches = []
    for addon in bpy.context.preferences.addons:
        module = sys.modules.get(addon.module)
        filename = getattr(module, '__file__', None)
        if (not filename or not getattr(module, '__addon_enabled__', True)
                or not callable(getattr(module, 'register', None))):
            continue
        manifest = Path(filename).resolve().parent / 'blender_manifest.toml'
        try:
            data = tomllib.loads(manifest.read_text(encoding='utf8'))
        except (OSError, ValueError):
            continue
        if data.get('id') == 'harhtools':
            matches.append(module)
    if len(matches) > 1:
        raise RuntimeError('More than one Harhtools copy is enabled. Disable the extra copy before reloading.')
    return matches[0] if matches else None


def _recovery_candidate():
    """Find installed code after Blender removed the failed root/preferences entry."""
    candidates = {}
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if not _is_harhtools(path.parent):
            continue
        root_name = name if path.name == '__init__.py' else getattr(module, '__package__', '')
        if root_name:
            candidates[(root_name, str(path.parent))] = (root_name, path.parent)
    extensions = getattr(bpy.context.preferences, 'extensions', None)
    for repo in getattr(extensions, 'repos', ()):
        if not getattr(repo, 'enabled', True):
            continue
        directory = Path(repo.directory)
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and _is_harhtools(child):
                name = 'bl_ext.' + repo.module + '.' + child.name
                candidates[(name, str(child.resolve()))] = (name, child.resolve())
    if len(candidates) != 1:
        raise RuntimeError('Recovery requires exactly one installed Harhtools copy; found ' + str(len(candidates)))
    return next(iter(candidates.values()))


def _recover_disabled():
    root_name, directory = _recovery_candidate()
    # Load the installed watcher directly from source, outside the stale package
    # cache. It supplies the same idle guard and immutable-source import finder.
    path = directory / 'live_reload.py'
    if not path.is_file():
        raise RuntimeError('Install the corrected Harhtools release before running this helper.')
    spec = importlib.util.spec_from_file_location(root_name + '.live_reload', path)
    coordinator = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), coordinator.__dict__)
    reason = coordinator._busy_reason()
    if reason:
        raise RuntimeError('Harhtools recovery is waiting: ' + reason + '. Then run this script again.')
    _, sources = coordinator._source_snapshot()
    sources = coordinator._compile_snapshot(sources)
    old_modules = {name: module for name, module in sys.modules.items()
                   if name == root_name or name.startswith(root_name + '.')}
    # A failed register() can have cleaned only part of its classes. Attempt all
    # Harhtools cleanup hooks; never unload unrelated packages or change modes.
    for suffix in ('live_reload', 'centering', 'outline_tool', 'array_tool',
                   'shape_builder', 'shape_library', 'shortcuts', 'icons'):
        module = old_modules.get(root_name + '.' + suffix)
        cleanup = getattr(module, 'unregister', None)
        if cleanup is not None:
            try:
                cleanup()
            except Exception as exc:
                print('Harhtools recovery cleanup:', suffix, str(exc))
    for name in old_modules:
        sys.modules.pop(name, None)
    parent_name, _, child_name = root_name.rpartition('.')
    parent = sys.modules.get(parent_name)
    if parent is not None and hasattr(parent, child_name):
        delattr(parent, child_name)
    finder = coordinator._SnapshotFinder(sources)
    errors = []
    sys.meta_path.insert(0, finder)
    try:
        package = addon_utils.enable(root_name, default_set=True, persistent=True,
                                     handle_error=errors.append)
        if package is None:
            raise RuntimeError('Harhtools could not be enabled: ' + '; '.join(map(str, errors)))
        for name in sorted(sources):
            importlib.import_module(name)
    finally:
        sys.meta_path.remove(finder)
    watcher = sys.modules[root_name + '.live_reload']
    watcher._set_status('Recovered ' + watcher._loaded_version + '; current file kept open')
    print('Harhtools recovered:', watcher._loaded_version, '|', directory)
    return watcher


def main():
    package = _enabled_harhtools()
    if package is None:
        return _recover_disabled()
    watcher_name = package.__name__ + '.live_reload'
    watcher = sys.modules.get(watcher_name)
    running = watcher is not None and bpy.app.timers.is_registered(watcher._poll)
    if watcher is None:
        try:
            watcher = importlib.import_module(watcher_name)
        except ImportError as exc:
            raise RuntimeError('Install a Harhtools release with live_reload.py before running this script') from exc
    if not running:
        watcher.register()
        version = getattr(package, 'bl_info', {}).get('version')
        watcher._loaded_version = '.'.join(map(str, version)) if version else 'previous session'
    watcher.request_reload()
    print('Harhtools reload queued. Finish active tools and use Object Mode; your current file stays open.')
    return watcher


if __name__ == '__main__':
    main()
