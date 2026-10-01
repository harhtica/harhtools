"""Live arc editing on one selected mesh chain; outside vertices stay fixed."""
import math
import time
import statistics
from bisect import bisect_right
import bpy
import bmesh
from mathutils import Vector
from bpy.props import FloatProperty,IntProperty,BoolProperty,PointerProperty,EnumProperty

STATE='harhtools_arc_preview'


def selection(obj):
    bm=bmesh.from_edit_mesh(obj.data)
    return tuple((v.select,v.hide) for v in bm.verts)


def neighboring_spacing(obj,path,closed):
    """Median world-space edge length along up to three untouched edges per join."""
    if closed:return None
    section=set(path);lengths=[];seen=set()
    for anchor in (path[0],path[-1]):
        current=anchor;previous=None
        for _ in range(3):
            edges=[e for e in current.link_edges if not e.hide and len(e.link_faces)<=1
                   and e not in seen and e.other_vert(current) not in section
                   and not e.other_vert(current).select and e.other_vert(current)!=previous]
            if len(edges)!=1:break
            edge=edges[0];seen.add(edge);other=edge.other_vert(current)
            length=(obj.matrix_world.to_3x3()@(other.co-current.co)).length
            if length>1e-10:lengths.append(length)
            previous,current=current,other
    return statistics.median(lengths) if lengths else None

def signature(obj):
    if obj.mode=='EDIT':
        bm=bmesh.from_edit_mesh(obj.data);bm.verts.index_update()
        return (tuple(tuple(v.co) for v in bm.verts),tuple(tuple(v.index for v in e.verts) for e in bm.edges),
                tuple(tuple(v.index for v in f.verts) for f in bm.faces))
    return (tuple(tuple(v.co) for v in obj.data.vertices),tuple(tuple(e.vertices) for e in obj.data.edges),
            tuple(tuple(f.vertices) for f in obj.data.polygons))


def surrounding_points(path,closed):
    """Only connected, untouched geometry can establish the surrounding plane."""
    if closed:return []
    seen=set(path);pending=[path[0],path[-1]];points=[]
    while pending and len(points)<8192:
        current=pending.pop()
        for edge in current.link_edges:
            other=edge.other_vert(current)
            if edge.hide or other.hide or other.select or other in seen:continue
            seen.add(other);pending.append(other);points.append(tuple(other.co))
    return points


def fitted_normal(points):
    """A scale-relative plane test: a short edge is not a reason to change axes."""
    if len(points)<3:return None
    points=[Vector(p) for p in points];origin=points[0]
    farthest=max(points,key=lambda p:(p-origin).length_squared)
    span=(farthest-origin).length
    if span<1e-12:return None
    axis=(farthest-origin)/span
    cross=max((axis.cross(p-origin) for p in points),key=lambda p:p.length_squared)
    tolerance=max(span*2e-5,max(abs(c) for p in points for c in p)*2.4e-7,1e-12)
    if cross.length<=tolerance:return None
    normal=cross.normalized()
    if max(abs((p-origin).dot(normal)) for p in points)>tolerance:return None
    return normal


def frame(coords,closed,support,plane='AUTO',previous=None):
    original=[Vector(p) for p in coords];first=original[0];last=original[-1]
    center=Vector(tuple(math.fsum(p[i] for p in original)/len(original) for i in range(3))) if closed else (first+last)*.5
    chord=last-first
    span=max((p-center).length for p in original)
    tolerance=max(span*2e-5,max(abs(c) for p in original for c in p)*2.4e-7,1e-12)
    if not closed and chord.length<1e-12:raise ValueError('The arc endpoints must be different vertices.')
    normal=None;source='Selected curve'
    if plane!='AUTO':
        normal=Vector({'XY':(0,0,1),'XZ':(0,1,0),'YZ':(1,0,0)}[plane]);source='Object '+plane
    else:
        if support:
            normal=fitted_normal([tuple(first),tuple(last)]+support);source='Surrounding shape'
        if normal is None:normal=fitted_normal(coords);source='Selected curve'
        if normal is None and previous is not None:
            candidate=Vector(previous['normal']);origin=Vector(previous['center'])
            span=max((p-origin).length for p in original)
            if all(abs((p-origin).dot(candidate))<=max(span*2e-5,tolerance) for p in original):
                normal=candidate;source='Previous plane'
    if normal is None:
        raise ValueError('The selection has no unique arc plane. Choose Object XY, XZ or YZ.')
    if not closed and abs(chord.dot(normal))>tolerance:
        raise ValueError('The fixed endpoints do not share that plane. Choose another Arc Plane.')
    u=first-center if closed else chord
    u=(u-normal*u.dot(normal)).normalized()
    if u.length<.5:raise ValueError('The selected section has no width in that plane.')
    v=normal.cross(u).normalized()
    heights=[(p-center).dot(v) for p in original]
    side=math.fsum(heights)
    if abs(side)<=tolerance*len(coords):
        # A subdivided straight side bows away from the remaining outline.
        side=-math.fsum((Vector(p)-center).dot(v) for p in support)
        if abs(side)<=span*1e-6 and previous is not None:side=v.dot(Vector(previous['v']))
    if side<0:v.negate();normal.negate();heights=[-h for h in heights]
    height=max(heights)
    angle=math.tau if closed else max(math.radians(1),min(math.radians(359),4*math.atan2(2*height,chord.length)))
    return dict(center=tuple(center),u=tuple(u),v=tuple(v),normal=tuple(normal),angle=angle,
                radius=math.sqrt(sum((p-center).length_squared for p in original)/len(original)),
                plane_mode=plane,plane_source=source)


def capture(obj,plane='AUTO',previous=None):
    bm=bmesh.from_edit_mesh(obj.data);bm.verts.index_update();bm.edges.index_update()
    chosen={v for v in bm.verts if v.select and not v.hide}
    if not chosen:raise ValueError('Select the vertices of one continuous outline section.')
    links={v:[e.other_vert(v) for e in v.link_edges if e.other_vert(v) in chosen and not e.hide] for v in chosen}
    if any(len(row)>2 for row in links.values()):raise ValueError('Select a single boundary chain, without branching edges.')
    ends=[v for v in chosen if len(links[v])<2];closed=not ends
    if len(chosen)>1 and len(ends) not in (0,2):raise ValueError('Select one connected outline section.')
    start=min(ends or chosen,key=lambda v:v.index);path=[start];visited={start};previous_vertex=None;current=start
    while True:
        following=next((v for v in sorted(links[current],key=lambda v:v.index) if v!=previous_vertex and v not in visited),None)
        if following is None:break
        path.append(following);visited.add(following);previous_vertex,current=current,following
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
    support=surrounding_points(path,closed)
    wire=all(not vertex.link_faces and all(e.other_vert(vertex) in path for e in vertex.link_edges)
             for vertex in (path if closed else path[1:-1]))
    if closed and not wire:raise ValueError('For a filled mesh, select an open boundary section so its joins can stay fixed.')
    return dict(indices=[v.index for v in path],coords=coords,closed=closed,wire=wire,
                endpoint_selected=(path[0].select,path[-1].select),spacing=neighboring_spacing(obj,path,closed),
                support=support,**frame(coords,closed,support,plane,previous))


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
        i=min(len(lengths)-2,max(0,bisect_right(lengths,distance)-1))
        return spans[i].lerp(spans[i+1],(distance-lengths[i])/max(lengths[i+1]-lengths[i],1e-20))
    for i in range(count):
        t=i/(count if full else count-1)
        # Preserve every original vertex at zero influence without resampling.
        base=original[i] if count==len(original) else (original_at(t) if roundness!=1 else None)
        if closed:
            target=Vector(info['center'])+info['radius']*(u*math.cos(t*amount)+v*math.sin(t*amount))
        else:
            chord=(original[-1]-original[0]).length;half=amount*.5;radius=chord/(2*math.sin(half))
            target=(original[0]+original[-1])*.5+u*(radius*math.sin((t-.5)*amount))+v*(radius*(math.cos((t-.5)*amount)-math.cos(half)))
        points.append(tuple(target if roundness==1 else base.lerp(target,roundness)))
    if not closed:points[0]=tuple(original[0]);points[-1]=tuple(original[-1])
    return points,full


def matched_count(obj,info,cfg):
    if not cfg.match_spacing or not info['wire'] or not info['spacing']:return cfg.vertices
    samples,closed=positions(info,257,cfg.amount,cfg.roundness,cfg.reverse)
    matrix=obj.matrix_world.to_3x3();points=[matrix@Vector(p) for p in samples]
    pairs=list(zip(points,points[1:]))+([(points[-1],points[0])] if closed else [])
    length=math.fsum((b-a).length for a,b in pairs)
    return max(3,min(2048,round(length/info['spacing'])+(0 if closed else 1)))


def write(obj,snapshot,info,coords,closed):
    editing=obj.mode=='EDIT';bm=bmesh.from_edit_mesh(obj.data) if editing else bmesh.new()
    try:
        select_mode=set(bm.select_mode) or {'VERT'}
        bm.clear();bm.from_mesh(snapshot);bm.select_mode=select_mode;bm.verts.ensure_lookup_table()
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
            pairs=list(zip(created,created[1:]))+([(created[-1],created[0])] if closed else [])
            for a,b in pairs:bm.edges.new((a,b))
            flags={vertex:True for vertex in created}
            if not info['closed']:
                flags[created[0]],flags[created[-1]]=info['endpoint_selected']
            # Edge selection propagates to vertices in Blender, so establish
            # edge flags first and restore the precise vertex flags last.
            for a,b in pairs:bm.edges.get((a,b)).select=flags[a] and flags[b]
            for vertex,flag in flags.items():vertex.select=flag
        bm.normal_update()
        if editing:bmesh.update_edit_mesh(obj.data,loop_triangles=True,destructive=True)
        else:bm.to_mesh(obj.data);obj.data.update()
    finally:
        if not editing:bm.free()


def changed(cfg,context):
    state=bpy.app.driver_namespace.get(STATE)
    if state and not getattr(state,'_syncing',False):
        if not state._info['closed'] and cfg.amount>math.radians(359)+1e-6:
            cfg.amount=math.radians(359)
        state._dirty=True;state._area.tag_redraw()

class HARHTOOLS_PG_edit_arc(bpy.types.PropertyGroup):
    plane:EnumProperty(name='Arc Plane',default='AUTO',items=[
        ('AUTO','Shape','Use the connected surrounding shape, then the selected curve'),
        ('XY','Object XY','Bend in the object local XY plane'),
        ('XZ','Object XZ','Bend in the object local XZ plane'),
        ('YZ','Object YZ','Bend in the object local YZ plane')],update=changed)
    amount:FloatProperty(name='Arc Amount',default=math.pi,min=math.radians(.1),max=math.tau,subtype='ANGLE',update=changed)
    vertices:IntProperty(name='Vertices',default=64,min=3,max=2048,soft_max=512,update=changed)
    roundness:FloatProperty(name='Roundness',default=1,min=0,max=1,update=changed)
    reverse:BoolProperty(name='Reverse Bend',default=False,update=changed)
    match_spacing:BoolProperty(name='Match Nearby Spacing',default=True,update=changed,
        description='Match the edge spacing of adjoining unselected wire vertices; face topology stays unchanged')

class MESH_OT_harhtools_edit_arc(bpy.types.Operator):
    bl_idname='mesh.harhtools_edit_arc';bl_label='Adjust Selected Arc';bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):
        return context.mode=='EDIT_MESH' and not any(bpy.app.driver_namespace.get(k) for k in
            (STATE,'arch_tools_shape_builder','harhtools_outline_preview','harhtools_array_preview'))
    def invoke(self,context,event):
        self._done=False;self._snapshot=None;self._expected=None;self._timer=None;self._area=context.area;self._wm=context.window_manager
        self._obj=context.active_object;self._dirty=False;self._error='';self._key=None;self._next_tick=0
        self._syncing=False;self._valid=False;self._selection=None
        try:
            self.adopt_mesh()
            bpy.app.driver_namespace[STATE]=self
            self._timer=self._wm.event_timer_add(1/30,window=context.window);self._wm.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception as exc:self.finish(cancel=True);self.report({'ERROR'},str(exc));return {'CANCELLED'}
    def settings_key(self):
        cfg=self._wm.harhtools_edit_arc
        return (cfg.amount,cfg.vertices,cfg.roundness,cfg.reverse,cfg.match_spacing,cfg.plane)
    def adopt_mesh(self):
        """Manual edits become the new baseline; never write from a draw callback."""
        self._valid=False
        info=capture(self._obj,self._wm.harhtools_edit_arc.plane,getattr(self,'_info',None))
        if self._snapshot is None:self._snapshot=bpy.data.meshes.new('Harhtools arc undo snapshot')
        bmesh.from_edit_mesh(self._obj.data).to_mesh(self._snapshot)
        self._info=info;self._expected=signature(self._obj);self._selection=selection(self._obj)
        self._syncing=True
        try:
            cfg=self._wm.harhtools_edit_arc
            cfg.amount=info['angle'];cfg.vertices=len(info['coords']);cfg.roundness=1;cfg.reverse=False
        finally:self._syncing=False
        self._valid=True;self._dirty=False;self._error='';self._key=self.settings_key()
        self._area.tag_redraw()
    def observe_mesh(self):
        current=signature(self._obj);selected=selection(self._obj)
        if current==self._expected and selected==self._selection:return False
        try:self.adopt_mesh()
        except ValueError as exc:
            self._expected=current;self._selection=selected;self._valid=False
            self._dirty=False;self._error=str(exc);self._area.tag_redraw()
        return True
    def native_tool_running(self,context):
        # Blender's own transform/select modal must finish or cancel before
        # recapturing its mesh. Our timer must not fight a live G/R/S operation.
        window=getattr(context,'window',None)
        return any(getattr(op,'bl_idname','') not in {self.bl_idname,'MESH_OT_harhtools_edit_arc'}
                   for op in getattr(window,'modal_operators',()))
    def refresh(self):
        # Catch edits even if a slider callback arrives before the next timer.
        cfg=self._wm.harhtools_edit_arc;requested=self.settings_key();pending=self._dirty
        recaptured=self.observe_mesh()
        if not self._valid and pending:
            try:self.adopt_mesh();recaptured=True
            except ValueError as exc:self._error=str(exc);self._dirty=False
        if recaptured and self._valid and pending:
            self._syncing=True
            try:
                for name,value in zip(('amount','vertices','roundness','reverse','match_spacing','plane'),requested):setattr(cfg,name,value)
            finally:self._syncing=False
            self._key=None
        if not self._valid:return
        key=self.settings_key()
        self._dirty=False
        if key==self._key:return
        try:
            if self._info['plane_mode']!=cfg.plane:
                self._info.update(frame(self._info['coords'],self._info['closed'],self._info['support'],cfg.plane,self._info))
            count=matched_count(self._obj,self._info,cfg)
            coords,closed=positions(self._info,count,cfg.amount,cfg.roundness,cfg.reverse)
            write(self._obj,self._snapshot,self._info,coords,closed)
            self._expected=signature(self._obj);self._selection=selection(self._obj);self._error=''
            self._syncing=True
            try:cfg.vertices=len(coords)
            finally:self._syncing=False
            self._key=self.settings_key()
        except Exception as exc:self._error=str(exc)
        self._area.tag_redraw()
    def modal(self,context,event):
        if self._done:return {'CANCELLED'}
        if context.mode!='EDIT_MESH' or context.active_object!=self._obj:
            self.finish();return {'FINISHED'}
        if self.native_tool_running(context):return {'PASS_THROUGH'}
        if event.type=='TIMER':
            now=time.monotonic()
            if now>=self._next_tick:
                self._next_tick=now+(.033 if self._dirty else .12)
                if self._dirty:self.refresh()
                else:self.observe_mesh()
            return {'PASS_THROUGH'}
        if event.type=='ESC' and event.value=='PRESS':
            self.observe_mesh();self.finish(cancel=True);return {'CANCELLED'}
        over_ui=any(r.type=='UI' and r.x<=event.mouse_x<r.x+r.width and r.y<=event.mouse_y<r.y+r.height for r in self._area.regions)
        if over_ui:return {'PASS_THROUGH'}
        if event.type in {'RET','NUMPAD_ENTER'} and event.value=='PRESS':
            self.refresh()
            if self._error:return {'RUNNING_MODAL'}
            self.finish();return {'FINISHED'}
        return {'PASS_THROUGH'}
    def finish(self,cancel=False):
        if self._done:return
        self._done=True
        if self._timer:self._wm.event_timer_remove(self._timer);self._timer=None
        if self._snapshot:
            if cancel and self._valid and self._expected is not None and signature(self._obj)==self._expected:
                write(self._obj,self._snapshot,self._info,self._info['coords'],self._info['closed'])
            elif cancel:self.report({'INFO'},'Kept your latest mesh edits.')
            bpy.data.meshes.remove(self._snapshot);self._snapshot=None
        if bpy.app.driver_namespace.get(STATE) is self:bpy.app.driver_namespace.pop(STATE,None)
        if self._area:self._area.tag_redraw()


def cancel(*args):
    state=bpy.app.driver_namespace.get(STATE)
    if state:state.finish(cancel=True)

def draw_panel(layout,context):
    if context.mode!='EDIT_MESH':return
    box=layout.box();box.label(text='Selected Arc');state=bpy.app.driver_namespace.get(STATE)
    cfg=context.window_manager.harhtools_edit_arc
    box.prop(cfg,'plane')
    if state:
        box.prop(cfg,'amount',slider=True);box.prop(cfg,'roundness',slider=True)
        row=box.row();row.enabled=state._info['wire'];row.prop(cfg,'match_spacing')
        row=box.row();row.enabled=state._info['wire'] and (not cfg.match_spacing or not state._info['spacing']);row.prop(cfg,'vertices',slider=True)
        if state._info['wire'] and cfg.match_spacing and not state._info['spacing']:box.label(text='No adjoining spacing found; using Vertices.')
        box.prop(cfg,'reverse')
        box.label(text='Joins to the rest stay fixed.')
        if not state._info['wire']:box.label(text='Face-connected: existing vertices retained.')
        box.label(text='Edit vertices normally; controls follow.')
        box.label(text='Enter: keep · Esc: undo slider changes')
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
