"""Reload the real package with isolated storage; optionally start from an old source.

Blender --background --factory-startup --python-exit-code 1 --python this_file
Optional arguments after --: --old-source /path/to/a/previous/extension
"""
import argparse
import importlib
import importlib.util
from pathlib import Path
import re
import shutil
import sys
import tempfile

import bpy
import addon_utils

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).resolve().parent / '_artifacts'
OUTPUT.mkdir(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('--old-source', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
TEMP = Path(tempfile.mkdtemp(prefix='real_reload_', dir=OUTPUT))
PACKAGE = TEMP / 'real_reload_fixture'
sys.path.insert(0, str(TEMP))


def copy_isolated(source):
    shutil.copytree(source, PACKAGE, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    path = PACKAGE / 'shortcuts.py'
    value = path.read_text(encoding='utf8')
    value = value.replace("return Path(bpy.utils.user_resource('CONFIG'))/'harhtools'/'color_themes.json'",
                          "return Path(__file__).parent/'_test_store'/'color_themes.json'")
    path.write_text(value, encoding='utf8')
    path = PACKAGE / 'shape_library.py'
    value = path.read_text(encoding='utf8').replace('_storage_override = None',
        "_storage_override = Path(__file__).parent/'_test_store'/'shapes'")
    path.write_text(value, encoding='utf8')


def stamp_version(version):
    path = PACKAGE / 'blender_manifest.toml'
    value = re.sub(r'(?m)^version = "[^"]+"', 'version = "' + version + '"', path.read_text(encoding='utf8'))
    path.write_text(value, encoding='utf8')


def reload_ready(watcher):
    assert watcher._poll() == 2.0
    watcher._candidate_since -= 3
    return watcher._poll()


copy_isolated(args.old_source or ROOT / 'extension')
enable_errors = []
# The real Preferences enable path imports/registers inside RestrictBlend. Direct
# package.register() misses that contract and previously hid the _RestrictData bug.
package = addon_utils.enable('real_reload_fixture', default_set=True, persistent=True,
                             handle_error=enable_errors.append)
assert package is not None and not enable_errors, enable_errors
if hasattr(package, 'live_reload'):
    from _bpy_restrict_state import RestrictBlend
    # Disabling/re-registering the watcher is also safe in that restricted scope.
    with RestrictBlend():
        package.live_reload.unregister()
        package.live_reload.register()
    assert bpy.app.timers.is_registered(package.live_reload._poll)
    assert package.live_reload._poll() == 2.0
    assert bpy.context.window_manager.harhtools_live_reload_version == package.live_reload._loaded_version
print('PASS: addon_utils.enable registers the real package through Blender restricted context')
cube = bpy.context.active_object
cube['unsaved_reload_data'] = 123
wm = bpy.context.window_manager
wm.harhtools_array.count = 31
wm.arch_shape_builder_gap_snap = .25
wm.harhtools_panel_tab = 'SETTINGS'
package.shortcuts.settings().toggle_key = 'F8'
package.shortcuts.settings().preview_opacity = 37
bpy.context.scene.harhtools_shape_placement.target_object = cube
object_pointer = cube.as_pointer()
mesh_pointer = cube.data.as_pointer()
vertices = tuple(tuple(v.co) for v in cube.data.vertices)
filepath = bpy.data.filepath


def assert_scene_settings():
    active_package = sys.modules['real_reload_fixture']
    assert cube.as_pointer() == object_pointer and cube.data.as_pointer() == mesh_pointer
    assert tuple(tuple(v.co) for v in cube.data.vertices) == vertices
    assert cube['unsaved_reload_data'] == 123
    assert cube.select_get() and bpy.context.active_object is cube
    assert bpy.data.filepath == filepath
    assert wm.harhtools_array.count == 31
    assert wm.arch_shape_builder_gap_snap == .25
    assert wm.harhtools_panel_tab == 'SETTINGS'
    assert active_package.shortcuts.settings().toggle_key == 'F8'
    assert active_package.shortcuts.settings().preview_opacity == 37
    assert bpy.context.scene.harhtools_shape_placement.target_object is cube


try:
    if args.old_source:
        assert not hasattr(package, 'live_reload')
        copy_isolated(ROOT / 'extension')
        spec = importlib.util.spec_from_file_location('reload_helper_integration', ROOT / 'tools/reload_harhtools.py')
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        watcher = helper.main()
        assert reload_ready(watcher) is None
        package = sys.modules['real_reload_fixture']
        assert hasattr(package, 'outline_tool')
        assert_scene_settings()
        assert not bpy.app.timers.is_registered(watcher._poll)
        print('PASS: actual previous-release bootstrap preserves objects, library target, settings and shortcuts')

    wm.harhtools_outline.thickness = .375
    wm.harhtools_outline.direction = 'OUTWARD'
    wm.harhtools_outline.snap_geometry = True
    watcher = package.live_reload
    previous_curve = package.curve_geometry if hasattr(package, 'curve_geometry') else package.shape_builder.curve_geometry
    stamp_version('90.0.1')
    assert reload_ready(watcher) is None
    package = sys.modules['real_reload_fixture']
    assert package.shape_builder.curve_geometry is not previous_curve
    assert_scene_settings()
    assert wm.harhtools_outline.thickness == .375
    assert wm.harhtools_outline.direction == 'OUTWARD' and wm.harhtools_outline.snap_geometry
    print('PASS: full package reload preserves real outline/array/builder/theme settings')

    watcher = package.live_reload
    # Fail after earlier classes have registered, exercising real unregister cleanup.
    path = PACKAGE / 'centering.py'
    original = path.read_text(encoding='utf8')
    path.write_text(original.replace('def register():', "def register():\n    raise RuntimeError('intentional real registration failure')"), encoding='utf8')
    stamp_version('90.0.2')
    assert reload_ready(watcher) == 2.0
    assert sys.modules['real_reload_fixture'] is package
    assert_scene_settings()
    assert wm.harhtools_outline.thickness == .375
    assert bpy.app.timers.is_registered(watcher._poll)
    assert bpy.types.VIEW3D_OT_arch_shape_builder.is_registered
    assert watcher._failed_version == '90.0.2'
    print('PASS: actual partial registration rollback restores old tools and settings')
finally:
    # This fixture has no extension repository to refresh; skip global repo-cache
    # maintenance so the test never writes the user's extension cache.
    addon_utils.disable('real_reload_fixture', default_set=True, refresh_handled=True)
