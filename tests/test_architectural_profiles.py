"""Native moulding presets: shape, preview, editability and rollback."""
import bpy,bmesh,sys,math,time,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_profiles as profiles,outline_bevel as bevel,outline_preview as preview,outline_tool as tool

mesh=bpy.data.meshes.new('Profile test frame')
mesh.from_pydata([(-1.2,-1.2,0),(1.2,-1.2,0),(1.2,1.2,0),(-1.2,1.2,0),(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)],[],
                 [(i,(i+1)%4,(i+1)%4+4,i+4) for i in range(4)])
obj=bpy.data.objects.new('Profile test frame',mesh);bpy.context.collection.objects.link(obj)
# Evaluate one weighted edge independently to compare the actual native bevel
# cross-section with the sidebar's CurveProfile samples, including undercuts.
box_mesh=bpy.data.meshes.new('Section box')
box_mesh.from_pydata([(-2,-1,0),(2,-1,0),(2,1,0),(-2,1,0),(-2,-1,-.5),(2,-1,-.5),(2,1,-.5),(-2,1,-.5)],[],
                    [(0,1,2,3),(7,6,5,4),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)])
box=bpy.data.objects.new('Section box',box_mesh);bpy.context.collection.objects.link(box)
attribute=box_mesh.attributes.new(bevel.weight_name(),'FLOAT','EDGE')
for e in box_mesh.edges:attribute.data[e.index].value=float(all(abs(box_mesh.vertices[i].co.y-1)<1e-7 and abs(box_mesh.vertices[i].co.z)<1e-7 for i in e.vertices))
box_mod=box.modifiers.new('Section','BEVEL');box_mod.limit_method='WEIGHT';box_mod.width=.2;box_mod.segments=32;box_mod.profile_type='CUSTOM'
if hasattr(box_mod,'edge_weight'):box_mod.edge_weight=bevel.weight_name()
before=tuple(tuple(v.co) for v in mesh.vertices);ids=(set(bpy.data.objects),set(bpy.data.meshes),set(bpy.data.scenes))
surfaces=[];sections=[];thumbnails={};times=[]
for name,label,_ in profiles.ITEMS:
    bevel.apply([obj],depth=.2,width=.04,segments=32,profile=name)
    mod=obj.modifiers[bevel.BEVEL_NAME];assert mod.profile_type=='CUSTOM'
    expected=list(reversed(profiles.path(name)))
    assert len(mod.custom_profile.points)==len(expected)
    assert all(math.dist(p.location,co)<1e-6 for p,co in zip(mod.custom_profile.points,expected))
    bpy.context.view_layer.update();ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());result=ev.to_mesh()
    bm=bmesh.new();bm.from_mesh(result)
    assert all(e.is_manifold for e in bm.edges),name
    assert min(f.calc_area() for f in bm.faces)>1e-12,name
    assert bm.calc_volume(signed=True)>0,name
    assert len(bm.verts)-len(bm.edges)+len(bm.faces)==0,name
    assert all(math.isfinite(x) for v in bm.verts for x in v.co)
    surfaces.append(str(sorted(tuple(round(x,7) for x in v.co) for v in bm.verts)))
    bm.free();ev.to_mesh_clear()
    assert tuple(tuple(v.co) for v in mesh.vertices)==before
    section=preview.profile_points(name,32,.5);sections.append(str(section))
    assert math.dist(section[0],(0,1))<1e-5 and math.dist(section[-1],(1,0))<1e-5,(name,section[0],section[-1])
    assert len(section)==33,(name,len(section))
    profiles.configure(box_mod.custom_profile,name,32);box.update_tag()
    bpy.context.view_layer.update();box_ev=box.evaluated_get(bpy.context.evaluated_depsgraph_get());box_result=box_ev.to_mesh()
    native=[((v.co.y-.8)/.2,(v.co.z+.2)/.2) for v in box_result.vertices if abs(v.co.x-2)<1e-6 and v.co.y>=.79999 and v.co.z>=-.200001]
    assert len(native)==33,(name,len(native))
    assert max(min(math.dist(p,q) for q in native) for p in section)<1e-5,(name,section,native)
    box_ev.to_mesh_clear()
    start=time.perf_counter();cfg=SimpleNamespace(bevel_profile=name,bevel_segments=32,bevel_shape=.5)
    preview.profile_icon(cfg);times.append(time.perf_counter()-start)
    pixels=tuple(preview._icons['profile'].image_pixels_float)
    thumbnails[label]=[round(max(0,min(1,p))*255) for p in pixels]
    with patch.object(preview,'profile_points',side_effect=AssertionError('Unchanged panel must reuse thumbnail')):
        preview.profile_icon(cfg)
    assert (set(bpy.data.objects),set(bpy.data.meshes),set(bpy.data.scenes))==ids
assert len(set(surfaces))==len(set(sections))==len(profiles.ITEMS)
assert len({str(p) for p in thumbnails.values()})==len(profiles.ITEMS)
# A failed multi-object update restores the complete original custom path.
bevel.apply([obj],depth=.2,width=.04,segments=32,profile='CYMA_RECTA')
saved=profiles.snapshot(obj.modifiers[bevel.BEVEL_NAME].custom_profile)
fresh=bpy.data.objects.new('Second frame',mesh.copy());bpy.context.collection.objects.link(fresh)
real=bevel._configure
def fail(item,*args):
    real(item,*args)
    if item==fresh:raise RuntimeError('Injected late profile failure')
with patch.object(bevel,'_configure',side_effect=fail):
    try:bevel.apply([obj,fresh],depth=.3,width=.05,segments=24,profile='BEAK')
    except RuntimeError:pass
    else:raise AssertionError('Expected failure')
restored=profiles.snapshot(obj.modifiers[bevel.BEVEL_NAME].custom_profile)
assert restored==saved,(saved,restored)
assert not fresh.modifiers
tool.register()
try:
    cfg=tool.settings();cfg.bevel_segments=6;cfg.bevel_profile='TORUS'
    assert cfg.bevel_segments==32
    cfg.bevel_segments=20;assert cfg.bevel_segments==20
    from extension import live_reload
    saved_settings=live_reload._rna_snapshot(cfg)
    cfg.bevel_profile='ROUND';cfg.bevel_segments=6
    live_reload._restore_rna(cfg,saved_settings)
    assert cfg.bevel_profile=='TORUS' and cfg.bevel_segments==20
    cfg.bevel_profile='BEAK'
    state=SimpleNamespace(_done=False,_original_settings={'bevel_segments':20,'bevel_profile':'TORUS'})
    tool.VIEW3D_OT_harhtools_make_outline.finish(state,bpy.context,cancel=True)
    assert cfg.bevel_profile=='TORUS' and cfg.bevel_segments==20
finally:tool.unregister();preview.clear()
out=ROOT/'tests/_artifacts';out.mkdir(exist_ok=True)
(out/'architectural_profile_pixels.json').write_text(json.dumps(thumbnails))
(out/'architectural_profiles_results.json').write_text(json.dumps(dict(profiles=len(profiles.ITEMS),thumbnail_seconds_max=max(times),thumbnail_seconds_mean=sum(times)/len(times)),indent=2))
print('ARCHITECTURAL_PROFILES_PASS:',len(profiles.ITEMS),'distinct native profiles and thumbnails, manifold hollow frames, source preservation, rollback, default detail, no scratch leaks; max thumbnail seconds',max(times))
