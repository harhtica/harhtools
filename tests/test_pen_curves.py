import bpy,sys,math,json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / '_artifacts'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from extension import shape_builder as sb,curve_geometry as cg
from mathutils import Vector

def clear():
    for o in list(bpy.data.objects):bpy.data.objects.remove(o,do_unlink=True)

def circle(name,x,y,r):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D'
    s=data.splines.new('BEZIER');s.bezier_points.add(3);s.use_cyclic_u=True
    k=4/3*math.tan(math.pi/8)
    for i,p in enumerate(s.bezier_points):
        a=i*math.pi/2;v=Vector((math.cos(a),math.sin(a),0));t=Vector((-math.sin(a),math.cos(a),0))
        p.co=Vector((x,y,0))+r*v;p.handle_left_type='FREE';p.handle_right_type='FREE'
        p.handle_left=p.co-r*k*t;p.handle_right=p.co+r*k*t
    o=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(o);o.select_set(True)
    return o

def curved(data):
    return any((p.handle_right-p.co).cross(s.bezier_points[(i+1)%len(s.bezier_points)].co-p.co).length>1e-4
               for s in data.splines for i,p in enumerate(s.bezier_points))

reports=[]
cp=((0.,0.),(.2,1.8),(2.1,-.3),(2.5,.8))
sub=cg.subcurve(cp,.137,.823)
assert max(math.dist(cg.evaluate(sub,i/20),cg.evaluate(cp,.137+(.823-.137)*i/20)) for i in range(21))<1e-12
reports.append({'case':'de Casteljau subinterval identity','error_below':1e-12})
clear();a=circle('A',-.5,0,1);b=circle('B',.5,0,1)
arr,_=sb.build_pen_arrangement(bpy.context)
assert len(arr['regions'])==3,len(arr['regions'])
union=cg.curve_data(arr,set(range(3)))
assert len(union.splines)==1 and union.splines[0].use_cyclic_u
assert len(union.splines[0].bezier_points)<=10
assert curved(union)
def source_distance(point):
    best=1e10
    for primitive in arr['source_primitives']:
        c=primitive['cp']
        t=min((i/40 for i in range(41)),key=lambda t:math.dist(cg.evaluate(c,t),point))
        for _ in range(12):
            p=cg.evaluate(c,t);d=cg.derivative(c,t)
            dd=tuple(6*((1-t)*(c[2][j]-2*c[1][j]+c[0][j])+t*(c[3][j]-2*c[2][j]+c[1][j])) for j in range(3))
            diff=tuple(p[j]-point[j] for j in range(3))
            den=sum(d[j]*d[j]+diff[j]*dd[j] for j in range(3))
            if abs(den)<1e-12:break
            t=max(0,min(1,t-sum(diff[j]*d[j] for j in range(3))/den))
        best=min(best,math.dist(cg.evaluate(c,t),point))
    return best
deviation=0
for spline in union.splines:
    for i,p in enumerate(spline.bezier_points):
        q=spline.bezier_points[(i+1)%len(spline.bezier_points)]
        cp=[tuple(arr['origin']+arr['u']*v.x+arr['v']*v.y) for v in (p.co,p.handle_right,q.handle_left,q.co)]
        deviation=max(deviation,max(source_distance(cg.evaluate(cp,k/8)) for k in range(9)))
assert deviation<2e-6,deviation
left=sb.region_at_world(arr,Vector((-1,0,0)))
difference=cg.curve_data(arr,{left})
assert len(difference.splines)==1 and curved(difference)
assert len(arr['edge_fragments'])==4,len(arr['edge_fragments'])
trim=cg.curve_data(arr,edge_runs=arr['edge_fragments'][1:])
assert any(not s.use_cyclic_u for s in trim.splines)
reports.append({'case':'overlapping cubic circles','regions':len(arr['regions']),'union_points':len(union.splines[0].bezier_points),'difference_points':len(difference.splines[0].bezier_points),'trim_fragments':len(arr['edge_fragments'])})

clear();circle('Outer',0,0,2);circle('Inner',0,0,1)
arr,_=sb.build_pen_arrangement(bpy.context);ring=sb.region_at_world(arr,Vector((1.5,0,0)))
data=cg.curve_data(arr,{ring});assert len(data.splines)==2 and all(s.use_cyclic_u for s in data.splines)
ring_obj=bpy.data.objects.new('RingResult',data);bpy.context.collection.objects.link(ring_obj)
bpy.context.view_layer.update();evaluated=ring_obj.evaluated_get(bpy.context.evaluated_depsgraph_get());evaluated_mesh=evaluated.to_mesh()
ring_area=sum(p.area for p in evaluated_mesh.polygons);evaluated.to_mesh_clear()
assert abs(ring_area-3*math.pi)<.04,ring_area
reports.append({'case':'nested hole','loops':len(data.splines)})

clear();circle('Left',-2,0,1);circle('Right',2,0,1)
arr,_=sb.build_pen_arrangement(bpy.context);data=cg.curve_data(arr,set(range(len(arr['regions']))))
assert len(data.splines)==2
reports.append({'case':'disconnected regions','loops':2})

clear();data=bpy.data.curves.new('Open','CURVE');data.dimensions='2D';s=data.splines.new('BEZIER');s.bezier_points.add(1)
for p,co,hl,hr in zip(s.bezier_points,[(0,0,0),(2,0,0)],[(0,0,0),(2,1,0)],[(0,1,0),(2,0,0)]):
    p.co=co;p.handle_left_type='FREE';p.handle_right_type='FREE';p.handle_left=hl;p.handle_right=hr
o=bpy.data.objects.new('Open',data);bpy.context.collection.objects.link(o);o.select_set(True)
arr,_=sb.build_pen_arrangement(bpy.context);out=cg.curve_data(arr,edge_runs=arr['edge_fragments'])
assert not out.splines[0].use_cyclic_u and len(out.splines[0].bezier_points)==2
reports.append({'case':'open cubic','retained_control_points':2})

clear();mesh=bpy.data.meshes.new('Square');mesh.from_pydata([(0,0,0),(1,0,0),(1,1,0),(0,1,0)],[(0,1),(1,2),(2,3),(3,0)],[])
o=bpy.data.objects.new('Square',mesh);bpy.context.collection.objects.link(o);o.select_set(True)
arr,_=sb.build_pen_arrangement(bpy.context);out=cg.curve_data(arr,{0})
assert len(out.splines[0].bezier_points)==4
assert not curved(out)
reports.append({'case':'mesh wire square','straight_bezier_points':4})

clear();mesh=bpy.data.meshes.new('SingleLine');mesh.from_pydata([(0,0,0),(2,0,0)],[(0,1)],[])
o=bpy.data.objects.new('SingleLine',mesh);bpy.context.collection.objects.link(o);o.select_set(True)
arr,_=sb.build_pen_arrangement(bpy.context);out=cg.curve_data(arr,edge_runs=arr['edge_fragments'])
assert len(out.splines)==1 and len(out.splines[0].bezier_points)==2
reports.append({'case':'single straight open edge','points':2})

clear();a=circle('TangentA',-1,0,1);circle('TangentB',1,0,1)
arr,_=sb.build_pen_arrangement(bpy.context)
assert len(arr['regions'])==2,len(arr['regions'])
out=cg.curve_data(arr,set(range(2)))
assert len(out.splines)==2,len(out.splines)
reports.append({'case':'endpoint tangent circles','loops':2})

clear();circle('DuplicateA',0,0,1);circle('DuplicateB',0,0,1)
arr,_=sb.build_pen_arrangement(bpy.context);assert len(arr['regions'])==1
out=cg.curve_data(arr,{0});assert len(out.splines)==1
reports.append({'case':'coincident duplicate circles','loops':1})

clear();mesh=bpy.data.meshes.new('CircleMetadata');mesh.from_pydata([(0,1,0),(0,0,1),(0,-1,0),(0,0,-1)],[(0,1),(1,2),(2,3),(3,0)],[])
o=bpy.data.objects.new('CircleMetadata',mesh);bpy.context.collection.objects.link(o);o.select_set(True)
o['harh_circle']=True;o['harh_circle_radius']=1.;o['harh_plane_u']=[0.,1.,0.];o['harh_plane_v']=[0.,0.,1.]
o.location=(2,3,4);o.rotation_euler=(.2,.4,.6);o.scale=(1,2,1)
bpy.context.view_layer.update()
arr,_=sb.build_pen_arrangement(bpy.context);out=cg.curve_data(arr,{0})
assert len(out.splines[0].bezier_points)==4 and curved(out)
assert mesh.vertices[0].co==Vector((0,1,0))
reports.append({'case':'transformed annotated circle','points':4,'source_unchanged':True})

clear();edit_obj=circle('EditCurve',0,0,1);bpy.context.view_layer.objects.active=edit_obj
for p in edit_obj.data.splines[0].bezier_points:p.select_control_point=True
bpy.ops.object.mode_set(mode='EDIT')
arr,_=sb.build_pen_arrangement(bpy.context);assert len(arr['regions'])==1
bpy.ops.object.mode_set(mode='OBJECT')
reports.append({'case':'Curve Edit Mode selected segments','regions':1})

clear()
for quadrant in range(4):
    angle=quadrant*math.pi/2
    for x,y,r in ((0,2.065,.45),(-.3,1.12,.65),(.3,1.12,.65)):
        circle('CuspedFoil',x*math.cos(angle)-y*math.sin(angle),x*math.sin(angle)+y*math.cos(angle),r)
arr,_=sb.build_pen_arrangement(bpy.context);out=cg.curve_data(arr,set(range(len(arr['regions']))))
assert len(out.splines)==1,len(out.splines)
reports.append({'case':'12-circle cusped quatrefoil','regions':len(arr['regions']),'outline_anchors':len(out.splines[0].bezier_points)})

reports.append({'case':'union geometry stays on original cubics','max_deviation':deviation})

(OUTPUT_DIR/'pen_curve_results.json').write_text(json.dumps(reports,indent=2))
print('PEN_CURVE_TESTS_PASS',json.dumps(reports))
