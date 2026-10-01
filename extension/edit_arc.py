"""Live arc editing on one selected mesh chain; outside vertices stay fixed."""
import math
import time
import bpy
import bmesh
from mathutils import Vector
from bpy.props import FloatProperty,IntProperty,BoolProperty,PointerProperty

STATE='harhtools_arc_preview'

def signature(obj):
    if obj.mode=='EDIT':
        bm=bmesh.from_edit_mesh(obj.data);bm.verts.index_update()
        return (tuple(tuple(v.co) for v in bm.verts),tuple(tuple(v.index for v in e.verts) for e in bm.edges),
                tuple(tuple(v.index for v in f.verts) for f in bm.faces))
    return (tuple(tuple(v.co) for v in obj.data.vertices),tuple(tuple(e.vertices) for e in obj.data.edges),
            tuple(tuple(f.vertices) for f in obj.data.polygons))


def capture(obj):
    bm=bmesh.from_edit_mesh(obj.data);bm.verts.index_update();bm.edges.index_update()
    chosen={v for v in bm.verts if v.select and not v.hide}
    if not chosen:raise ValueError('Select the vertices of one continuous outline section.')
    links={v:[e.other_vert(v) for e in v.link_edges if e.other_vert(v) in chosen and not e.hide] for v in chosen}
    if any(len(row)>2 for row in links.values()):raise ValueError('Select a single boundary chain, without branching edges.')
    ends=[v for v in chosen if len(links[v])<2];closed=not ends
    if len(chosen)>1 and len(ends) not in (0,2):raise ValueError('Select one connected outline section.')
    start=min(ends or chosen,key=lambda v:v.index);path=[start];previous=None;current=start
    while True:
        following=next((v for v in sorted(links[current],key=lambda v:v.index) if v!=previous and v not in path),None)
        if following is None:break
        path.append(following);previous,current=current,following
    if len(path)!=len(chosen):raise ValueError('Select one connected outline section.')
    if not closed:
        if len(path)==1:
            neighbors=[e.other_vert(path[0]) for e in path[0].link_edges if not e.hide]
            if len(neighbors)!=2:raise ValueError('A single selected tip needs exactly two neighboring vertices.')
            path=[neighbors[0],path[0],neighbors[1]]
        else:
            for at,insert in ((0,0),(-1,len(path))):
                endpoint=path[at];outside=[e.other_vert(endpoint) for e in endpoint.link_edges if e.other_vert(endpoint) not in chosen and not e.hide]
                if len(outside)==1:
                    if at==0:path.insert(0,outside[0])
                    else:path.append(outside[0])
        if len(path)<3:raise ValueError('Select at least one interior vertex between two endpoints.')
    coords=[tuple(v.co) for v in path]
    first=Vector(coords[0]);last=Vector(coords[-1]);chord=last-first
    if closed:
        center=Vector(tuple(math.fsum(p[i] for p in coords)/len(coords) for i in range(3)))
        u=(first-center).normalized();cross=max((u.cross(Vector(p)-center) for p in coords),key=lambda p:p.length_squared)
    else:
        if chord.length<1e-9:raise ValueError('The arc endpoints must be different vertices.')
        center=(first+last)*.5;u=chord.normalized();cross=max((u.cross(Vector(p)-first) for p in coords),key=lambda p:p.length_squared)
    if cross.length<1e-9:cross=u.cross(Vector((0,0,1)))
    if cross.length<1e-9:cross=u.cross(Vector((0,1,0)))
    normal=cross.normalized();v=normal.cross(u).normalized()
    if sum((Vector(p)-center).dot(v) for p in coords)<0:v.negate();normal.negate()
    span=max((Vector(p)-center).length for p in coords)
    if any(abs((Vector(p)-center).dot(normal))>max(span*2e-6,1e-7) for p in coords):
        raise ValueError('The selected section must lie in one plane.')
    height=max((Vector(p)-center).dot(v) for p in coords)
    angle=math.tau if closed else max(math.radians(1),min(math.radians(359),4*math.atan2(2*height,chord.length)))
    wire=all(not vertex.link_faces and all(e.other_vert(vertex) in path for e in vertex.link_edges)
             for vertex in (path if closed else path[1:-1]))
    if closed and not wire:raise ValueError('For a filled mesh, select an open boundary section so its joins can stay fixed.')
    return dict(indices=[v.index for v in path],coords=coords,closed=closed,wire=wire,
                center=tuple(center),u=tuple(u),v=tuple(v),angle=angle,radius=math.sqrt(sum((Vector(p)-center).length_squared for p in coords)/len(coords)))


def positions(info,count,amount,roundness,reverse=False):
    original=[Vector(p) for p in info['coords']];closed=info['closed']
    if not info['wire']:count=len(original)
    count=max(3,int(count));u=Vector(info['u']);v=Vector(info['v'])*(-1 if reverse else 1)
    points=[];full=closed and amount>=math.tau-1e-6
    if not closed:amount=min(amount,math.radians(359))
    spans=original+original[:1] if closed else original
    lengths=[0.]
    for a,b in zip(spans,spans[1:]):lengths.append(lengths[-1]+(b-a).length)
    def original_at(t):
        distance=t*lengths[-1]
        for i in range(len(lengths)-1):
            if distance<=lengths[i+1]:return spans[i].lerp(spans[i+1],(distance-lengths[i])/max(lengths[i+1]-lengths[i],1e-20))
        return spans[-1].copy()
    for i in range(count):
        t=i/(count if full else count-1)
        # Preserve every original vertex at zero influence without resampling.
        base=original[i] if count==len(original) else original_at(t)
        if closed:
            target=Vector(info['center'])+info['radius']*(u*math.cos(t*amount)+v*math.sin(t*amount))
        else:
            chord=(original[-1]-original[0]).length;half=amount*.5;radius=chord/(2*math.sin(half))
            target=(original[0]+original[-1])*.5+u*(radius*math.sin((t-.5)*amount))+v*(radius*(math.cos((t-.5)*amount)-math.cos(half)))
        points.append(tuple(base.lerp(target,roundness)))
    if not closed:points[0]=tuple(original[0]);points[-1]=tuple(original[-1])
    return points,full


def write(obj,snapshot,info,coords,closed):
    editing=obj.mode=='EDIT';bm=bmesh.from_edit_mesh(obj.data) if editing else bmesh.new()
    try:
        bm.clear();bm.from_mesh(snapshot);bm.verts.ensure_lookup_table()
        path=[bm.verts[i] for i in info['indices']]
        if len(coords)==len(path) and closed==info['closed']:
            for vertex,co in zip(path,coords):vertex.co=co
        else:
            if not info['wire']:raise ValueError('Changing vertex count is supported on wire chains; face-connected sections keep their topology.')
            pairs=list(zip(path,path[1:]))+([(path[-1],path[0])] if info['closed'] else [])
            for a,b in pairs:
                edge=bm.edges.get((a,b))
                if edge:bm.edges.remove(edge)
            remove=path if info['closed'] else path[1:-1]
            for vertex in remove:bm.verts.remove(vertex)
            if info['closed']:created=[bm.verts.new(co) for co in coords]
            else:created=[path[0]]+[bm.verts.new(co) for co in coords[1:-1]]+[path[-1]]
            for vertex in created:vertex.select_set(True)
            pairs=list(zip(created,created[1:]))+([(created[-1],created[0])] if closed else [])
            for a,b in pairs:bm.edges.new((a,b)).select_set(True)
        bm.normal_update()
        if editing:bmesh.update_edit_mesh(obj.data,loop_triangles=True,destructive=True)
        else:bm.to_mesh(obj.data);obj.data.update()
    finally:
        if not editing:bm.free()


def changed(cfg,context):
    state=bpy.app.driver_namespace.get(STATE)
    if state:
        if not state._info['closed'] and cfg.amount>math.radians(359)+1e-6:
            cfg.amount=math.radians(359)
        state._dirty=True;state._area.tag_redraw()

class HARHTOOLS_PG_edit_arc(bpy.types.PropertyGroup):
    amount:FloatProperty(name='Arc Amount',default=math.pi,min=math.radians(.1),max=math.tau,subtype='ANGLE',update=changed)
    vertices:IntProperty(name='Vertices',default=64,min=3,max=2048,soft_max=512,update=changed)
    roundness:FloatProperty(name='Roundness',default=1,min=0,max=1,update=changed)
    reverse:BoolProperty(name='Reverse Bend',default=False,update=changed)

class MESH_OT_harhtools_edit_arc(bpy.types.Operator):
    bl_idname='mesh.harhtools_edit_arc';bl_label='Adjust Selected Arc';bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):
        return context.mode=='EDIT_MESH' and not any(bpy.app.driver_namespace.get(k) for k in
            (STATE,'arch_tools_shape_builder','harhtools_outline_preview','harhtools_array_preview'))
    def invoke(self,context,event):
        self._done=False;self._snapshot=None;self._expected=None;self._timer=None;self._area=context.area;self._wm=context.window_manager
        self._obj=context.active_object;self._dirty=True;self._error='';self._key=None;self._next_tick=0
        try:
            self._info=capture(self._obj)
            self._snapshot=bpy.data.meshes.new('Harhtools arc undo snapshot')
            bmesh.from_edit_mesh(self._obj.data).to_mesh(self._snapshot)
            self._expected=signature(self._obj)
            cfg=self._wm.harhtools_edit_arc;cfg.amount=self._info['angle'];cfg.vertices=len(self._info['coords']);cfg.roundness=1;cfg.reverse=False
            bpy.app.driver_namespace[STATE]=self;self.refresh()
            self._timer=self._wm.event_timer_add(1/30,window=context.window);self._wm.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception as exc:self.finish(cancel=True);self.report({'ERROR'},str(exc));return {'CANCELLED'}
    def refresh(self):
        cfg=self._wm.harhtools_edit_arc;key=(cfg.amount,cfg.vertices,cfg.roundness,cfg.reverse)
        self._dirty=False
        if key==self._key:return
        self._key=key
        try:
            if signature(self._obj)!=self._expected:
                raise ValueError('The mesh changed outside these controls. Finish this preview before editing it elsewhere.')
            coords,closed=positions(self._info,cfg.vertices,cfg.amount,cfg.roundness,cfg.reverse)
            write(self._obj,self._snapshot,self._info,coords,closed);self._expected=signature(self._obj);self._error=''
        except Exception as exc:self._error=str(exc)
        self._area.tag_redraw()
    def modal(self,context,event):
        if self._done:return {'CANCELLED'}
        if context.mode!='EDIT_MESH' or context.active_object!=self._obj:
            self.finish(cancel=True);return {'CANCELLED'}
        if event.type=='TIMER':
            now=time.monotonic()
            if self._dirty and now>=self._next_tick:self._next_tick=now+1/30;self.refresh()
            return {'PASS_THROUGH'}
        if event.type=='ESC' and event.value=='PRESS':self.finish(cancel=True);return {'CANCELLED'}
        over_ui=any(r.type=='UI' and r.x<=event.mouse_x<r.x+r.width and r.y<=event.mouse_y<r.y+r.height for r in self._area.regions)
        if over_ui:return {'PASS_THROUGH'}
        if event.type in {'RET','NUMPAD_ENTER'} and event.value=='PRESS':
            self.refresh()
            if self._error:return {'RUNNING_MODAL'}
            self.finish();return {'FINISHED'}
        if event.type=='RIGHTMOUSE' and event.value=='PRESS':self.finish(cancel=True);return {'CANCELLED'}
        if event.type in {'MIDDLEMOUSE','WHEELUPMOUSE','WHEELDOWNMOUSE','TRACKPADPAN','TRACKPADZOOM','NDOF_MOTION'}:return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}
    def finish(self,cancel=False):
        if self._done:return
        self._done=True
        if self._timer:self._wm.event_timer_remove(self._timer);self._timer=None
        if self._snapshot:
            if cancel and self._expected is not None and signature(self._obj)==self._expected:
                write(self._obj,self._snapshot,self._info,self._info['coords'],self._info['closed'])
            elif cancel:self.report({'WARNING'},'Other mesh edits were detected; kept the current mesh instead of overwriting them.')
            bpy.data.meshes.remove(self._snapshot);self._snapshot=None
        if bpy.app.driver_namespace.get(STATE) is self:bpy.app.driver_namespace.pop(STATE,None)
        if self._area:self._area.tag_redraw()


def cancel(*args):
    state=bpy.app.driver_namespace.get(STATE)
    if state:state.finish(cancel=True)

def draw_panel(layout,context):
    if context.mode!='EDIT_MESH':return
    box=layout.box();box.label(text='Selected Arc');state=bpy.app.driver_namespace.get(STATE)
    if state:
        cfg=context.window_manager.harhtools_edit_arc
        box.prop(cfg,'amount',slider=True);box.prop(cfg,'roundness',slider=True)
        row=box.row();row.enabled=state._info['wire'];row.prop(cfg,'vertices',slider=True)
        box.prop(cfg,'reverse')
        box.label(text='Joins to the rest stay fixed.')
        if not state._info['wire']:box.label(text='Face-connected: existing vertices retained.')
        box.label(text='Enter: keep · Esc: restore')
        if state._error:box.label(text=state._error,icon='ERROR')
    else:
        box.label(text='Select one continuous outline section.')
        box.operator('mesh.harhtools_edit_arc',icon='CURVE_BEZCIRCLE')

CLASSES=(HARHTOOLS_PG_edit_arc,MESH_OT_harhtools_edit_arc)
def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.WindowManager.harhtools_edit_arc=PointerProperty(type=HARHTOOLS_PG_edit_arc)
    bpy.app.handlers.load_pre.append(cancel)
def unregister():
    cancel()
    if cancel in bpy.app.handlers.load_pre:bpy.app.handlers.load_pre.remove(cancel)
    if hasattr(bpy.types.WindowManager,'harhtools_edit_arc'):del bpy.types.WindowManager.harhtools_edit_arc
    for cls in reversed(CLASSES):
        if hasattr(cls,'bl_rna'):
            try:bpy.utils.unregister_class(cls)
            except RuntimeError:pass
