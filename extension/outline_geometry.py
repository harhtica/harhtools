"""Non-destructive, world-space planar borders with validated offsets.

Original Bezier boundaries are adaptively sampled with a control-hull chord
error bound. Result curves are explicitly POLY splines, not claimed exact cubic
offsets. Round joins avoid outward miter spikes. Topological collapse, boundary
crossings, and insufficient clearance raise ValueError before any data is made.
"""
import math
from collections import defaultdict
import bpy
from mathutils import Vector,Matrix
from mathutils.geometry import delaunay_2d_cdt
from . import curve_geometry

MAX_POINTS=20000

def _sub(a,b):return (a[0]-b[0],a[1]-b[1])
def _add(a,b):return (a[0]+b[0],a[1]+b[1])
def _mul(a,t):return (a[0]*t,a[1]*t)
def _cross(a,b):return a[0]*b[1]-a[1]*b[0]
def _dot(a,b):return a[0]*b[0]+a[1]*b[1]
def _area(loop):return sum(_cross(a,b) for a,b in zip(loop,loop[1:]+loop[:1]))*.5

def _point_segment_sq(p,a,b):
    d=_sub(b,a);den=_dot(d,d)
    t=max(0.0,min(1.0,_dot(_sub(p,a),d)/den)) if den>0 else 0.0
    q=_sub(p,_add(a,_mul(d,t)))
    return _dot(q,q)

def _segment_distance_sq(a,b,c,d):
    ab,cd=_sub(b,a),_sub(d,c);den=_cross(ab,cd)
    if abs(den)>1e-24:
        t=_cross(_sub(c,a),cd)/den;u=_cross(_sub(c,a),ab)/den
        if 0<=t<=1 and 0<=u<=1:return 0.0
    return min(_point_segment_sq(a,c,d),_point_segment_sq(b,c,d),
               _point_segment_sq(c,a,b),_point_segment_sq(d,a,b))

def _edges(loops,kind=0):
    rows=[]
    for loop_id,loop in enumerate(loops):
        for index,(a,b) in enumerate(zip(loop,loop[1:]+loop[:1])):
            rows.append((min(a[0],b[0]),max(a[0],b[0]),min(a[1],b[1]),max(a[1],b[1]),kind,loop_id,index,a,b,len(loop)))
    return rows

def _candidates(rows,margin=0.0):
    active=[]
    for current in sorted(rows,key=lambda row:row[0]):
        active=[old for old in active if old[1]+margin>=current[0]]
        for old in active:
            if old[3]+margin<current[2] or current[3]+margin<old[2]:continue
            yield old,current
        active.append(current)

def _validate_simple(loops,epsilon,message):
    for a,b in _candidates(_edges(loops),epsilon):
        if a[5]==b[5] and (abs(a[6]-b[6]) in (0,1,a[9]-1)):continue
        if _segment_distance_sq(a[7],a[8],b[7],b[8])<=epsilon*epsilon:
            raise ValueError(message)

def _contains(point,loop):
    inside=False;x,y=point
    for a,b in zip(loop,loop[1:]+loop[:1]):
        if (a[1]>y)!=(b[1]>y):
            crossing=a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if crossing>x:inside=not inside
    return inside

def _inside(point,loops):return sum(_contains(point,loop) for loop in loops)%2==1

def _clean(loop,epsilon):
    result=[]
    for p in loop:
        p=(float(p[0]),float(p[1]))
        if not result or math.dist(p,result[-1])>epsilon:result.append(p)
    if len(result)>1 and math.dist(result[0],result[-1])<=epsilon:result.pop()
    if len(result)<3 or abs(_area(result))<=epsilon*epsilon:
        raise ValueError('The outline contains a collapsed or zero-area loop.')
    return result

def _flatten(cp,tolerance):
    """The Bezier convex hull lies within tolerance of every emitted chord."""
    result=[cp[0]]
    def walk(control,depth):
        error=max(_point_segment_sq(p,control[0],control[3]) for p in control[1:3])
        if error<=tolerance*tolerance:
            result.append(control[3]);return
        if depth>=20 or len(result)>=MAX_POINTS:
            raise ValueError('Curve detail exceeds the outline sampling budget. Increase sampling tolerance.')
        a,b=curve_geometry.split(control,.5)
        walk(a,depth+1);walk(b,depth+1)
    walk(cp,0)
    return result

def _mesh_loops(obj):
    mesh=obj.data;edge_faces=defaultdict(int)
    for polygon in mesh.polygons:
        ids=list(polygon.vertices)
        for a,b in zip(ids,ids[1:]+ids[:1]):edge_faces[tuple(sorted((a,b)))]+=1
    if any(count>2 for count in edge_faces.values()):
        raise ValueError(f'{obj.name}: non-manifold faces have ambiguous boundaries. Use a clean planar surface or closed wire loop.')
    edges=[tuple(e.vertices) for e in mesh.edges if edge_faces[tuple(sorted(e.vertices))]<=1]
    neighbors=defaultdict(list)
    for index,(a,b) in enumerate(edges):neighbors[a].append((index,b));neighbors[b].append((index,a))
    if not edges or any(len(rows)!=2 for rows in neighbors.values()):
        raise ValueError(f'{obj.name}: mesh boundaries must be closed, unbranched loops. Remove open or branching guide edges first.')
    pending=set(range(len(edges)));loops=[]
    while pending:
        first=next(iter(pending));start=edges[first][0];current=start;indices=[]
        while True:
            choices=[row for row in neighbors[current] if row[0] in pending]
            if not choices:break
            index,nxt=choices[0];pending.remove(index);indices.append(current);current=nxt
            if current==start:break
        if current!=start or len(indices)<3:raise ValueError(f'{obj.name}: invalid closed mesh boundary.')
        loops.append([tuple(obj.matrix_world@mesh.vertices[i].co) for i in indices])
    return loops

def prepare_sources(objects,*,tolerance=None):
    """Snapshot closed Bezier/POLY/mesh boundaries without changing sources.

    All positions and tolerances are in world units. Holes use even-odd nesting.
    Exact original source segments are retained separately for snapping.
    """
    segment_loops=[];names=[]
    for obj in objects:
        if obj.type not in {'CURVE','MESH'}:continue
        if obj.mode!='OBJECT':raise ValueError('Make Outline currently uses Object Mode. Finish editing the source first.')
        before=len(segment_loops)
        if obj.type=='MESH':
            for loop in _mesh_loops(obj):
                segment_loops.append([{'kind':'LINE','cp':curve_geometry.line(a,b)} for a,b in zip(loop,loop[1:]+loop[:1])])
        else:
            for spline in obj.data.splines:
                if not spline.use_cyclic_u:
                    raise ValueError(f'{obj.name}: close the spline before making an outline.')
                if spline.type=='BEZIER':
                    points=spline.bezier_points
                    if len(points)<2:raise ValueError(f'{obj.name}: the spline has too few anchors.')
                    rows=[]
                    for i,a in enumerate(points):
                        b=points[(i+1)%len(points)]
                        rows.append({'kind':'BEZIER','cp':tuple(tuple(obj.matrix_world@p) for p in (a.co,a.handle_right,b.handle_left,b.co))})
                    segment_loops.append(rows)
                elif spline.type=='POLY':
                    loop=[tuple(obj.matrix_world@p.co.xyz) for p in spline.points]
                    if len(loop)<3:raise ValueError(f'{obj.name}: the spline has too few points.')
                    segment_loops.append([{'kind':'LINE','cp':curve_geometry.line(a,b)} for a,b in zip(loop,loop[1:]+loop[:1])])
                else:raise ValueError(f'{obj.name}: convert NURBS to Bezier before making an outline. No automatic flattening was performed.')
        if len(segment_loops)>before:names.append(obj.name)
    if not segment_loops:raise ValueError('Select a closed curve or a planar mesh boundary.')
    segments=[s for loop in segment_loops for s in loop]
    points=[Vector(p) for s in segments for p in s['cp']]
    origin=sum(points,Vector())/len(points)
    centered=[p-origin for p in points];furthest=max(centered,key=lambda p:p.length_squared)
    scale=furthest.length
    if scale<1e-9:raise ValueError('The selected outline has zero size.')
    u=furthest.normalized();cross=max((u.cross(p) for p in centered),key=lambda p:p.length_squared)
    if cross.length<scale*1e-9:raise ValueError('The selected outline has zero area.')
    normal=cross.normalized()
    if normal[max(range(3),key=lambda i:abs(normal[i]))]<0:normal.negate()
    v=normal.cross(u).normalized()
    if any(abs(p.dot(normal))>max(scale*2e-6,1e-7) for p in centered):
        raise ValueError('Make Outline requires boundaries in one plane; depth and nonplanar geometry are not supported.')
    tolerance=max(scale*1e-5,1e-7) if tolerance is None else float(tolerance)
    if not math.isfinite(tolerance) or tolerance<=0:raise ValueError('Sampling tolerance must be positive and finite.')
    epsilon=max(scale*1e-8,1e-9)
    loops=[]
    for segment_loop in segment_loops:
        loop=[]
        for segment in segment_loop:
            cp=[]
            for point in segment['cp']:
                delta=Vector(point)-origin;cp.append((delta.dot(u),delta.dot(v)))
            sampled=[cp[0],cp[3]] if segment['kind']=='LINE' else _flatten(tuple(cp),tolerance)
            loop.extend(sampled[:-1])
        loops.append(_clean(loop,epsilon))
    if sum(map(len,loops))>MAX_POINTS:raise ValueError('Outline exceeds the sampling budget. Increase sampling tolerance.')
    _validate_simple(loops,epsilon,'Source boundaries intersect or touch ambiguously. Use separate clean closed loops before making an outline.')
    depths=[]
    for i,loop in enumerate(loops):
        depth=sum(_contains(loop[0],other) for j,other in enumerate(loops) if j!=i)
        depths.append(depth)
        if (_area(loop)>0)!=(depth%2==0):loop.reverse()
    matrix=Matrix.Identity(4)
    for i,axis in enumerate((u,v,normal)):
        for j in range(3):matrix[j][i]=axis[j]
    matrix.translation=origin
    world_loops=[[tuple(origin+u*x+v*y) for x,y in loop] for loop in loops]
    return {'origin':origin,'u':u,'v':v,'normal':normal,'scale':scale,'loops':loops,
            'world_loops':world_loops,'world_segments':segments,'source_names':names,
            'tolerance':tolerance,'epsilon':epsilon,'depths':depths,'matrix_world':matrix}

def _offset_loop(loop,distance,tolerance,epsilon):
    result=[]
    for index,point in enumerate(loop):
        previous=loop[index-1];following=loop[(index+1)%len(loop)]
        incoming=_sub(point,previous);outgoing=_sub(following,point)
        il,ol=math.hypot(*incoming),math.hypot(*outgoing)
        if min(il,ol)<=epsilon:raise ValueError('Source contains an edge too short for a stable offset.')
        incoming=_mul(incoming,1/il);outgoing=_mul(outgoing,1/ol)
        n0=(-incoming[1],incoming[0]);n1=(-outgoing[1],outgoing[0])
        a=_add(point,_mul(n0,distance));b=_add(point,_mul(n1,distance))
        turn=math.atan2(_cross(incoming,outgoing),_dot(incoming,outgoing))
        if abs(turn)<1e-10:result.append(a);continue
        if turn*distance<0:
            # The offset opens this corner: a circular join has no miter spike.
            radius=abs(distance)
            max_angle=2*math.acos(max(-1,min(1,1-tolerance/radius)))
            steps=max(1,math.ceil(abs(turn)/max(min(max_angle,math.pi/12),1e-5)))
            start=math.atan2(a[1]-point[1],a[0]-point[0])
            for i in range(steps+1):
                angle=start+turn*i/steps
                result.append((point[0]+radius*math.cos(angle),point[1]+radius*math.sin(angle)))
        else:
            den=_cross(incoming,outgoing)
            if abs(den)<1e-12:raise ValueError('Thickness collapses a sharp cusp. Reduce thickness or round that source cusp.')
            along=_cross(_sub(b,a),outgoing)/den
            intersection=_add(a,_mul(incoming,along))
            if not all(math.isfinite(x) for x in intersection):raise ValueError('The offset could not resolve a sharp corner.')
            result.append(intersection)
    return _clean(result,epsilon)

def _winding(point,loop):
    result=0
    for a,b in zip(loop,loop[1:]+loop[:1]):
        side=_cross(_sub(b,a),_sub(point,a))
        if a[1]<=point[1]<b[1] and side>0:result+=1
        elif b[1]<=point[1]<a[1] and side<0:result-=1
    return result

def _trim_offset_overruns(loop,orientation,epsilon,max_trim_distance):
    """Remove reversed local loops where dense offsets overrun a sharp apex.

    A pointed arch's short sampled edges can run past its correct inset apex.
    CDT splits those intersections; only faces with the original winding sign
    survive. Multiple surviving components/holes are a real topology change and
    are rejected. Cleanup is deliberately local (within four border widths),
    so a vanished narrow limb cannot be silently mistaken for a corner trim.
    The caller still verifies all source-boundary clearances.
    """
    try:
        _validate_simple([loop],epsilon,'overrun')
        return loop,False
    except ValueError:
        pass
    scale=max(math.hypot(*point) for point in loop)
    points=[Vector((point[0]/scale,point[1]/scale)) for point in loop]
    edges=[(i,(i+1)%len(points)) for i in range(len(points))]
    vertices,_,triangles,_,_,_=delaunay_2d_cdt(points,edges,[],0,epsilon/scale,False)
    xy=[(point.x*scale,point.y*scale) for point in vertices]
    boundary=set()
    for triangle in triangles:
        if len(triangle)!=3:continue
        a,b,c=(xy[i] for i in triangle)
        centroid=((a[0]+b[0]+c[0])/3,(a[1]+b[1]+c[1])/3)
        if _winding(centroid,loop)*orientation<=0:continue
        if _cross(_sub(b,a),_sub(c,a))<0:triangle=tuple(reversed(triangle))
        for a,b in zip(triangle,triangle[1:]+triangle[:1]):
            if (b,a) in boundary:boundary.remove((b,a))
            else:boundary.add((a,b))
    following=defaultdict(list);incoming=defaultdict(list)
    for a,b in boundary:following[a].append(b);incoming[b].append(a)
    if not boundary or any(len(rows)!=1 for rows in list(following.values())+list(incoming.values())):
        raise ValueError('Thickness collapses or splits a sharp feature. Reduce thickness.')
    start=min(following);current=start;indices=[]
    while True:
        indices.append(current);nxt=following[current][0]
        boundary.remove((current,nxt));current=nxt
        if current==start:break
        if len(indices)>len(xy):raise ValueError('Unable to resolve a stable offset boundary. Reduce thickness.')
    if boundary:raise ValueError('Thickness changes the boundary topology. Reduce thickness.')
    result=_clean([xy[i] for i in indices],epsilon)
    result_edges=list(zip(result,result[1:]+result[:1]))
    if any(min(_point_segment_sq(point,a,b) for a,b in result_edges)>max_trim_distance**2 for point in loop):
        raise ValueError('Thickness removes a narrow limb or requires a large sharp-tip trim. Reduce thickness or round that tip.')
    if (_area(result)>0)!=(orientation>0):result.reverse()
    return result,True

def build_outline(prepared,thickness,*,direction='INWARD'):
    """Build a validated border result; creates no Blender datablocks.

    Topology-changing offsets (collapsed tips, merged holes, self-crossings) are
    deliberately rejected. Reducing thickness retains the original topology.
    """
    thickness=float(thickness);direction=str(direction).upper()
    if direction not in {'INWARD','OUTWARD'}:raise ValueError('Direction must be INWARD or OUTWARD.')
    if not math.isfinite(thickness) or thickness<=0:raise ValueError('Outline thickness must be positive and finite.')
    tolerance=prepared['tolerance'];epsilon=prepared['epsilon']
    if thickness<=4*tolerance:
        raise ValueError(f'Thickness is below the current sampling precision. Use more than {4*tolerance:.6g} world units or prepare with a smaller tolerance.')
    distance=thickness if direction=='INWARD' else -thickness
    originals=prepared['loops']
    offsets=[];trimmed=0
    for loop in originals:
        raw=_offset_loop(loop,distance,tolerance,epsilon)
        cleaned,changed=_trim_offset_overruns(raw,1 if _area(loop)>0 else -1,epsilon,4*thickness)
        offsets.append(cleaned);trimmed+=int(changed)
    if sum(map(len,offsets))>MAX_POINTS:raise ValueError('Offset detail exceeds the sampling budget. Increase sampling tolerance.')
    _validate_simple(offsets,epsilon,'Thickness makes offset boundaries cross or touch. Reduce thickness; no source geometry was changed.')
    for old,new in zip(originals,offsets):
        old_area,new_area=_area(old),_area(new)
        if old_area*new_area<=0 or distance*(old_area-new_area)<=0:
            raise ValueError('Thickness collapses or reverses a boundary. Reduce thickness; no source geometry was changed.')
        expected_inside=direction=='INWARD'
        # The clearance pass below proves the entire new boundary cannot cross
        # an original boundary, so one membership probe per loop is sufficient.
        # Testing every dense curve sample here would add quadratic preview cost.
        if _inside(new[0],originals)!=expected_inside:
            raise ValueError('Thickness crosses a nearby source boundary or collapses a narrow feature. Reduce thickness.')
    for i,loop in enumerate(offsets):
        depth=sum(_contains(loop[0],other) for j,other in enumerate(offsets) if j!=i)
        if depth!=prepared['depths'][i]:raise ValueError('Thickness changes the hole or island topology. Reduce thickness.')
    # Every offset edge must clear every source boundary, including a remote
    # concave feature. Round chord sagitta and original sampling have tolerance.
    clearance=max(0,thickness-3*tolerance)
    for a,b in _candidates(_edges(originals,0)+_edges(offsets,1),clearance):
        if a[4]==b[4]:continue
        if _segment_distance_sq(a[7],a[8],b[7],b[8])<clearance*clearance:
            raise ValueError('Thickness exceeds local boundary clearance or removes a narrow tip. Reduce thickness; no source geometry was changed.')
    border=([list(loop) for loop in originals]+[list(reversed(loop)) for loop in offsets]
            if direction=='INWARD' else [list(loop) for loop in offsets]+[list(reversed(loop)) for loop in originals])
    return {'border_loops':border,'offset_loops':offsets,'source_loops':originals,
            'matrix_world':prepared['matrix_world'].copy(),'thickness':thickness,'direction':direction,
            'diagnostics':{'source_chord_error_bound':tolerance,'round_join_chord_error_bound':tolerance,
                           'minimum_validated_clearance':clearance,'source_loop_count':len(originals),
                           'offset_loop_count':len(offsets),'poly_points':sum(map(len,border)),
                           'trimmed_offset_intersections':trimmed,'topology_preserved':True,'editable_type':'POLY'}}

def make_curve_data(result,name='Outline'):
    """Create a filled, editable POLY Curve only after successful validation."""
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D';data.fill_mode='BOTH';data.resolution_u=1
    try:
        for loop in result['border_loops']:
            spline=data.splines.new('POLY');spline.points.add(len(loop)-1);spline.use_cyclic_u=True
            for point,(x,y) in zip(spline.points,loop):point.co=(x,y,0,1)
        data['harhtools_outline_thickness']=result['thickness']
        data['harhtools_outline_direction']=result['direction']
        data['harhtools_outline_sampling_error']=result['diagnostics']['source_chord_error_bound']
        return data
    except Exception:
        bpy.data.curves.remove(data);raise
