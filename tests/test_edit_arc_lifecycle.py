"""Real expired Blender operator RNA must not truncate the sidebar or block reload."""
import sys,math
from pathlib import Path
from types import SimpleNamespace,FunctionType
from unittest.mock import patch
import bpy,bmesh
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import edit_arc as ea,live_reload as lr

for obj in bpy.context.selected_objects:obj.select_set(False)
mesh=bpy.data.meshes.new('Arc lifecycle fixture')
mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)],[],[(0,1,2,3)])
obj=bpy.data.objects.new('Arc lifecycle fixture',mesh);bpy.context.collection.objects.link(obj)
obj.select_set(True);bpy.context.view_layer.objects.active=obj;bpy.ops.object.mode_set(mode='EDIT')
bpy.context.tool_settings.mesh_select_mode=(False,True,False)
bm=bmesh.from_edit_mesh(mesh);bm.verts.ensure_lookup_table()
for f in bm.faces:f.select_set(False)
for e in bm.edges:e.select_set(False)
for v in bm.verts:v.select_set(False)
bm.edges.get((bm.verts[0],bm.verts[1])).select_set(True);bmesh.update_edit_mesh(mesh)
original=ea.signature(obj);selected=ea.selection(obj)
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D')

def execute_retired_fixture(self,context):
    # A real Blender operator is freed on FINISHED. Older versions left its
    # Python wrapper and private snapshot behind when history ended the tool.
    self._done=False;self._info=ea.capture(obj);self._valid=True;self._error=''
    self._wm=context.window_manager;self._area=area;self._obj=obj
    self._snapshot=bpy.data.meshes.new('Harhtools arc undo snapshot')
    bmesh.from_edit_mesh(mesh).to_mesh(self._snapshot)
    self._timer=self._wm.event_timer_add(.1,window=context.window)
    bpy.app.driver_namespace[ea.STATE]=self
    return {'FINISHED'}
ea.MESH_OT_harhtools_edit_arc.execute=execute_retired_fixture
ea.register()

class Layout:
    def __init__(self):self.calls=[]
    def box(self):return self
    def row(self):return self
    def label(self,**kw):self.calls.append(('label',kw.get('text')))
    def prop(self,owner,name,**kw):getattr(owner,name);self.calls.append(('prop',name))
    def operator(self,name,**kw):self.calls.append(('operator',name))
def retired():
    with bpy.context.temp_override(area=area):
        assert bpy.ops.mesh.harhtools_edit_arc('EXEC_DEFAULT')=={'FINISHED'}
    state=bpy.app.driver_namespace[ea.STATE]
    try:state._info
    except ReferenceError:pass
    else:raise AssertionError('Fixture must contain REAL expired operator RNA')
    return state

class Manager:
    harhtools_edit_arc=bpy.context.window_manager.harhtools_edit_arc
    def event_timer_add(self,*a,**kw):return object()
    def event_timer_remove(self,*a):pass
    def modal_handler_add(self,*a):pass
class Harness:pass
for name,method in vars(ea.MESH_OT_harhtools_edit_arc).items():
    if isinstance(method,FunctionType):setattr(Harness,name,method)
Harness.bl_idname=ea.MESH_OT_harhtools_edit_arc.bl_idname;Harness.report=lambda *a:None
ctx=SimpleNamespace(mode='EDIT_MESH',active_object=obj,window_manager=Manager(),window=None,
                    area=SimpleNamespace(regions=[],tag_redraw=lambda:None))
event=lambda kind:SimpleNamespace(type=kind,value='PRESS',mouse_x=0,mouse_y=0)
cfg=ctx.window_manager.harhtools_edit_arc
try:
    before=set(bpy.data.meshes);state=retired();record=object.__getattribute__(state,'__dict__')
    layout=Layout()
    scratch=record['_snapshot']
    ea.draw_panel(layout,bpy.context)
    assert set(bpy.data.meshes)==before|{scratch}  # No ID removal in panel drawing.
    assert ('operator','mesh.harhtools_edit_arc') in layout.calls
    assert not bpy.app.driver_namespace.get(ea.STATE)
    ea.cleanup_retired();assert set(bpy.data.meshes)==before and record['_done']
    assert ea.signature(obj)==original and ea.selection(obj)==selected
    # Slider callbacks and polling also recover if no panel has drawn yet.
    retired();cfg.amount=math.pi/2;ea.cleanup_retired();assert not bpy.app.driver_namespace.get(ea.STATE)
    retired();assert ea.MESH_OT_harhtools_edit_arc.poll(bpy.context);ea.cleanup_retired()
    retired();lr._busy_reason();assert not bpy.app.driver_namespace.get(ea.STATE);ea.cleanup_retired()
    assert set(bpy.data.meshes)==before and ea.signature(obj)==original
    # Undo and redo handlers finish before history replaces BMesh/RNA. They
    # must not restore a slider baseline on top of Blender's own undo result.
    assert ea.history_pre in bpy.app.handlers.undo_pre and ea.history_pre in bpy.app.handlers.redo_pre
    for _ in range(2):
        h=Harness();assert h.invoke(ctx,event('LEFTMOUSE'))=={'RUNNING_MODAL'}
        cfg.match_spacing=False;cfg.vertices=9;cfg.amount=math.pi;h.refresh();preview=ea.signature(obj)
        assert preview!=original and not h._error
        layout=Layout();ea.draw_panel(layout,bpy.context);assert ('prop','amount') in layout.calls
        ea.history_pre();assert h._done and ea.signature(obj)==preview
        assert not bpy.app.driver_namespace.get(ea.STATE) and set(bpy.data.meshes)==before
        assert h.modal(ctx,event('TIMER'))=={'CANCELLED'}
    # Blender's native cancel callback cleans up just like Escape.
    h=Harness();h.invoke(ctx,event('LEFTMOUSE'));baseline=ea.signature(obj)
    cfg.amount=math.pi/3;h.refresh();h.cancel(ctx)
    assert ea.signature(obj)==baseline and not bpy.app.driver_namespace.get(ea.STATE)
    # A modal exception is reported once and releases all private state.
    h=Harness();h.invoke(ctx,event('LEFTMOUSE'))
    with patch.object(h,'modal_event',side_effect=RuntimeError('injected modal failure')):
        assert h.modal(ctx,event('TIMER'))=={'CANCELLED'}
    ea.cleanup_retired();assert set(bpy.data.meshes)==before and not bpy.app.driver_namespace.get(ea.STATE)
    # Unregistration itself must survive a stale wrapper from an older release.
    retired()
finally:
    ea.unregister()
    del ea.MESH_OT_harhtools_edit_arc.execute
assert not bpy.app.driver_namespace.get(ea.STATE) and set(bpy.data.meshes)==before
assert not bpy.app.timers.is_registered(ea.cleanup_retired)
assert ea.history_pre not in bpy.app.handlers.undo_pre and ea.history_pre not in bpy.app.handlers.redo_pre
bpy.ops.object.mode_set(mode='OBJECT')
print('EDIT_ARC_LIFECYCLE_PASS: real expired operator RNA, read-only panel recovery, slider/poll/reload guards, Undo/Redo, native cancel, exception cleanup and unregister')
