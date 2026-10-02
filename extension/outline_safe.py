"""Resolve offset collisions as changes to the remaining planar area.

Every solve starts from the immutable source boundary. Collapsed limbs/holes
therefore return when the width is reduced; no source vertices are welded.
"""
import math
from collections import defaultdict
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt
from . import outline_geometry as g


def arrangement(loops,epsilon):
    original=[];edges=[]
    for loop in loops:
        base=len(original);original.extend(loop)
        edges.extend((base+i,base+(i+1)%len(loop)) for i in range(len(loop)))
    center=tuple(math.fsum(p[i] for p in original)/len(original) for i in range(2))
    scale=max(math.dist(p,center) for p in original)
    points=[Vector(((p[0]-center[0])/scale,(p[1]-center[1])/scale)) for p in original]
    coords,all_edges,faces,original_vertices,original_edges,_=delaunay_2d_cdt(points,edges,[],0,epsilon/scale,True)
    xy=[tuple(original[ids[0]]) if ids else (center[0]+p.x*scale,center[1]+p.y*scale)
        for p,ids in zip(coords,original_vertices)]
    triangles=[tuple(tri) if g._area([xy[i] for i in tri])>0 else tuple(reversed(tri)) for tri in faces
               if len(tri)==3 and abs(g._area([xy[i] for i in tri]))>max(epsilon*epsilon,scale*scale*1e-14)]
    constraints={tuple(sorted(edge)) for edge,ids in zip(all_edges,original_edges) if ids}
    edge_faces=defaultdict(list)
    for index,tri in enumerate(triangles):
        for a,b in zip(tri,tri[1:]+tri[:1]):edge_faces[tuple(sorted((a,b)))].append(index)
    parents=list(range(len(triangles)))
    def root(i):
        while i!=parents[i]:parents[i]=parents[parents[i]];i=parents[i]
        return i
    for edge,adjacent in edge_faces.items():
        if len(adjacent)==2 and edge not in constraints:
            a,b=map(root,adjacent);parents[a]=b
    groups=defaultdict(list)
    for i in range(len(triangles)):groups[root(i)].append(i)
    return xy,triangles,groups.values()


def boundaries(xy,triangles,chosen,epsilon):
    edges=set()
    for index in chosen:
        tri=triangles[index]
        for a,b in zip(tri,tri[1:]+tri[:1]):
            if (b,a) in edges:edges.remove((b,a))
            else:edges.add((a,b))
    following=defaultdict(list);incoming=defaultdict(list)
    for a,b in edges:following[a].append(b);incoming[b].append(a)
    # An exact collapse event has a point contact. Retry at a sub-tolerance
    # width shift instead of creating a non-manifold pinched mesh vertex.
    if any(len(v)!=1 for v in list(following.values())+list(incoming.values())):
        raise ValueError('Safe Inset reached an exact point contact.')
    loops=[]
    while edges:
        start=min(edges)[0];current=start;indices=[]
        while True:
            indices.append(current);nxt=following[current][0]
            edges.remove((current,nxt));current=nxt
            if current==start:break
        loop=[xy[i] for i in indices]
        if abs(g._area(loop))>epsilon*epsilon:loops.append(g._clean(loop,epsilon))
    return loops


def solve(prepared,width,direction,join_style):
    source=prepared['loops'];epsilon=prepared['epsilon'];tolerance=prepared['tolerance']
    distance=width if direction=='INWARD' else -width
    raw=[]
    for loop in source:
        try:raw.append(g._offset_loop(loop,distance,tolerance,epsilon,join_style))
        except ValueError as exc:
            if 'collapsed or zero-area' not in str(exc):raise
            # A boundary contracted to zero area. Keep the source, drop only
            # its remaining offset contour.
    xy,triangles,groups=arrangement(source+raw,epsilon)
    index=prepared.get('_segment_index')
    if index is None:index=prepared['_segment_index']=g._SegmentIndex(source)
    chosen=set()
    for group in groups:
        seed=max(group,key=lambda i:abs(g._area([xy[j] for j in triangles[i]])))
        point=tuple(math.fsum(xy[j][axis] for j in triangles[seed])/3 for axis in range(2))
        inside=g._inside(point,source)
        winding=sum(g._winding(point,loop) for loop in raw)
        near=index.within(point,point,max(0,width-tolerance))
        keep=(inside and winding>0 and not near) if direction=='INWARD' else (inside or winding>0 or near)
        if keep:chosen.update(group)
    offsets=boundaries(xy,triangles,chosen,epsilon)
    g._validate_simple(offsets,epsilon,'Safe Inset could not separate a point contact.')
    clearance=max(0,width-4*tolerance)
    for loop in offsets:
        if g._inside(loop[0],source)!=(direction=='INWARD'):
            raise ValueError('Safe Inset could not resolve the offset side.')
        for a,b in zip(loop,loop[1:]+loop[:1]):
            if index.within(a,b,clearance):raise ValueError('Safe Inset could not resolve a corner collision.')
    source_area=math.fsum(g._area(loop) for loop in source)
    offset_area=math.fsum(g._area(loop) for loop in offsets)
    if direction=='INWARD':
        if offset_area < -epsilon*epsilon or offset_area>=source_area:raise ValueError('Safe Inset could not resolve the remaining interior.')
    elif not offsets or offset_area<=source_area:raise ValueError('Safe Inset could not resolve the outside boundary.')
    return offsets


def build(prepared,thickness,direction,join_style):
    tolerance=prepared['tolerance'];epsilon=prepared['epsilon'];originals=prepared['loops']
    # Resolving the exact event to its thicker side changes width by less than
    # the sampling tolerance and gives a manifold result at the transition.
    error=None
    for shift in (0.,max(epsilon*16,tolerance*.25)):
        try:offsets=solve(prepared,thickness+shift,direction,join_style);break
        except ValueError as exc:error=exc
    else:raise error
    if sum(map(len,offsets))>g.MAX_POINTS:raise ValueError('Safe Inset exceeds the sampling budget.')
    border=([list(loop) for loop in originals]+[list(reversed(loop)) for loop in offsets]
            if direction=='INWARD' else [list(loop) for loop in offsets]+[list(reversed(loop)) for loop in originals])
    g._validate_simple(border,epsilon,'Safe Inset could not separate the border boundaries.')
    return {'border_loops':border,'offset_loops':offsets,'source_loops':originals,
            'matrix_world':prepared['matrix_world'].copy(),'thickness':thickness,'direction':direction,'join_style':join_style,
            'safe_inset':True,'adaptive_topology':True,'offset_correspondence':[],
            'diagnostics':{'source_chord_error_bound':tolerance,'round_join_chord_error_bound':tolerance if join_style=='ROUND' else 0.,
                'join_style':join_style,'minimum_validated_clearance':max(0,thickness-4*tolerance),
                'source_loop_count':len(originals),'offset_loop_count':len(offsets),'poly_points':sum(map(len,border)),
                'trimmed_offset_intersections':0,'topology_preserved':False,'editable_type':'POLY',
                'safe_inset':True,'collapsed_interior':not offsets,'collision_resolved':True}}
