"""Read-only edge-length picking and visible outline snap feedback."""
import math
import time
from collections import defaultdict
import bpy
from mathutils import Vector
from . import outline_snap, display_units

STATE_KEY='harhtools_outline_measure'


def draw_feedback(hit,region,view,label,measure=None):
    """Draw in pixels so the target stays legible at every zoom and orientation."""
    if not hit:return
    import gpu,blf
    from gpu_extras.batch import batch_for_shader
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    def project(p):return location_3d_to_region_2d(region,view,Vector(p))
    scale=max(1.,bpy.context.preferences.system.ui_scale)
    points=[project(p) for p in hit['target_world_points']]
    lines=[(p.x,p.y,0.) for a,b in zip(points,points[1:]) if a is not None and b is not None for p in (a,b)]
    center=project(hit['world_point'])
    if center is None:return
    x,y=center;r=7*scale
    marker=[(x-r,y,0),(x,y+r,0),(x,y+r,0),(x+r,y,0),
            (x+r,y,0),(x,y-r,0),(x,y-r,0),(x-r,y,0)]
    distance_line=[]
    if measure:
        a,b=(project(p) for p in measure)
        if a is not None and b is not None:distance_line=[(*a,0),(*b,0)]
    shader=gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    old=(gpu.state.blend_get(),gpu.state.depth_test_get(),gpu.state.depth_mask_get())
    try:
        gpu.state.blend_set('ALPHA');gpu.state.depth_test_set('NONE');gpu.state.depth_mask_set(False)
        shader.bind();shader.uniform_float('viewportSize',gpu.state.viewport_get()[2:])
        for width,color in ((6,(.015,.02,.025,.95)),(3,(.15,1.,.8,1.))):
            shader.uniform_float('lineWidth',width*scale);shader.uniform_float('color',color)
            batch_for_shader(shader,'LINES',{'pos':lines+marker}).draw(shader)
        if distance_line:
            shader.uniform_float('lineWidth',1.5*scale);shader.uniform_float('color',(1.,1.,1.,1.))
            batch_for_shader(shader,'LINES',{'pos':distance_line}).draw(shader)
    finally:
        gpu.state.blend_set(old[0]);gpu.state.depth_test_set(old[1]);gpu.state.depth_mask_set(old[2])
    blf.size(0,round(13*scale));text_width,text_height=blf.dimensions(0,label)
    tx=max(8*scale,min(x+14*scale,region.width-text_width-8*scale))
    ty=max(8*scale,min(y+18*scale,region.height-text_height-8*scale))
    blf.position(0,tx+scale,ty-scale,0);blf.color(0,0,0,0,1);blf.draw(0,label)
    blf.position(0,tx,ty,0);blf.color(0,.3,1.,.85,1);blf.draw(0,label)


class EdgeLengthCache:
    """Snapshot selectable straight edges once; rebuild screen tiles only on view changes."""
    def __init__(self,context):
        self.context=context;self.edges=[];self._screen_key=None
        allowed=outline_snap._selectable_paths(context)
        depsgraph=context.evaluated_depsgraph_get()
        for obj in context.view_layer.objects:
            if obj.type not in {'MESH','CURVE'} or obj.hide_select or obj.as_pointer() not in allowed or not obj.visible_get():continue
            evaluated=obj.evaluated_get(depsgraph);matrix=evaluated.matrix_world.copy()
            def add(a,b,sample=None):
                a,b=tuple(matrix@a),tuple(matrix@b);length=math.dist(a,b)
                if not math.isfinite(length) or length<=1e-6:return
                self.edges.append(dict(object=obj,object_name=obj.name,a=a,b=b,length=length,
                    matrix=tuple(v for row in matrix for v in row),data=obj.data,sample=sample,paths=allowed[obj.as_pointer()]))
            if obj.type=='MESH':
                data=evaluated.to_mesh()
                try:
                    for edge in data.edges:
                        a,b=(data.vertices[i] for i in edge.vertices)
                        if edge.hide or a.hide or b.hide:continue
                        sample=(edge.index,tuple((int(i),tuple(obj.data.vertices[i].co)) for i in edge.vertices)) if not obj.modifiers else None
                        add(a.co,b.co,sample)
                finally:evaluated.to_mesh_clear()
            else:
                # A curved Bezier segment has no single straight edge length.
                # POLY segments (including generated borders) do.
                for spline in evaluated.data.splines:
                    if spline.type!='POLY':continue
                    pts=spline.points
                    for i in range(len(pts) if spline.use_cyclic_u else len(pts)-1):
                        a,b=pts[i],pts[(i+1)%len(pts)]
                        if not a.hide and not b.hide:add(a.co.xyz,b.co.xyz)

    def _live(self,edge):
        try:
            obj=edge['object']
            if obj.name!=edge['object_name'] or obj.data!=edge['data'] or obj.hide_select or not obj.visible_get():return False
            if tuple(v for row in obj.matrix_world for v in row)!=edge['matrix']:return False
            if not any(all(not (l.exclude or l.hide_viewport or l.collection.hide_viewport or l.collection.hide_select) for l in path) for path in edge['paths']):return False
            if edge['sample']:
                index,vertices=edge['sample']
                if obj.data.edges[index].hide or any(obj.data.vertices[i].hide or tuple(obj.data.vertices[i].co)!=co for i,co in vertices):return False
            return True
        except (ReferenceError,IndexError,RuntimeError):return False

    def query(self,mouse,region,view):
        scale=max(1.,self.context.preferences.system.ui_scale);radius=22*scale;tile=radius*2
        key=(region.width,region.height,tuple(v for row in view.perspective_matrix for v in row),scale)
        if key!=self._screen_key:
            self._screen_key=key;self._grid=defaultdict(set);self._projected={}
            for i,edge in enumerate(self.edges):
                clips=[view.perspective_matrix@Vector((*edge[k],1)) for k in ('a','b')]
                if any(p.w<=1e-10 for p in clips):continue
                a,b=[(region.width*.5*(1+p.x/p.w),region.height*.5*(1+p.y/p.w)) for p in clips]
                self._projected[i]=(a,b,clips[0].w,clips[1].w)
                xmin=max(-radius,min(a[0],b[0])-radius);xmax=min(region.width+radius,max(a[0],b[0])+radius)
                ymin=max(-radius,min(a[1],b[1])-radius);ymax=min(region.height+radius,max(a[1],b[1])+radius)
                for x in range(math.floor(xmin/tile),math.floor(xmax/tile)+1):
                    for y in range(math.floor(ymin/tile),math.floor(ymax/tile)+1):self._grid[x,y].add(i)
        best=None
        for i in sorted(self._grid.get((math.floor(mouse[0]/tile),math.floor(mouse[1]/tile)),())):
            a,b,w0,w1=self._projected[i];screen,fraction,distance=outline_snap.nearest_on_segment(mouse,a,b)
            if distance>radius*radius or best and distance>=best['distance']:continue
            edge=self.edges[i]
            if not self._live(edge):continue
            t=fraction*w0/(w1*(1-fraction)+fraction*w0)
            best=dict(distance=distance,thickness=edge['length'],object_name=edge['object_name'],
                target_world_points=[edge['a'],edge['b']],world_point=outline_snap._point((edge['a'],edge['b']),t))
        return best


class VIEW3D_OT_harhtools_copy_thickness(bpy.types.Operator):
    bl_idname='view3d.harhtools_copy_thickness'
    bl_label='Copy Thickness'
    bl_description='Click a mesh edge or straight Poly segment to copy its world-space length as outline thickness'
    bl_options={'INTERNAL'}

    @classmethod
    def poll(cls,context):
        return context.mode=='OBJECT' and context.area and context.area.type=='VIEW_3D' and not any(
            bpy.app.driver_namespace.get(k) for k in (STATE_KEY,'arch_tools_shape_builder','harhtools_array_preview','harhtools_arc_preview'))

    def invoke(self,context,event):
        self._done=False;self._handler=None;self._timer=None;self._hit=None;self._pending=None;self._next=0
        self._area=context.area;self._wm=context.window_manager;self._window=context.window;self._workspace=context.workspace
        self._region=next(r for r in self._area.regions if r.type=='WINDOW');self._view=self._area.spaces.active.region_3d
        try:
            self._cache=EdgeLengthCache(context)
            if not self._cache.edges:raise ValueError('No visible mesh edges or straight Poly segments to measure.')
            from . import outline_tool
            parent=bpy.app.driver_namespace.get(outline_tool.STATE_KEY)
            if parent:
                parent._dragging=False;parent._pending_mouse=None;parent._snap_hit=None;parent._measure=None
            bpy.app.driver_namespace[STATE_KEY]=self
            self._handler=bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay,(),'WINDOW','POST_PIXEL')
            self._timer=self._wm.event_timer_add(1/30,window=self._window)
            self._window.cursor_modal_set('EYEDROPPER')
            self._workspace.status_text_set('Copy Thickness | Click an edge across a border | Esc: cancel')
            self._wm.modal_handler_add(self);return {'RUNNING_MODAL'}
        except Exception as exc:
            self.finish();self.report({'ERROR'},str(exc));return {'CANCELLED'}

    def update(self,event):
        self._hit=self._cache.query((event.mouse_x-self._region.x,event.mouse_y-self._region.y),self._region,self._view)
        self._area.tag_redraw()

    def modal(self,context,event):
        if self._done:return {'CANCELLED'}
        try:
            if self._area.type!='VIEW_3D' or context.mode!='OBJECT':self.finish();return {'CANCELLED'}
            if event.type in {'ESC','RIGHTMOUSE'} and event.value=='PRESS':self.finish();return {'CANCELLED'}
            if event.type in {'MIDDLEMOUSE','WHEELUPMOUSE','WHEELDOWNMOUSE','TRACKPADPAN','TRACKPADZOOM','NDOF_MOTION'}:
                self._hit=None;self._pending=None;return {'PASS_THROUGH'}
            if event.type=='MOUSEMOVE':self._pending=(event.mouse_x,event.mouse_y)
            if event.type=='TIMER' and time.monotonic()>=self._next:
                self._next=time.monotonic()+1/30
                if self._pending:
                    from types import SimpleNamespace
                    self.update(SimpleNamespace(mouse_x=self._pending[0],mouse_y=self._pending[1]));self._pending=None
                return {'PASS_THROUGH'}
            if event.type=='LEFTMOUSE' and event.value=='PRESS':
                if not (self._region.x<=event.mouse_x<self._region.x+self._region.width and self._region.y<=event.mouse_y<self._region.y+self._region.height):return {'RUNNING_MODAL'}
                self.update(event)
                if self._hit:
                    from . import outline_tool
                    width=self._hit['thickness'];outline_tool.settings(context).thickness=width
                    self.finish();self.report({'INFO'},'Copied edge length: '+display_units.format_length(context,width));return {'FINISHED'}
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.finish();self.report({'ERROR'},str(exc));return {'CANCELLED'}

    def draw_overlay(self):
        if self._done or bpy.context.area!=self._area:return
        import blf
        scale=max(1.,bpy.context.preferences.system.ui_scale)
        blf.size(0,round(13*scale));blf.position(0,20*scale,28*scale,0);blf.color(0,.3,1.,.85,1)
        blf.draw(0,'Copy Thickness: click an edge across an existing border · Esc to cancel')
        if self._hit:
            label='Copy '+display_units.format_length(bpy.context,self._hit['thickness'])+' · '+self._hit['object_name']
            draw_feedback(self._hit,self._region,self._view,label)

    def finish(self):
        if getattr(self,'_done',False):return
        self._done=True
        if self._timer:self._wm.event_timer_remove(self._timer);self._timer=None
        if self._handler:bpy.types.SpaceView3D.draw_handler_remove(self._handler,'WINDOW');self._handler=None
        if bpy.app.driver_namespace.get(STATE_KEY) is self:bpy.app.driver_namespace.pop(STATE_KEY,None)
        try:self._workspace.status_text_set(None);self._window.cursor_modal_restore();self._area.tag_redraw()
        except (ReferenceError,RuntimeError):pass
        parent=bpy.app.driver_namespace.get('harhtools_outline_preview')
        if parent and not getattr(parent,'_done',False):
            self._window.cursor_modal_set('CROSSHAIR')
            self._workspace.status_text_set('Make Outline | Drag: thickness | S: snap | C: copy edge length | Enter / Ctrl+A: apply | Esc: cancel')

    def cancel(self,context):self.finish()


def cancel_running(*_args):
    state=bpy.app.driver_namespace.get(STATE_KEY)
    if state:state.finish()
