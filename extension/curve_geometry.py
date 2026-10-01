"""Planar pen curves, source-subcurve reconstruction and bounded junction repair.

Polyline chords are used only for picking/region topology. Saved Bezier output
uses subintervals of the original control polygons, never a fit to those chords.
Precision-scale junction detours are welded with explicitly recorded endpoint
and handle displacement; meaningful spans and source guides are preserved.
Intersection parameters are refined on the original cubics before tessellation.
"""
import math
import json
from collections import defaultdict
import bpy
import bmesh
from mathutils import Vector


def lerp(a,b,t): return tuple(x+(y-x)*t for x,y in zip(a,b))

def split(cp,t):
    a,b,c=(lerp(cp[i],cp[i+1],t) for i in range(3))
    d,e=lerp(a,b,t),lerp(b,c,t);f=lerp(d,e,t)
    return (cp[0],a,d,f),(f,e,c,cp[3])

def subcurve(cp,a,b):
    if b<a:return tuple(reversed(subcurve(cp,b,a)))
    if a<=0 and b>=1:return tuple(cp)
    left=split(cp,b)[0] if b<1 else cp
    return split(left,a/b)[1] if a>0 and b>0 else tuple(left)

def evaluate(cp,t):
    s=1-t
    return tuple(s*s*s*cp[0][i]+3*s*s*t*cp[1][i]+3*s*t*t*cp[2][i]+t*t*t*cp[3][i] for i in range(len(cp[0])))

def derivative(cp,t):
    s=1-t
    return tuple(3*(s*s*(cp[1][i]-cp[0][i])+2*s*t*(cp[2][i]-cp[1][i])+t*t*(cp[3][i]-cp[2][i])) for i in range(len(cp[0])))

def second_derivative(cp,t):
    return tuple(6*((1-t)*(cp[2][i]-2*cp[1][i]+cp[0][i])+t*(cp[3][i]-2*cp[2][i]+cp[1][i])) for i in range(len(cp[0])))

def line(a,b):return (tuple(a),lerp(a,b,1/3),lerp(a,b,2/3),tuple(b))

def collect(context):
    editing=context.mode in {'EDIT_CURVE','EDIT_MESH'}
    objects=list(context.objects_in_mode_unique_data if editing else context.selected_objects)
    result=[];names=[]
    for obj in objects:
        if not obj.visible_get() or obj.type not in {'CURVE','MESH'}:continue
        before=len(result);matrix=obj.matrix_world
        if obj.type=='CURVE':
            if obj.mode=='EDIT':obj.update_from_editmode()
            for si,spline in enumerate(obj.data.splines):
                if spline.type=='BEZIER':
                    points=spline.bezier_points
                    for i in range(len(points) if spline.use_cyclic_u else len(points)-1):
                        a,b=points[i],points[(i+1)%len(points)]
                        if a.hide or b.hide:continue
                        if editing and not (a.select_control_point and b.select_control_point):continue
                        cp=[tuple(matrix@p) for p in (a.co,a.handle_right,b.handle_left,b.co)]
                        result.append({'cp':cp,'source':obj.name,'spline':si,'segment':i,'kind':'BEZIER'})
                elif spline.type=='POLY':
                    points=spline.points
                    for i in range(len(points) if spline.use_cyclic_u else len(points)-1):
                        a,b=points[i],points[(i+1)%len(points)]
                        if a.hide or b.hide:continue
                        if editing and not (a.select and b.select):continue
                        result.append({'cp':line(matrix@a.co.xyz,matrix@b.co.xyz),'source':obj.name,'spline':si,'segment':i,'kind':'LINE'})
                else:
                    raise ValueError('Editable output supports Bezier and Poly splines. Convert NURBS to Bezier first; no automatic flattening was performed.')
        else:
            if not editing and obj.get('harh_circle'):
                radius=float(obj['harh_circle_radius'])
                axis_u=Vector(obj.get('harh_plane_u',(1,0,0)))
                axis_v=Vector(obj.get('harh_plane_v',(0,1,0)))
                intervals=[{'start':0.0,'end':math.tau}]
                if obj.get('harh_arc_role'):
                    raw=obj.get('harh_arc_intervals','[]')
                    intervals=json.loads(raw) if isinstance(raw,str) else raw
                for interval in intervals:
                    lo,hi=float(interval['start']),float(interval['end'])
                    count=max(1,math.ceil(abs(hi-lo)/(math.pi/2)))
                    for n in range(count):
                        a=lo+(hi-lo)*n/count;b=lo+(hi-lo)*(n+1)/count
                        k=4/3*math.tan((b-a)/4)
                        p=radius*(axis_u*math.cos(a)+axis_v*math.sin(a))
                        q=radius*(axis_u*math.cos(b)+axis_v*math.sin(b))
                        dp=radius*(-axis_u*math.sin(a)+axis_v*math.cos(a))
                        dq=radius*(-axis_u*math.sin(b)+axis_v*math.cos(b))
                        result.append({'cp':[tuple(matrix@v) for v in (p,p+k*dp,q-k*dq,q)],'source':obj.name,'segment':len(result),'kind':'CIRCLE_CUBIC'})
                if len(result)>before:names.append(obj.name)
                continue
            bm=bmesh.from_edit_mesh(obj.data).copy() if obj.mode=='EDIT' else bmesh.new()
            try:
                if obj.mode!='EDIT':bm.from_mesh(obj.data)
                for i,e in enumerate(bm.edges):
                    if e.hide or any(v.hide for v in e.verts) or (editing and not e.select):continue
                    result.append({'cp':line(*(matrix@v.co for v in e.verts)),'source':obj.name,'segment':i,'kind':'LINE'})
            finally:bm.free()
        if len(result)>before:names.append(obj.name)
    if not result:raise ValueError('Select visible Bezier segments or mesh edges first.')
    return result,names

def adaptive(cp,tolerance=1e-4,max_depth=14):
    result=[(0.0,cp[0])]
    def visit(c,a,b,depth):
        dx,dy=c[3][0]-c[0][0],c[3][1]-c[0][1];length=math.hypot(dx,dy)
        flat=max(abs(dx*(p[1]-c[0][1])-dy*(p[0]-c[0][0]))/max(length,1e-16) for p in c[1:3])
        # Also subdivide folded/backtracking cubics whose controls lie on chord.
        hull=sum(math.dist(c[i],c[i+1]) for i in range(3))
        if depth>=max_depth or (flat<=tolerance and hull-length<=tolerance):
            result.append((b,c[3]));return
        left,right=split(c,.5);middle=(a+b)*.5
        visit(left,a,middle,depth+1);visit(right,middle,b,depth+1)
    visit(cp,0,1,0)
    return result

def refine(a,b,t,u):
    """Bounded Newton solve of A(t)==B(u), in normalized planar coordinates."""
    for _ in range(24):
        p,q=evaluate(a,t),evaluate(b,u);dx,dy=p[0]-q[0],p[1]-q[1]
        if math.hypot(dx,dy)<2e-11:return t,u
        da,db=derivative(a,t),derivative(b,u)
        det=da[1]*db[0]-da[0]*db[1]
        if abs(det)<1e-16:break
        dt=(dx*db[1]-dy*db[0])/det
        du=(da[1]*dx-da[0]*dy)/det
        if not (-1e-6<=t+dt<=1+1e-6 and -1e-6<=u+du<=1+1e-6):break
        t=max(0,min(1,t+dt));u=max(0,min(1,u+du))
    return (t,u) if math.dist(evaluate(a,t),evaluate(b,u))<2e-8 else None


def nearest_parameter(cp,point):
    """Closest cubic parameter, using several local seeds for folded cubics."""
    seeds=sorted((math.dist(evaluate(cp,i/32),point),i/32) for i in range(33))[:3]
    candidates=[(math.dist(cp[0],point),0.0),(math.dist(cp[3],point),1.0)]
    for _,t in seeds:
        for _ in range(20):
            p=evaluate(cp,t);d=derivative(cp,t)
            dd=tuple(6*((1-t)*(cp[2][i]-2*cp[1][i]+cp[0][i])+t*(cp[3][i]-2*cp[2][i]+cp[1][i])) for i in range(2))
            delta=tuple(p[i]-point[i] for i in range(2))
            denominator=sum(d[i]*d[i]+delta[i]*dd[i] for i in range(2))
            if abs(denominator)<1e-18:break
            new=max(0,min(1,t-sum(delta[i]*d[i] for i in range(2))/denominator))
            if abs(new-t)<1e-13:break
            t=new
        candidates.append((math.dist(evaluate(cp,t),point),t))
    return min(candidates)[1]


def straight(cp):
    dx,dy=cp[3][0]-cp[0][0],cp[3][1]-cp[0][1];length=math.hypot(dx,dy)
    return length>1e-12 and max(abs(dx*(p[1]-cp[0][1])-dy*(p[0]-cp[0][0]))/length for p in cp[1:3])<5e-8


def check_partial_coincidence(a,b):
    """Refuse ambiguous overlapping guide intervals instead of creating slivers.

    Exact full duplicates can use the existing shared CDT constraint chain.
    Partial overlaps require source ownership choices, so they are rejected.
    """
    contacts=[]
    for t in (0.0,1.0):
        u=nearest_parameter(b,a[int(t)*3])
        if math.dist(evaluate(b,u),a[int(t)*3])<1e-7:contacts.append((t,u))
    for u in (0.0,1.0):
        t=nearest_parameter(a,b[int(u)*3])
        if math.dist(evaluate(a,t),b[int(u)*3])<1e-7:contacts.append((t,u))
    for index,(t0,u0) in enumerate(contacts):
        for t1,u1 in contacts[index+1:]:
            if abs(t1-t0)<1e-5 or abs(u1-u0)<1e-5:continue
            ca,cb=subcurve(a,t0,t1),subcurve(b,u0,u1)
            same=max(math.dist(x,y) for x,y in zip(ca,cb))<3e-7
            if straight(a) and straight(b):same=True
            if not same:continue
            complete=(min(t0,t1)<1e-6 and max(t0,t1)>1-1e-6 and min(u0,u1)<1e-6 and max(u0,u1)>1-1e-6)
            if not complete:
                raise ValueError('Some selected curve guides overlap along only part of the same curve. Remove the duplicate overlapping guide or split it at the overlap ends first. No geometry was changed.')


def polynomial_roots_unit(a,b,c,d):
    """Real roots on [0,1], including double roots at derivative extrema."""
    def value(t):return ((a*t+b)*t+c)*t+d
    breaks=[0.0,1.0]
    if abs(a)<1e-15:
        if abs(b)>1e-15:breaks.append(-c/(2*b))
    else:
        discriminant=4*b*b-12*a*c
        if discriminant>=0:
            q=math.sqrt(discriminant)
            breaks.extend(((-2*b-q)/(6*a),(-2*b+q)/(6*a)))
    breaks=sorted(set(t for t in breaks if 0<=t<=1));roots=[]
    for t in breaks:
        if abs(value(t))<3e-8:roots.append(t)
    for lo,hi in zip(breaks,breaks[1:]):
        flo,fhi=value(lo),value(hi)
        if flo*fhi>=0:continue
        for _ in range(55):
            mid=(lo+hi)*.5;fm=value(mid)
            if flo*fm<=0:hi=mid;fhi=fm
            else:lo=mid;flo=fm
        roots.append((lo+hi)*.5)
    return roots


def line_contacts(curve,line_cp):
    dx,dy=line_cp[3][0]-line_cp[0][0],line_cp[3][1]-line_cp[0][1]
    length=math.hypot(dx,dy)
    if length<1e-12:return []
    distances=[(dx*(p[1]-line_cp[0][1])-dy*(p[0]-line_cp[0][0]))/length for p in curve]
    if max(abs(v) for v in distances)<3e-8:return []
    a=-distances[0]+3*distances[1]-3*distances[2]+distances[3]
    b=3*distances[0]-6*distances[1]+3*distances[2]
    c=-3*distances[0]+3*distances[1];d=distances[0]
    result=[]
    for t in polynomial_roots_unit(a,b,c,d):
        point=evaluate(curve,t)
        along=((point[0]-line_cp[0][0])*dx+(point[1]-line_cp[0][1])*dy)/(length*length)
        if not -1e-8<=along<=1+1e-8:continue
        u=nearest_parameter(line_cp,point)
        if math.dist(evaluate(line_cp,u),point)<1e-7:result.append((t,u))
    return result


def closest_chord_parameters(a,b,c,d):
    """Closest finite-segment points for tangency candidate seeding."""
    def projection(p,q,r):
        dx,dy=r[0]-q[0],r[1]-q[1];den=dx*dx+dy*dy
        return max(0,min(1,((p[0]-q[0])*dx+(p[1]-q[1])*dy)/den)) if den>1e-24 else 0.0
    values=[]
    for s,p in ((0.0,a),(1.0,b)):
        r=projection(p,c,d);values.append((math.dist(p,lerp(c,d,r)),s,r))
    for r,p in ((0.0,c),(1.0,d)):
        s=projection(p,a,b);values.append((math.dist(p,lerp(a,b,s)),s,r))
    return min(values)


def refine_tangent(a,b,t,u):
    """Solve parallel tangents and zero along-tangent separation.

    Unlike intersection Newton, this system is well-conditioned at an ordinary
    tangency. The final full point distance still has to validate the contact.
    """
    def cross(p,q):return p[0]*q[1]-p[1]*q[0]
    def dot(p,q):return p[0]*q[0]+p[1]*q[1]
    for _ in range(24):
        p,q=evaluate(a,t),evaluate(b,u);delta=(p[0]-q[0],p[1]-q[1])
        da,db=derivative(a,t),derivative(b,u)
        aa,bb=second_derivative(a,t),second_derivative(b,u)
        g,h=cross(da,db),dot(delta,da)
        j00,j01=cross(aa,db),cross(da,bb)
        j10,j11=dot(da,da)+dot(delta,aa),-dot(db,da)
        det=j00*j11-j01*j10
        if abs(det)<1e-18:break
        dt=(-g*j11+j01*h)/det;du=(-j00*h+g*j10)/det
        if not (-1e-7<=t+dt<=1+1e-7 and -1e-7<=u+du<=1+1e-7):return None
        t=max(0,min(1,t+dt));u=max(0,min(1,u+du))
        if abs(dt)+abs(du)<2e-12:break
    da,db=derivative(a,t),derivative(b,u)
    lengths=math.hypot(*da)*math.hypot(*db)
    if lengths<1e-16:return None
    if abs(cross(da,db))/lengths<1e-6 and math.dist(evaluate(a,t),evaluate(b,u))<5e-8:
        return t,u
    return None

def prepare(primitives,basis):
    origin,axis_u,axis_v,normal,scale,_=basis
    projected=[]
    for primitive in primitives:
        cp=[]
        for co in primitive['cp']:
            # Do the subtraction in double precision before projecting. A
            # float32 world Vector near a translated workshop can lose several
            # microns and turn one intended junction into microscopic spans.
            p=tuple((float(co[i])-float(origin[i]))/scale for i in range(3))
            cp.append((sum(p[i]*axis_u[i] for i in range(3)),sum(p[i]*axis_v[i] for i in range(3))))
        projected.append(tuple(cp))
    samples=[adaptive(cp,2e-4) for cp in projected]
    cuts=[{0.0,1.0} for _ in primitives]
    pair_cuts=defaultdict(lambda:[set(),set()])
    def record_contact(i,t,j,u):
        if i>j:i,j,t,u=j,i,u,t
        pair_cuts[(i,j)][0].add(t)
        pair_cuts[(i,j)][1].add(u)
    tangent_hits=defaultdict(list)
    bounds=[(min(p[0] for p in cp),max(p[0] for p in cp),min(p[1] for p in cp),max(p[1] for p in cp)) for cp in projected]
    for i,a in enumerate(projected):
        for j in range(i+1,len(projected)):
            ai,bi=bounds[i],bounds[j]
            if ai[0]>bi[1]+1e-7 or bi[0]>ai[1]+1e-7 or ai[2]>bi[3]+1e-7 or bi[2]>ai[3]+1e-7:continue
            b=projected[j];check_partial_coincidence(a,b)
            if straight(b):
                for t,u in line_contacts(a,b):record_contact(i,t,j,u)
            if straight(a):
                for u,t in line_contacts(b,a):record_contact(i,t,j,u)
    chords=[]
    for k,rows in enumerate(samples):
        for (t,a),(u,b) in zip(rows,rows[1:]):
            chords.append((min(a[0],b[0]),max(a[0],b[0]),min(a[1],b[1]),max(a[1],b[1]),k,t,u,a,b))
    # Sweep broad phase avoids testing every chord against every other chord.
    active=[]
    for current in sorted(chords,key=lambda x:x[0]):
        x0,x1,y0,y1,i,t0,t1,a,b=current
        active=[r for r in active if r[1]>=x0-3e-4]
        for other in active:
            _,_,v0,v1,j,u0,u1,c,d=other
            if y1<v0-3e-4 or v1<y0-3e-4:continue
            if i==j and (abs(t0-u1)<1e-12 or abs(t1-u0)<1e-12):continue
            dx,dy=b[0]-a[0],b[1]-a[1];ex,ey=d[0]-c[0],d[1]-c[1]
            den=dx*ey-dy*ex
            lengths=math.hypot(dx,dy)*math.hypot(ex,ey)
            if i!=j and lengths>1e-20 and abs(den)/lengths<.25:
                distance,s,r=closest_chord_parameters(a,b,c,d)
                if distance<4e-4:
                    tangent=refine_tangent(projected[i],projected[j],t0+(t1-t0)*s,u0+(u1-u0)*r)
                    if tangent:
                        key=(i,j) if i<j else (j,i)
                        contact=tangent if i<j else tuple(reversed(tangent))
                        if not any(abs(contact[0]-p)+abs(contact[1]-q)<1e-5 for p,q in tangent_hits[key]):
                            tangent_hits[key].append(contact)
            if abs(den)>1e-16:
                s=((c[0]-a[0])*ey-(c[1]-a[1])*ex)/den
                r=((c[0]-a[0])*dy-(c[1]-a[1])*dx)/den
                if -.015<=s<=1.015 and -.015<=r<=1.015:
                    hit=refine(projected[i],projected[j],t0+(t1-t0)*max(0,min(1,s)),u0+(u1-u0)*max(0,min(1,r)))
                    if hit and not (i==j and abs(hit[0]-hit[1])<1e-5):
                        record_contact(i,round(hit[0],12),j,round(hit[1],12))
            # Exact endpoint contacts, including tangencies on Bezier knots.
            for ti,p in ((t0,a),(t1,b)):
                for uj,q in ((u0,c),(u1,d)):
                    if math.dist(p,q)<1e-8:
                        record_contact(i,ti,j,uj)
        active.append(current)
    for (i,j),contacts in tangent_hits.items():
        pair=pair_cuts[(i,j)]
        for t,u in contacts:
            # Single-precision Blender control points can turn a mathematical
            # double root into two microscopic crossings. Consolidate these
            # only for this verified tangent PAIR. Cuts from a third curve
            # remain separate and must survive even when extremely close.
            pair[0]={v for v in pair[0] if v in (0.0,1.0) or abs(v-t)>5e-4}
            pair[1]={v for v in pair[1] if v in (0.0,1.0) or abs(v-u)>5e-4}
            pair[0].add(t);pair[1].add(u)
    for (i,j),(first,second) in pair_cuts.items():
        cuts[i].update(first);cuts[j].update(second)
    points=[];edges=[];spans=[]
    for k,cp in enumerate(projected):
        values=sorted(cuts[k]);previous=None
        for lo,hi in zip(values,values[1:]):
            rows=adaptive(subcurve(cp,lo,hi),7e-5)
            for local,p in rows:
                t=lo+(hi-lo)*local
                if previous is not None and abs(previous[1]-t)<1e-12:continue
                index=len(points);points.append(Vector(primitives[k]['cp'][0]) if t==0 else Vector(evaluate(primitives[k]['cp'],t)))
                if previous is not None:
                    edges.append((previous[0],index));spans.append((k,previous[1],t))
                previous=(index,t)
    return points,edges,spans

def edge_fragments(arrangement):
    """Group sampled constraints into trim-able runs between junctions."""
    edges=list(arrangement.get('constraint_edges',()))
    neighbors=defaultdict(list)
    for i,(a,b) in enumerate(edges):neighbors[a].append(i);neighbors[b].append(i)
    pending=set(range(len(edges)));groups=[]
    while pending:
        first=next((i for i in pending if any(len(neighbors[v])!=2 for v in edges[i])),next(iter(pending)));a,b=edges[first]
        start=a if len(neighbors[a])!=2 else b if len(neighbors[b])!=2 else a
        run=[];current=start;eid=first
        while eid in pending:
            pending.remove(eid);x,y=edges[eid];nxt=y if x==current else x
            run.append((current,nxt));current=nxt
            if len(neighbors[current])!=2:break
            options=[j for j in neighbors[current] if j in pending]
            if not options:break
            eid=options[0]
        groups.append(run)
    return groups

def boundary_edges(arrangement,selected):
    chosen={i for rid in selected for i in arrangement['regions'][rid]['triangles']}
    result=[]
    for i in chosen:
        tri=arrangement['triangles'][i]
        for a,b in zip(tri,tri[1:]+tri[:1]):
            if sum(j in chosen for j in arrangement['edge_faces'][tuple(sorted((a,b)))])==1:result.append((a,b))
    return result

def paths_from_edges(edges,vertices,directed=True):
    pending=set(range(len(edges)));neighbors=defaultdict(list)
    for i,(a,b) in enumerate(edges):
        neighbors[a].append((i,b))
        if not directed:neighbors[b].append((i,a))
    paths=[]
    while pending:
        first=next(iter(pending));start=edges[first][0]
        if not directed:
            ends=[v for v in edges[first] if len(neighbors[v])==1]
            if not ends:
                # Prefer any open endpoint in the remaining graph.
                ends=[v for v,ns in neighbors.items() if len([i for i,_ in ns if i in pending])==1]
            if ends:start=ends[0]
        current=start;path=[];incoming=None
        while True:
            choices=[(i,v) for i,v in neighbors[current] if i in pending]
            if not choices:break
            if incoming is not None and len(choices)>1:
                def turn(row):
                    d=vertices[row[1]]-vertices[current]
                    angle=math.atan2(incoming.cross(d),incoming.dot(d))
                    return angle if directed else -abs(angle)
                eid,nxt=max(choices,key=turn)
            else:eid,nxt=choices[0]
            pending.remove(eid);path.append((current,nxt));incoming=vertices[nxt]-vertices[current];current=nxt
            if current==start:break
        if path:paths.append((path,current==start))
    return paths

def _source_precision(arrangement):
    """World-coordinate float32 precision, not an arbitrary modeling distance."""
    # Translation perpendicular to the drawing plane cannot reduce its 2D
    # precision. Weight coordinate uncertainty by its in-plane contribution.
    weights=[math.hypot(arrangement['u'][i],arrangement['v'][i]) for i in range(3)]
    ulp=max((math.ldexp(1.0,math.frexp(abs(float(value)))[1]-24)*weights[i]
             for primitive in arrangement.get('source_primitives',()) for point in primitive['cp']
             for i,value in enumerate(point) if value),default=0.)
    return max(4*ulp,float(arrangement.get('scale',1.))*2e-7,1e-12)

def _control_diameter(controls):
    points=[point for cp in controls for point in cp]
    return math.sqrt(sum((max(point[i] for point in points)-min(point[i] for point in points))**2 for i in range(3)))

def _clean_numerical_junctions(controls,cyclic,tolerance):
    """Weld only coordinate-precision detours between substantial curve spans.

    Native 2D Curve filling is unstable on tiny triangular detours left by
    float32 translated intersections. A tiny *region* is never removed: both
    neighboring spans must be over sixteen times larger than the precision
    threshold, and the entire removed chain must fit inside that threshold.
    Joining moves endpoints and their adjacent handles together; all other
    source controls remain unchanged. Displacement is returned for diagnostics.
    """
    if len(controls)<3:return controls,0,0.
    controls=[[point.copy() for point in cp] for cp in controls]
    if cyclic:
        start=next((i for i,cp in enumerate(controls) if _control_diameter([cp])>16*tolerance),None)
        if start is None:return controls,0,0.
        controls=controls[start:]+controls[:start]
    result=[];pending=[];removed=0;adjustment=0.
    def join(previous,following):
        nonlocal adjustment
        shared=(previous[3]+following[0])*.5
        before,after=shared-previous[3],shared-following[0]
        adjustment=max(adjustment,before.length,after.length)
        previous[2]+=before;previous[3]=shared.copy()
        following[1]+=after;following[0]=shared.copy()
    for cp in controls:
        if _control_diameter([cp])<=tolerance:
            pending.append(cp);continue
        if pending:
            if (result and _control_diameter([result[-1]])>16*tolerance
                    and _control_diameter([cp])>16*tolerance
                    and _control_diameter(pending+[[result[-1][3],cp[0]]])<=tolerance):
                join(result[-1],cp);removed+=len(pending)
            else:result.extend(pending)
            pending=[]
        result.append(cp)
    if pending:
        if (cyclic and len(result)>1 and _control_diameter([result[-1]])>16*tolerance
                and _control_diameter([result[0]])>16*tolerance
                and _control_diameter(pending+[[result[-1][3],result[0][0]]])<=tolerance):
            join(result[-1],result[0]);removed+=len(pending)
        else:result.extend(pending)
    return result,removed,adjustment

def curve_data(arrangement,selected=(),*,edge_runs=None,name='Shape Builder'):
    edges=boundary_edges(arrangement,selected) if edge_runs is None else [e for run in edge_runs for e in run]
    if not edges:raise ValueError('No retained curve segments remain.')
    paths=paths_from_edges(edges,arrangement['vertices'],directed=edge_runs is None)
    primitives=arrangement.get('source_primitives',[]);provenance=arrangement.get('source_spans',{})
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D';data.fill_mode='BOTH';data.resolution_u=24
    removed_total=0;maximum_adjustment=0.;precision=_source_precision(arrangement)
    try:
        for path,cyclic in paths:
            spans=[]
            for a,b in path:
                item=provenance.get(tuple(sorted((a,b))))
                if item:
                    k,t0,t1=item
                    if a>b:t0,t1=t1,t0
                    if spans and spans[-1][0]==k and abs(spans[-1][2]-t0)<2e-6:
                        spans[-1]=(k,spans[-1][1],t1)
                    else:spans.append((k,t0,t1))
                else:
                    # Explicit gap connectors and legacy straight mesh input.
                    spans.append((None,a,b))
            if cyclic and len(spans)>1 and spans[0][0] is not None and spans[0][0]==spans[-1][0] and abs(spans[-1][2]-spans[0][1])<2e-6:
                spans[0]=(spans[0][0],spans[-1][1],spans[0][2]);spans.pop()
            controls=[]
            for k,a,b in spans:
                if k is None:
                    cp=line(arrangement['world'][a],arrangement['world'][b])
                else:cp=subcurve(primitives[k]['cp'],a,b)
                local=[]
                for p in cp:
                    delta=tuple(float(p[i])-float(arrangement['origin'][i]) for i in range(3))
                    local.append(Vector((sum(delta[i]*arrangement['u'][i] for i in range(3)),
                                         sum(delta[i]*arrangement['v'][i] for i in range(3)),0)))
                controls.append(local)
            if edge_runs is None:
                controls,removed,adjustment=_clean_numerical_junctions(controls,cyclic,precision)
                removed_total+=removed;maximum_adjustment=max(maximum_adjustment,adjustment)
            spline=data.splines.new('BEZIER');spline.use_cyclic_u=cyclic
            spline.bezier_points.add(len(controls)-1 if cyclic else len(controls))
            for i,p in enumerate(spline.bezier_points):
                p.handle_left_type='FREE';p.handle_right_type='FREE'
                if i<len(controls):p.co=controls[i][0];p.handle_right=controls[i][1]
                else:p.co=controls[-1][3];p.handle_right=p.co
                p.handle_left=controls[i-1][2] if i>0 else controls[-1][2] if cyclic else p.co
        data['harhtools_geometry']='Original Bezier subcurves with bounded float-precision junction repair; source guides unchanged'
        data['harhtools_junction_precision']=precision
        data['harhtools_junction_spans_removed']=removed_total
        data['harhtools_junction_max_adjustment']=maximum_adjustment
        return data
    except Exception:
        bpy.data.curves.remove(data);raise
