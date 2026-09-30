"""harhtools Shape Builder: selected planar mesh edges and curve outlines.

Run this script once, then use harhtools > Shape Builder or Shift+M in 3D View.
Hover previews a bounded region. Click/drag adds; hold Alt and click/drag to remove.
Ordinary clicks keep chosen regions. Ctrl+Z undoes a stroke; Backspace clears.
Enter creates a new mesh from the chosen regions. Esc/right-click cancels.
Sources are never changed. In Edit Mode only selected visible edges are used.
Gap Snap adds short connectors across tiny gaps in the preview/new shape only;
set it to 0 for exact wires. Larger open gaps do not enclose a region.
Wires must share a plane, at any orientation.
Confirmed fills use clean planar n-gons, retaining only the connections needed
around holes. Boundary vertices and curves keep their original detail.
"""
import bpy
import bmesh
import math
from collections import defaultdict
from mathutils import Vector, Matrix
from mathutils.geometry import delaunay_2d_cdt
from mathutils.bvhtree import BVHTree
from bpy.props import FloatProperty

_STATE_KEY = 'arch_tools_shape_builder'
_KEYMAP_KEY = 'arch_tools_shape_builder_keymaps'


def collect_selection(context):
    editing = context.mode == 'EDIT_MESH'
    if context.mode not in {'OBJECT','EDIT_MESH'}:
        raise ValueError('Use Object Mode or mesh Edit Mode.')
    objects = list(context.objects_in_mode_unique_data if editing else context.selected_objects)
    points, edges, sources = [], [], []
    depsgraph = context.evaluated_depsgraph_get()
    for obj in objects:
        if not obj.visible_get() or obj.type not in {'MESH','CURVE'}:
            continue
        offset = len(points)
        if obj.type == 'MESH':
            bm = bmesh.from_edit_mesh(obj.data).copy() if editing else bmesh.new()
            try:
                if not editing: bm.from_mesh(obj.data)
                chosen = [e for e in bm.edges if not e.hide and not any(v.hide for v in e.verts)
                          and (not editing or e.select)]
                vertices = list(dict.fromkeys(v for e in chosen for v in e.verts))
                ids = {v:i+offset for i,v in enumerate(vertices)}
                points.extend(obj.matrix_world @ v.co for v in vertices)
                edges.extend(tuple(ids[v] for v in e.verts) for e in chosen)
            finally:
                bm.free()
        else:
            evaluated = obj.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh()
            try:
                points.extend(evaluated.matrix_world @ v.co for v in mesh.vertices)
                edges.extend(tuple(offset+i for i in e.vertices) for e in mesh.edges)
            finally:
                evaluated.to_mesh_clear()
        if len(points)>offset: sources.append(obj.name)
    if len(edges)<3:
        raise ValueError('Select wire outlines that enclose an area first.')
    return points,edges,sources


def planar_basis(points, facing=None):
    origin = sum(points,Vector())/len(points)
    centered = [p-origin for p in points]
    u = max(centered,key=lambda v:v.length_squared).normalized()
    cross = max((u.cross(p) for p in centered),key=lambda v:v.length_squared)
    if cross.length_squared<1e-20:
        raise ValueError('These edges do not enclose a two-dimensional area.')
    normal = cross.normalized()
    if facing is not None:
        if normal.dot(facing)<0: normal.negate()
    elif normal[max(range(3),key=lambda i:abs(normal[i]))]<0:
        normal.negate()
    v = normal.cross(u).normalized()
    scale = max(p.length for p in centered)
    tolerance = max(scale*2e-6,1e-7)
    if any(abs(p.dot(normal))>tolerance for p in centered):
        raise ValueError('Selected wires must lie in one flat plane. Exclude depth edges or beveled curves.')
    xy = [Vector((p.dot(u)/scale,p.dot(v)/scale)) for p in centered]
    return origin,u,v,normal,scale,xy


def close_tiny_gaps(xy, edges, tolerance):
    """Add short preview-only connectors at near contacts, retaining the wires."""
    if tolerance<=1e-7:return xy,edges,0
    candidates=[];active=[]
    ordered=sorted(range(len(edges)),key=lambda i:min(xy[v].x for v in edges[i]))
    for i in ordered:
        a,b=(xy[v] for v in edges[i]);ab=b-a
        if ab.length_squared<1e-20:continue
        left=min(a.x,b.x);bottom=min(a.y,b.y);top=max(a.y,b.y)
        active=[j for j in active if max(xy[v].x for v in edges[j])+tolerance>=left]
        for j in active:
            if set(edges[i]).intersection(edges[j]):continue
            c,d=(xy[v] for v in edges[j]);cd=d-c
            if cd.length_squared<1e-20 or max(c.y,d.y)+tolerance<bottom or min(c.y,d.y)-tolerance>top:continue
            cross=ab.cross(cd)
            if abs(cross)>1e-14:
                s=(c-a).cross(cd)/cross;t=(c-a).cross(ab)/cross
                if 0<=s<=1 and 0<=t<=1:continue
            pairs=[]
            for p in (a,b):pairs.append((p,c+cd*max(0,min(1,(p-c).dot(cd)/cd.length_squared))))
            for q in (c,d):pairs.append((a+ab*max(0,min(1,(q-a).dot(ab)/ab.length_squared)),q))
            p,q=min(pairs,key=lambda pq:(pq[0]-pq[1]).length_squared)
            distance=(p-q).length
            if 1e-7<distance<=tolerance:
                candidates.append((distance,p.copy(),q.copy(),max(ab.length,cd.length)*1.5))
        active.append(i)
    coords=list(xy);result=list(edges);contacts=[]
    for distance,p,q,radius in sorted(candidates,key=lambda row:row[0]):
        midpoint=(p+q)*.5
        if any((midpoint-center).length<max(radius,old_radius) for center,old_radius in contacts):continue
        index=len(coords);coords.extend((p,q));result.append((index,index+1))
        contacts.append((midpoint,radius))
    return coords,result,len(contacts)


def build_arrangement(points, edges, facing=None, gap_snap=0.0):
    origin,u,v,normal,scale,xy = planar_basis(points,facing)
    xy,edges,closed_gaps=close_tiny_gaps(xy,edges,gap_snap/100.0)
    # Give numerically coincident endpoints one index before triangulating.
    # This makes exact tangencies reliable even when coordinates came from
    # different object transforms with slightly different float rounding.
    merge=1e-6 if gap_snap else 1e-7
    cells=defaultdict(list);unique=[];ids=[]
    for point in xy:
        cell=(math.floor(point.x/merge),math.floor(point.y/merge));found=None
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for i in cells[(cell[0]+dx,cell[1]+dy)]:
                    if (unique[i]-point).length<=merge:found=i;break
                if found is not None:break
            if found is not None:break
        if found is None:
            found=len(unique);unique.append(point);cells[cell].append(found)
        ids.append(found)
    edges=list(dict.fromkeys(tuple(sorted((ids[a],ids[b]))) for a,b in edges if ids[a]!=ids[b]))
    vertices,out_edges,triangles,_,orig_edges,_ = delaunay_2d_cdt(unique,edges,[],0,1e-7,True)
    constraints = {tuple(sorted(e)) for e,ids in zip(out_edges,orig_edges) if ids}
    triangles = [tuple(t) if (vertices[t[1]]-vertices[t[0]]).cross(vertices[t[2]]-vertices[t[0]])>0
                 else tuple(reversed(t)) for t in triangles if len(t)==3]
    edge_faces = defaultdict(list)
    for i,tri in enumerate(triangles):
        for a,b in zip(tri,tri[1:]+tri[:1]):edge_faces[tuple(sorted((a,b)))].append(i)
    neighbors = [[] for _ in triangles]
    outside = set()
    for edge,faces in edge_faces.items():
        if edge in constraints:continue
        if len(faces)==1:outside.add(faces[0])
        elif len(faces)==2:
            a,b=faces;neighbors[a].append(b);neighbors[b].append(a)
    unseen = set(range(len(triangles)))
    regions,tri_region = [],[-1]*len(triangles)
    while unseen:
        seed=unseen.pop();component=[seed];stack=[seed];exterior=seed in outside
        while stack:
            for other in neighbors[stack.pop()]:
                if other in unseen:
                    unseen.remove(other);stack.append(other);component.append(other)
                    exterior |= other in outside
        area=sum(abs((vertices[triangles[i][1]]-vertices[triangles[i][0]]).cross(
                     vertices[triangles[i][2]]-vertices[triangles[i][0]]))*.5 for i in component)
        if exterior or area<1e-13:continue
        rid=len(regions)
        for i in component:tri_region[i]=rid
        boundary=[]
        for i in component:
            tri=triangles[i]
            for a,b in zip(tri,tri[1:]+tri[:1]):
                if tuple(sorted((a,b))) in constraints:boundary.append((a,b))
        regions.append({'triangles':component,'area':area*scale*scale,'boundary':boundary})
    if not regions:
        raise ValueError('No closed regions found. Include all boundary wires and close any gaps.')
    world=[origin+(u*p.x+v*p.y)*scale for p in vertices]
    bvh=BVHTree.FromPolygons([Vector((p.x,p.y,0)) for p in vertices],triangles,all_triangles=True)
    return {'vertices':vertices,'world':world,'triangles':triangles,'regions':regions,
            'tri_region':tri_region,'edge_faces':dict(edge_faces),'origin':origin,'u':u,'v':v,
            'normal':normal,'scale':scale,'bvh':bvh,'closed_gaps':closed_gaps}


def region_at_world(arrangement, point):
    p=(point-arrangement['origin'])/arrangement['scale']
    hit=arrangement['bvh'].ray_cast(Vector((p.dot(arrangement['u']),p.dot(arrangement['v']),1)),Vector((0,0,-1)))
    return arrangement['tri_region'][hit[2]] if hit[2] is not None else -1


def output_polygons(arrangement, selected):
    """Merge chosen cells; holed components are tessellated before cleanup."""
    triangles=arrangement['triangles'];edge_faces=arrangement['edge_faces'];xy=arrangement['vertices']
    remaining={i for rid in selected for i in arrangement['regions'][rid]['triangles']}
    polygons=[]
    while remaining:
        seed=remaining.pop();component={seed};stack=[seed]
        while stack:
            tri=triangles[stack.pop()]
            for a,b in zip(tri,tri[1:]+tri[:1]):
                for other in edge_faces[tuple(sorted((a,b)))]:
                    if other in remaining:
                        remaining.remove(other);component.add(other);stack.append(other)
        boundary=[]
        for i in component:
            tri=triangles[i]
            for a,b in zip(tri,tri[1:]+tri[:1]):
                if sum(j in component for j in edge_faces[tuple(sorted((a,b)))])==1:
                    boundary.append((a,b))
        following=defaultdict(list)
        for a,b in boundary:following[a].append(b)
        if boundary and all(len(xs)==1 for xs in following.values()):
            first=boundary[0][0];loop=[first];current=following[first][0]
            while current!=first and current not in loop and current in following:
                loop.append(current);current=following[current][0]
            if current==first and len(loop)==len(boundary) and len(set(loop))==len(loop):
                polygons.append(loop);continue
        polygons.extend(triangles[i] for i in sorted(component))
    return polygons


def clean_planar_fill(bm):
    """Dissolve coplanar interior edges without altering any boundary segment."""
    bm.normal_update()
    before_area=sum(face.calc_area() for face in bm.faces)
    boundary={tuple(sorted(tuple(v.co) for v in edge.verts))
              for edge in bm.edges if len(edge.link_faces)==1}
    interior=[edge for edge in bm.edges if len(edge.link_faces)==2]
    if interior:
        # New BMesh edges can carry sharp flags even on an entirely flat fill.
        # Angle and boundary checks protect geometry; do not use sharp/UV flags
        # as delimiters on this freshly generated, attribute-free surface.
        bmesh.ops.dissolve_limit(bm,angle_limit=.001,verts=[],edges=interior,
                                use_dissolve_boundaries=False,delimit=set())
    bm.normal_update()
    after_boundary={tuple(sorted(tuple(v.co) for v in edge.verts))
                    for edge in bm.edges if len(edge.link_faces)==1}
    after_area=sum(face.calc_area() for face in bm.faces)
    if (boundary!=after_boundary or abs(after_area-before_area)>max(before_area*2e-5,1e-10)
            or any(len(set(face.verts))!=len(face.verts) for face in bm.faces)
            or any(len(edge.link_faces)>2 for edge in bm.edges)):
        raise RuntimeError('The planar cleanup could not preserve the shape boundaries.')


def make_shape_mesh(arrangement, selected, name='Shape Builder'):
    polygons=output_polygons(arrangement,selected)
    used=sorted({i for p in polygons for i in p});remap={old:new for new,old in enumerate(used)}
    coords=[Vector((arrangement['vertices'][i].x*arrangement['scale'],
                    arrangement['vertices'][i].y*arrangement['scale'],0)) for i in used]
    bm=bmesh.new();mesh=None
    try:
        vertices=[bm.verts.new(p) for p in coords]
        for polygon in polygons:bm.faces.new([vertices[remap[i]] for i in polygon])
        clean_planar_fill(bm)
        expected=sum(arrangement['regions'][rid]['area'] for rid in selected)
        actual=sum(f.calc_area() for f in bm.faces)
        area_tolerance=max(expected*1e-5,arrangement['scale']**2*2e-8,1e-12)
        if abs(actual-expected)>area_tolerance or any(len(e.link_faces)>2 for e in bm.edges):
            raise RuntimeError(f'Could not validate the chosen shape (area {actual:.9g}, expected {expected:.9g}); the wire guides were not changed.')
        for face in bm.faces:face.select_set(True)
        mesh=bpy.data.meshes.new(name);bm.to_mesh(mesh);mesh.update()
        return mesh
    except Exception:
        if mesh and mesh.users==0:bpy.data.meshes.remove(mesh)
        raise
    finally:bm.free()


def commit_shape(context, arrangement, selected):
    if not selected:raise ValueError('Click or drag over at least one region first.')
    mesh=make_shape_mesh(arrangement,selected)
    obj=None
    try:
        obj=bpy.data.objects.new('Shape Builder',mesh)
        matrix=Matrix.Identity(4)
        for i,axis in enumerate((arrangement['u'],arrangement['v'],arrangement['normal'])):
            for j in range(3):matrix[j][i]=axis[j]
        matrix.translation=arrangement['origin'];obj.matrix_world=matrix
        collection=context.collection or context.scene.collection
        collection.objects.link(obj)
        if context.mode=='EDIT_MESH':bpy.ops.object.mode_set(mode='OBJECT')
        for source in context.selected_objects:source.select_set(False)
        obj.select_set(True);context.view_layer.objects.active=obj
        context.view_layer.update()
        return obj
    except Exception:
        if obj:bpy.data.objects.remove(obj,do_unlink=True)
        if mesh.users==0:bpy.data.meshes.remove(mesh)
        raise


def cancel_running(*_args):
    state=bpy.app.driver_namespace.get(_STATE_KEY)
    if state:state.finish()


class VIEW3D_OT_arch_shape_builder(bpy.types.Operator):
    bl_idname='view3d.arch_shape_builder'
    bl_label='Shape Builder'
    bl_description='Preview and combine enclosed regions from selected planar wires; Enter creates a new mesh, Esc cancels'
    bl_options={'UNDO','BLOCKING'}
    gap_snap: FloatProperty(name='Gap Snap (%)',default=.1,min=0,max=2,precision=3,
                           description='Treat tiny gaps as touching in the preview and new shape; 0 uses exact wires. Guides stay unchanged')

    @classmethod
    def poll(cls,context):
        return (context.area is not None and context.area.type=='VIEW_3D'
                and context.mode in {'OBJECT','EDIT_MESH'}
                and any(o.type in {'MESH','CURVE'} for o in
                        (context.objects_in_mode_unique_data if context.mode=='EDIT_MESH' else context.selected_objects)))

    def invoke(self,context,event):
        if bpy.app.driver_namespace.get(_STATE_KEY):
            self.report({'WARNING'},'Shape Builder is already active; Enter confirms, Esc cancels.')
            return {'CANCELLED'}
        self._handler=None;self._cursor_handler=None;self._done=False;self._area=context.area
        self._window=context.window;self._workspace=context.workspace
        self._region=next(r for r in self._area.regions if r.type=='WINDOW')
        self._view=self._area.spaces.active.region_3d
        self._selected=set();self._hover=-1;self._painting=False;self._navigation=False
        self._history=[];self._last_xy=None;self._dirty=True;self._alt=bool(event.alt)
        self._adding=not self._alt;self._cursor_xy=None
        try:
            points,edges,self._sources=collect_selection(context)
            facing=self._view.view_rotation @ Vector((0,0,1))
            if not self.properties.is_property_set('gap_snap'):
                self.gap_snap=context.window_manager.arch_shape_builder_gap_snap
            self._arr=build_arrangement(points,edges,facing,self.gap_snap)
            self._shader=None;self._selected_batch=None;self._hover_batch=None
            self._handler=bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay,(),'WINDOW','POST_VIEW')
            self._cursor_handler=bpy.types.SpaceView3D.draw_handler_add(self.draw_cursor,(),'WINDOW','POST_PIXEL')
            bpy.app.driver_namespace[_STATE_KEY]=self
            bpy.app.handlers.load_pre.append(cancel_running)
            self._window.cursor_modal_set('CROSSHAIR')
            self.update_status()
            context.window_manager.modal_handler_add(self)
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.finish();self.report({'ERROR'},str(exc));return {'CANCELLED'}

    def update_status(self):
        self._workspace.status_text_set(
            f'Shape Builder | {"REMOVE (-)" if self._alt else "ADD (+)"}: {len(self._selected)} selected / {len(self._arr["regions"])} regions'
            '   |   Click/drag: add   Hold Alt + click/drag: remove   Enter: create   Esc: cancel   Ctrl+Z: undo stroke')

    def hit(self,x,y):
        from bpy_extras.view3d_utils import region_2d_to_origin_3d,region_2d_to_vector_3d
        if not (0<=x<=self._region.width and 0<=y<=self._region.height):return -1
        origin=region_2d_to_origin_3d(self._region,self._view,(x,y))
        direction=region_2d_to_vector_3d(self._region,self._view,(x,y))
        denominator=direction.dot(self._arr['normal'])
        if abs(denominator)<1e-8:return -1
        t=(self._arr['origin']-origin).dot(self._arr['normal'])/denominator
        return region_at_world(self._arr,origin+direction*t)

    def mouse(self,event):
        for region in self._area.regions:
            if (region.type in {'UI','TOOLS','HEADER','TOOL_HEADER'} and region.width>2 and region.height>2
                    and region.x<=event.mouse_x<region.x+region.width
                    and region.y<=event.mouse_y<region.y+region.height):
                self._hover=-1;self._cursor_xy=None;self._last_xy=None;self._dirty=True;self._area.tag_redraw();return
        xy=Vector((event.mouse_x-self._region.x,event.mouse_y-self._region.y))
        self._cursor_xy=xy
        self._hover=self.hit(*xy)
        if self._painting:
            start=self._last_xy if self._last_xy is not None else xy
            steps=max(1,math.ceil((xy-start).length/5))
            for i in range(steps+1):
                rid=self.hit(*start.lerp(xy,i/steps))
                if rid>=0:
                    if self._adding:self._selected.add(rid)
                    else:self._selected.discard(rid)
            self.update_status()
        self._last_xy=xy;self._dirty=True;self._area.tag_redraw()

    def modal(self,context,event):
        if self._done:return {'CANCELLED'}
        if self._area.type!='VIEW_3D':self.finish();return {'CANCELLED'}
        alt=(event.value=='PRESS') if event.type in {'LEFT_ALT','RIGHT_ALT'} else bool(event.alt)
        if alt!=self._alt:
            self._alt=alt;self._adding=not alt
            # Switching modifiers must not repaint the previous mouse segment.
            self._last_xy=None;self._dirty=True
            self.update_status();self._area.tag_redraw()
        if event.type in {'LEFT_ALT','RIGHT_ALT'}:return {'RUNNING_MODAL'}
        if event.type in {'ESC','RIGHTMOUSE'} and event.value=='PRESS':
            self.finish();return {'CANCELLED'}
        if event.type in {'RET','NUMPAD_ENTER'} and event.value=='PRESS':
            if not self._selected:
                self.report({'WARNING'},'Click a region to choose it, then press Enter.');return {'RUNNING_MODAL'}
            try:obj=commit_shape(context,self._arr,self._selected)
            except Exception as exc:
                self.report({'ERROR'},str(exc));return {'RUNNING_MODAL'}
            count=len(self._selected);self.finish()
            self.report({'INFO'},f'Created {obj.name} from {count} region(s); wire guides kept.')
            return {'FINISHED'}
        if event.type=='Z' and event.ctrl and event.value=='PRESS':
            self._painting=False;self._last_xy=None
            if self._history:self._selected=self._history.pop()
            self._dirty=True;self.update_status();self._area.tag_redraw();return {'RUNNING_MODAL'}
        if event.type=='BACK_SPACE' and event.value=='PRESS':
            self._painting=False;self._last_xy=None
            self._history.append(self._selected.copy());self._selected.clear()
            self._dirty=True;self.update_status();self._area.tag_redraw();return {'RUNNING_MODAL'}
        if event.type=='MIDDLEMOUSE':
            self._navigation=event.value=='PRESS';return {'PASS_THROUGH'}
        if event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE','TRACKPADPAN','TRACKPADZOOM','NDOF_MOTION'}:
            return {'PASS_THROUGH'}
        if event.type=='MOUSEMOVE':
            if self._navigation:return {'PASS_THROUGH'}
            self.mouse(event);return {'RUNNING_MODAL'}
        if event.type=='LEFTMOUSE':
            if event.value=='PRESS':
                self.mouse(event);self._history.append(self._selected.copy())
                self._adding=not self._alt
                self._painting=True;self._last_xy=None;self.mouse(event)
            elif event.value=='RELEASE':
                if self._painting:self.mouse(event)
                self._painting=False;self._last_xy=None
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    def draw_overlay(self):
        if self._done or not bpy.context.area or bpy.context.area.as_pointer()!=self._area.as_pointer():return
        import gpu
        from gpu_extras.batch import batch_for_shader
        if self._shader is None:self._shader=gpu.shader.from_builtin('UNIFORM_COLOR')
        if self._dirty:
            def batch(ids):
                coords=[self._arr['world'][v] for rid in ids for i in self._arr['regions'][rid]['triangles']
                        for v in self._arr['triangles'][i]]
                return batch_for_shader(self._shader,'TRIS',{'pos':coords}) if coords else None
            # Leave the hovered region out of the base layer so remove/add
            # previews stay distinct instead of stacking translucent colors.
            self._selected_batch=batch(self._selected-{self._hover})
            hover_valid=self._hover>=0 and (not self._alt or self._hover in self._selected)
            self._hover_batch=batch([self._hover]) if hover_valid else None
            self._dirty=False
        old_blend=gpu.state.blend_get();old_depth=gpu.state.depth_test_get();old_mask=gpu.state.depth_mask_get()
        try:
            gpu.state.blend_set('ALPHA');gpu.state.depth_test_set('NONE');gpu.state.depth_mask_set(False)
            hover_color=(1,.30,.52,.62) if self._alt else (1,.94,.98,.5)
            for batch,color in ((self._selected_batch,(1,.60,.76,.38)),(self._hover_batch,hover_color)):
                if batch:
                    self._shader.bind();self._shader.uniform_float('color',color);batch.draw(self._shader)
        finally:
            gpu.state.blend_set(old_blend);gpu.state.depth_test_set(old_depth);gpu.state.depth_mask_set(old_mask)

    def draw_cursor(self):
        if (self._done or self._hover<0 or self._cursor_xy is None or self._navigation
                or not bpy.context.area or bpy.context.area.as_pointer()!=self._area.as_pointer()):return
        import blf
        scale=bpy.context.preferences.system.ui_scale
        blf.size(0,round(17*scale))
        blf.color(0,*( (1,.60,.76,1) if self._alt else (1,.96,.99,1) ))
        blf.position(0,self._cursor_xy.x+13*scale,self._cursor_xy.y-8*scale,0)
        blf.draw(0,'\u2212' if self._alt else '+')

    def finish(self):
        if getattr(self,'_done',False):return
        self._done=True
        if self._handler:
            bpy.types.SpaceView3D.draw_handler_remove(self._handler,'WINDOW');self._handler=None
        if getattr(self,'_cursor_handler',None):
            bpy.types.SpaceView3D.draw_handler_remove(self._cursor_handler,'WINDOW');self._cursor_handler=None
        if bpy.app.driver_namespace.get(_STATE_KEY)==self:bpy.app.driver_namespace.pop(_STATE_KEY,None)
        if cancel_running in bpy.app.handlers.load_pre:bpy.app.handlers.load_pre.remove(cancel_running)
        try:self._window.cursor_modal_restore();self._workspace.status_text_set(None);self._area.tag_redraw()
        except ReferenceError:pass

    def cancel(self,context):self.finish()


def _remove_shortcuts():
    # Search our own addon key bindings: driver_namespace resets on file load,
    # so it must not be the only place tracking addon registration resources.
    keyconfig=bpy.context.window_manager.keyconfigs.addon
    if keyconfig:
        for keymap in keyconfig.keymaps:
            for item in list(keymap.keymap_items):
                if item.idname=='view3d.arch_shape_builder':
                    keymap.keymap_items.remove(item)
    bpy.app.driver_namespace.pop(_KEYMAP_KEY,None)


def register():
    cancel_running()
    _remove_shortcuts()
    previous=getattr(bpy.types,VIEW3D_OT_arch_shape_builder.__name__,None)
    if previous:bpy.utils.unregister_class(previous)
    bpy.utils.register_class(VIEW3D_OT_arch_shape_builder)
    if not hasattr(bpy.types.WindowManager,'arch_shape_builder_gap_snap'):
        bpy.types.WindowManager.arch_shape_builder_gap_snap=FloatProperty(
            name='Gap Snap (%)',default=.1,min=0,max=2,soft_max=.5,precision=3,
            description='Close tiny gaps in the preview/new shape; 0 uses exact wires. Guides stay unchanged')
    keyconfig=bpy.context.window_manager.keyconfigs.addon
    if keyconfig:
        for name in ('Object Mode','Mesh'):
            keymap=keyconfig.keymaps.new(name=name,space_type='EMPTY')
            keymap.keymap_items.new('view3d.arch_shape_builder','M','PRESS',shift=True)


def unregister():
    cancel_running()
    _remove_shortcuts()
    previous=getattr(bpy.types,VIEW3D_OT_arch_shape_builder.__name__,None)
    if previous:bpy.utils.unregister_class(previous)
    if hasattr(bpy.types.WindowManager,'arch_shape_builder_gap_snap'):
        del bpy.types.WindowManager.arch_shape_builder_gap_snap
