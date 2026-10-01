"""The one-time Text Editor helper attaches safely to an older loaded release."""
import importlib
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile

import bpy

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
