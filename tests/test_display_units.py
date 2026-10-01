"""Stud fields round-trip distances without changing scene or mesh scale."""
import sys
from pathlib import Path
import bpy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import display_units as units,outline_tool as ot,array_tool as at,live_reload
units.register();ot.register();at.register()
try:
    cfg=ot.settings();array=at.settings();scene=bpy.context.scene
    mesh=bpy.context.object.data;vertices=tuple(tuple(v.co) for v in mesh.vertices)
    transform=tuple(tuple(row) for row in bpy.context.object.matrix_world)
    for scale in (1,.01,.28):
        scene.unit_settings.scale_length=scale
        cfg.thickness=.28/scale
        assert abs(cfg.thickness_studs-1)<1e-6
        cfg.thickness_studs=2.5;assert abs(cfg.thickness-.7/scale)<1e-5
        cfg.bevel_depth_studs=.02;assert abs(cfg.bevel_depth-.0056/scale)<1e-6
        cfg.bevel_width_studs=.001;assert abs(cfg.bevel_width-.00028/scale)<1e-7
        array.gap_studs=-.25;assert abs(array.gap+.07/scale)<1e-6
        array.radius_studs=4;assert abs(array.radius-1.12/scale)<1e-5
        array.resolved_radius=.28/scale;assert abs(array.resolved_radius_studs-1)<1e-6
        assert units.format_length(bpy.context,.28/scale)=='1.000 studs'
        assert scene.unit_settings.scale_length==scale or abs(scene.unit_settings.scale_length-scale)<1e-7
        assert not any(name.endswith('_studs') for name in live_reload._rna_snapshot(cfg))
    before=cfg.thickness;bpy.context.window_manager.harhtools_distance_units='SCENE'
    assert cfg.thickness==before and 'studs' not in units.format_length(bpy.context,before)
    assert tuple(tuple(v.co) for v in mesh.vertices)==vertices
    assert tuple(tuple(row) for row in bpy.context.object.matrix_world)==transform
finally:at.unregister();ot.unregister();units.unregister()
print('DISPLAY_UNITS_PASS: official 0.28 m/stud, scene scale, input/output round trips, negative array gap, reload excludes derived values, geometry unchanged')
