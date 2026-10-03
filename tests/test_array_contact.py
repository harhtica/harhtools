"""Exact contact for thick, flat, slanted and disconnected repeated surfaces."""
import math
import sys
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace as NS
from unittest.mock import patch
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import extension as ext
from extension import array_core as core, array_contact as contact

def select(source):
    for o in bpy.context.selected_objects:o.select_set(False)
    source.select_set(True);bpy.context.view_layer.objects.active=source
    bpy.context.view_layer.update()

def mesh(points,faces):
    data=bpy.data.meshes.new('Contact test')
    data.from_pydata(points,[],faces)
    uv=data.uv_layers.new(name='Keep UV')
    for i,d in enumerate(uv.data):d.uv=(i*.013,.5)
    obj=bpy.data.objects.new('Contact test',data)
    bpy.context.collection.objects.link(obj);select(obj)
    return obj

def config(**kwargs):
    values=dict(mode='CIRCULAR',count=4,radial_axis='Z',orientation='WORLD',
                sweep=math.tau,pivot='BOUNDS',radius=3.,fit_ring=True,fit_side='CONTACT',
                rotate_copies=True,flip_bend=False,deform_enabled=False)
    values.update(kwargs);return NS(**values)

def plan(obj,**kwargs):
    select(obj);snap=core.snapshot(bpy.context,contact=True)
    return snap,core.build_plan(snap,config(**kwargs),bpy.context.scene)

def close(a,b,tol=2e-5):assert abs(a-b)<tol,(a,b)

def verify_marker(snap,plan):
    points,indices=snap.contact_mesh
    source=BVHTree.FromPolygons([Vector(p) for p in points],indices,all_triangles=True)
    if plan.contact_info['seam_limited']:
        matrix=plan.transforms[-1]
        point=plan.contact_info['points'][0]
    else:
        matrix=plan.transforms[0]
        point=plan.contact_info['points'][0]
    other=BVHTree.FromPolygons([matrix@Vector(p) for p in points],indices,all_triangles=True)
    assert source.find_nearest(point)[3]<4e-5
    assert other.find_nearest(point)[3]<4e-5

for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
bpy.ops.mesh.primitive_cube_add(size=2)
cube=bpy.context.object
half=math.pi/5
for flip in (False,True):
    for sign in (-1,1):
        snap,result=plan(cube,flip_bend=flip,sweep=sign*math.tau)
        close(result.resolved_radius,1/math.tan(half)+1)
        verify_marker(snap,result)
        assert len(result.contact_info['points'])==4
print('PASS thick surfaces touch without penetrating for both bends and sweep signs')

flat=mesh([(0,-1,-1),(0,1,-1),(0,1,1),(0,-1,1)],[(0,1,2,3)])
snap,result=plan(flat)
close(result.resolved_radius,1/math.tan(half))
verify_marker(snap,result)
horizontal=mesh([(-.2,-1,0),(.2,-1,0),(.2,1,0),(-.2,1,0)],[(0,1,2,3)])
snap,result=plan(horizontal)
close(result.resolved_radius,1/math.tan(half)+.2)
verify_marker(snap,result)
print('PASS vertical planes and coplanar triangles including edge contact')

# Broad bounds would leave an unnecessary gap because maximum depth and width
# occur on different pieces/heights. The real surfaces fit more closely.
pieces=mesh([(1,-2,0),(1,2,0),(1,2,1),(1,-2,1),
             (-1,-.1,10),(-1,.1,10),(-1,.1,11),(-1,-.1,11)],[(0,1,2,3),(4,5,6,7)])
snap,result=plan(pieces)
close(result.resolved_radius,2/math.tan(half)-1)
verify_marker(snap,result)
bound=core.build_plan(snap,config(fit_side='INSIDE'),bpy.context.scene)
assert bound.resolved_radius-result.resolved_radius>1.9
print('PASS disconnected pieces at different heights use real contact, not a convex or bounding envelope')

slanted=mesh([(2,-2,0),(2,2,0),(0,0,4)],[(0,1,2)])
snap,result=plan(slanted)
close(result.resolved_radius,2/math.tan(half)-1)
verify_marker(snap,result)
print('PASS slanted gable surfaces fit at their real lower corner')

snap,result=plan(cube,sweep=math.radians(350))
assert result.contact_info['seam_limited']
close(result.resolved_radius,1/math.tan(math.radians(5))+1,1e-4)
verify_marker(snap,result)
print('PASS end seam prevents overlap when an almost closed arc leaves a tighter final gap')

snap,result=plan(cube)
with patch.object(contact,'solve',wraps=contact.solve) as solve:
    again=core.build_plan(snap,config(),bpy.context.scene)
    assert solve.call_count==0
    core.build_plan(snap,config(sweep=-math.tau),bpy.context.scene)
    assert solve.call_count==1
print('PASS unchanged radius/contact reuses the snapshot cache')

uv=[tuple(d.uv) for d in cube.data.uv_layers.active.data]
matrix=cube.matrix_world.copy()
original=[v.co.copy() for v in cube.data.vertices]
select(cube)
copies=core.commit(bpy.context,snap,result,linked=True)
assert all(o.data==cube.data for o in copies)
for obj,pose in zip(copies,result.transforms):
    assert all(abs(x-y)<1e-5 for a,b in zip(obj.matrix_world,pose@matrix) for x,y in zip(a,b))
for obj in copies:bpy.data.objects.remove(obj,do_unlink=True)
assert cube.matrix_world==matrix and [v.co for v in cube.data.vertices]==original
assert [tuple(d.uv) for d in cube.data.uv_layers.active.data]==uv
print('PASS generated poses match contact preview and preserve source geometry and UVs')

# A fixed cursor changes the solved angle/count, never the center or original.
select(flat)
bpy.context.scene.cursor.location=(-4,0,0)
cursor=bpy.context.scene.cursor.location.copy()
snap=core.snapshot(bpy.context,geometry=True,contact=True)
for sweep in (math.tau,-math.tau):
    result=core.build_plan(snap,config(pivot='CURSOR',sweep=sweep),bpy.context.scene)
    close(abs(result.ring_info['step']),2*math.atan(1/4),1e-5)
    assert result.pivot==cursor and bpy.context.scene.cursor.location==cursor
    assert result.new_object_count==11
    verify_marker(snap,result)
print('PASS exact surface-contact angles around fixed cursor for both travel directions')

# Angular bounds can be too wide when the extremes belong to different
# disconnected heights. Conservative advancement closes that real surface gap.
select(pieces)
bpy.context.scene.cursor.location=(-4,0,0)
snap=core.snapshot(bpy.context,geometry=True,contact=True)
result=core.build_plan(snap,config(pivot='CURSOR'),bpy.context.scene)
close(result.ring_info['step'],2*math.atan(2/5),2e-5)
verify_marker(snap,result)
assert result.pivot==bpy.context.scene.cursor.location
print('PASS fixed-center fit uses real surfaces across disconnected heights')

scratch=Path(mkdtemp(dir=ROOT/'tests'/'_artifacts',prefix='contact_'))
ext.shortcuts._theme_path=lambda:scratch/'theme.json'
ext.shape_library._storage_override=scratch/'library'
ext.register()
try:
    cfg=ext.array_tool.settings();cfg.fit_side='CONTACT'
    assert cfg.fit_side=='CONTACT'
finally:ext.unregister()
print('ARRAY_CONTACT_PASS')
