"""Straight/subdivided arcs stay in the connected shape's plane at every orientation."""
import sys,math,json
from pathlib import Path
from types import FunctionType,SimpleNamespace
import bpy,bmesh
from mathutils import Matrix,Vector,Euler
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import edit_arc as ea
BASE=[(-1,-1,0),(-.5,-1,0),(0,-1,0),(.5,-1,0),(1,-1,0),(1,1,0),(-1,1,0)]
def fixture(points,selected,faces=False,closed=True):
    if bpy.context.mode=='EDIT_MESH':bpy.ops.object.mode_set(mode='OBJECT')
    for obj in bpy.context.selected_objects:obj.select_set(False)
    mesh=bpy.data.meshes.new('Arc plane fixture')
    edges=[(i,i+1) for i in range(len(points)-1)]+([(len(points)-1,0)] if closed else [])
    mesh.from_pydata(points,edges,[tuple(range(len(points)))] if faces else [])
    obj=bpy.data.objects.new('Arc plane fixture',mesh);bpy.context.collection.objects.link(obj)
    obj.select_set(True);bpy.context.view_layer.objects.active=obj;bpy.ops.object.mode_set(mode='EDIT')
    bm=bmesh.from_edit_mesh(mesh);bm.verts.ensure_lookup_table()
    for face in bm.faces:face.select_set(False)
    for edge in bm.edges:edge.select=False
    for i,vertex in enumerate(bm.verts):vertex.select=i in selected
    for edge in bm.edges:
        if all(v.select for v in edge.verts):edge.select=True
    bmesh.update_edit_mesh(mesh)
    return obj

def assert_plane(points,origin,normal,tolerance):
    error=max(abs((Vector(p)-origin).dot(normal)) for p in points)
    assert error<tolerance,(error,tolerance)
    return error

axes=[Matrix.Identity(4),Matrix.Rotation(math.pi/2,4,'X'),Matrix.Rotation(math.pi/2,4,'Y'),Euler((.61,-.39,.87)).to_matrix().to_4x4()]
errors=[]
for scale in (1e-5,.003,1.,100.):
    for rotation in axes:
        transform=Matrix.Translation((.017,-.029,.013))@rotation@Matrix.Diagonal((scale,scale,scale,1.))
        points=[tuple(transform@Vector(p)) for p in BASE]
        for faces in (False,True):
            obj=fixture(points,{1,2,3},faces=faces)
            original=ea.signature(obj);info=ea.capture(obj)
            assert info['plane_source']=='Surrounding shape'
            normal=rotation.to_3x3()@Vector((0,0,1));origin=Vector(points[0])
            for reverse in (False,True):
                arc,closed=ea.positions(info,17,math.pi,1,reverse)
                errors.append(assert_plane(arc,origin,normal,max(scale*1e-5,1e-8)))
                assert arc[0]==info['coords'][0] and arc[-1]==info['coords'][-1]
                # Bend direction is in-plane and away from the untouched top.
                toward=rotation.to_3x3()@Vector((0,1,0))
                assert ((Vector(arc[len(arc)//2])-origin).dot(toward)>0)==reverse
            assert ea.signature(obj)==original,'Capture/preview changed the input mesh'
            snapshot=bpy.data.meshes.new('test source');bmesh.from_edit_mesh(obj.data).to_mesh(snapshot)
            arc,closed=ea.positions(info,17,math.pi,1);ea.write(obj,snapshot,info,arc,closed)
            result=ea.signature(obj)
            assert all(original[0][i] in result[0] for i in (0,4,5,6))
            assert_plane(result[0],origin,normal,max(scale*1e-5,1e-8))
            obj.matrix_world=Matrix.Translation((35,-12,19))@Euler((.31,.71,-.9)).to_matrix().to_4x4()@Matrix.Diagonal((2.,.6,1.4,1.))
            world_normal=(obj.matrix_world.to_3x3().inverted().transposed()@normal).normalized()
            assert_plane([tuple(obj.matrix_world@Vector(p)) for p in result[0]],obj.matrix_world@origin,world_normal,max(scale*2e-5,5e-6))
            ea.write(obj,snapshot,info,info['coords'],info['closed']);assert ea.signature(obj)==original
            bpy.data.meshes.remove(snapshot)

# Geometry accidentally bent off-plane by the old fallback uses the untouched
# outline to recover its plane. Only adjusted vertices are projected, on edit.
bad=list(BASE);bad[1]=(-.5,-1,.2);bad[2]=(0,-1,.4);bad[3]=(.5,-1,.2)
obj=fixture(bad,{1,2,3});info=ea.capture(obj);assert info['plane_source']=='Surrounding shape'
arc,_=ea.positions(info,9,math.pi,1);assert all(abs(p[2])<1e-7 for p in arc)

# Disconnected geometry in the same mesh must not control the selected plane.
bm=bmesh.from_edit_mesh(obj.data);a=bm.verts.new((20,0,0));b=bm.verts.new((20,0,20));c=bm.verts.new((20,20,20))
bm.edges.new((a,b));bm.edges.new((b,c));bmesh.update_edit_mesh(obj.data)
assert abs(Vector(ea.capture(obj)['normal']).z)>.999

# A tiny isolated *curved* section has a valid plane despite its small radius.
tiny=[(0,1e-6*math.cos(i*math.pi/8),1e-6*math.sin(i*math.pi/8)) for i in range(9)]
obj=fixture(tiny,set(range(9)),closed=False);info=ea.capture(obj)
assert info['plane_source']=='Selected curve'
arc,_=ea.positions(info,17,math.pi,1);assert all(abs(p[0])<1e-12 for p in arc)
straight=[tuple(Vector(tiny[0]).lerp(Vector(tiny[-1]),i/8)) for i in range(9)]
flat=ea.frame(straight,False,[],'AUTO',info)
assert flat['plane_source']=='Previous plane' and abs(flat['normal'][0])>.999

# Isolated straight lines require an explicit object plane, not an arbitrary
# global-axis guess. The fixed endpoints prevent an incompatible override.
line=[(-1,0,0),(-.5,0,0),(0,0,0),(.5,0,0),(1,0,0)]
obj=fixture(line,set(range(5)),closed=False);original=ea.signature(obj)
try:ea.capture(obj)
except ValueError as exc:assert 'no unique arc plane' in str(exc)
else:raise AssertionError('Auto guessed an unsupported plane')
assert ea.signature(obj)==original
for plane,coordinate in (('XY',2),('XZ',1)):
    info=ea.capture(obj,plane);arc,_=ea.positions(info,9,math.pi,1)
    assert all(abs(p[coordinate])<1e-7 for p in arc)
try:ea.capture(obj,'YZ')
except ValueError as exc:assert 'fixed endpoints' in str(exc)
else:raise AssertionError('An override moved the fixed endpoints')

ea.register()
class Manager:
    harhtools_edit_arc=bpy.context.window_manager.harhtools_edit_arc
    def event_timer_add(self,*a,**kw):return object()
    def event_timer_remove(self,*a):pass
    def modal_handler_add(self,*a):pass
class Harness:pass
for name,method in vars(ea.MESH_OT_harhtools_edit_arc).items():
    if isinstance(method,FunctionType):setattr(Harness,name,method)
Harness.bl_idname=ea.MESH_OT_harhtools_edit_arc.bl_idname;Harness.report=lambda *a:None
cfg=bpy.context.window_manager.harhtools_edit_arc
ctx=SimpleNamespace(mode='EDIT_MESH',active_object=obj,window_manager=Manager(),area=SimpleNamespace(regions=[],tag_redraw=lambda:None),window=None)
event=lambda name:SimpleNamespace(type=name,value='PRESS',mouse_x=0,mouse_y=0)
try:
    # Recapturing a straight section after a manual subdivide retains the
    # surrounding plane; plane overrides can change during the same preview.
    obj=fixture(BASE,{1,2,3});ctx.active_object=obj;cfg.plane='AUTO';h=Harness()
    assert h.invoke(ctx,event('LEFTMOUSE'))=={'RUNNING_MODAL'}
    bpy.ops.mesh.subdivide(number_cuts=2,smoothness=0);manual=ea.signature(obj)
    h._next_tick=0;h.modal(ctx,event('TIMER'));assert h._info['plane_source']=='Surrounding shape'
    cfg.amount=math.pi;h.refresh();assert not h._error
    assert all(abs(p[2])<1e-7 for p in ea.signature(obj)[0])
    h.modal(ctx,event('ESC'));assert ea.signature(obj)==manual
    obj=fixture(line,set(range(5)),closed=False);ctx.active_object=obj;cfg.plane='XY';h=Harness();h.invoke(ctx,event('LEFTMOUSE'))
    cfg.amount=math.pi;h.refresh();cfg.plane='XZ';h.refresh();assert not h._error
    assert all(abs(p[1])<1e-7 for p in ea.signature(obj)[0])
    cfg.plane='YZ';h.refresh();assert h._error
    cfg.plane='XY';h.refresh();assert not h._error
    h.modal(ctx,event('ESC'));assert ea.signature(obj)==original
finally:ea.unregister();bpy.ops.object.mode_set(mode='OBJECT')
print('EDIT_ARC_PLANE_PASS: 32 orientations/scales/wire-face fixtures, transformed world planes, fixed joins, reverse, off-plane recovery, disconnected guides, tiny curves, explicit planes and live subdivision')
