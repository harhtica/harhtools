"""Selected bottom arc changes; unselected top, joins and cancel remain exact."""
import bpy,bmesh,sys,math
from pathlib import Path
from types import FunctionType,SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import edit_arc as ea
for obj in bpy.context.selected_objects:obj.select_set(False)
coords=[(0,2,0),(-.8,.4,0),(-1,0,0),(-.8,-.4,0),(0,-1,0),(.8,-.4,0),(1,0,0),(.8,.4,0)]
mesh=bpy.data.meshes.new('Pointed top and bottom');mesh.from_pydata(coords,[(i,(i+1)%8) for i in range(8)],[])
obj=bpy.data.objects.new('Pointed top and bottom',mesh);bpy.context.collection.objects.link(obj)
obj.select_set(True);bpy.context.view_layer.objects.active=obj;bpy.ops.object.mode_set(mode='EDIT')
bm=bmesh.from_edit_mesh(mesh);bm.verts.ensure_lookup_table();bm.verts.index_update()
for e in bm.edges:e.select_set(False)
for v in bm.verts:v.select_set(False)
for i in (3,4,5):bm.verts[i].select_set(True)
for e in bm.edges:
    if all(v.select for v in e.verts):e.select_set(True)
bmesh.update_edit_mesh(mesh)
original=[tuple(v.co) for v in bm.verts];info=ea.capture(obj)
assert info['indices']==[2,3,4,5,6] and info['wire'] and not info['closed']
snapshot=bpy.data.meshes.new('test snapshot');bm.to_mesh(snapshot)
rounded,closed=ea.positions(info,17,math.pi,1)
ea.write(obj,snapshot,info,rounded,closed);bm=bmesh.from_edit_mesh(mesh)
after=[tuple(v.co) for v in bm.verts]
for i in (0,1,2,6,7):assert original[i] in after,'Unselected top/joins moved'
assert len(after)==20
for point in rounded:assert abs(math.hypot(point[0],point[1])-1)<2e-6 and point[1]<1e-6
ea.write(obj,snapshot,info,info['coords'],info['closed']);bm=bmesh.from_edit_mesh(mesh)
assert [tuple(v.co) for v in bm.verts]==original
assert [v.index for v in bm.verts if v.select]==[3,4,5]
bpy.data.meshes.remove(snapshot)

ea.register()
class Manager:
    harhtools_edit_arc=bpy.context.window_manager.harhtools_edit_arc
    def event_timer_add(self,*a,**kw):return object()
    def event_timer_remove(self,*a):pass
    def modal_handler_add(self,*a):pass
class Harness:pass
Harness.bl_idname=ea.MESH_OT_harhtools_edit_arc.bl_idname
for name,method in vars(ea.MESH_OT_harhtools_edit_arc).items():
    if isinstance(method,FunctionType):setattr(Harness,name,method)
Harness.report=lambda *a:None
area=SimpleNamespace(regions=[],tag_redraw=lambda:None)
ctx=SimpleNamespace(mode='EDIT_MESH',active_object=obj,area=area,window_manager=Manager(),window=None)
event=lambda kind:SimpleNamespace(type=kind,value='PRESS',mouse_x=0,mouse_y=0)
try:
    before_meshes=set(bpy.data.meshes);h=Harness()
    assert h.invoke(ctx,event('LEFTMOUSE'))=={'RUNNING_MODAL'}
    cfg=ctx.window_manager.harhtools_edit_arc
    cfg.match_spacing=False
    for n in range(10,40):cfg.vertices=n
    assert h._dirty
    h.modal(ctx,event('TIMER'));assert not h._dirty
    assert h.modal(ctx,event('ESC'))=={'CANCELLED'}
    assert set(bpy.data.meshes)==before_meshes and not bpy.app.driver_namespace.get(ea.STATE)
    bm=bmesh.from_edit_mesh(mesh);assert [tuple(v.co) for v in bm.verts]==original
    h=Harness();assert h.invoke(ctx,event('LEFTMOUSE'))=={'RUNNING_MODAL'}
    cfg.amount=math.pi;cfg.vertices=17
    assert h.modal(ctx,event('RET'))=={'FINISHED'}
    assert set(bpy.data.meshes)==before_meshes
    bm=bmesh.from_edit_mesh(mesh);assert len(bm.verts)==20
    for i in (0,1,2,6,7):assert original[i] in [tuple(v.co) for v in bm.verts]

    # Rebuild the fixture as a filled face. Its selected bottom vertices can
    # round, but a resolution edit must not remove any face-connected vertex.
    bpy.ops.object.mode_set(mode='OBJECT')
    mesh.clear_geometry();mesh.from_pydata(coords,[],[tuple(range(8))]);mesh.update()
    bpy.ops.object.mode_set(mode='EDIT');bm=bmesh.from_edit_mesh(mesh);bm.verts.ensure_lookup_table()
    for f in bm.faces:f.select_set(False)
    for e in bm.edges:e.select_set(False)
    for v in bm.verts:v.select_set(False)
    for i in (3,4,5):bm.verts[i].select_set(True)
    original_signature=ea.signature(obj);h=Harness()
    assert h.invoke(ctx,event('LEFTMOUSE'))=={'RUNNING_MODAL'}
    assert not h._info['wire']
    cfg.amount=math.pi;cfg.vertices=100;h.refresh()
    bm=bmesh.from_edit_mesh(mesh);bm.verts.ensure_lookup_table()
    assert len(bm.verts)==8 and len(bm.faces)==1
    for i in (0,1,2,6,7):assert tuple(bm.verts[i].co)==original_signature[0][i]
    assert tuple(tuple(v.index for v in f.verts) for f in bm.faces)==original_signature[2]
    cfg.amount=math.tau;assert cfg.amount<math.tau-.001
    assert h.modal(ctx,event('ESC'))=={'CANCELLED'}
    assert ea.signature(obj)==original_signature

    # External geometry edits become the next slider baseline; Escape keeps
    # those edits while cancelling only subsequent slider changes.
    h=Harness();assert h.invoke(ctx,event('LEFTMOUSE'))=={'RUNNING_MODAL'}
    bm=bmesh.from_edit_mesh(mesh);bm.verts.ensure_lookup_table();bm.verts[0].co.z=.5
    bmesh.update_edit_mesh(mesh);external=ea.signature(obj)
    cfg.roundness=.25;h.refresh();assert not h._error
    h.modal(ctx,event('ESC'));assert ea.signature(obj)==external
    assert set(bpy.data.meshes)==before_meshes
finally:
    ea.unregister();bpy.ops.object.mode_set(mode='OBJECT')
print('EDIT_ARC_PASS: bottom-only circular preview, fixed top/joins, local resampling, exact cancellation/selection, modal coalescing, confirmation and scratch cleanup')
