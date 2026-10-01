"""Synthetic add-on hot reload: debounce, busy guards, settings and rollback.

Run with Blender --background --factory-startup --python-exit-code 1 --python.
No installed extension or existing blend file is read or modified.
"""
import ast
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).resolve().parent / '_artifacts'
OUTPUT.mkdir(exist_ok=True)
TEMP = Path(tempfile.mkdtemp(prefix='reload_', dir=OUTPUT))
PACKAGE = TEMP / 'reload_fixture'
PACKAGE.mkdir()
shutil.copy2(ROOT / 'extension/live_reload.py', PACKAGE / 'live_reload.py')
sys.path.insert(0, str(TEMP))
checks = []

INIT = '''
import bpy
from bpy.props import PointerProperty, FloatProperty, StringProperty
from . import helper, live_reload
FAIL_REGISTER = False
class FixtureInner(bpy.types.PropertyGroup):
    radius: FloatProperty(default=1.0)
class FixtureOuter(bpy.types.PropertyGroup):
    nested: PointerProperty(type=FixtureInner)
    label: StringProperty(default='default')
    target: PointerProperty(type=bpy.types.Object)
class FixturePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    strength: FloatProperty(default=.25)
    def draw(self, context): pass
CLASSES = (FixtureInner, FixtureOuter, FixturePreferences)
def register():
    for cls in CLASSES: bpy.utils.register_class(cls)
    bpy.types.WindowManager.harhtools_outline = PointerProperty(type=FixtureOuter)
    bpy.types.Scene.harhtools_shape_placement = PointerProperty(type=FixtureOuter)
    if FAIL_REGISTER: raise RuntimeError('intentional registration failure')
    live_reload.register()
def unregister():
    live_reload.unregister()
    for owner, name in ((bpy.types.WindowManager, 'harhtools_outline'),
                        (bpy.types.Scene, 'harhtools_shape_placement')):
        if hasattr(owner, name): delattr(owner, name)
    for cls in reversed(CLASSES):
        if cls.is_registered: bpy.utils.unregister_class(cls)
'''


def write(version, helper='VALUE = 1\n', init=INIT):
    (PACKAGE / '__init__.py').write_text(init, encoding='utf8')
    (PACKAGE / 'helper.py').write_text(helper, encoding='utf8')
    # The manifest is the completed-install signal and must be written last.
    (PACKAGE / 'blender_manifest.toml').write_text('version = "' + version + '"\n', encoding='utf8')


def current():
    return sys.modules['reload_fixture']


def ready(watcher):
    assert watcher._poll() == watcher._INTERVAL
    watcher._candidate_since -= watcher._DEBOUNCE + .1


def assert_kept(watcher):
    assert bpy.data.objects.get(cube.name) is cube
    assert cube.as_pointer() == object_pointer
    assert cube.data.as_pointer() == mesh_pointer
    assert tuple(tuple(vertex.co) for vertex in cube.data.vertices) == vertices
    assert cube['unsaved_note'] == 'keep this'
    assert cube.select_get() and bpy.context.view_layer.objects.active is cube
    assert bpy.data.filepath == filepath
    assert bpy.context.scene.frame_current == 17
    assert bpy.context.window_manager.harhtools_outline.nested.radius == 4.25
    assert bpy.context.window_manager.harhtools_outline.label == 'unsaved outline preference'
    assert bpy.context.window_manager.harhtools_outline.target is cube
    assert bpy.context.scene.harhtools_shape_placement.nested.radius == 3.5
    assert bpy.context.scene.harhtools_shape_placement.target is cube
    assert bpy.context.preferences.addons['reload_fixture'].preferences.strength == .75
    assert bpy.app.timers.is_registered(watcher._poll)


write('1.0.0')
package = importlib.import_module('reload_fixture')
bpy.context.preferences.addons.new().module = 'reload_fixture'
package.register()
try:
    cube = bpy.context.active_object
    cube['unsaved_note'] = 'keep this'
    object_pointer, mesh_pointer = cube.as_pointer(), cube.data.as_pointer()
    vertices = tuple(tuple(vertex.co) for vertex in cube.data.vertices)
    filepath = bpy.data.filepath
    bpy.context.scene.frame_set(17)
    wm = bpy.context.window_manager
    wm.harhtools_outline.nested.radius = 4.25
    wm.harhtools_outline.label = 'unsaved outline preference'
    wm.harhtools_outline.target = cube
    bpy.context.scene.harhtools_shape_placement.nested.radius = 3.5
    bpy.context.scene.harhtools_shape_placement.target = cube
    bpy.context.preferences.addons['reload_fixture'].preferences.strength = .75
    watcher = package.live_reload
    assert watcher._poll() == 2.0 and current() is package
    assert watcher._busy_reason() == ''
    assert watcher._busy_reason(SimpleNamespace(mode='EDIT_CURVE')) == 'finish Edit/Sculpt mode'
    assert watcher._busy_reason(SimpleNamespace(mode='OBJECT', window_manager=SimpleNamespace(is_interface_locked=True))) == 'Blender is busy'
    checks.append('unchanged version does not reload; edit/interface guards defer')

    real_bpy = watcher.bpy
    fake_window = SimpleNamespace(view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
                                  screen=SimpleNamespace(is_animation_playing=False), modal_operators=[object()])
    fake_manager = SimpleNamespace(windows=[fake_window], is_interface_locked=False)
    fake_app = SimpleNamespace(driver_namespace={}, is_job_running=lambda job: False)
    watcher.bpy = SimpleNamespace(data=SimpleNamespace(window_managers=[fake_manager]), app=fake_app)
    try:
        fake_context = SimpleNamespace(mode='OBJECT', window_manager=fake_manager)
        assert watcher._busy_reason(fake_context) == 'finish the active interaction'
        fake_window.modal_operators = []
        fake_window.screen.is_animation_playing = True
        assert watcher._busy_reason(fake_context) == 'stop animation playback'
        fake_window.screen.is_animation_playing = False
        fake_app.is_job_running = lambda job: job == 'RENDER'
        assert watcher._busy_reason(fake_context) == 'wait for the running job'
    finally:
        watcher.bpy = real_bpy
    checks.append('native modal interactions, playback, and render jobs defer the update')

    write('1.0.1', helper='VALUE = 2\n')
    wm.harhtools_live_reload_enabled = False
    assert watcher._poll() == 2.0 and current() is package
    wm.harhtools_live_reload_enabled = True
    ready(watcher)
    bpy.app.driver_namespace['harhtools_outline_preview'] = object()
    assert watcher._poll() == 2.0 and current() is package
    del bpy.app.driver_namespace['harhtools_outline_preview']
    assert watcher._poll() is None
    package = current()
    assert package.helper.VALUE == 2
    assert package.live_reload._loaded_version == '1.0.1'
    assert_kept(package.live_reload)
    checks.append('new code/children load; opt-out and modal deferral; nested settings/preferences/scene preserved')

    watcher = package.live_reload
    write('1.0.2', helper='raise RuntimeError("intentional import failure")\n')
    ready(watcher)
    assert watcher._poll() == 2.0
    assert current() is package and current().helper.VALUE == 2
    assert watcher._loaded_version == '1.0.1' and watcher._failed_version == '1.0.2'
    assert_kept(watcher)
    assert watcher._poll() == 2.0 and current() is package
    checks.append('import failure restores old modules and blocks repeated attempts')

    write('1.0.3', helper='VALUE = 3\n', init=INIT.replace('FAIL_REGISTER = False', 'FAIL_REGISTER = True'))
    ready(watcher)
    assert watcher._poll() == 2.0
    assert current() is package and package.helper.VALUE == 2
    assert watcher._loaded_version == '1.0.1' and watcher._failed_version == '1.0.3'
    assert_kept(watcher)
    checks.append('partial registration failure restores usable old classes and settings')

    write('1.0.4', helper='VALUE =\n')
    ready(watcher)
    assert watcher._failed_version != '1.0.4'  # An incomplete first scan is allowed to settle.
    assert watcher._poll() == 2.0 and watcher._failed_version == '1.0.4'
    assert current() is package
    assert_kept(watcher)
    checks.append('syntax preflight waits for stable files and preserves old registration')

    write('1.0.4', helper='VALUE = 4\n')
    watcher.request_reload()
    ready(watcher)
    assert watcher._poll() is None
    package = current()
    assert package.helper.VALUE == 4
    assert_kept(package.live_reload)
    checks.append('explicit retry can load a corrected failed version')

    tree = ast.parse((ROOT / 'extension/live_reload.py').read_text(encoding='utf8'))
    assert not any(isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                   and node.value.id == 'bpy' and node.attr == 'ops' for node in ast.walk(tree))
    checks.append('watcher invokes no Blender operators, file loads, saves, mode switches or process control')

    # Only the test loads its own synthetic file. The watcher does not keep
    # references to the previous Scene/WindowManager or depend on driver_namespace.
    scene_file = TEMP / 'synthetic_reload_lifecycle.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(scene_file))
    bpy.ops.wm.open_mainfile(filepath=str(scene_file), load_ui=False, use_scripts=False)
    watcher = current().live_reload
    assert bpy.app.timers.is_registered(watcher._poll)
    assert watcher._busy_reason() == ''
    assert watcher._poll() == 2.0
    assert bpy.context.window_manager.harhtools_live_reload_version == watcher._loaded_version
    checks.append('persistent watcher remains usable after opening a synthetic blend file')

    bpy.context.preferences.edit.use_global_undo = True
    loaded_cube = bpy.data.objects['Cube']
    before_x = loaded_cube.location.x
    bpy.ops.ed.undo_push(message='Reload watcher: before synthetic change')
    loaded_cube.location.x = before_x + 2
    bpy.ops.ed.undo_push(message='Reload watcher: after synthetic change')
    bpy.ops.ed.undo()
    assert bpy.data.objects['Cube'].location.x == before_x
    assert bpy.app.timers.is_registered(watcher._poll)
    assert watcher._busy_reason() == '' and watcher._poll() == 2.0
    checks.append('watcher remains registered and idle-safe after actual scene undo')
finally:
    current().unregister()
    bpy.context.preferences.addons.remove(bpy.context.preferences.addons['reload_fixture'])
    assert not hasattr(bpy.types.WindowManager, 'harhtools_live_reload_status')
for check in checks:
    print('PASS:', check)
print(str(len(checks)) + ' live-reload checks passed')
