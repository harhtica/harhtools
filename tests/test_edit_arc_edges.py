"""Selected face edges round independently without detaching or deleting faces."""
import math
import sys
import time
from pathlib import Path
from types import FunctionType,SimpleNamespace
import bpy
import bmesh
from mathutils import Matrix,Vector,Euler

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import edit_arc as ea

def fixture(points,faces,selected,edges=()):
    if bpy.context.mode=='EDIT_MESH':bpy.ops.object.mode_set(mode='OBJECT')
    for obj in bpy.context.selected_objects:obj.select_set(False)
    mesh=bpy.data.meshes.new('Face edge arc fixture');mesh.from_pydata(points,edges,faces)
    obj=bpy.data.objects.new('Face edge arc fixture',mesh);bpy.context.collection.objects.link(obj)
    obj.select_set(True);bpy.context.view_layer.objects.active=obj;bpy.ops.object.mode_set(mode='EDIT')
    bpy.context.tool_settings.mesh_select_mode=(False,True,False)
    bm=bmesh.from_edit_mesh(mesh);bm.select_mode={'EDGE'};bm.verts.ensure_lookup_table()
    for f in bm.faces:f.select=False
    for e in bm.edges:e.select=False
    for v in bm.verts:v.select=False
    for a,b in selected:bm.edges.get((bm.verts[a],bm.verts[b])).select_set(True)
    uv=bm.loops.layers.uv.new('Arc test UV')
    for f in bm.faces:
        f.material_index=3
        for loop in f.loops:loop[uv].uv=(loop.vert.co.x,loop.vert.co.y)
    bmesh.update_edit_mesh(mesh)
    snapshot=bpy.data.meshes.new('Face edge snapshot');bm.to_mesh(snapshot)
    return obj,snapshot

def apply(obj,snapshot,info,count=9,amount=math.pi):
    output=[ea.positions(item,count,amount,1) for item in ea.sections(info)]
    coords,closed=tuple(zip(*output)) if 'sections' in info else output[0]
    ea.write(obj,snapshot,info,coords,closed)
    return output

base=[(-1,-2,0),(1,-2,0),(1,2,0),(-1,2,0)]
# A single selected edge gains arc points while its corners and other geometry
# remain exact, including on small, rotated meshes and transformed objects.
cases=0
for scale in (1e-5,.005,1.):
    for rotation in (Matrix.Identity(4),Matrix.Rotation(math.pi/2,4,'Y'),Euler((.63,-.42,.38)).to_matrix().to_4x4()):
        matrix=Matrix.Translation((.013,-.019,.011))@rotation@Matrix.Diagonal((scale,scale,scale,1))
        points=[tuple(matrix@Vector(p)) for p in base]
        obj,snapshot=fixture(points,[(0,1,2,3)],[(0,1)])
        obj.matrix_world=Matrix.Translation((4,7,-2))@Euler((.3,.7,.2)).to_matrix().to_4x4()
        original=ea.signature(obj);selected=ea.selection(obj);info=ea.capture(obj)
        assert info['indices']==[0,1] and not info['wire'] and info['resample']
        apply(obj,snapshot,info)
        bm=bmesh.from_edit_mesh(obj.data);bm.verts.ensure_lookup_table()
        assert len(bm.verts)==11 and len(bm.edges)==11 and len(bm.faces)==1
        for i in range(4):assert tuple(bm.verts[i].co)==original[0][i]
        normal=rotation.to_3x3()@Vector((0,0,1));origin=Vector(original[0][0])
        assert max(abs((v.co-origin).dot(normal)) for v in bm.verts)<max(scale*2e-5,1e-8)
        assert all(len(e.link_faces)==1 for e in bm.edges)
        face=next(iter(bm.faces));assert face.material_index==3 and len(face.verts)==11
        uv=bm.loops.layers.uv['Arc test UV'];by_vertex={loop.vert:tuple(loop[uv].uv) for loop in face.loops}
        for i in range(4):assert by_vertex[bm.verts[i]]==original[0][i][:2]
        ea.write(obj,snapshot,info,None,None)
        assert ea.signature(obj)==original and ea.selection(obj)==selected
        bpy.data.meshes.remove(snapshot);cases+=1

# Two separate cap edges of the SAME filled plane round independently. Every
# original corner is selected, so the face itself must establish each plane.
obj,snapshot=fixture(base,[(0,1,2,3)],[(0,1),(2,3)])
info=ea.capture(obj);assert len(ea.sections(info))==2
original=ea.signature(obj);selected=ea.selection(obj)
output=apply(obj,snapshot,info,17)
assert output[0][0][8][1]<-2 and output[1][0][8][1]>2
bm=bmesh.from_edit_mesh(obj.data)
assert len(bm.verts)==34 and len(bm.faces)==1 and all(len(e.link_faces)==1 for e in bm.edges)
assert all(co in ea.signature(obj)[0] for co in original[0])
ea.write(obj,snapshot,info,None,None);assert ea.signature(obj)==original
bpy.data.meshes.remove(snapshot)

# Selected vertices alone would include the unselected closing edge and
# diagonal, falsely producing a branch. Only the three chosen edges count.
obj,snapshot=fixture(base,[(0,1,2),(0,2,3)],[(0,1),(1,2),(2,3)])
info=ea.capture(obj);assert info['indices']==[0,1,2,3] and not info['closed']
apply(obj,snapshot,info,19)
bm=bmesh.from_edit_mesh(obj.data);bm.verts.ensure_lookup_table()
assert len(bm.faces)==2 and len(bm.verts)==19
assert len(bm.edges.get((bm.verts[0],bm.verts[2])).link_faces)==2
assert not bm.edges.get((bm.verts[0],bm.verts[2])).select
small,_=ea.positions(info,3,math.pi,1);assert len(small)==4,'Deleted an existing face vertex'
ea.write(obj,snapshot,info,None,None)
# Changing selected edges with exactly the same selected vertices is detected.
before=ea.selection(obj);bm=bmesh.from_edit_mesh(obj.data);bm.verts.ensure_lookup_table()
bm.edges.get((bm.verts[0],bm.verts[2])).select=True
assert ea.selection(obj)!=before
try:ea.capture(obj)
except ValueError as exc:assert 'unbranched' in str(exc)
else:raise AssertionError('A genuinely branched edge selection was accepted')
bpy.data.meshes.remove(snapshot)

# An internal edge shares new points with BOTH adjacent faces; no crack,
# duplicate seam vertices or lost material assignments.
obj,snapshot=fixture(base,[(0,1,2),(0,2,3)],[(0,2)])
info=ea.capture(obj);apply(obj,snapshot,info,9,math.pi/6)
bm=bmesh.from_edit_mesh(obj.data)
assert len(bm.verts)==11 and len(bm.faces)==2
assert sum(e.select and len(e.link_faces)==2 for e in bm.edges)==8
assert all(f.material_index==3 and len(f.verts)==10 for f in bm.faces)
bpy.data.meshes.remove(snapshot)

# Modal behavior: start without edits, auto spacing, manual density, live
# recapture, exact Escape restoration, Ctrl+A commit and no leaked scratch mesh.
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
ctx=SimpleNamespace(mode='EDIT_MESH',window_manager=Manager(),window=None,
                    area=SimpleNamespace(regions=[],tag_redraw=lambda:None))
event=lambda kind,ctrl=False:SimpleNamespace(type=kind,value='PRESS',ctrl=ctrl,mouse_x=0,mouse_y=0)
cfg=ctx.window_manager.harhtools_edit_arc
try:
    obj,snapshot=fixture(base,[(0,1,2,3)],[(0,1),(2,3)]);bpy.data.meshes.remove(snapshot)
    ctx.active_object=obj;original=ea.signature(obj);selected=ea.selection(obj);before=set(bpy.data.meshes)
    h=Harness();assert h.invoke(ctx,event('LEFTMOUSE'))=={'RUNNING_MODAL'}
    assert ea.signature(obj)==original
    cfg.match_spacing=False;cfg.vertices=17;cfg.amount=math.pi;h.refresh()
    assert not h._error and len(bmesh.from_edit_mesh(obj.data).verts)==34,h._error
    cfg.vertices=9;h.refresh();assert len(bmesh.from_edit_mesh(obj.data).verts)==18
    assert h.modal(ctx,event('ESC'))=={'CANCELLED'}
    assert ea.signature(obj)==original and ea.selection(obj)==selected and set(bpy.data.meshes)==before
    h=Harness();h.invoke(ctx,event('LEFTMOUSE'));cfg.vertices=17;cfg.amount=math.pi
    assert h.modal(ctx,event('A',True))=={'FINISHED'}
    assert len(bmesh.from_edit_mesh(obj.data).verts)==34 and set(bpy.data.meshes)==before
    h=Harness();h.invoke(ctx,event('LEFTMOUSE'))
    bm=bmesh.from_edit_mesh(obj.data)
    for v in bm.verts:
        if v.select and abs(v.co.y)>2.01:v.co.y*=1.05
    bmesh.update_edit_mesh(obj.data);manual=ea.signature(obj)
    h.observe_mesh();assert h._valid and ea.signature(obj)==manual
    cfg.amount=math.pi*.7;h.refresh();assert not h._error,h._error
    h.modal(ctx,event('ESC'));assert ea.signature(obj)==manual
    # Large single edge resampling exercises native edge splits, not a rewrite
    # of surrounding topology, and remains responsive.
    obj,snapshot=fixture(base,[(0,1,2,3)],[(0,1)]);ctx.active_object=obj
    bpy.data.meshes.remove(snapshot);original=ea.signature(obj)
    h=Harness();h.invoke(ctx,event('LEFTMOUSE'));cfg.match_spacing=True;cfg.amount=math.pi;h.refresh()
    assert cfg.vertices==3 and not h._error
    cfg.match_spacing=False;cfg.vertices=2048
    started=time.perf_counter();h.refresh();elapsed=time.perf_counter()-started
    assert not h._error and len(bmesh.from_edit_mesh(obj.data).verts)==2050 and elapsed<1.,(h._error,elapsed)
    h.modal(ctx,event('ESC'));assert ea.signature(obj)==original
finally:
    ea.unregister()
    if bpy.context.mode=='EDIT_MESH':bpy.ops.object.mode_set(mode='OBJECT')
print(f'EDIT_ARC_EDGES_PASS: {cases} plane/scale cases, independent face caps, explicit edge selection, shared face subdivision, custom data, live edits, cancel, Ctrl+A; 2048 points {elapsed*1000:.1f} ms')
