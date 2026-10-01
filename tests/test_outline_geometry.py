"""Headless width/topology/source-preservation tests for Make Outline."""
import sys,math,time,json
from pathlib import Path
import bpy
from mathutils import Vector,Matrix,Euler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from extension import outline_geometry as og
from extension import curve_geometry as cg

REPORTS=[]

def poly(name,loops,matrix=None,mesh=False):
    if mesh:
        data=bpy.data.meshes.new(name);verts=[];edges=[]
        for loop in loops:
            base=len(verts);verts.extend((x,y,0) for x,y in loop)
            edges.extend((base+i,base+(i+1)%len(loop)) for i in range(len(loop)))
        data.from_pydata(verts,edges,[])
    else:
        data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D'
        for loop in loops:
            s=data.splines.new('POLY');s.points.add(len(loop)-1);s.use_cyclic_u=True
            for p,(x,y) in zip(s.points,loop):p.co=(x,y,0,1)
    obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj)
    if matrix is not None:obj.matrix_world=matrix
    return obj

def circle(name,r=1,matrix=None):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D'
    spline=data.splines.new('BEZIER');spline.bezier_points.add(3);spline.use_cyclic_u=True
    k=4/3*math.tan(math.pi/8)
    for i,p in enumerate(spline.bezier_points):
        a=i*math.pi/2;v=Vector((math.cos(a),math.sin(a),0));t=Vector((-math.sin(a),math.cos(a),0))
        p.co=r*v;p.handle_left_type='FREE';p.handle_right_type='FREE'
        p.handle_left=p.co-r*k*t;p.handle_right=p.co+r*k*t
    obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj)
    if matrix is not None:obj.matrix_world=matrix
    return obj

def evaluated_area(result):
    obj=bpy.data.objects.new('Test outline',og.make_curve_data(result));bpy.context.collection.objects.link(obj)
    obj.matrix_world=result['matrix_world'];bpy.context.view_layer.update()
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
    area=sum(p.area for p in mesh.polygons);evaluated.to_mesh_clear()
    return area

def rejects(callback,fragment=None):
    try:callback()
    except ValueError as exc:
        if fragment:assert fragment.lower() in str(exc).lower(),str(exc)
        return str(exc)
    raise AssertionError('Expected safe rejection')

def check_width(prepared,result,width,limit=1e-6):
    # For regular shape offsets, each output sample is width away from the
    # nearest original edge. Convex closing-corner miters are excluded here.
    source_edges=[(a,b) for loop in prepared['loops'] for a,b in zip(loop,loop[1:]+loop[:1])]
    deviations=[]
    for loop in result['offset_loops']:
        for a,b in zip(loop,loop[1:]+loop[:1]):
            p=((a[0]+b[0])*.5,(a[1]+b[1])*.5)
            dist=math.sqrt(min(og._point_segment_sq(p,c,d) for c,d in source_edges))
            deviations.append(abs(dist-width))
    assert max(deviations)<limit,(max(deviations),limit)
    return max(deviations)

square=[(-2,-2),(2,-2),(2,2),(-2,2)]
obj=poly('Square',[square]);prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.25)
assert len(result['border_loops'])==2
assert abs(abs(og._area(result['offset_loops'][0]))-3.5**2)<1e-5
assert abs(evaluated_area(result)-(16-3.5**2))<1e-5
check_width(prepared,result,.25)
REPORTS.append({'case':'square exact inward width and evaluated ring area','points':result['diagnostics']['poly_points']})

result=og.build_outline(prepared,.25,direction='OUTWARD')
assert abs(evaluated_area(result)-(16*.25+math.pi*.25**2))<3e-5
check_width(prepared,result,.25,prepared['tolerance']*1.1)
REPORTS.append({'case':'square outward rounded joins','points':result['diagnostics']['poly_points']})

obj=circle('Circle');snapshot=[tuple(v) for p in obj.data.splines[0].bezier_points for v in (p.co,p.handle_left,p.handle_right)]
t0=time.perf_counter();prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.1);duration=time.perf_counter()-t0
err=check_width(prepared,result,.1,prepared['tolerance']*1.1)
assert len(prepared['world_segments'])==4 and all(s['kind']=='BEZIER' for s in prepared['world_segments'])
assert snapshot==[tuple(v) for p in obj.data.splines[0].bezier_points for v in (p.co,p.handle_left,p.handle_right)]
assert abs(evaluated_area(result)-math.pi*(1-.9**2))<.001
REPORTS.append({'case':'Bezier circle sampled offset','max_chord_width_error':err,'seconds':duration,'points':result['diagnostics']['poly_points']})

obj=poly('Concave L',[[(0,0),(3,0),(3,1),(1,1),(1,3),(0,3)]])
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.15)
err=check_width(prepared,result,.15,prepared['tolerance']*1.1)
assert evaluated_area(result)>0
REPORTS.append({'case':'concave L rounded interior corner','max_width_error':err})

obj=poly('Hole',[square,[(-1,-1),(1,-1),(1,1),(-1,1)]])
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.2)
assert prepared['depths']==[0,1]
assert len(result['border_loops'])==4
expected=(16-3.6**2)+(8*.2+math.pi*.2**2)
assert abs(evaluated_area(result)-expected)<5e-5,(evaluated_area(result),expected)
REPORTS.append({'case':'hole border and evaluated fill remains empty','area':evaluated_area(result)})

transform=Matrix.Translation((2,5,9))@Euler((.53,.25,.74)).to_matrix().to_4x4()@Matrix.Diagonal((2.0,.75,1,1))
obj=poly('Transformed mesh',[square],transform,mesh=True)
bpy.context.view_layer.update()
matrix_before=obj.matrix_world.copy();coords_before=[tuple(v.co) for v in obj.data.vertices]
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.25)
assert abs(evaluated_area(result)-(8*3-7.5*2.5))<2e-5
check_width(prepared,result,.25,1e-6)
assert obj.matrix_world==matrix_before and coords_before==[tuple(v.co) for v in obj.data.vertices]
assert abs(result['matrix_world'].to_3x3().determinant()-1)<1e-6
REPORTS.append({'case':'rotated nonuniform mesh scale uses uniform world-unit width'})

for name,loops,width in [('square collapse',[square],2.1),('narrow concave feature',[[(0,0),(3,0),(3,.2),(1,.2),(1,3),(0,3)]],.15),('hole collision',[square,[(-1.8,-1.8),(1.8,-1.8),(1.8,1.8),(-1.8,1.8)]],.15)]:
    prepared=og.prepare_sources([poly(name,loops)])
    message=rejects(lambda:og.build_outline(prepared,width))
    REPORTS.append({'case':name,'rejected':message})

rejects(lambda:og.prepare_sources([poly('Bow tie',[[(0,0),(2,2),(0,2),(2,0)]])]))
open_obj=poly('Open',[square]);open_obj.data.splines[0].use_cyclic_u=False
rejects(lambda:og.prepare_sources([open_obj]),'close')
nonplanar=poly('Nonplanar',[square],mesh=True);nonplanar.data.vertices[0].co.z=.1
rejects(lambda:og.prepare_sources([nonplanar]),'plane')
REPORTS.append({'case':'open, self-intersecting, and nonplanar sources rejected'})

# Subdivision bound is tested against the actual input cubic, not a true circle:
# Blender's four-cubic circle is itself only an approximation to a circle.
obj=circle('Bound check');prepared=og.prepare_sources([obj]);edges=[(a,b) for loop in prepared['loops'] for a,b in zip(loop,loop[1:]+loop[:1])]
worst=0
for segment in prepared['world_segments']:
    for i in range(301):
        point=Vector(cg.evaluate(segment['cp'],i/300))-prepared['origin'];p=(point.dot(prepared['u']),point.dot(prepared['v']))
        worst=max(worst,math.sqrt(min(og._point_segment_sq(p,a,b) for a,b in edges)))
assert worst<prepared['tolerance']*1.02,(worst,prepared['tolerance'])
REPORTS.append({'case':'input cubic sampling bound','measured_error':worst,'bound':prepared['tolerance']})

# Two round lobes meeting at genuine concave cusps, built from circular cubic
# spans. Output must stay a valid single inner boundary at the cusp joins.
data=bpy.data.curves.new('Cusped lobes','CURVE');data.dimensions='2D'
arcs=[];theta=math.acos(.6)
for cx,start,end in [(-.6,theta,math.tau-theta),(.6,math.pi+theta,3*math.pi-theta)]:
    count=math.ceil((end-start)/(math.pi/2))
    for i in range(count):
        a=start+(end-start)*i/count;b=start+(end-start)*(i+1)/count;k=4/3*math.tan((b-a)/4)
        p=Vector((cx+math.cos(a),math.sin(a),0));q=Vector((cx+math.cos(b),math.sin(b),0))
        ta=Vector((-math.sin(a),math.cos(a),0));tb=Vector((-math.sin(b),math.cos(b),0))
        arcs.append((p,p+k*ta,q-k*tb,q))
spline=data.splines.new('BEZIER');spline.bezier_points.add(len(arcs)-1);spline.use_cyclic_u=True
for i,p in enumerate(spline.bezier_points):
    p.handle_left_type='FREE';p.handle_right_type='FREE';p.co=arcs[i][0]
    p.handle_right=arcs[i][1];p.handle_left=arcs[i-1][2]
obj=bpy.data.objects.new('Cusped lobes',data);bpy.context.collection.objects.link(obj)
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.08)
assert len(result['offset_loops'])==1 and evaluated_area(result)>0
check_width(prepared,result,.08,prepared['tolerance']*1.1)
REPORTS.append({'case':'circular cubic lobes with concave cusps','points':result['diagnostics']['poly_points']})

obj=poly('Islands',[[(-3,-1),(-1,-1),(-1,1),(-3,1)],[(1,-1),(3,-1),(3,1),(1,1)]])
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.15)
assert len(result['border_loops'])==4 and abs(evaluated_area(result)-2*(4-1.7**2))<1e-5
REPORTS.append({'case':'separate islands remain separate'})

obj=poly('Outward hole',[square,[(-1,-1),(1,-1),(1,1),(-1,1)]])
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.2,direction='OUTWARD')
assert len(result['border_loops'])==4
assert abs(evaluated_area(result)-(16*.2+math.pi*.2**2+4-1.6**2))<5e-5
REPORTS.append({'case':'outward outline respects hole clearance and evaluated fill'})

obj=circle('Transformed Bezier ellipse',matrix=transform);bpy.context.view_layer.update()
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.12)
check_width(prepared,result,.12,prepared['tolerance']*1.1)
assert abs(prepared['normal'].dot(Vector((transform.to_3x3().inverted().transposed()@Vector((0,0,1))).normalized())))>1-1e-6
REPORTS.append({'case':'rotated nonuniform Bezier scale uses uniform world-unit width'})

arch_spans=[cg.line((-1,0,0),(1,0,0)),cg.line((1,0,0),(1,1,0))]
for cx,a,b in [(-1,0,math.pi/3),(1,2*math.pi/3,math.pi)]:
    k=4/3*math.tan((b-a)/4)
    p=(cx+2*math.cos(a),1+2*math.sin(a),0);q=(cx+2*math.cos(b),1+2*math.sin(b),0)
    arch_spans.append((p,(p[0]-2*k*math.sin(a),p[1]+2*k*math.cos(a),0),
                       (q[0]+2*k*math.sin(b),q[1]-2*k*math.cos(b),0),q))
arch_spans.append(cg.line((-1,1,0),(-1,0,0)))
data=bpy.data.curves.new('Pointed arch','CURVE');data.dimensions='2D'
spline=data.splines.new('BEZIER');spline.bezier_points.add(len(arch_spans)-1);spline.use_cyclic_u=True
for i,p in enumerate(spline.bezier_points):
    p.handle_left_type='FREE';p.handle_right_type='FREE';p.co=arch_spans[i][0]
    p.handle_right=arch_spans[i][1];p.handle_left=arch_spans[i-1][2]
obj=bpy.data.objects.new('Pointed arch',data);bpy.context.collection.objects.link(obj)
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.05)
assert result['diagnostics']['trimmed_offset_intersections']==1
assert len(result['offset_loops'])==1 and evaluated_area(result)>0
check_width(prepared,result,.05,prepared['tolerance']*1.1)
REPORTS.append({'case':'pointed arch dense arc offsets trim cleanly at convex apex'})

directory=Path(__file__).parent/'_artifacts';directory.mkdir(exist_ok=True)
(directory/'outline_geometry_report.json').write_text(json.dumps(REPORTS,indent=2))
print(json.dumps(REPORTS,indent=2));print('PASS Make Outline geometry',len(REPORTS),'checks')
