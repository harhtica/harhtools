"""harhtools Shape Builder: selected planar mesh edges and curve outlines.

Run this script once, then use harhtools > Shape Builder or Shift+Q in 3D View.
Hover previews a bounded region. Click/drag adds; hold Alt and click/drag to remove.
Separate clicks create separate fills; one drag merges only touched fills.
Ctrl+Z undoes a stroke. Shape Library saves are manual through its + button.
Enter creates an editable Bezier curve by default. Esc/right-click cancels.
Guides stay unchanged unless Cut Selected Guides is enabled on confirmation.
In Edit Mode only selected visible mesh edges or Bezier segments are used.
Gap Snap adds short connectors across tiny gaps in the preview/new shape only;
set it to 0 for exact wires. Larger open gaps do not enclose a region.
Wires must share a plane, at any orientation.
Editable output reconstructs original Bezier subcurves and retains holes.
Optional mesh output uses cleaned planar faces. Edge Trim retains open paths.
"""
import bpy
import bmesh
import math
import time
from collections import defaultdict
from mathutils import Vector, Matrix
from mathutils.geometry import delaunay_2d_cdt
from mathutils.bvhtree import BVHTree
from bpy.props import FloatProperty, EnumProperty, BoolProperty
from . import shortcuts, intersection_cuts, curve_geometry, fill_groups

_STATE_KEY = 'arch_tools_shape_builder'
_KEYMAP_KEY = 'arch_tools_shape_builder_keymaps'
_FEEDBACK_SECONDS=.42
_COMET_SECONDS=.85
_COMET_MAX_REGIONS=8
_COMET_MAX_SEGMENTS=2048
_NAVIGATION_OPERATORS={'VIEW3D_OT_rotate','VIEW3D_OT_move','VIEW3D_OT_zoom',
                       'VIEW3D_OT_dolly','VIEW3D_OT_view_roll','VIEW3D_OT_walk','VIEW3D_OT_fly'}

def feedback_tick():
    state=bpy.app.driver_namespace.get(_STATE_KEY)
    if not state or getattr(state,'_done',False):return None
    now=time.monotonic()
    expired=[rid for rid,(started,adding) in state._feedback.items() if now-started>=_FEEDBACK_SECONDS]
    for rid in expired:state._feedback.pop(rid,None)
    comets=getattr(state,'_comets',{})
    for rid in [rid for rid,(started,adding) in comets.items() if now-started>=_COMET_SECONDS]:
        comets.pop(rid,None)
        getattr(state,'_comet_paths',{}).pop(rid,None)
    if expired:state._dirty=True
    try:state._area.tag_redraw()
    except ReferenceError:return None
    return .025 if state._feedback or comets else None


def feedback_alpha(age,adding,opacity):
    # Confirm a fill immediately; animation must never delay visible feedback.
    if adding:return opacity
    t=max(0,min(1,age/_FEEDBACK_SECONDS))
    smooth=t*t*(3-2*t)
    # Ease into the persistent fill without an overshooting brightness pulse.
    return opacity*.65*(1-smooth)


def boundary_paths(arrangement,rid):
    """Ordered, separate region boundaries; never bridge holes or loose slits."""
    boundary=arrangement['regions'][rid]['boundary']
    if len(boundary)>50000:return []
    counts=defaultdict(int)
    for a,b in boundary:counts[tuple(sorted((a,b)))]+=1
    edges={(a,b) for a,b in boundary if counts[tuple(sorted((a,b)))]==1}
    following=defaultdict(set)
    for a,b in edges:following[a].add(b)
    paths=[];world=arrangement['world']
    while edges:
        first=min(edges);start,current=first;indices=[start,current]
        edges.remove(first);following[start].remove(current)
        while current!=start and following[current]:
            # Exact constraint edges only. Stable ordering also handles touching
            # loops without jumping across their interior.
            target=min(following[current])
            edges.remove((current,target));following[current].remove(target)
            indices.append(target);current=target
        points=[world[i].copy() for i in indices]
        lengths=[0.0]
        for a,b in zip(points,points[1:]):lengths.append(lengths[-1]+(b-a).length)
        if lengths[-1]>1e-10:paths.append((points,lengths))
    # Outer boundary plus the largest holes; even complex fills remain responsive.
    return sorted(paths,key=lambda path:path[1][-1],reverse=True)[:4]


def comet_segments(path,age,max_segments=_COMET_MAX_SEGMENTS):
    """Return exact edge pieces and their tapered weights for one comet pass."""
    if age<=0 or age>=_COMET_SECONDS or max_segments<=0:return []
    points,lengths=path;length=lengths[-1]
    progress=age/_COMET_SECONDS
    head=length*progress;tail=length*.19
    start=max(0.0,head-tail)
    fade_in=min(1.0,progress/.10)
    fade_out=min(1.0,(1-progress)/.28)
    envelope=fade_in*fade_in*(3-2*fade_in)*fade_out*fade_out*(3-2*fade_out)
    result=[]
    # Walk back from the head. If a dense path hits the drawing budget, discard
    # only its faint tail, keeping the useful current position visible.
    from bisect import bisect_left
    end=min(len(points)-2,max(0,bisect_left(lengths,head)-1))
    for i in range(end,-1,-1):
        left,right=lengths[i],lengths[i+1]
        if right<=start:break
        span=right-left
        if span<=1e-12:continue
        a=max(left,start);b=min(right,head)
        if b<=a:continue
        # Short subsegments keep the small bright head narrow even on a single
        # long straight side. They remain precisely on that original edge.
        pieces=max(1,min(16,math.ceil((b-a)/max(tail/12,1e-12))))
        for j in reversed(range(pieces)):
            s=a+(b-a)*j/pieces;t=a+(b-a)*(j+1)/pieces
            weights=[envelope*max(0.0,1-(head-d)/tail)**2 for d in (s,t)]
            result.append((points[i].lerp(points[i+1],(s-left)/span),
                           points[i].lerp(points[i+1],(t-left)/span),*weights))
            if len(result)>=max_segments:return result
    return result



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


def build_arrangement(points, edges, facing=None, gap_snap=0.0, source_spans=None, source_primitives=None, allow_open=False, pen_basis=None):
    if pen_basis is None:
        origin,u,v,normal,scale,xy = planar_basis(points,facing)
    else:
        origin,u,v,normal,scale,_=pen_basis
        xy=[Vector(((p-origin).dot(u)/scale,(p-origin).dot(v)/scale)) for p in points]
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
    remapped={};span_lookup={}
    for index,(a,b) in enumerate(edges):
        if ids[a]==ids[b]:continue
        key=tuple(sorted((ids[a],ids[b])))
        if key not in remapped:
            remapped[key]=len(remapped)
            if source_spans is not None and index<len(source_spans):
                k,t0,t1=source_spans[index]
                span_lookup[remapped[key]]=(k,t0,t1,a,b)
    edges=list(remapped)
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
    if not regions and not allow_open:
        raise ValueError('No closed regions found. Include all boundary wires and close any gaps.')
    # Only count original wire constraints, never triangulation diagonals.
    junction_neighbors=defaultdict(set)
    for a,b in constraints:
        junction_neighbors[a].add(b);junction_neighbors[b].add(a)
    junctions=[i for i,neighbors in junction_neighbors.items() if len(neighbors)>=3]
    world=[origin+(u*p.x+v*p.y)*scale for p in vertices]
    bvh=BVHTree.FromPolygons([Vector((p.x,p.y,0)) for p in vertices],triangles,all_triangles=True) if triangles else None
    output_spans={}
    for edge,originals in zip(out_edges,orig_edges):
        match=next((span_lookup[i] for i in originals if i in span_lookup),None)
        if match is None:continue
        k,t0,t1,a,b=match;delta=xy[b]-xy[a];den=delta.length_squared
        if den<1e-24:continue
        aa,bb=sorted(edge)
        params=[t0+(t1-t0)*max(0,min(1,(vertices[v]-xy[a]).dot(delta)/den)) for v in (aa,bb)]
        output_spans[(aa,bb)]=(k,*params)
    return {'vertices':vertices,'world':world,'triangles':triangles,'regions':regions,
            'tri_region':tri_region,'edge_faces':dict(edge_faces),'origin':origin,'u':u,'v':v,
            'normal':normal,'scale':scale,'bvh':bvh,'closed_gaps':closed_gaps,
            'junctions':junctions,'constraint_edges':list(constraints),
            'source_spans':output_spans,'source_primitives':source_primitives or []}


def build_pen_arrangement(context,facing=None,gap_snap=0.0):
    primitives,names=curve_geometry.collect(context)
    control_points=[Vector(p) for s in primitives for p in s['cp']]
    try:basis=planar_basis(control_points,facing)
    except ValueError as exc:
        if 'two-dimensional area' not in str(exc):raise
        origin=sum(control_points,Vector())/len(control_points)
        delta=max((p-origin for p in control_points),key=lambda p:p.length_squared)
        if delta.length<1e-10:raise ValueError('The selected segments have zero length.')
        u=delta.normalized();normal=Vector(facing) if facing is not None else Vector((0,0,1))
        normal-=u*normal.dot(u)
        if normal.length<1e-8:
            normal=u.cross(Vector((0,1,0)))
            if normal.length<1e-8:normal=u.cross(Vector((1,0,0)))
        normal.normalize();v=normal.cross(u).normalized();scale=delta.length
        basis=(origin,u,v,normal,scale,[])
    points,edges,spans=curve_geometry.prepare(primitives,basis)
    arr=build_arrangement(points,edges,facing,gap_snap,spans,primitives,allow_open=True,pen_basis=basis)
    arr['edge_fragments']=curve_geometry.edge_fragments(arr)
    return arr,names


def region_at_world(arrangement, point):
    if arrangement['bvh'] is None:return -1
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


def guide_selection_snapshot(context):
    objects=context.objects_in_mode_unique_data if context.mode=='EDIT_MESH' else context.selected_objects
    result={}
    for obj in objects:
        if obj.type=='MESH' and obj.visible_get():
            geometry=intersection_cuts.selected_geometry(obj)
            if geometry['edges']:result[obj.name]=geometry
    return result


def cut_original_guides(context, expected=None):
    objects=context.objects_in_mode_unique_data if context.mode=='EDIT_MESH' else context.selected_objects
    if any(obj.type=='CURVE' and obj.visible_get() for obj in objects):
        raise ValueError('Convert curve guides to meshes before using Cut Selected Guides.')
    current=guide_selection_snapshot(context)
    if not current:
        raise ValueError('Cut Selected Guides needs mesh edges or faces. Convert curve guides to meshes first.')
    if expected is not None and current!=expected:
        raise ValueError('The guide selection or geometry changed. Restart Shape Builder before cutting guides.')
    return intersection_cuts.run(push_undo=False)


def commit_fill_groups(context, arrangement, groups, *, cut_guides=False, guide_snapshot=None, output_type='CURVE', edge_runs=None):
    """Build independent fills transactionally; never capture library presets."""
    groups=fill_groups.copy_groups(groups)
    if edge_runs is not None:groups=[set()]
    if not groups:raise ValueError('Click or drag over at least one region first.')
    data_blocks=[];objects=[]
    try:
        # Validate every output before linking anything or changing guide selection.
        for group in groups:
            data_blocks.append(curve_geometry.curve_data(arrangement,group,edge_runs=edge_runs)
                               if output_type=='CURVE' else make_shape_mesh(arrangement,group))
        matrix=Matrix.Identity(4)
        for i,axis in enumerate((arrangement['u'],arrangement['v'],arrangement['normal'])):
            for j in range(3):matrix[j][i]=axis[j]
        matrix.translation=arrangement['origin']
        collection=context.collection or context.scene.collection
        for data in data_blocks:
            obj=bpy.data.objects.new('Shape Builder',data);objects.append(obj)
            obj.matrix_world=matrix;collection.objects.link(obj)
        # Run once with the ORIGINAL guide selection, never on a preceding result.
        if cut_guides:cut_original_guides(context,guide_snapshot)
        if context.mode in {'EDIT_MESH','EDIT_CURVE'}:bpy.ops.object.mode_set(mode='OBJECT')
        for source in context.selected_objects:source.select_set(False)
        for obj in objects:obj.select_set(True)
        context.view_layer.objects.active=objects[-1]
        context.view_layer.update()
        return objects
    except Exception:
        for obj in objects:bpy.data.objects.remove(obj,do_unlink=True)
        for data in data_blocks:
            if data.users==0:(bpy.data.curves if output_type=='CURVE' else bpy.data.meshes).remove(data)
        raise


def commit_shape(context, arrangement, selected, **kwargs):
    """Compatibility entry point for a single explicit fill/edge result."""
    return commit_fill_groups(context,arrangement,[selected],**kwargs)[0]


def cancel_running(*_args):
    state=bpy.app.driver_namespace.get(_STATE_KEY)
    if state:state.finish()
    if bpy.app.timers.is_registered(feedback_tick):bpy.app.timers.unregister(feedback_tick)


class VIEW3D_OT_arch_shape_builder(bpy.types.Operator):
    bl_idname='view3d.arch_shape_builder'
    bl_label='Shape Builder'
    bl_description='Combine regions or trim edge fragments into an editable Bezier curve; Enter creates the result, Esc cancels'
    bl_options={'UNDO'}
    gap_snap: FloatProperty(name='Gap Snap',subtype='PERCENTAGE',default=0,min=0,max=2,precision=3,
                           description='Treat tiny gaps as touching in the preview and new shape; 0 uses exact wires. Guides stay unchanged')

    @classmethod
    def poll(cls,context):
        return (context.area is not None and context.area.type=='VIEW_3D'
                and not bpy.app.driver_namespace.get('harhtools_array_preview')
                and context.mode in {'OBJECT','EDIT_MESH','EDIT_CURVE'}
                and any(o.type in {'MESH','CURVE'} for o in
                        (context.objects_in_mode_unique_data if context.mode in {'EDIT_MESH','EDIT_CURVE'} else context.selected_objects)))

    def invoke(self,context,event):
        if bpy.app.driver_namespace.get('harhtools_array_preview'):
            self.report({'WARNING'},'Finish the Array preview first.')
            return {'CANCELLED'}
        if bpy.app.driver_namespace.get(_STATE_KEY):
            self.report({'WARNING'},'Shape Builder is already active; Enter confirms, Esc cancels.')
            return {'CANCELLED'}
        self._handler=None;self._cursor_handler=None;self._done=False;self._area=context.area
        self._window=context.window;self._workspace=context.workspace
        self._region=next(r for r in self._area.regions if r.type=='WINDOW')
        self._view=self._area.spaces.active.region_3d
        self._selected=set();self._groups=[];self._stroke_groups=();self._stroke_hits=set()
        self._hover=-1;self._painting=False;self._navigation=False
        self._hover_edge=-1;self._retained_edges=set();self._touched=False
        self._edge_mode=context.window_manager.arch_shape_builder_edit_mode=='EDGES'
        self._history=[];self._last_xy=None;self._dirty=True
        self._outline_key=None;self._hover_outline_key=None
        self._outline=[];self._hover_outline=[];self._feedback_batches={}
        self._projection_key=None;self._projected={};self._screen_line_cache={}
        self._cursor_shader=None;self._junction_batches=None
        self._mode=context.window_manager.arch_shape_builder_mode
        self._alt_held=shortcuts.remove_held(event,context);self._alt=self._mode=='REMOVE' or self._alt_held
        self._adding=not self._alt;self._cursor_xy=None;self._trail=[];self._feedback={}
        self._comets={};self._comet_paths={};self._comet_shader=None
        try:
            self._guide_snapshot=guide_selection_snapshot(context)
            facing=self._view.view_rotation @ Vector((0,0,1))
            if not self.properties.is_property_set('gap_snap'):
                self.gap_snap=context.window_manager.arch_shape_builder_gap_snap
            self._arr,self._sources=build_pen_arrangement(context,facing,self.gap_snap)
            self._retained_edges=set(range(len(self._arr['edge_fragments'])))
            if not self._arr['regions']:
                self._edge_mode=True;context.window_manager.arch_shape_builder_edit_mode='EDGES'
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
        cfg=shortcuts.settings()
        status=(f'{len(self._retained_edges)} retained edge fragments' if self._edge_mode
                else f'{len(self._groups)} separate fills / {len(self._selected)} regions')
        self._workspace.status_text_set(
            f'Shape Builder | {"REMOVE (-)" if self._alt else "ADD (+)"}: {status}'
            f'   |   Click: separate fill   Drag: merge touched fills   Hold {cfg.remove_modifier.title()}: remove   '
            f'{shortcuts.key_label(cfg.confirm_key)}: create   {shortcuts.key_label(cfg.cancel_key)}: cancel   Ctrl+{cfg.undo_key}: undo stroke')

    def hit(self,x,y):
        from bpy_extras.view3d_utils import region_2d_to_origin_3d,region_2d_to_vector_3d
        if not (0<=x<=self._region.width and 0<=y<=self._region.height):return -1
        origin=region_2d_to_origin_3d(self._region,self._view,(x,y))
        direction=region_2d_to_vector_3d(self._region,self._view,(x,y))
        denominator=direction.dot(self._arr['normal'])
        if abs(denominator)<1e-8:return -1
        t=(self._arr['origin']-origin).dot(self._arr['normal'])/denominator
        return region_at_world(self._arr,origin+direction*t)

    def hit_edge(self,x,y):
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        point=Vector((x,y));best=-1;distance=(9*bpy.context.preferences.system.ui_scale)**2
        projected=self.projection_cache()
        for index,run in enumerate(self._arr['edge_fragments']):
            for a,b in run:
                for v in (a,b):
                    if v not in projected:projected[v]=location_3d_to_region_2d(self._region,self._view,self._arr['world'][v])
                pa,pb=projected[a],projected[b]
                if pa is None or pb is None:continue
                delta=pb-pa
                if delta.length_squared<1e-12:continue
                t=max(0,min(1,(point-pa).dot(delta)/delta.length_squared))
                d=(point-pa-delta*t).length_squared
                if d<distance:best=index;distance=d
        return best

    def projection_cache(self):
        """Reuse screen positions until navigation or viewport dimensions change."""
        key=(self._region.width,self._region.height,
             tuple(value for row in self._view.perspective_matrix for value in row),
             bpy.context.preferences.system.ui_scale)
        if key!=self._projection_key:
            self._projection_key=key;self._projected={}
            self._screen_line_cache={};self._junction_batches=None
        return self._projected

    def preview_boundaries(self):
        """Geometry is fixed during a session; only changed fill ownership rebuilds it."""
        key=(self._edge_mode,tuple(sorted(self._retained_edges)) if self._edge_mode
             else fill_groups.snapshot_groups(self._groups))
        if key!=self._outline_key:
            self._outline_key=key
            self._outline=([e for i in sorted(self._retained_edges) for e in self._arr['edge_fragments'][i]]
                if self._edge_mode else sorted({tuple(sorted(edge))
                    for outline in fill_groups.boundary_edges_for_groups(self._arr,self._groups)
                    for edge in outline}))
        hover_regions=fill_groups.group_for_region(self._groups,self._hover)
        hover_key=frozenset(hover_regions)
        if hover_key!=self._hover_outline_key:
            self._hover_outline_key=hover_key
            self._hover_outline=(fill_groups.boundary_edges_for_groups(self._arr,[hover_regions])[0]
                                 if hover_regions else [])
        return hover_regions

    def set_mode(self,mode):
        self._mode=mode
        self._alt=mode=='REMOVE' or self._alt_held
        self._adding=not self._alt
        self._painting=False;self._last_xy=None;self._trail=[];self._dirty=True
        self.update_status();self._area.tag_redraw()

    def over_controls(self,event):
        return any(region.type in {'UI','TOOLS','HEADER','TOOL_HEADER'}
                   and region.width>2 and region.height>2
                   and region.x<=event.mouse_x<region.x+region.width
                   and region.y<=event.mouse_y<region.y+region.height
                   for region in self._area.regions)

    def mark_feedback(self,rid,adding):
        started=time.monotonic()
        self._feedback[rid]=(started,adding)
        self._comets.pop(rid,None)
        self._comets[rid]=(started,adding)
        self._comet_paths[rid]=boundary_paths(self._arr,rid)
        while len(self._comets)>_COMET_MAX_REGIONS:
            oldest=next(iter(self._comets))
            self._comets.pop(oldest,None);self._comet_paths.pop(oldest,None)
        self._dirty=True
        if not bpy.app.timers.is_registered(feedback_tick):
            bpy.app.timers.register(feedback_tick,first_interval=.025)

    def mouse(self,event):
        if self.over_controls(event):
            self._hover=-1;self._cursor_xy=None;self._last_xy=None
            self._dirty=True;self._area.tag_redraw();return
        xy=Vector((event.mouse_x-self._region.x,event.mouse_y-self._region.y))
        self._cursor_xy=xy
        previous_hover=(self._edge_mode,self._hover,self._hover_edge)
        self._edge_mode=bpy.context.window_manager.arch_shape_builder_edit_mode=='EDGES'
        self._hover=self.hit(*xy) if not self._edge_mode else -1
        self._hover_edge=self.hit_edge(*xy) if self._edge_mode else -1
        if previous_hover!=(self._edge_mode,self._hover,self._hover_edge):self._dirty=True
        if self._painting:
            if not self._trail or (xy-self._trail[-1]).length>=2:
                self._trail.append(xy.copy())
                # Only the cosmetic trail is bounded; every drag segment still
                # participates in region hit testing and fill ownership.
                if len(self._trail)>256:self._trail=self._trail[-256:]
            start=self._last_xy if self._last_xy is not None else xy
            steps=max(1,math.ceil((xy-start).length/5))
            hit_count=len(self._stroke_hits);edges_changed=False
            # The previous endpoint was already handled by its event. The new
            # endpoint is the current hover hit, so avoid two redundant casts.
            for i in range(1,steps+1):
                location=start.lerp(xy,i/steps)
                if self._edge_mode:
                    eid=self._hover_edge if i==steps else self.hit_edge(*location)
                    if eid>=0:
                        edges_changed|=(eid in self._retained_edges)!=self._adding
                        if self._adding:self._retained_edges.add(eid)
                        else:self._retained_edges.discard(eid)
                    continue
                rid=self._hover if i==steps else self.hit(*location)
                if rid>=0:self._stroke_hits.add(rid)
            groups_changed=False
            if not self._edge_mode and len(self._stroke_hits)!=hit_count:
                previous=self._selected.copy()
                groups=fill_groups.gesture_groups(self._stroke_groups,self._stroke_hits,erase=not self._adding)
                groups_changed=groups!=self._groups
                self._groups=groups
                self._selected=fill_groups.selected_regions(self._groups)
                for rid in self._selected-previous:self.mark_feedback(rid,True)
                for rid in previous-self._selected:self.mark_feedback(rid,False)
            if groups_changed or edges_changed:
                self._dirty=True;self.update_status()
        self._last_xy=xy;self._area.tag_redraw()

    def modal(self,context,event):
        if self._done:return {'CANCELLED'}
        if self._area.type!='VIEW_3D':self.finish();return {'CANCELLED'}
        cfg=shortcuts.settings(context)
        modifier_events={'LEFT_'+cfg.remove_modifier,'RIGHT_'+cfg.remove_modifier}
        alt=(event.value=='PRESS') if event.type in modifier_events else shortcuts.remove_held(event,context)
        self._alt_held=alt
        alt=self._mode=='REMOVE' or alt
        if alt!=self._alt:
            self._alt=alt;self._adding=not alt
            # Switching modifiers must not repaint the previous mouse segment.
            self._last_xy=None;self._dirty=True
            self._stroke_groups=fill_groups.snapshot_groups(self._groups);self._stroke_hits=set()
            self.update_status();self._area.tag_redraw()
        if event.type in modifier_events:return {'RUNNING_MODAL'}
        # Let native sidebar buttons receive clicks while the preview stays live.
        # End a stroke here so returning to the canvas cannot paint a bridge.
        if self.over_controls(event):
            self._painting=False;self._navigation=False;self._last_xy=None;self._trail=[]
            self._hover=-1;self._cursor_xy=None;self._dirty=True
            self._area.tag_redraw()
            return {'PASS_THROUGH'}
        if event.type in {cfg.cancel_key,'RIGHTMOUSE'} and event.value=='PRESS':
            self.finish();return {'CANCELLED'}
        if (event.type==cfg.confirm_key or cfg.confirm_key=='RET' and event.type=='NUMPAD_ENTER') and event.value=='PRESS':
            if not self._selected and not (self._edge_mode and self._retained_edges):
                self.report({'WARNING'},'Click a region to choose it, then press Enter.');return {'RUNNING_MODAL'}
            curve_guides=any(bpy.data.objects.get(name) is not None and bpy.data.objects[name].type=='CURVE' for name in self._sources)
            skip_curve_cut=curve_guides and context.window_manager.arch_shape_builder_cut_guides
            try:objects=commit_fill_groups(context,self._arr,self._groups,
                cut_guides=context.window_manager.arch_shape_builder_cut_guides and not curve_guides,
                guide_snapshot=getattr(self,'_guide_snapshot',None),
                output_type='CURVE' if self._edge_mode else context.window_manager.arch_shape_builder_output_type,
                edge_runs=[self._arr['edge_fragments'][i] for i in sorted(self._retained_edges)] if self._edge_mode else None)
            except Exception as exc:
                self.report({'ERROR'},str(exc));return {'RUNNING_MODAL'}
            self.finish()
            if skip_curve_cut:
                self.report({'WARNING'},'Created editable result. Curve guides were preserved; Cut Selected Guides only applies to mesh input.')
            else:self.report({'INFO'},f'Created {len(objects)} separate shape(s). Use Shape Library + to save manually.')
            return {'FINISHED'}
        if event.type==cfg.undo_key and event.ctrl and event.value=='PRESS':
            self._feedback.clear()
            self._comets.clear();self._comet_paths.clear()
            self._painting=False;self._last_xy=None;self._trail=[]
            if self._history:
                snapshot,self._retained_edges,self._touched=self._history.pop()
                self._groups=fill_groups.restore_groups(snapshot)
                self._selected=fill_groups.selected_regions(self._groups)
            self._stroke_groups=fill_groups.snapshot_groups(self._groups);self._stroke_hits=set()
            self._dirty=True;self.update_status();self._area.tag_redraw();return {'RUNNING_MODAL'}
        if event.type=='MIDDLEMOUSE':
            self._navigation=event.value=='PRESS';return {'PASS_THROUGH'}
        if event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE','TRACKPADPAN','TRACKPADZOOM','NDOF_MOTION'}:
            return {'PASS_THROUGH'}
        if event.type in {'MOUSEMOVE','INBETWEEN_MOUSEMOVE'}:
            # Blender's navigation operator can consume the middle-button
            # release. Recover as soon as that operator has finished.
            if self._navigation:
                operators=getattr(context.window,'modal_operators',None)
                if operators is not None:
                    self._navigation=any(getattr(op,'bl_idname','') in _NAVIGATION_OPERATORS
                                         for op in operators)
            if self._navigation:return {'PASS_THROUGH'}
            if event.type=='MOUSEMOVE':self.mouse(event)
            return {'RUNNING_MODAL'}
        if event.type=='LEFTMOUSE':
            if event.value=='PRESS':
                self._navigation=False
                self.mouse(event);self._history.append((fill_groups.snapshot_groups(self._groups),self._retained_edges.copy(),self._touched))
                self._stroke_groups=fill_groups.snapshot_groups(self._groups);self._stroke_hits=set()
                self._touched=True
                self._adding=not self._alt
                self._painting=True;self._last_xy=None;self._trail=[];self.mouse(event)
            elif event.value=='RELEASE':
                if self._painting:self.mouse(event)
                self._painting=False;self._last_xy=None;self._trail=[]
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    def draw_overlay(self):
        if self._done or not bpy.context.area or bpy.context.area.as_pointer()!=self._area.as_pointer():return
        import gpu
        from gpu_extras.batch import batch_for_shader
        if self._shader is None:self._shader=gpu.shader.from_builtin('UNIFORM_COLOR')
        def batch(ids):
            coords=[self._arr['world'][v] for rid in ids for i in self._arr['regions'][rid]['triangles']
                    for v in self._arr['triangles'][i]]
            return batch_for_shader(self._shader,'TRIS',{'pos':coords}) if coords else None
        if self._dirty:
            # Leave the hovered region out of the base layer so remove/add
            # previews stay distinct instead of stacking translucent colors.
            hover_regions=self.preview_boundaries()
            self._selected_batch=batch(self._selected-hover_regions-set(self._feedback))
            hover_valid=self._hover>=0 and (not self._alt or self._hover in self._selected)
            self._hover_batch=batch(hover_regions-set(self._feedback)) if hover_valid else None
            self._dirty=False
        old_blend=gpu.state.blend_get();old_depth=gpu.state.depth_test_get();old_mask=gpu.state.depth_mask_get()
        try:
            gpu.state.blend_set('ALPHA');gpu.state.depth_test_set('NONE');gpu.state.depth_mask_set(False)
            cfg=shortcuts.settings()
            opacity=cfg.preview_opacity/100
            hover_color=(*cfg.remove_color,opacity*.65) if self._alt else (*cfg.accent_color,opacity if self._hover in self._selected else opacity*.15)
            for fill_batch,color in ((self._selected_batch,(*cfg.accent_color,opacity)),(self._hover_batch,hover_color)):
                if fill_batch:
                    self._shader.bind();self._shader.uniform_float('color',color);fill_batch.draw(self._shader)
            now=time.monotonic()
            for rid,(started,adding) in self._feedback.items():
                strength=feedback_alpha(now-started,adding,opacity)
                if strength<=0:continue
                if rid not in self._feedback_batches:self._feedback_batches[rid]=batch([rid])
                fill_batch=self._feedback_batches[rid]
                if fill_batch:
                    color=(*cfg.accent_color,strength) if adding else (*cfg.remove_color,strength)
                    self._shader.bind();self._shader.uniform_float('color',color);fill_batch.draw(self._shader)
            self.draw_comets(cfg,now)
        finally:
            gpu.state.blend_set(old_blend);gpu.state.depth_test_set(old_depth);gpu.state.depth_mask_set(old_mask)

    def draw_comets(self,cfg,now):
        if not self._comets or cfg.preview_opacity<=0:return
        import gpu
        from gpu_extras.batch import batch_for_shader
        if self._comet_shader is None:
            self._comet_shader=gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
        positions=[];tints=[];weights=[]
        budget=_COMET_MAX_SEGMENTS
        bias=(self._view.view_rotation @ Vector((0,0,1)))*max(self._arr['scale']*2e-6,1e-7)
        for rid,(started,adding) in reversed(list(self._comets.items())):
            tint=cfg.accent_color if adding else cfg.remove_color
            for path in self._comet_paths.get(rid,()):
                segments=comet_segments(path,now-started,budget)
                for a,b,wa,wb in segments:
                    positions.extend((a+bias,b+bias));weights.extend((wa,wb));tints.extend((tint,tint))
                budget-=len(segments)
                if budget<=0:break
            if budget<=0:break
        if not positions:return
        shader=self._comet_shader
        strength=min(1.0,cfg.preview_opacity/100*1.4)
        scale=bpy.context.preferences.system.ui_scale
        gpu.state.depth_test_set('LESS_EQUAL')
        shader.bind()
        shader.uniform_float('viewportSize',gpu.state.viewport_get()[2:])
        # Wide translucent halo, soft tail, narrow core. No full-region flash,
        # displacement, random noise, or permanent extra contour is introduced.
        for width,alpha,head_mix in ((6.0,.055,0),(3.0,.13,0),(1.35,.55,.35)):
            colors=[]
            for tint,weight in zip(tints,weights):
                mix=head_mix*weight**6
                rgb=[tint[i]*(1-mix)+cfg.light_color[i]*mix for i in range(3)]
                colors.append((*rgb,weight*alpha*strength))
            shader.uniform_float('lineWidth',width*scale)
            batch_for_shader(shader,'LINES',{'pos':positions,'color':colors}).draw(shader)

    def draw_cursor(self):
        if (self._done or not bpy.context.area
                or bpy.context.area.as_pointer()!=self._area.as_pointer()):return
        import blf,gpu
        from gpu_extras.batch import batch_for_shader
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        scale=bpy.context.preferences.system.ui_scale
        cfg=shortcuts.settings()
        if self._cursor_shader is None:self._cursor_shader=gpu.shader.from_builtin('UNIFORM_COLOR')
        shader=self._cursor_shader
        old_blend=gpu.state.blend_get();old_depth=gpu.state.depth_test_get()
        old_mask=gpu.state.depth_mask_get()
        def draw(coords,color):
            if coords:
                shader.bind();shader.uniform_float('color',color)
                batch_for_shader(shader,'TRIS',{'pos':coords}).draw(shader)
        def segment(coords,a,b,width):
            delta=b-a
            if delta.length_squared<1e-8:return
            n=Vector((-delta.y,delta.x)).normalized()*width*.5
            corners=[a+n,a-n,b-n,b+n]
            coords.extend((corners[i].x,corners[i].y,0) for i in (0,1,2,0,2,3))
        def disk(coords,p,radius):
            for i in range(16):
                a=i*math.tau/16;b=(i+1)*math.tau/16
                coords.extend(((p.x,p.y,0),(p.x+radius*math.cos(a),p.y+radius*math.sin(a),0),
                               (p.x+radius*math.cos(b),p.y+radius*math.sin(b),0)))
        projected=self.projection_cache()
        def project(index):
            if index not in projected:
                projected[index]=location_3d_to_region_2d(self._region,self._view,self._arr['world'][index])
            return projected[index]
        def draw_edges(name,edges,color,width):
            cached=self._screen_line_cache.get(name)
            if cached is None or cached[0] is not edges or cached[1]!=width:
                coords=[]
                for a,b in edges:
                    pa,pb=project(a),project(b)
                    if pa is not None and pb is not None:segment(coords,pa,pb,width)
                line_batch=batch_for_shader(shader,'TRIS',{'pos':coords}) if coords else None
                cached=(edges,width,line_batch);self._screen_line_cache[name]=cached
            if cached[2]:
                shader.bind();shader.uniform_float('color',color);cached[2].draw(shader)
        try:
            gpu.state.blend_set('ALPHA');gpu.state.depth_test_set('NONE');gpu.state.depth_mask_set(False)
            # Project the true region boundaries; no triangulation lines are shown.
            draw_edges('selected',self._outline,(*cfg.accent_color,.95),1.5*scale)
            draw_edges('hover',self._hover_outline,
                       (*cfg.remove_color,1) if self._alt else (*cfg.light_color,1),2*scale)
            if self._edge_mode and self._hover_edge>=0:
                draw_edges('edge',self._arr['edge_fragments'][self._hover_edge],
                           (*cfg.remove_color,1) if self._alt else (*cfg.light_color,1),3*scale)
            if self._junction_batches is None:
                outer=[];inner=[]
                for index in self._arr.get('junctions',[]):
                    point=project(index)
                    if point is not None and 0<=point.x<=self._region.width and 0<=point.y<=self._region.height:
                        disk(outer,point,5*scale);disk(inner,point,3.2*scale)
                self._junction_batches=[batch_for_shader(shader,'TRIS',{'pos':coords}) if coords else None
                                        for coords in (outer,inner)]
            for marker_batch,color in zip(self._junction_batches,((.12,.08,.10,.95),(*cfg.light_color,1))):
                if marker_batch:
                    shader.bind();shader.uniform_float('color',color);marker_batch.draw(shader)
            # A dashed drag trail like Illustrator's Shape Builder gesture.
            if self._painting and len(self._trail)>1:
                shadow=[];dashes=[];distance=0;dash=7*scale
                for a,b in zip(self._trail,self._trail[1:]):
                    length=(b-a).length
                    if length<1e-6:continue
                    segment(shadow,a,b,3*scale)
                    offset=0
                    while offset<length:
                        phase=distance%(dash*2)
                        step=min(length-offset,dash-(phase%dash))
                        if step<1e-6:step=min(length-offset,1e-5)
                        if phase<dash:
                            segment(dashes,a.lerp(b,offset/length),a.lerp(b,(offset+step)/length),1.5*scale)
                        offset+=step;distance+=step
                draw(shadow,(.12,.08,.10,.85))
                draw(dashes,(*cfg.remove_color,1) if self._alt else (*cfg.light_color,1))
            if self._cursor_xy is not None and not self._navigation:
                blf.size(0,round(17*scale))
                blf.color(0,*(cfg.remove_color if self._alt else cfg.light_color),1)
                blf.position(0,self._cursor_xy.x+13*scale,self._cursor_xy.y-8*scale,0)
                blf.draw(0,'\u2212' if self._alt else '+')
            # Keep the hint inside the unobscured viewport, above its bottom edge.
            left=12*scale;right=self._region.width-12*scale;bottom=18*scale
            for region in self._area.regions:
                if region.width<=2 or region.height<=2:continue
                if region.type=='UI':right=min(right,region.x-self._region.x-12*scale)
                elif region.type=='TOOLS':left=max(left,region.x+region.width-self._region.x+12*scale)
                elif region.type=='HEADER' and region.y<=self._region.y+2:
                    bottom=max(bottom,region.height+12*scale)
            cfg=shortcuts.settings()
            remove_hint=cfg.remove_modifier+' + drag to remove'
            confirm_hint=shortcuts.key_label(cfg.confirm_key).upper()+' to confirm'
            hint=('click + DRAG to remove' if self._alt else 'click + DRAG to add')+'  |  '+remove_hint+'  |  '+confirm_hint
            blf.size(0,round(13*scale))
            available=max(80*scale,right-left)
            lines=[hint] if blf.dimensions(0,hint)[0]<=available else [hint.split('  |  ')[0]+'  |  '+remove_hint,confirm_hint]
            for i,line in enumerate(reversed(lines)):
                width=blf.dimensions(0,line)[0];x=left+max(0,(available-width)*.5);y=bottom+i*18*scale
                blf.color(0,.05,.03,.04,.95);blf.position(0,x+scale,y-scale,0);blf.draw(0,line)
                blf.color(0,*cfg.light_color,1);blf.position(0,x,y,0);blf.draw(0,line)
        finally:
            gpu.state.blend_set(old_blend);gpu.state.depth_test_set(old_depth);gpu.state.depth_mask_set(old_mask)

    def finish(self):
        if getattr(self,'_done',False):return
        self._done=True
        if bpy.app.timers.is_registered(feedback_tick):bpy.app.timers.unregister(feedback_tick)
        self._feedback.clear()
        self._comets.clear();self._comet_paths.clear()
        if self._handler:
            bpy.types.SpaceView3D.draw_handler_remove(self._handler,'WINDOW');self._handler=None
        if getattr(self,'_cursor_handler',None):
            bpy.types.SpaceView3D.draw_handler_remove(self._cursor_handler,'WINDOW');self._cursor_handler=None
        if bpy.app.driver_namespace.get(_STATE_KEY)==self:bpy.app.driver_namespace.pop(_STATE_KEY,None)
        if cancel_running in bpy.app.handlers.load_pre:bpy.app.handlers.load_pre.remove(cancel_running)
        try:self._window.cursor_modal_restore();self._workspace.status_text_set(None);self._area.tag_redraw()
        except ReferenceError:pass

    def cancel(self,context):self.finish()


_MODE_ITEMS=[('ADD','Add','Add regions to the preview'),
             ('REMOVE','Remove','Remove regions from the preview; keep wire guides')]


class VIEW3D_OT_harhtools_shape_mode(bpy.types.Operator):
    bl_idname='view3d.harhtools_shape_mode'
    bl_label='Shape Builder Mode'
    bl_description='Choose how clicking or dragging changes the Shape Builder preview'
    mode: EnumProperty(items=_MODE_ITEMS,default='ADD')

    def execute(self,context):
        context.window_manager.arch_shape_builder_mode=self.mode
        state=bpy.app.driver_namespace.get(_STATE_KEY)
        if state:state.set_mode(self.mode)
        if context.area:context.area.tag_redraw()
        return {'FINISHED'}


def register_modes():
    previous=getattr(bpy.types,VIEW3D_OT_harhtools_shape_mode.__name__,None)
    if previous:bpy.utils.unregister_class(previous)
    bpy.utils.register_class(VIEW3D_OT_harhtools_shape_mode)
    if not hasattr(bpy.types.WindowManager,'arch_shape_builder_mode'):
        bpy.types.WindowManager.arch_shape_builder_mode=EnumProperty(
            name='Shape Builder Mode',items=_MODE_ITEMS,default='ADD',options={'SKIP_SAVE'})


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
    register_modes()
    if not hasattr(bpy.types.WindowManager,'arch_shape_builder_output_type'):
        bpy.types.WindowManager.arch_shape_builder_output_type=EnumProperty(
            name='Output',items=[('CURVE','Editable Curve','Keep original Bezier handles and exact subcurves'),
                                 ('MESH','Planar Mesh','Create the sampled planar mesh')],default='CURVE')
    if not hasattr(bpy.types.WindowManager,'arch_shape_builder_edit_mode'):
        bpy.types.WindowManager.arch_shape_builder_edit_mode=EnumProperty(
            name='Edit',items=[('REGIONS','Regions','Merge or remove enclosed regions'),
                               ('EDGES','Edge Trim','Alt-click or drag to erase individual fragments; click to restore')],default='REGIONS')
    if not hasattr(bpy.types.WindowManager,'arch_shape_builder_gap_snap'):
        bpy.types.WindowManager.arch_shape_builder_gap_snap=FloatProperty(
            name='Gap Snap',subtype='PERCENTAGE',default=0,min=0,max=2,soft_max=.5,precision=3,
            description='Close tiny gaps in the preview/new shape; 0 uses exact wires. Guides stay unchanged')
    if not hasattr(bpy.types.WindowManager,'arch_shape_builder_cut_guides'):
        bpy.types.WindowManager.arch_shape_builder_cut_guides=BoolProperty(
            name='Cut Selected Guides',default=False,
            description='Mesh input only: on confirmation cut intersections into the selected mesh guides. Curve guides stay unchanged')
    keyconfig=bpy.context.window_manager.keyconfigs.addon
    if keyconfig:
        for name in ('Object Mode','Mesh','Curve'):
            keymap=keyconfig.keymaps.new(name=name,space_type='EMPTY')
            cfg=shortcuts.settings()
            keymap.keymap_items.new('view3d.arch_shape_builder',cfg.toggle_key,'PRESS',
                                   shift=cfg.toggle_shift,ctrl=cfg.toggle_ctrl,alt=cfg.toggle_alt,oskey=cfg.toggle_oskey)


def unregister():
    cancel_running()
    _remove_shortcuts()
    previous=getattr(bpy.types,VIEW3D_OT_arch_shape_builder.__name__,None)
    if previous:bpy.utils.unregister_class(previous)
    previous=getattr(bpy.types,VIEW3D_OT_harhtools_shape_mode.__name__,None)
    if previous:bpy.utils.unregister_class(previous)
    if hasattr(bpy.types.WindowManager,'arch_shape_builder_mode'):
        del bpy.types.WindowManager.arch_shape_builder_mode
    if hasattr(bpy.types.WindowManager,'arch_shape_builder_gap_snap'):
        del bpy.types.WindowManager.arch_shape_builder_gap_snap
    if hasattr(bpy.types.WindowManager,'arch_shape_builder_cut_guides'):
        del bpy.types.WindowManager.arch_shape_builder_cut_guides
    for name in ('arch_shape_builder_output_type','arch_shape_builder_edit_mode'):
        if hasattr(bpy.types.WindowManager,name):delattr(bpy.types.WindowManager,name)
