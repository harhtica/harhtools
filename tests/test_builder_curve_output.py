"""Shape Builder output regression on the 12-circle Gothic construction."""
import math,sys,json,time
from pathlib import Path
import bpy
from mathutils import Vector,Matrix
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import shape_builder as sb,curve_geometry as cg
OUT=ROOT/'tests'/'_artifacts';OUT.mkdir(exist_ok=True)

def clear():
    for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)

def circle(name,x,y,r,transform=None):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D';data.resolution_u=24
    spline=data.splines.new('BEZIER');spline.bezier_points.add(3);spline.use_cyclic_u=True
    k=4/3*math.tan(math.pi/8)
    for i,p in enumerate(spline.bezier_points):
        angle=i*math.pi/2;v=Vector((math.cos(angle),math.sin(angle),0));t=Vector((-math.sin(angle),math.cos(angle),0))
        p.handle_left_type=p.handle_right_type='FREE';p.co=Vector((x,y,0))+r*v
        p.handle_left=p.co-k*r*t;p.handle_right=p.co+k*r*t
    obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj);obj.select_set(True)
    if transform:obj.matrix_world=transform
    return obj

def fixture(transform=None):
    clear()
    for arm in range(4):
        angle=arm*math.pi/2
        for label,x,y,r in [('C',0,2.065,.45),('L',-.3,1.12,.65),('R',.3,1.12,.65)]:
            circle(str(arm)+label,x*math.cos(angle)-y*math.sin(angle),x*math.sin(angle)+y*math.cos(angle),r,transform)
    bpy.context.view_layer.update()

def workshop_fixture(_transform=None):
    """Portable reconstruction of the exact workshop's analytic-circle knots.

    It includes knots at every circle intersection and translations Y18/Z-23,
    which expose the float32 micro-junction failure that four-knot circles miss.
    """
    clear();circles=[]
    for arm in range(4):
        angle=arm*math.pi/2
        for label,x,y,r in [('C',0,2.065,.45),('L',-.3,1.12,.65),('R',.3,1.12,.65)]:
            circles.append((str(arm)+label,x*math.cos(angle)-y*math.sin(angle),x*math.sin(angle)+y*math.cos(angle),r))
    for name,x,y,r in circles:
        angles={0.,math.pi/2,math.pi,3*math.pi/2}
        for other,u,v,s in circles:
            d=math.hypot(u-x,v-y)
            if other==name or not abs(r-s)<d<r+s:continue
            angle=math.atan2(v-y,u-x);half=math.acos((r*r+d*d-s*s)/(2*r*d))
            angles.update(((angle-half)%math.tau,(angle+half)%math.tau))
        angles=sorted(angles);data=bpy.data.curves.new(name,'CURVE');data.dimensions='3D'
        spline=data.splines.new('BEZIER');spline.bezier_points.add(len(angles)-1);spline.use_cyclic_u=True
        for i,(p,a) in enumerate(zip(spline.bezier_points,angles)):
            prev=angles[i-1] if i else angles[-1]-math.tau;nxt=angles[(i+1)%len(angles)] if i+1<len(angles) else math.tau
            left=4/3*math.tan((a-prev)/4);right=4/3*math.tan((nxt-a)/4)
            co=Vector((0,r*math.cos(a),r*math.sin(a)));tangent=Vector((0,-r*math.sin(a),r*math.cos(a)))
            p.handle_left_type=p.handle_right_type='FREE';p.co=co;p.handle_left=co-left*tangent;p.handle_right=co+right*tangent
        obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj);obj.location=(0,18+x,-23+y);obj.select_set(True)
    bpy.context.view_layer.update()

def area(data):
    obj=bpy.data.objects.new('Output',data);bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.update();evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
    value=sum(p.area for p in mesh.polygons);evaluated.to_mesh_clear()
    return value

def evaluated_triangles(data):
    obj=bpy.data.objects.new('Diagnostic output',data);bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.update();evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
    mesh.calc_loop_triangles()
    triangles=[[tuple(mesh.vertices[i].co) for i in triangle.vertices] for triangle in mesh.loop_triangles]
    evaluated.to_mesh_clear();return triangles

def diagnostic(before,after):
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="880" viewBox="0 0 1600 880">',
         '<rect width="1600" height="880" fill="#f6f8fb"/>',
         '<text x="50" y="55" font-family="Arial" font-size="32" fill="#1c293a">Shape Builder — evaluated Blender fill, identical source curves</text>',
         '<text x="50" y="91" font-family="Arial" font-size="20" fill="#536075">The preview boundary was correct; precision-scale junction fragments corrupted Blender’s filled output.</text>']
    for index,(label,data,color) in enumerate([('Before junction repair',before,'#b45252'),('After bounded junction repair',after,'#4d759f')]):
        cx=400+800*index;cy=470;scale=110
        def point(p):return cx+scale*p[0],cy-scale*p[1]
        svg.append(f'<rect x="{30+800*index}" y="125" width="740" height="690" rx="10" fill="white" stroke="#d6dee8"/>')
        svg.append(f'<text x="{60+800*index}" y="170" font-family="Arial" font-size="25" fill="#1c293a">{label}</text>')
        path=' '.join('M '+' L '.join('%.5f,%.5f'%point(p) for p in triangle)+' Z' for triangle in evaluated_triangles(data))
        svg.append(f'<path d="{path}" fill="{color}"/>')
        for spline in data.splines:
            p=spline.bezier_points;path='M %.5f,%.5f'%point(p[0].co)
            for i,a in enumerate(p):
                b=p[(i+1)%len(p)];path+=' C '+' '.join('%.5f,%.5f'%point(v) for v in (a.handle_right,b.handle_left,b.co))
            svg.append(f'<path d="{path} Z" fill="none" stroke="#142033" stroke-width="1.8"/>')
        svg.append(f'<text x="{60+800*index}" y="785" font-family="Arial" font-size="20" fill="#536075">{len(data.splines[0].bezier_points)} anchors · evaluated filled area {area(data):.5f}</text>')
    svg.append('<text x="50" y="855" font-family="Arial" font-size="20" fill="#536075">Retained junction adjustment ≤ 0.00000136 world units. Original source curves are unchanged.</text></svg>')
    (OUT/'builder_fill_before_after.svg').write_text('\n'.join(svg),encoding='utf-8')

def report_case(name,transform=None,facing=None,make_fixture=fixture):
    make_fixture(transform);start=time.perf_counter();arr,_=sb.build_pen_arrangement(bpy.context,facing=facing)
    selected=set(range(len(arr['regions'])));data=cg.curve_data(arr,selected)
    expected=sum(region['area'] for region in arr['regions']);actual=area(data)
    provenance=arr['source_spans'];world=arr['world'];primitives=arr['source_primitives'];gaps=[]
    for a,b in cg.boundary_edges(arr,selected):
        span=provenance.get(tuple(sorted((a,b))))
        if span:
            k,t0,t1=span
            if a>b:t0,t1=t1,t0
            gaps.append(max(math.dist(cg.evaluate(primitives[k]['cp'],t0),world[a]),math.dist(cg.evaluate(primitives[k]['cp'],t1),world[b])))
    report=dict(case=name,regions=len(arr['regions']),splines=len(data.splines),points=[len(s.bezier_points) for s in data.splines],expected_area=expected,actual_area=actual,relative_area_error=abs(actual-expected)/expected,max_span_endpoint_error=max(gaps),seconds=time.perf_counter()-start)
    report.update(removed=data.get('harhtools_junction_spans_removed'),max_adjustment=data.get('harhtools_junction_max_adjustment'),precision=data.get('harhtools_junction_precision'))
    print(json.dumps(report),flush=True)
    return report,data,arr

reports=[]
for name,transform,facing in [('XY',None,None),('XY back',None,Vector((0,0,-1))),('YZ translated',Matrix.Translation((0,26,0))@Matrix.Rotation(math.pi/2,4,'Y'),None),('YZ translated back',Matrix.Translation((0,26,0))@Matrix.Rotation(math.pi/2,4,'Y'),Vector((-1,0,0)))]:
    report,data,arr=report_case(name,transform,facing);reports.append(report)
    assert report['relative_area_error']<.005,report
    assert report['splines']==1,report
for facing in [Vector((1,0,0)),Vector((-1,0,0))]:
    report,data,arr=report_case('Workshop intersection knots '+str(facing.x),facing=facing,make_fixture=workshop_fixture)
    reports.append(report)
    assert report['relative_area_error']<.005 and report['splines']==1,report
    assert report['removed']>0 and report['max_adjustment']<=report['precision'],report
    if facing.x>0:
        cleanup=cg._clean_numerical_junctions
        try:
            cg._clean_numerical_junctions=lambda controls,cyclic,tolerance:(controls,0,0.)
            before=cg.curve_data(arr,set(range(len(arr['regions']))))
        finally:cg._clean_numerical_junctions=cleanup
        assert area(before)<report['expected_area']*.5,'Fixture no longer reproduces the real native-fill regression'
        diagnostic(before,data)
    # A confirmed editable output must remain usable as the next pen source.
    for obj in bpy.context.selected_objects:obj.select_set(False)
    reused=bpy.data.objects.new('Reused output',data);bpy.context.collection.objects.link(reused);reused.select_set(True)
    reused.matrix_world=sb.basis_matrix(arr) if hasattr(sb,'basis_matrix') else Matrix(((arr['u'].x,arr['v'].x,arr['normal'].x,arr['origin'].x),(arr['u'].y,arr['v'].y,arr['normal'].y,arr['origin'].y),(arr['u'].z,arr['v'].z,arr['normal'].z,arr['origin'].z),(0,0,0,1)))
    bpy.context.view_layer.update();again,_=sb.build_pen_arrangement(bpy.context,facing=facing)
    repeated=cg.curve_data(again,set(range(len(again['regions']))))
    expected=sum(r['area'] for r in again['regions'])
    assert abs(area(repeated)-expected)/expected<.005
    reports.append({'case':'reuse repaired editable output '+str(facing.x),'area':area(repeated)})

tiny=[list(map(Vector,cg.line(a,b))) for a,b in [((0,0,0),(1e-7,0,0)),((1e-7,0,0),(0,1e-7,0)),((0,1e-7,0),(0,0,0))]]
cleaned,removed,adjustment=cg._clean_numerical_junctions(tiny,True,1e-5)
assert len(cleaned)==3 and removed==0 and adjustment==0
broken=[list(map(Vector,cg.line(a,b))) for a,b in [((0,0,0),(1,0,0)),((1,0,0),(1+1e-7,0,0)),((20,0,0),(21,0,0))]]
cleaned,removed,adjustment=cg._clean_numerical_junctions(broken,False,1e-5)
assert removed==0 and adjustment==0,'Never weld across malformed provenance gaps'
parallel={'u':Vector((1,0,0)),'v':Vector((0,1,0)),'scale':1.,'source_primitives':[{'cp':[(.1,.1,1e8)]*4}]}
assert cg._source_precision(parallel)<1e-6,'Huge perpendicular translations must not erase planar details'
reports.append({'case':'tiny islands, malformed gaps and perpendicular translation precision preserved'})
(OUT/'builder_curve_output_report.json').write_text(json.dumps(reports,indent=2))
print('PASS builder curve output',len(reports),'cases')
