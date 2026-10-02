"""World-space edge copying, snap capture/feedback and native RNA registration."""
import sys,math
from pathlib import Path
from types import SimpleNamespace,FunctionType
from unittest.mock import patch
import bpy
from mathutils import Vector,Matrix,Euler
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_pick as p, outline_tool as ot, outline_snap as s

for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
data=bpy.data.meshes.new('Width edge');data.from_pydata([(0,0,0),(1,0,0)],[(0,1)],[])
obj=bpy.data.objects.new('Width edge',data);bpy.context.collection.objects.link(obj)
obj.matrix_world=Matrix.Translation((-.5,0,.1))@Euler((.4,.2,.3)).to_matrix().to_4x4()@Matrix.Diagonal((.24,3.,2.,1.))
obj.select_set(True);bpy.context.view_layer.objects.active=obj;bpy.context.view_layer.update()
region=SimpleNamespace(x=0,y=0,width=1000,height=800,type='WINDOW')
view=SimpleNamespace(perspective_matrix=Matrix.Identity(4))
def screen(point):return (region.width*.5*(1+point[0]),region.height*.5*(1+point[1]))
a,b=[obj.matrix_world@v.co for v in obj.data.vertices];mouse=screen((a+b)*.5)
cache=p.EdgeLengthCache(bpy.context);hit=cache.query(mouse,region,view)
assert abs(hit['thickness']-.24)<1e-6
assert hit['target_world_points']==[tuple(a),tuple(b)]
key=cache._screen_key;grid=cache._grid
for _ in range(200):assert cache.query(mouse,region,view)
assert cache._grid is grid and cache._screen_key==key
obj.hide_set(True);assert cache.query(mouse,region,view) is None;obj.hide_set(False)
data.vertices[1].co.x=2;assert cache.query(mouse,region,view) is None;data.vertices[1].co.x=1
obj.hide_select=True;assert cache.query(mouse,region,view) is None;obj.hide_select=False

# Wide capture radius and exact target geometry are available to draw feedback.
obj.select_set(False);obj.matrix_world=Matrix.Translation((0,.5,0));bpy.context.view_layer.update()
snap=s.OutlineSnapCache(bpy.context,(0,0,0),(0,0,1),2,[[(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)]],pixel_tolerance=22)
near=(600,617) # target at y=600; 17 pixels away, beyond the old 12px capture.
hit=snap.query(near,region,view)
assert hit and abs(hit['pixel_distance']-17)<1e-5
assert hit['target_world_points']==[(0.,.5,0.),(1.,.5,0.)]
assert snap.query((600,625),region,view) is None

class Harness:pass
for name,method in vars(p.VIEW3D_OT_harhtools_copy_thickness).items():
    if isinstance(method,FunctionType):setattr(Harness,name,method)
handlers=[];timers=[];removed=[];status=[]
area=SimpleNamespace(type='VIEW_3D',regions=[region],spaces=SimpleNamespace(active=SimpleNamespace(region_3d=view)),tag_redraw=lambda:None)
manager=SimpleNamespace(event_timer_add=lambda *a,**kw:timers.append(object()) or timers[-1],event_timer_remove=removed.append,modal_handler_add=lambda op:None,
                       harhtools_outline=None)
ctx=SimpleNamespace(mode='OBJECT',area=area,window_manager=manager,window=SimpleNamespace(cursor_modal_set=lambda *a:None,cursor_modal_restore=lambda:None),
                    workspace=SimpleNamespace(status_text_set=status.append),view_layer=bpy.context.view_layer,preferences=bpy.context.preferences,
                    evaluated_depsgraph_get=bpy.context.evaluated_depsgraph_get,scene=bpy.context.scene)
space=SimpleNamespace(draw_handler_add=lambda *a:handlers.append(object()) or handlers[-1],draw_handler_remove=lambda h,*a:handlers.remove(h))
fake=SimpleNamespace(app=bpy.app,context=ctx,types=SimpleNamespace(SpaceView3D=space))
def event(kind,x=600,y=600):return SimpleNamespace(type=kind,value='PRESS',mouse_x=x,mouse_y=y)
ot.register()
try:
    manager.harhtools_outline=ot.settings();cfg=ot.settings();assert cfg.safe_inset
    before=(list(bpy.data.objects),tuple(v.co[:] for v in data.vertices))
    with patch.object(p,'bpy',fake):
        parent=SimpleNamespace(_dragging=True,_pending_mouse=(2,3),_snap_hit=hit,_measure=(a,b),request_refresh=lambda ctx:None)
        bpy.app.driver_namespace[ot.STATE_KEY]=parent
        h=Harness();h.report=lambda *a:None
        assert h.invoke(ctx,event('MOUSEMOVE'))=={'RUNNING_MODAL'}
        assert not parent._dragging and parent._pending_mouse is None
        assert ot.VIEW3D_OT_harhtools_make_outline.modal(SimpleNamespace(_done=False),ctx,event('ESC'))=={'PASS_THROUGH'}
        assert h.modal(ctx,event('LEFTMOUSE'))=={'FINISHED'}
        assert abs(cfg.thickness-1)<1e-6 and not handlers and not bpy.app.driver_namespace.get(p.STATE_KEY)
        bpy.app.driver_namespace.pop(ot.STATE_KEY)
        h=Harness();h.report=lambda *a:None;h.invoke(ctx,event('MOUSEMOVE'))
        assert h.modal(ctx,event('ESC'))=={'CANCELLED'}
        assert abs(cfg.thickness-1)<1e-6 and len(removed)==2
    assert before==(list(bpy.data.objects),tuple(v.co[:] for v in data.vertices))
finally:
    bpy.app.driver_namespace.pop(ot.STATE_KEY,None);ot.unregister()
print('PICK PASS: transformed length, selected edges, capture, cache, stale/hidden filtering, nested modal, cancel, no scene edits')
