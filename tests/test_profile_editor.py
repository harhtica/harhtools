"""Native movable points fork defaults, persist as assets and drive real bevels."""
import sys,json
from pathlib import Path
import bpy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_tool as ot,profile_editor as pe,outline_profiles as profiles,outline_preview as op,outline_bevel as bevel,outline_geometry as og
ot.register();pe.register()
cfg=ot.settings();cfg.bevel_enabled=True;cfg.output_type='MESH'
before=set(bpy.data.curves);original={name:profiles.path(name) for name in profiles.NAMES}
try:
    cfg.bevel_profile='TORUS';assert bpy.ops.object.harhtools_edit_profile()=={'FINISHED'}
    draft=cfg.working_profile;baseline=pe.serialize(draft)
    assert len(draft.bevel_profile.points)>2 and not draft.use_fake_user
    draft.bevel_profile.points[3].select=True;pe.tick()
    assert cfg.bevel_profile=='TORUS' and not draft.get(pe.TAG),'Selecting a point should not save a shape'
    draft.bevel_profile.points[3].location.x-=.035;draft.bevel_profile.update();pe.tick()
    assert cfg.bevel_profile=='EDITED' and cfg.edited_profile==draft
    assert draft.use_fake_user and draft.get(pe.TAG) and baseline!=pe.serialize(draft)
    assert original=={name:profiles.path(name) for name in profiles.NAMES}
    assert not any(obj.data==draft for obj in bpy.data.objects)
    # Point-edited native samples match the thumbnail and resulting modifier.
    options=bevel.options(cfg);section=op.profile_points('EDITED',cfg.bevel_segments,cfg.bevel_shape,options['profile_data'])
    native=list(reversed([tuple(p.location) for p in draft.bevel_profile.segments]+[(0.,1.)]))
    assert section==native
    mesh=bpy.data.meshes.new('Editor ring source');mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)],[(0,1),(1,2),(2,3),(3,0)],[])
    source=bpy.data.objects.new('Editor ring source',mesh);bpy.context.collection.objects.link(source);bpy.context.view_layer.update()
    result=og.build_outline(og.prepare_sources([source]),.2,join_style='MITER')
    surface=op.surface([result],options);assert surface['pos']
    first_data=options['profile_data'];first_positions=surface['pos']
    draft.bevel_profile.points[4].location.x-=.05;draft.bevel_profile.update();pe.tick()
    assert pe.serialize(draft)!=first_data
    assert op.surface([result],bevel.options(cfg))['pos']!=first_positions
    op.profile_icon(cfg);bpy.app.timers.unregister(op._refresh_icon);op._refresh_icon()
    assert op._icon_key[-1]==pe.serialize(draft) and op._error_key is None
    # Copying a user asset forks it as well; changing a new copy never changes
    # the original saved profile. Built-ins can always be chosen again.
    saved=pe.serialize(draft);second=pe.start(cfg)
    second.bevel_profile.points[2].location.x-=.04;second.bevel_profile.update();pe.tick()
    assert second!=draft and second.get(pe.TAG) and pe.serialize(draft)==saved
    cfg.bevel_profile='TORUS';assert pe.active_curve(cfg) is None
    third=pe.start(cfg);assert pe.serialize(third)==baseline
    pe.start(cfg);assert third not in set(bpy.data.curves)
    # Loading cleanup removes only untouched drafts, never authored profiles.
    pe.load_pre();assert cfg.working_profile is None
    assert draft in bpy.data.curves.values() and second in bpy.data.curves.values()
    assert set(bpy.data.curves)-before=={draft,second}
    # Native profile points serialize with the blend, without linked objects.
    artifact=ROOT/'tests'/'_artifacts'/'custom_profile_roundtrip.blend'
    bpy.data.libraries.write(str(artifact),{draft,second})
    with bpy.data.libraries.load(str(artifact)) as (src,dst):dst.curves=list(src.curves)
    assert any(pe.serialize(curve)==saved and curve.get(pe.TAG) for curve in dst.curves)
finally:
    pe.unregister();ot.unregister()
assert not bpy.app.timers.is_registered(pe.tick)
print('PROFILE_EDITOR_PASS: native control points, copy on shape edit, immutable presets, real modifier/thumbnail updates, independent user copies, persistence and draft cleanup')
