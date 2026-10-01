"""Native modifier profiles, perimeter weights, editability and rollback."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
import bpy
import bmesh

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_bevel as ob, outline_geometry as og, outline_mesh as om, outline_tool as ot
CHECKS=[]


def border(name):
    curve=bpy.data.curves.new(name,'CURVE');curve.dimensions='2D'
    s=curve.splines.new('POLY');s.points.add(3);s.use_cyclic_u=True
    for p,xy in zip(s.points,[(-1,-1),(1,-1),(1,1),(-1,1)]):p.co=(*xy,0,1)
    source=bpy.data.objects.new(name,curve);bpy.context.collection.objects.link(source)
    bpy.context.view_layer.update()
    result=og.build_outline(og.prepare_sources([source]),.2,join_style='MITER')
    obj=bpy.data.objects.new(name+' border',om.make_mesh_data(result));bpy.context.collection.objects.link(obj)
    return obj


def signature(obj):
    return (tuple(tuple(v.co) for v in obj.data.vertices),tuple(tuple(p.vertices) for p in obj.data.polygons),
            tuple(tuple(uv.uv) for uv in obj.data.uv_layers.active.data))


def evaluated(obj):
    bpy.context.view_layer.update()
    ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return ev,ev.to_mesh()


obj=border('Frame');before=signature(obj)
profiles={}
for profile in (*ob.PROFILES,'CUSTOM'):
    ob.apply([obj],depth=.2,width=.04,segments=6,profile=profile,custom_shape=.9)
    assert signature(obj)==before
    assert [m.name for m in obj.modifiers]==[ob.DEPTH_NAME,ob.BEVEL_NAME]
    bevel=obj.modifiers[ob.BEVEL_NAME]
    assert bevel.segments==(1 if profile=='CHAMFER' else 6)
    ev,mesh=evaluated(obj)
    bm=bmesh.new();bm.from_mesh(mesh)
    assert all(e.is_manifold for e in bm.edges)
    assert all(f.calc_area()>1e-10 for f in bm.faces)
    assert 0<abs(bm.calc_volume(signed=True))<1.44*.201
    assert len(mesh.vertices)-len(mesh.edges)+len(mesh.polygons)==0,'Hollow frame must retain its opening'
    profiles[profile]=sorted(tuple(round(x,6) for x in v.co) for v in mesh.vertices)
    bm.free();ev.to_mesh_clear()
assert len({str(coords) for coords in profiles.values()})==5,'Profile presets must produce different surfaces'
CHECKS.append('All five profiles evaluate to distinct watertight hollow frames; base mesh and UVs unchanged')

counts=om._edge_faces([list(f.vertices) for f in obj.data.polygons])
weights=obj.data.attributes[ob.weight_name()]
for edge in obj.data.edges:
    assert weights.data[edge.index].value==(1.0 if len(counts[tuple(sorted(edge.vertices))])==1 else 0.0)
obj.modifiers[ob.BEVEL_NAME].show_viewport=False
ev,mesh=evaluated(obj);side_edges=0
for edge in mesh.edges:
    z=[mesh.vertices[i].co.z for i in edge.vertices]
    if abs(z[0]-z[1])>.1:
        side_edges+=1
        assert mesh.attributes[ob.weight_name()].data[edge.index].value==0,'Vertical corner must stay sharp'
assert side_edges==8
ev.to_mesh_clear();obj.modifiers[ob.BEVEL_NAME].show_viewport=True
CHECKS.append('Only top/bottom perimeters bevel; internal seams and vertical miter edges have zero weight')

bad=border('Bad');bad.data.vertices[0].co.z=.2;bad.data.update()
before_mods=[(m.name,m.width if m.type=='BEVEL' else m.thickness) for m in obj.modifiers]
try:ob.apply([obj,bad],depth=.5,width=.1)
except ValueError:pass
else:raise AssertionError('Nonplanar batch must be rejected before mutation')
assert before_mods==[(m.name,m.width if m.type=='BEVEL' else m.thickness) for m in obj.modifiers]
assert not bad.modifiers
CHECKS.append('Invalid second object leaves entire batch untouched')

fresh=border('Fresh');configure=ob._configure
saved_weights=[p.value for p in obj.data.attributes[ob.weight_name()].data]
def fail_late(item,*args):
    configure(item,*args)
    if item==fresh:raise RuntimeError('Injected second-object failure after native modifiers were created')
with patch.object(ob,'_configure',side_effect=fail_late):
    try:ob.apply([obj,fresh],depth=.4,width=.09)
    except RuntimeError:pass
    else:raise AssertionError('Injected native mutation failure must propagate')
assert not fresh.modifiers and not fresh.data.attributes.get(ob.weight_name())
assert before_mods==[(m.name,m.width if m.type=='BEVEL' else m.thickness) for m in obj.modifiers]
assert saved_weights==[p.value for p in obj.data.attributes[ob.weight_name()].data]
CHECKS.append('Mid-batch modifier failure restores existing settings and removes newly created data')

ot.register()
try:
    cfg=ot.settings();cfg.bevel_enabled=True;cfg.output_type='MESH'
    cfg.bevel_profile='CONCAVE';cfg.bevel_depth=.12;cfg.bevel_width=.02
    for item in bpy.context.selected_objects:item.select_set(False)
    obj.select_set(True);bpy.context.view_layer.objects.active=obj
    assert bpy.ops.object.harhtools_border_bevel()=={'FINISHED'}
    assert abs(obj.modifiers[ob.BEVEL_NAME].profile-.15)<1e-6
    assert len(obj.modifiers)==2 and signature(obj)==before
    assert ot.bevel_options(cfg)['profile']=='CONCAVE'
    cfg.output_type='CURVE';assert ot.bevel_options(cfg) is None
    CHECKS.append('Registered update operator edits existing mesh modifiers without duplicating them')
finally:ot.unregister()

output=ROOT/'tests/_artifacts';output.mkdir(exist_ok=True)
(output/'outline_bevel_results.json').write_text(json.dumps(CHECKS,indent=2))
print('OUTLINE_BEVEL_PASS',json.dumps(CHECKS))
