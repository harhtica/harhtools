"""Connected planar border meshes from validated Make Outline boundaries.

Unchanged miter offsets retain source-to-offset quad strips. Junctions that
changed correspondence use constrained triangles, merged into convex quads
where possible. Original boundary coordinates are never fitted or moved.
Safe Inset collisions use continuous quad collars and all-quad junctions.
The collars provide uninterrupted loop cuts even where a feature collapses.
"""
import math
from collections import defaultdict

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree
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
    return _triangulate_boundaries([source,offset],epsilon,[(i,len(source)+j) for i,j in seams],len(source))


def _triangulate_boundaries(loops,epsilon,seams=(),split=None,interior=()):
    original=[];edges=[]
    for loop in loops:
        base=len(original);original.extend(loop)
        edges.extend((base+i,base+(i+1)%len(loop)) for i in range(len(loop)))
    boundary_count=len(original)
    original.extend(interior)
    if split is None:split=len(loops[0])
    center=tuple(math.fsum(p[i] for p in original)/len(original) for i in range(2))
    scale=max(math.dist(p,center) for p in original)
    boundary_edges=list(edges)
    edges.extend(seams)
    normalized=[Vector(((p[0]-center[0])/scale,(p[1]-center[1])/scale)) for p in original]
    coords,cdt_edges,triangles,orig_vertices,orig_edges,_=delaunay_2d_cdt(normalized,edges,[],0,epsilon/scale,True)
    vertices=[];old_to_new={};boundary_side={}
    for index,(co,ids) in enumerate(zip(coords,orig_vertices)):
        if len(ids)>1:
            raise ValueError('Outline boundary points are too close to mesh reliably. Increase sampling tolerance.')
        if ids:
            old=ids[0];vertices.append(original[old]);old_to_new[old]=index
            if old<boundary_count:boundary_side[index]=0 if old<split else 1
        else:vertices.append((center[0]+co[0]*scale,center[1]+co[1]*scale))
    if len(old_to_new)!=len(original):
        raise ValueError('The mesh triangulator could not preserve every outline boundary point.')
    membership=[_membership_index(loop) for loop in loops]
    faces=[]
    for triangle in triangles:
        triangle=list(triangle)
        # Restoring exact boundary coordinates can turn CDT's float32 slivers
        # along collinear outer edges back into zero-area triangles.
        if abs(_signed_area(vertices,triangle))<=max(epsilon*epsilon,scale*scale*1e-14):continue
        center=tuple(math.fsum(vertices[v][axis] for v in triangle)/len(triangle) for axis in range(2))
        if sum(inside(center) for inside in membership)%2:faces.append(_ccw(vertices,triangle))
    # Collision rails can meet/cross at a junction. Keep every CDT subdivision
    # of the constraint, rather than expecting one unsplit start-to-end edge.
    protected={tuple(sorted(edge)) for edge,ids in zip(cdt_edges,orig_edges)
               if any(i>=len(boundary_edges) for i in ids)}
    faces=_merge_triangles(vertices,faces,epsilon,boundary_side,protected)
    if not protected <= set(_edge_faces(faces)):
        raise ValueError('The outline mesh could not preserve a miter corner seam.')
    boundary={tuple(sorted((old_to_new[a],old_to_new[b]))) for a,b in boundary_edges}
    return vertices,faces,boundary


def _first_contact(point,velocity,width,segments,epsilon):
    """First time a competing finite edge comes closer than the moving inset.

    A miter ray is p(t)=point+t*velocity. Solve distance(p(t), edge)^2=t^2
    on the segment interior and its two endpoint regions. The earliest entering
    root terminates the rail on the local collision ridge, not a distant corner.
    """
    stop=width
    speed2=geometry._dot(velocity,velocity)
    for a,b in segments:
        if point==a or point==b:continue
        edge=geometry._sub(b,a);length=math.hypot(*edge)
        if length<=epsilon:continue
        delta=geometry._sub(point,a)
        cross0=geometry._cross(edge,delta)/length
        crossv=geometry._cross(edge,velocity)/length
        candidates=[]
        for sign in (-1,1):
            denominator=sign-crossv
            if abs(denominator)>1e-14:
                t=cross0/denominator
                if epsilon<t<stop:
                    hit=geometry._add(point,geometry._mul(velocity,t))
                    u=geometry._dot(geometry._sub(hit,a),edge)/(length*length)
                    if 0<=u<=1 and 2*(cross0+crossv*t)*crossv-2*t < -epsilon:candidates.append(t)
        for endpoint,is_end in ((a,False),(b,True)):
            delta=geometry._sub(point,endpoint)
            aa=speed2-1;bb=2*geometry._dot(delta,velocity);cc=geometry._dot(delta,delta)
            if abs(aa)<1e-12:
                roots=[-cc/bb] if abs(bb)>1e-14 else []
            else:
                discriminant=bb*bb-4*aa*cc
                if discriminant<0:roots=[]
                else:
                    q=-.5*(bb+math.copysign(math.sqrt(discriminant),bb))
                    roots=[q/aa,cc/q] if q else []
            for t in roots:
                if not epsilon<t<stop or 2*aa*t+bb>=-epsilon:continue
                hit=geometry._add(point,geometry._mul(velocity,t))
                u=geometry._dot(geometry._sub(hit,a),edge)/(length*length)
                if (is_end and u>=1) or (not is_end and u<=0):candidates.append(t)
        if candidates:stop=min(candidates)
    return stop


def _collision_rails(result,epsilon):
    """Retain local normal connections through collapsed / trimmed sections."""
    sources=result['source_loops'];offsets=result['offset_loops'];loops=sources+offsets
    points=[tuple(p) for loop in loops for p in loop];boundary_count=len(points)
    edge_tree=geometry._SegmentIndex(sources)
    def competitors(a,b,width):
        query=(min(a[0],b[0]),max(a[0],b[0]),min(a[1],b[1]),max(a[1],b[1]))
        def nearby(bounds):
            dx=max(0,bounds[0]-query[1],query[0]-bounds[1]);dy=max(0,bounds[2]-query[3],query[2]-bounds[3])
            return dx*dx+dy*dy<=width*width
        stack=[edge_tree.root]
        while stack:
            bounds,rows,left,right=stack.pop()
            if not nearby(bounds):continue
            if rows is None:stack.extend((left,right))
            else:
                for row in rows:
                    if nearby(row) and geometry._segment_distance_sq(a,b,row[7],row[8])<=width*width:yield row[7],row[8]
    width=result['thickness'];sign=1 if result['direction']=='INWARD' else -1
    tolerance=max(epsilon*64,result['diagnostics']['source_chord_error_bound']*.01)
    cells=defaultdict(list)
    def cell(p):return tuple(math.floor(v/tolerance) for v in p)
    for i,p in enumerate(points):cells[cell(p)].append(i)
    def index(p):
        x,y=cell(p)
        nearby=[i for dx in (-1,0,1) for dy in (-1,0,1) for i in cells[x+dx,y+dy] if math.dist(p,points[i])<=tolerance]
        if nearby:return min(nearby,key=lambda i:math.dist(p,points[i]))
        i=len(points);points.append(p);cells[x,y].append(i);return i
    seams=[];base=0
    membership=[_membership_index(loop) for loop in loops]
    for source in sources:
        for i,p in enumerate(source):
            incoming=geometry._sub(p,source[i-1]);outgoing=geometry._sub(source[(i+1)%len(source)],p)
            incoming=geometry._mul(incoming,1/math.hypot(*incoming));outgoing=geometry._mul(outgoing,1/math.hypot(*outgoing))
            den=1+geometry._dot(incoming,outgoing)
            if den<=1e-10:continue
            velocity=geometry._mul((-incoming[1]-outgoing[1],incoming[0]+outgoing[0]),sign/den)
            end=geometry._add(p,geometry._mul(velocity,width))
            # A spatial distance gate avoids solving every remote edge.
            stop=_first_contact(p,velocity,width,competitors(p,end,width),epsilon)
            end=geometry._add(p,geometry._mul(velocity,stop))
            if math.dist(p,end)<=tolerance:continue
            if any(sum(inside(geometry._add(p,geometry._mul(geometry._sub(end,p),t))) for inside in membership)%2==0 for t in (.1,.5,.9)):continue
            j=index(end)
            if j!=base+i:seams.append((base+i,j))
        base+=len(source)
    # Several rays may reach the same ridge at different positions. Explicitly
    # split a longer rail at those existing points before float32 CDT; otherwise
    # a nearly collinear junction becomes a paper-thin triangle / T-junction.
    split=set()
    point_tree=KDTree(len(points))
    for i,p in enumerate(points):point_tree.insert((*p,0),i)
    point_tree.balance()
    for a,b in seams:
        delta=geometry._sub(points[b],points[a]);length2=geometry._dot(delta,delta)
        stops=[(0.,a),(1.,b)]
        middle=geometry._mul(geometry._add(points[a],points[b]),.5)
        for _,i,_ in point_tree.find_range((*middle,0),math.sqrt(length2)*.5+tolerance*2):
            p=points[i]
            if i in (a,b):continue
            t=geometry._dot(geometry._sub(p,points[a]),delta)/length2
            if 0<t<1 and geometry._point_segment_sq(p,points[a],points[b])<=tolerance*tolerance:stops.append((t,i))
        stops.sort()
        split.update(tuple(sorted((a[1],b[1]))) for a,b in zip(stops,stops[1:]) if a[1]!=b[1])
    return sorted(split),points[boundary_count:]


def _validate(vertices,faces,boundary,expected_area,epsilon,euler_characteristic=0):
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
    if len(vertices)-len(edges)+len(faces)!=euler_characteristic:
        raise ValueError('The outline mesh would change the resolved border topology.')


def _quad_loop_layout(vertices,faces,width,epsilon):
    """Add a continuous quad row at every boundary; quadrangulate the core.

    Subdividing triangles alone creates three-valence poles that stop a loop
    cut. An explicit collar keeps an opposite-edge route around each boundary
    outside those junctions. Original coordinates and sharp tips stay fixed;
    extra boundary points are exact edge midpoints, never fitted samples.
    """
    edges=_edge_faces(faces)
    boundary={edge for edge,ids in edges.items() if len(ids)==1}
    next_vertex={};previous={};incident=defaultdict(list)
    for fi,face in enumerate(faces):
        for a,b in zip(face,face[1:]+face[:1]):
            incident[a].append(fi)
            if tuple(sorted((a,b))) in boundary:next_vertex[a]=b;previous[b]=a
    if set(next_vertex)!=set(previous):
        raise ValueError('The outline boundary cannot form a continuous quad row.')
    movement={}
    for i in next_vertex:
        p=vertices[i];a=geometry._sub(p,vertices[previous[i]]);b=geometry._sub(vertices[next_vertex[i]],p)
        a=geometry._mul(a,1/math.hypot(*a));b=geometry._mul(b,1/math.hypot(*b))
        denominator=max(1e-12,1+geometry._dot(a,b))
        velocity=geometry._mul((-a[1]-b[1],a[0]+b[0]),1/denominator)
        limit=width*.35
        # Limit each move by the incident faces' halfplanes, not a global
        # smallest width: a tiny cusp must not shrink every other quad row.
        for fi in incident[i]:
            face=faces[fi]
            for j in range(len(face)):
                ids=[face[j],face[(j+1)%len(face)],face[(j+2)%len(face)]]
                if i not in ids:continue
                p0,p1,p2=(vertices[k] for k in ids)
                area=geometry._cross(geometry._sub(p1,p0),geometry._sub(p2,p1))
                moved=[geometry._add(vertices[k],velocity) if k==i else vertices[k] for k in ids]
                rate=geometry._cross(geometry._sub(moved[1],moved[0]),geometry._sub(moved[2],moved[1]))-area
                # A boundary point on a straight quad side becomes a reflex
                # corner when moved in. Split that core quad instead of
                # forcing the entire collar down to a zero-width sliver.
                if rate<0 and area>epsilon*epsilon*100:limit=min(limit,area/-rate*.22)
        movement[i]=geometry._mul(velocity,limit)
    core=list(vertices)
    def core_patch(face):
        if _convex(core,face,epsilon):return [face]
        if len(face)==4:
            a,b,c,d=face
            for triangles in (([a,b,c],[a,c,d]),([a,b,d],[b,c,d])):
                if all(_signed_area(core,t)>epsilon*epsilon for t in triangles):return list(triangles)
        return None
    # Simultaneous corner moves can constrain one another. Relax only the
    # affected neighborhood, retaining generous rows on the regular arcs.
    for _ in range(64):
        for i,delta in movement.items():core[i]=geometry._add(vertices[i],delta)
        bad=set()
        for face in faces:
            if core_patch(face) is None:bad.update(i for i in face if i in movement)
        for a,b in next_vertex.items():
            collar=[vertices[a],vertices[b],core[b],core[a]]
            # At an inner corner the opposite endpoint's displacement sets
            # the sign. Halving both endpoints preserves a bad width ratio.
            if geometry._cross(geometry._sub(core[a],core[b]),geometry._sub(vertices[a],core[a]))<=epsilon*epsilon:bad.add(b)
            if geometry._cross(geometry._sub(core[b],vertices[b]),geometry._sub(core[a],core[b]))<=epsilon*epsilon:bad.add(a)
        if not bad:break
        for i in bad:movement[i]=geometry._mul(movement[i],.5)
    else:raise ValueError('The outline is too narrow to create a reliable quad row.')
    faces=[patch for face in faces for patch in core_patch(face)]
    edges=_edge_faces(faces)
    output=list(vertices);core_ids={i:i for i in range(len(vertices))}
    for i in next_vertex:core_ids[i]=len(output);output.append(core[i])
    # Split triangle edges and carry a split through opposite quad edges.
    # Regular arc quads need at most two faces, rather than blanket subdivision
    # adding a face center and four faces to every otherwise clean quad.
    marked={tuple(sorted((a,b))) for face in faces if len(face)==3 for a,b in zip(face,face[1:]+face[:1])}
    pending=[fi for fi,face in enumerate(faces) if len(face)==4]
    while pending:
        fi=pending.pop();face=faces[fi]
        fedges=[tuple(sorted((a,b))) for a,b in zip(face,face[1:]+face[:1])]
        found=[j for j,edge in enumerate(fedges) if edge in marked]
        added=[]
        if len(found)==1:added=[fedges[(found[0]+2)%4]]
        elif len(found)==3 or (len(found)==2 and (found[1]-found[0])%2):added=[e for e in fedges if e not in marked]
        for edge in added:
            marked.add(edge)
            pending.extend(i for i in edges[edge] if i!=fi and len(faces[i])==4)
    edge_ids={}
    for a,b in sorted(marked):
        edge_ids[a,b]=len(output);output.append(geometry._mul(geometry._add(core[a],core[b]),.5))
    quads=[]
    for face in faces:
        fedges=[tuple(sorted((a,b))) for a,b in zip(face,face[1:]+face[:1])]
        found=[j for j,edge in enumerate(fedges) if edge in marked]
        if not found:
            quads.append([core_ids[i] for i in face]);continue
        if len(face)==4 and len(found)==2:
            j=found[0];a,b,c,d=face[j:]+face[:j]
            mid_a=edge_ids[tuple(sorted((a,b)))];mid_b=edge_ids[tuple(sorted((c,d)))]
            quads.extend(([mid_a,core_ids[b],core_ids[c],mid_b],[mid_b,core_ids[d],core_ids[a],mid_a]));continue
        center=len(output);output.append(tuple(math.fsum(core[i][axis] for i in face)/len(face) for axis in range(2)))
        for j,i in enumerate(face):
            quads.append([core_ids[i],edge_ids[tuple(sorted((i,face[(j+1)%len(face)])))],center,
                          edge_ids[tuple(sorted((face[j-1],i)))]] )
    new_boundary=set();collar_faces=[]
    for a,b in next_vertex.items():
        edge=tuple(sorted((a,b)))
        if edge not in marked:
            collar_faces.append(len(quads));quads.append([a,b,core_ids[b],core_ids[a]])
            new_boundary.add(edge);continue
        middle=len(output);output.append(geometry._mul(geometry._add(vertices[a],vertices[b]),.5))
        inner=edge_ids[edge]
        collar_faces.extend((len(quads),len(quads)+1))
        quads.extend(([a,middle,inner,core_ids[a]],[middle,b,core_ids[b],inner]))
        new_boundary.update((tuple(sorted((a,middle))),tuple(sorted((middle,b)))))
    # Verify the route Blender follows, rather than equating 'all quads' with
    # loop-cut support. Opposite edges in the collar must make closed rings.
    adjacency=_edge_faces(quads);unvisited=set(collar_faces);rings=0
    while unvisited:
        first=min(unvisited);face=quads[first];edge=tuple(sorted((face[0],face[3])))
        current=first;visited=set()
        while current not in visited:
            if current not in unvisited:raise ValueError('The outline quad row branches unexpectedly.')
            visited.add(current);f=quads[current]
            j=next(j for j in range(4) if tuple(sorted((f[j],f[(j+1)%4])))==edge)
            edge=tuple(sorted((f[(j+2)%4],f[(j+3)%4])))
            neighbors=adjacency[edge]
            if len(neighbors)!=2:raise ValueError('The outline loop cut would stop at a junction.')
            current=neighbors[0] if neighbors[1]==current else neighbors[1]
        if current!=first:raise ValueError('The outline quad row did not close.')
        unvisited.difference_update(visited);rings+=1
    return output,quads,new_boundary,{'loop_cut_rings':rings,'loop_cut_faces':len(collar_faces)}


def _adaptive_mesh(result):
    sources=result['source_loops'];offsets=result['offset_loops'];loops=sources+offsets
    original=[tuple(p) for loop in loops for p in loop]
    extent=max(max(p[axis] for p in original)-min(p[axis] for p in original) for axis in range(2))
    epsilon=max(extent*1e-9,1e-11);seams=[]
    interior=[]
    if result.get('join_style')=='MITER':
        seams,interior=_collision_rails(result,epsilon)
    vertices,faces,boundary=_triangulate_boundaries(loops,epsilon,seams,sum(map(len,sources)),interior)
    expected_area=math.fsum(geometry._area(loop) for loop in result['border_loops'])
    euler=sum(1 if geometry._area(loop)>0 else -1 for loop in result['border_loops'])
    _validate(vertices,faces,boundary,expected_area,epsilon,euler)
    vertices,faces,boundary,loop_diagnostics=_quad_loop_layout(vertices,faces,result['thickness'],epsilon)
    _validate(vertices,faces,boundary,expected_area,epsilon,euler)
    return {'vertices':[(x,y,0.) for x,y in vertices],'faces':faces,'diagnostics':{
        'quad_faces':sum(len(face)==4 for face in faces),'triangle_faces':sum(len(face)==3 for face in faces),
        'direct_quad_rings':0,'triangulated_rings':len(loops),'boundary_rings':len(loops),
        'loose_vertices':0,'protected_miter_seams':len(seams),'collision_rails':len(seams),'adaptive_topology':True,
        **loop_diagnostics}}


def build_mesh(result):
    """Return validated local-XY vertices/faces; no Blender data is changed."""
    if result.get('adaptive_topology') or (result.get('safe_inset') and result.get('join_style')=='MITER' and any(result.get('offset_trimmed',()))):
        return _adaptive_mesh(result)
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
