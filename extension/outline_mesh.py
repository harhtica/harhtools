"""Connected planar border meshes from validated Make Outline boundaries.

Unchanged miter offsets retain source-to-offset quad strips. Junctions that
changed correspondence use constrained triangles, merged into convex quads
where possible. Original boundary coordinates are never fitted or moved.
"""
import math
from collections import defaultdict

import bpy
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt

from . import outline_geometry as geometry


def _signed_area(vertices, face):
    return math.fsum(vertices[a][0]*vertices[b][1] - vertices[b][0]*vertices[a][1]
                     for a,b in zip(face, face[1:]+face[:1]))*.5


def _ccw(vertices, face):
    return list(face) if _signed_area(vertices, face) > 0 else list(reversed(face))


def _convex(vertices, face, epsilon):
    return all(geometry._cross(geometry._sub(vertices[b], vertices[a]),
                               geometry._sub(vertices[c], vertices[b])) > epsilon*epsilon
               for a,b,c in zip(face, face[1:]+face[:1], face[2:]+face[:2]))


def _edge_faces(faces):
    edges = defaultdict(list)
    for index, face in enumerate(faces):
        for a,b in zip(face, face[1:]+face[:1]):
            edges[tuple(sorted((a,b)))].append(index)
    return edges


def _crossing_edges(vertices, faces, epsilon):
    rows=[]
    for index,(a,b) in enumerate(_edge_faces(faces)):
        p,q=vertices[a],vertices[b]
        rows.append((min(p[0],q[0]),max(p[0],q[0]),min(p[1],q[1]),max(p[1],q[1]),a,b,p,q,index))
    for a,b in geometry._candidates(rows, epsilon):
        if set(a[4:6]) & set(b[4:6]):
            continue
        if geometry._segment_distance_sq(a[6],a[7],b[6],b[7]) <= epsilon*epsilon:
            return True
    return False


def _membership_index(loop):
    low=min(p[1] for p in loop);high=max(p[1] for p in loop)
    count=min(128,max(8,math.ceil(math.sqrt(len(loop)))))
    step=max((high-low)/count,1e-30);buckets=[[] for _ in range(count)]
    for a,b in zip(loop,loop[1:]+loop[:1]):
        if a[1]==b[1]:continue
        first=max(0,min(count-1,int((min(a[1],b[1])-low)/step)))
        last=max(0,min(count-1,int((max(a[1],b[1])-low)/step)))
        for i in range(first,last+1):buckets[i].append((a,b))
    def contains(point):
        x,y=point
        if y<low or y>high:return False
        inside=False
        for a,b in buckets[max(0,min(count-1,int((y-low)/step)))]:
            if (a[1]>y)!=(b[1]>y) and a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])>x:
                inside=not inside
        return inside
    return contains


def _merge_triangles(vertices, faces, epsilon, boundary_side, protected=()):
    candidates=[]
    for edge,neighbors in _edge_faces(faces).items():
        if len(neighbors)!=2 or edge in protected:continue
        a,b=neighbors
        boundary={}
        for face in (faces[a],faces[b]):
            for p,q in zip(face,face[1:]+face[:1]):
                if tuple(sorted((p,q)))!=edge:boundary[p]=q
        if len(boundary)!=4:continue
        start=min(boundary);quad=[start]
        for _ in range(3):quad.append(boundary.get(quad[-1],start))
        if len(set(quad))!=4 or boundary.get(quad[-1])!=start or not _convex(vertices,quad,epsilon):continue
        sides=[boundary_side.get(i) for i in quad]
        paired=sides.count(0)==2 and sides.count(1)==2
        lengths=[math.dist(vertices[p],vertices[q]) for p,q in zip(quad,quad[1:]+quad[:1])]
        quality=min(lengths)/max(lengths)
        candidates.append((paired,quality,a,b,quad))
    used=set();result=[]
    for _,_,a,b,quad in sorted(candidates,reverse=True):
        if a in used or b in used:continue
        used.update((a,b));result.append(quad)
    result.extend(face for i,face in enumerate(faces) if i not in used)
    return result


def _corner_turns(loop):
    return [math.atan2(geometry._cross(geometry._sub(p,loop[i-1]),geometry._sub(loop[(i+1)%len(loop)],p)),
                       geometry._dot(geometry._sub(p,loop[i-1]),geometry._sub(loop[(i+1)%len(loop)],p)))
            for i,p in enumerate(loop)]


def _corners(loop):
    turns=_corner_turns(loop)
    # Retain obvious corners and isolated tangent discontinuities, while a
    # regularly sampled smooth arc need not constrain every cross-strip edge.
    return [(i,turn) for i,turn in enumerate(turns)
            if abs(turn)>max(math.radians(.1),min(math.radians(5),
                4*max(abs(turns[i-1]),abs(turns[(i+1)%len(turns)]))))]


def _miter_seams(source,offset,distance,epsilon):
    """Pair actual corners even when local offset cleanup changed vertex count.

    Pair to a surviving corner on the same side, near its analytic miter. A
    proposed seam must stay entirely in the ring and cross neither a boundary
    nor another seam. No source or offset vertex is moved.
    """
    targets=_corners(offset);chosen=[];used=set();inside_a=_membership_index(source);inside_b=_membership_index(offset)
    boundaries=[(a,b) for loop in (source,offset) for a,b in zip(loop,loop[1:]+loop[:1])]
    for i,turn in sorted(_corners(source),key=lambda row:-abs(row[1])):
        point=source[i];incoming=geometry._sub(point,source[i-1]);outgoing=geometry._sub(source[(i+1)%len(source)],point)
        incoming=geometry._mul(incoming,1/math.hypot(*incoming));outgoing=geometry._mul(outgoing,1/math.hypot(*outgoing))
        denominator=1+geometry._dot(incoming,outgoing)
        if denominator<=1e-12:continue
        expected=geometry._add(point,geometry._mul((-incoming[1]-outgoing[1],incoming[0]+outgoing[0]),distance/denominator))
        candidates=sorted((math.dist(expected,offset[j]),j) for j,t in targets if t*turn>0 and j not in used)
        for error,j in candidates:
            if error>max(abs(distance)*4,epsilon*32):break
            end=offset[j]
            if math.dist(point,end)<=epsilon:continue
            # Other boundary vertices and crossing edges cannot lie on a seam.
            if any(geometry._point_segment_sq(q,point,end)<=epsilon*epsilon
                   for loop in (source,offset) for q in loop if q!=point and q!=end):continue
            if any(geometry._segment_distance_sq(point,end,a,b)<=epsilon*epsilon
                   for a,b in boundaries if point not in (a,b) and end not in (a,b)):continue
            if any(inside_a(geometry._add(point,geometry._mul(geometry._sub(end,point),t)))==
                   inside_b(geometry._add(point,geometry._mul(geometry._sub(end,point),t))) for t in (.1,.5,.9)):continue
            if any(geometry._segment_distance_sq(point,end,source[a],offset[b])<=epsilon*epsilon for a,b in chosen):continue
            chosen.append((i,j));used.add(j);break
    return chosen


def _triangulate_ring(source, offset, epsilon, seams=()):
    original=source+offset;n=len(source)
    center=tuple(math.fsum(p[i] for p in original)/len(original) for i in range(2))
    scale=max(math.dist(p,center) for p in original)
    edges=[(i,(i+1)%n) for i in range(n)]
    edges.extend((n+i,n+(i+1)%len(offset)) for i in range(len(offset)))
    boundary_edges=list(edges)
    edges.extend((i,n+j) for i,j in seams)
    normalized=[Vector(((p[0]-center[0])/scale,(p[1]-center[1])/scale)) for p in original]
    coords,_,triangles,orig_vertices,_,_=delaunay_2d_cdt(normalized,edges,[],0,epsilon/scale,True)
    vertices=[];old_to_new={};boundary_side={}
    for index,(co,ids) in enumerate(zip(coords,orig_vertices)):
        if len(ids)>1:
            raise ValueError('Outline boundary points are too close to mesh reliably. Increase sampling tolerance.')
        if ids:
            old=ids[0];vertices.append(original[old]);old_to_new[old]=index
            boundary_side[index]=0 if old<n else 1
        else:vertices.append((center[0]+co[0]*scale,center[1]+co[1]*scale))
    if len(old_to_new)!=len(original):
        raise ValueError('The mesh triangulator could not preserve every outline boundary point.')
    in_source,in_offset=_membership_index(source),_membership_index(offset)
    faces=[]
    for triangle in triangles:
        triangle=list(triangle)
        center=tuple(math.fsum(vertices[v][axis] for v in triangle)/len(triangle) for axis in range(2))
        if in_source(center)!=in_offset(center):faces.append(_ccw(vertices,triangle))
    protected={tuple(sorted((old_to_new[i],old_to_new[n+j]))) for i,j in seams}
    faces=_merge_triangles(vertices,faces,epsilon,boundary_side,protected)
    if not protected <= set(_edge_faces(faces)):
        raise ValueError('The outline mesh could not preserve a miter corner seam.')
    boundary={tuple(sorted((old_to_new[a],old_to_new[b]))) for a,b in boundary_edges}
    return vertices,faces,boundary


def _validate(vertices,faces,boundary,expected_area,epsilon):
    if not faces or any(len(face) not in (3,4) or len(set(face))!=len(face) for face in faces):
        raise ValueError('The border could not be made into clean mesh faces.')
    used={v for face in faces for v in face}
    edges=_edge_faces(faces)
    if used!=set(range(len(vertices))) or any(len(ids)>2 for ids in edges.values()):
        raise ValueError('The outline mesh would contain loose or non-manifold geometry.')
    if {edge for edge,ids in edges.items() if len(ids)==1}!=boundary:
        raise ValueError('The outline mesh would not preserve its two open boundaries.')
    areas=[_signed_area(vertices,face) for face in faces]
    if min(areas)<=epsilon*epsilon:
        raise ValueError('The outline mesh would contain a collapsed face.')
    if abs(math.fsum(areas)-expected_area)>max(expected_area*2e-6,epsilon*epsilon*len(faces)*4):
        raise ValueError('The outline mesh would overlap or leave gaps in the border.')
    if len(vertices)-len(edges)+len(faces)!=0:
        raise ValueError('The outline mesh would change the hollow border topology.')


def build_mesh(result):
    """Return validated local-XY vertices/faces; no Blender data is changed."""
    sources=result['source_loops'];offsets=result['offset_loops']
    if len(sources)!=len(offsets) or not sources:
        raise ValueError('Each outline source needs its matching offset boundary.')
    correspondence=result.get('offset_correspondence',[None]*len(sources))
    vertices=[];faces=[];direct=0;triangulated=0;seam_count=0
    for index,(source,offset) in enumerate(zip(sources,offsets)):
        source=[tuple(p) for p in source];offset=[tuple(p) for p in offset]
        extent=max(max(p[axis] for p in source+offset)-min(p[axis] for p in source+offset) for axis in range(2))
        epsilon=max(extent*1e-9,1e-11)
        expected_area=abs(abs(geometry._area(source))-abs(geometry._area(offset)))
        local_vertices=source+offset;n=len(source)
        boundary={tuple(sorted((i,(i+1)%n))) for i in range(n)}
        boundary.update(tuple(sorted((n+i,n+(i+1)%len(offset)))) for i in range(len(offset)))
        local_faces=None
        mapping=correspondence[index] if index<len(correspondence) else None
        if len(source)==len(offset) and mapping==list(range(n)):
            candidate=[_ccw(local_vertices,[i,(i+1)%n,n+(i+1)%n,n+i]) for i in range(n)]
            if all(_convex(local_vertices,face,epsilon) for face in candidate) and not _crossing_edges(local_vertices,candidate,epsilon):
                try:_validate(local_vertices,candidate,boundary,expected_area,epsilon)
                except ValueError:pass
                else:local_faces=candidate;direct+=1
        if local_faces is None:
            seams=_miter_seams(source,offset,result['thickness']*(1 if result['direction']=='INWARD' else -1),epsilon) if result.get('join_style')=='MITER' else []
            local_vertices,local_faces,boundary=_triangulate_ring(source,offset,epsilon,seams)
            _validate(local_vertices,local_faces,boundary,expected_area,epsilon)
            triangulated+=1;seam_count+=len(seams)
        base=len(vertices);vertices.extend((x,y,0.0) for x,y in local_vertices)
        faces.extend(tuple(base+i for i in face) for face in local_faces)
    return {'vertices':vertices,'faces':faces,'diagnostics':{
        'quad_faces':sum(len(face)==4 for face in faces),
        'triangle_faces':sum(len(face)==3 for face in faces),
        'direct_quad_rings':direct,'triangulated_rings':triangulated,
        'boundary_rings':len(sources)*2,'loose_vertices':0,'protected_miter_seams':seam_count}}


def make_mesh_data(result,name='Outline'):
    """Create an editable, hollow mesh border only after topology validation."""
    built=build_mesh(result)
    data=bpy.data.meshes.new(name)
    try:
        data.from_pydata(built['vertices'],[],built['faces']);data.update()
        if data.validate(verbose=False,clean_customdata=False):
            raise ValueError('Blender found invalid outline mesh topology.')
        uv=data.uv_layers.new(name='UVMap')
        xmin=min(p[0] for p in built['vertices']);ymin=min(p[1] for p in built['vertices'])
        span=max(max(p[0] for p in built['vertices'])-xmin,max(p[1] for p in built['vertices'])-ymin)
        for loop in data.loops:
            point=built['vertices'][loop.vertex_index]
            uv.data[loop.index].uv=((point[0]-xmin)/span,(point[1]-ymin)/span)
        data['harhtools_outline_thickness']=result['thickness']
        data['harhtools_outline_direction']=result['direction']
        data['harhtools_outline_sampling_error']=result['diagnostics']['source_chord_error_bound']
        data['harhtools_outline_join_style']=result.get('join_style','ROUND')
        data['harhtools_outline_mesh_quads']=built['diagnostics']['quad_faces']
        data['harhtools_outline_mesh_triangles']=built['diagnostics']['triangle_faces']
        return data
    except Exception:
        bpy.data.meshes.remove(data);raise
