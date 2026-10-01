"""The one-time Text Editor helper attaches safely to an older loaded release."""
import importlib
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
from types import ModuleType, SimpleNamespace

import bpy
import addon_utils

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(__file__).resolve().parent / '_artifacts'
ARTIFACTS.mkdir(exist_ok=True)
TEMP = Path(tempfile.mkdtemp(prefix='bootstrap_', dir=ARTIFACTS))
PACKAGE = TEMP / 'bootstrap_fixture'
PACKAGE.mkdir()
sys.path.insert(0, str(TEMP))

OLD = '''
import bpy
from bpy.props import IntProperty
bl_info = {'version': (1, 5, 1)}
def register():
    bpy.types.WindowManager.harhtools_fixture_count = IntProperty(default=6)
def unregister():
    if hasattr(bpy.types.WindowManager, 'harhtools_fixture_count'):
        del bpy.types.WindowManager.harhtools_fixture_count
'''
NEW = OLD.replace("bl_info = {'version': (1, 5, 1)}", "from . import live_reload\nbl_info = {'version': (1, 5, 2)}")
NEW = NEW.replace('def unregister():', '    live_reload.register()\ndef unregister():\n    live_reload.unregister()')

(PACKAGE / '__init__.py').write_text(OLD, encoding='utf8')
(PACKAGE / 'blender_manifest.toml').write_text('id = "harhtools"\nversion = "1.5.1"\n', encoding='utf8')
old = importlib.import_module('bootstrap_fixture')
old.register()
bpy.context.preferences.addons.new().module = 'bootstrap_fixture'
assert 'bootstrap_fixture.live_reload' not in sys.modules
wm = bpy.context.window_manager
wm.harhtools_fixture_count = 19
cube = bpy.context.active_object
cube['unsaved_bootstrap_work'] = 'preserved'
pointer = cube.as_pointer()

# Simulate a completed update on disk while the older Python package is running.
shutil.copy2(ROOT / 'extension/live_reload.py', PACKAGE / 'live_reload.py')
(PACKAGE / '__init__.py').write_text(NEW, encoding='utf8')
(PACKAGE / 'blender_manifest.toml').write_text('id = "harhtools"\nversion = "1.5.2"\n', encoding='utf8')
spec = importlib.util.spec_from_file_location('bootstrap_helper', ROOT / 'tools/reload_harhtools.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
try:
    watcher = helper.main()
    assert watcher._loaded_version == '1.5.1'
    assert watcher._requested and bpy.app.timers.is_registered(watcher._poll)
    assert watcher._poll() == 2.0
    watcher._candidate_since -= 3
    assert watcher._poll() is None
    new = sys.modules['bootstrap_fixture']
    assert new is not old
    assert new.bl_info['version'] == (1, 5, 2)
    assert wm.harhtools_fixture_count == 19
    assert cube.as_pointer() == pointer and cube['unsaved_bootstrap_work'] == 'preserved'
    assert not bpy.app.timers.is_registered(watcher._poll), 'bootstrap old watcher leaked'
    assert bpy.app.timers.is_registered(new.live_reload._poll)
    assert helper.main() is new.live_reload, 'rerunning helper must reuse the current watcher'
    print('PASS: bootstrap from old loaded package; one active watcher; settings and unsaved objects preserved')
finally:
    sys.modules['bootstrap_fixture'].unregister()
    bpy.context.preferences.addons.remove(bpy.context.preferences.addons['bootstrap_fixture'])
    for name in list(sys.modules):
        if name == 'bootstrap_fixture' or name.startswith('bootstrap_fixture.'):
            del sys.modules[name]

# Reproduce the real Preferences failure: enable removes the failed root and
# preferences entry but leaves imported children cached in this same process.
recovery = TEMP / 'recovery_fixture'
shutil.copytree(ROOT / 'extension', recovery, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
path = recovery / 'shortcuts.py'
path.write_text(path.read_text(encoding='utf8').replace(
    "return Path(bpy.utils.user_resource('CONFIG'))/'harhtools'/'color_themes.json'",
    "return Path(__file__).parent/'_test_store'/'color_themes.json'"), encoding='utf8')
path = recovery / 'shape_library.py'
path.write_text(path.read_text(encoding='utf8').replace('_storage_override = None',
    "_storage_override = Path(__file__).parent/'_test_store'/'shapes'"), encoding='utf8')
path = recovery / 'live_reload.py'
fixed_source = path.read_text(encoding='utf8')
path.write_text(fixed_source.replace("managers = getattr(bpy.data, 'window_managers', ())",
                                      'managers = bpy.data.window_managers'), encoding='utf8')
errors = []
failed = addon_utils.enable('recovery_fixture', default_set=True, persistent=True, handle_error=errors.append)
assert failed is None and any('_RestrictData' in str(exc) for exc in errors), errors
assert 'recovery_fixture' not in sys.modules
assert bpy.context.preferences.addons.get('recovery_fixture') is None
stale_watcher = sys.modules['recovery_fixture.live_reload']
path.write_text(fixed_source, encoding='utf8')

# Discovery is confined to our synthetic orphan modules. Never enumerate or
# activate a real configured repository when running this regression suite.
helper.bpy = SimpleNamespace(context=SimpleNamespace(preferences=SimpleNamespace(
    addons=bpy.context.preferences.addons, extensions=SimpleNamespace(repos=[]))), app=bpy.app)
try:
    bpy.app.driver_namespace['arch_tools_shape_builder'] = object()
    try:
        helper.main()
        raise AssertionError('Recovery must wait for active tools')
    except RuntimeError as exc:
        assert 'finish the active Harhtools tool' in str(exc)
    finally:
        del bpy.app.driver_namespace['arch_tools_shape_builder']
    assert 'recovery_fixture' not in sys.modules

    other = TEMP / 'ambiguous_fixture'
    other.mkdir()
    (other / 'blender_manifest.toml').write_text('id = "harhtools"\nversion = "1.0.0"\n', encoding='utf8')
    ambiguous = ModuleType('ambiguous_fixture.child')
    ambiguous.__file__ = str(other / 'child.py')
    ambiguous.__package__ = 'ambiguous_fixture'
    sys.modules[ambiguous.__name__] = ambiguous
    try:
        helper.main()
        raise AssertionError('Recovery must reject ambiguous installations')
    except RuntimeError as exc:
        assert 'exactly one installed Harhtools copy; found 2' in str(exc)
    finally:
        del sys.modules[ambiguous.__name__]
    assert 'recovery_fixture' not in sys.modules
    print('PASS: recovery defers for active tools and rejects ambiguous installations before mutation')

    recovered_watcher = helper.main()
    recovered = sys.modules['recovery_fixture']
    assert recovered_watcher is not stale_watcher
    assert recovered.__addon_enabled__
    assert bpy.context.preferences.addons.get('recovery_fixture') is not None
    assert bpy.app.timers.is_registered(recovered_watcher._poll)
    assert not bpy.app.timers.is_registered(stale_watcher._poll)
    assert bpy.types.VIEW3D_OT_arch_shape_builder.is_registered
    assert bpy.types.VIEW3D_OT_harhtools_make_outline.is_registered
    assert cube.as_pointer() == pointer and cube['unsaved_bootstrap_work'] == 'preserved'
    print('PASS: failed Preferences enable -> fixed installed source -> same-session helper recovery, without stale children')
finally:
    addon_utils.disable('recovery_fixture', default_set=True, refresh_handled=True)
