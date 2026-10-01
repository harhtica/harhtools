"""Live manual vertex edits, anchored resampling and adjoining edge density."""
import sys,math,time
from pathlib import Path
from types import FunctionType,SimpleNamespace
from unittest.mock import patch
import bpy,bmesh
from mathutils import Matrix,Vector
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import edit_arc as ea
for obj in bpy.context.selected_objects:obj.select_set(False)
coords=[(math.cos(i*math.tau/64),math.sin(i*math.tau/64),0) for i in range(64)]
mesh=bpy.data.meshes.new('64 sample circle');mesh.from_pydata(coords,[(i,(i+1)%64) for i in range(64)],[])
obj=bpy.data.objects.new('Arc density fixture',mesh);bpy.context.collection.objects.link(obj)
obj.select_set(True);bpy.context.view_layer.objects.active=obj;bpy.ops.object.mode_set(mode='EDIT')
bm=bmesh.from_edit_mesh(mesh);bm.verts.ensure_lookup_table()
for edge in bm.edges:edge.select_set(False)
for vertex in bm.verts:vertex.select_set(False)
for i in range(1,32):bm.verts[i].select_set(True)
bmesh.update_edit_mesh(mesh)
original=ea.signature(obj);selected=ea.selection(obj)
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
ctx=SimpleNamespace(mode='EDIT_MESH',active_object=obj,window_manager=Manager(),
                    area=SimpleNamespace(regions=[],tag_redraw=lambda:None),window=SimpleNamespace(modal_operators=[]))
cfg=ctx.window_manager.harhtools_edit_arc
event=lambda kind:SimpleNamespace(type=kind,value='PRESS',mouse_x=0,mouse_y=0)
def tick(h):h._next_tick=0;h.modal(ctx,event('TIMER'))
def outside():
    bm=bmesh.from_edit_mesh(mesh)
    return sorted(tuple(v.co) for v in bm.verts if not v.select)
def restore():
    bpy.ops.object.mode_set(mode='OBJECT');mesh.clear_geometry()
    mesh.from_pydata(coords,[(i,(i+1)%64) for i in range(64)],[]);mesh.update()
    bpy.ops.object.mode_set(mode='EDIT');bm=bmesh.from_edit_mesh(mesh);bm.verts.ensure_lookup_table()
    for e in bm.edges:e.select_set(False)
    for v in bm.verts:v.select_set(False)
    for i in range(1,32):bm.verts[i].select_set(True)
    bmesh.update_edit_mesh(mesh)
try:
    before=set(bpy.data.meshes);h=Harness();h.invoke(ctx,event('LEFTMOUSE'))
    assert ea.signature(obj)==original,'Starting controls must not reshape the mesh'
    assert cfg.match_spacing and abs(h._info['spacing']-2*math.sin(math.pi/64))<1e-6
    fixed=outside();cfg.amount=math.pi;cfg.roundness=.999;tick(h)
    assert cfg.vertices==33 and len(bmesh.from_edit_mesh(mesh).verts)==64
    cfg.roundness=1;cfg.amount=math.pi/2;tick(h)
    assert cfg.vertices==24 and outside()==fixed,(cfg.vertices,len(outside()),len(fixed),h._error,[(p,p in fixed) for p in outside() if p not in fixed])
    cfg.amount=math.pi*1.5;tick(h)
    assert cfg.vertices==69 and outside()==fixed
    # All selected points lie on the circular target, and untouched join
    # vertices remain unselected through topology replacement.
    for vertex in bmesh.from_edit_mesh(mesh).verts:
        if vertex.select:assert abs((vertex.co-Vector((0,1,0))).length-math.sqrt(2))<3e-6
    h.modal(ctx,event('ESC'));assert ea.signature(obj)==original and ea.selection(obj)==selected
    # Blender's G/R/S/selection events pass through, and transform completion
    # is observed before the next arc change. No writes while a transform runs.
    h=Harness();h.invoke(ctx,event('LEFTMOUSE'))
    for kind in ('G','R','S','LEFTMOUSE','B','RIGHTMOUSE'):assert h.modal(ctx,event(kind))=={'PASS_THROUGH'}
    ctx.window.modal_operators=[SimpleNamespace(bl_idname='TRANSFORM_OT_translate')]
    bpy.ops.transform.translate(value=(0,.3,0))
    manual=ea.signature(obj)
    with patch.object(h,'observe_mesh',side_effect=AssertionError('Do not observe mid-transform')):tick(h)
    assert ea.signature(obj)==manual
    ctx.window.modal_operators=[];tick(h)
    assert ea.signature(obj)==manual and abs(cfg.amount-math.pi)>.1 and h._valid
    cfg.amount=math.pi/2;tick(h);assert ea.signature(obj)!=manual and outside()==fixed
    h.modal(ctx,event('ESC'));assert ea.signature(obj)==manual,'Cancel overwrote manual vertex edit'
    # A changed selection is recaptured. Invalid selections pause cleanly and
    # can recover without leaving the tool or rewriting any mesh data.
    restore();h=Harness();h.invoke(ctx,event('LEFTMOUSE'))
    bm=bmesh.from_edit_mesh(mesh)
    for v in bm.verts:v.select_set(False)
    bmesh.update_edit_mesh(mesh);tick(h);assert not h._valid and h._error
    invalid=ea.signature(obj);cfg.amount=1;tick(h);assert ea.signature(obj)==invalid
    bm.verts.ensure_lookup_table()
    for i in range(33,64):bm.verts[i].select_set(True)
    bmesh.update_edit_mesh(mesh);tick(h);assert h._valid and not h._error
    cfg.amount=math.pi/2;tick(h);assert cfg.vertices==24
    h.finish()
    # Manual count remains available. Counts cap at the supported range.
    restore();h=Harness();h.invoke(ctx,event('LEFTMOUSE'))
    cfg.match_spacing=False;cfg.vertices=17;cfg.amount=math.pi;tick(h)
    assert cfg.vertices==17 and len(bmesh.from_edit_mesh(mesh).verts)==48
    h.modal(ctx,event('ESC'));assert ea.signature(obj)==original
    # Compare world-space arc length against world-space neighbor spacing
    # under nonuniform scale. Using local units here would give a wrong count.
    obj.matrix_world=Matrix.Diagonal((3.,.5,1.,1.));info=ea.capture(obj)
    cfg.match_spacing=True;cfg.amount=math.pi
    count=ea.matched_count(obj,info,cfg)
    assert count!=33 and 3<=count<=2048
    tiny=dict(info,spacing=1e-10);assert ea.matched_count(obj,tiny,cfg)==2048
    obj.matrix_world=Matrix.Identity(4)
    # Selection recapture and large counts stay responsive on the fixture.
    h=Harness();h.invoke(ctx,event('LEFTMOUSE'));cfg.match_spacing=False;cfg.vertices=2048
    started=time.perf_counter();tick(h);elapsed=time.perf_counter()-started
    assert cfg.vertices==2048 and elapsed<1.,elapsed
    h.modal(ctx,event('ESC'))
    assert set(bpy.data.meshes)==before and ea.signature(obj)==original
finally:
    ea.unregister();bpy.ops.object.mode_set(mode='OBJECT')
print(f'EDIT_ARC_LIVE_PASS: manual edits, fixed anchors, 64-circle density matching, auto/manual counts, transform guard, selection recovery, scale, cancellation; 2048 vertices {elapsed*1000:.1f} ms')
