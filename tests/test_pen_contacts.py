"""Regression checks for partial overlaps and non-knot tangent contacts."""
import bpy,sys,json,math
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / '_artifacts'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import shape_builder as sb,curve_geometry as cg
from mathutils import Matrix,Vector

def clear():
    for o in list(bpy.data.objects):bpy.data.objects.remove(o,do_unlink=True)

def cubic(name,cp):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D'
    s=data.splines.new('BEZIER');s.bezier_points.add(1)
    a,b=s.bezier_points
    for p in s.bezier_points:p.handle_left_type=p.handle_right_type='FREE'
    a.co=cp[0];a.handle_left=cp[0];a.handle_right=cp[1]
    b.co=cp[3];b.handle_left=cp[2];b.handle_right=cp[3]
    o=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(o);o.select_set(True)
    return o

reports=[]
clear();cp=((0.,0.,0.),(.2,1.8,0.),(2.1,-.3,0.),(2.5,.8,0.))
cubic('Full',cp);cubic('Partial',cg.subcurve(cp,.2,.8))
try:sb.build_pen_arrangement(bpy.context)
except ValueError as e:
    assert 'overlap along only part' in str(e),str(e)
    reports.append({'case':'partial coincident cubic','safe_rejection':True,'objects_unchanged':len(bpy.data.objects)==2})
else:raise AssertionError('Partial overlap must fail safely before sliver regions are created.')

clear();cubic('First portion',cg.subcurve(cp,0,.7));cubic('Last portion',cg.subcurve(cp,.3,1))
try:sb.build_pen_arrangement(bpy.context)
except ValueError as e:
    assert 'overlap along only part' in str(e),str(e)
    reports.append({'case':'two overlapping partial cubics','safe_rejection':True})
else:raise AssertionError('Partial overlap must fail safely.')

clear();cubic('Parabola',((0.,.1369,0.),(1/3,.1369-.74/3,0.),(2/3,.1369-2*.74/3+1/3,0.),(1.,.3969,0.)))
cubic('Tangent',cg.line((-1.,0.,0.),(2.,0.,0.)))
arr,_=sb.build_pen_arrangement(bpy.context)
assert len(arr['junctions'])==1,len(arr['junctions'])
assert len(arr['edge_fragments'])==4,len(arr['edge_fragments'])
assert len(arr['regions'])==0,len(arr['regions'])
reports.append({'case':'interior cubic-line tangency t=.37','junctions':1,'fragments':4,'false_regions':0})

clear();upper=((0.,.1369,0.),(1/3,.1369-.74/3,0.),(2/3,.1369-2*.74/3+1/3,0.),(1.,.3969,0.))
cubic('Upper',upper);cubic('Lower',tuple((x,-y,z) for x,y,z in upper))
arr,_=sb.build_pen_arrangement(bpy.context)
assert len(arr['junctions'])==1,len(arr['junctions'])
assert len(arr['edge_fragments'])==4,len(arr['edge_fragments'])
assert len(arr['regions'])==0,len(arr['regions'])
reports.append({'case':'interior cubic-cubic tangency t=.37','junctions':1,'fragments':4,'false_regions':0})

cubic('Independent nearby crossing',cg.line((.3703,-1.,0.),(.3703,1.,0.)))
primitives,_=cg.collect(bpy.context)
basis=sb.planar_basis([Vector(p) for s in primitives for p in s['cp']])
_,_,spans=cg.prepare(primitives,basis)
upper_index=next(i for i,s in enumerate(primitives) if s['source']=='Upper')
parameters={t for k,a,b in spans if k==upper_index for t in (a,b)}
crossing_error=min(abs(t-.3703) for t in parameters)
assert crossing_error<1e-6,crossing_error
assert min(abs(t-.37) for t in parameters)<1e-6
reports.append({'case':'third-curve crossing next to tangent','crossing_parameter_error':crossing_error,'both_cuts_retained':True})

clear();k=4/3*math.tan(math.pi/8)
quarter=((1.,0.,0.),(1.,k,0.),(k,1.,0.),(0.,1.,0.))
contact=Vector(cg.evaluate(quarter,.37))
def bezier_circle(name,reflected=False):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D';s=data.splines.new('BEZIER');s.bezier_points.add(3);s.use_cyclic_u=True
    for index,p in enumerate(s.bezier_points):
        angle=index*math.pi/2;co=Vector((math.cos(angle),math.sin(angle),0));d=Vector((-math.sin(angle),math.cos(angle),0))*k
        pts=(co,co-d,co+d)
        if reflected:pts=tuple(2*contact-q for q in pts)
        p.co,p.handle_left,p.handle_right=pts;p.handle_left_type=p.handle_right_type='FREE'
    o=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(o);o.select_set(True)
    o.matrix_world=Matrix.Translation((2.3,-1.5,4.1))@Matrix.Rotation(.731,4,'Z')@Matrix.Rotation(.463,4,'Y')@Matrix.Diagonal((1.7,.8,1.,1.))
bezier_circle('OffKnotCircleA');bezier_circle('OffKnotCircleB',True)
bpy.context.view_layer.update();arr,_=sb.build_pen_arrangement(bpy.context)
assert len(arr['junctions'])==1,len(arr['junctions'])
assert len(arr['regions'])==2,len(arr['regions'])
out=cg.curve_data(arr,{0,1});assert len(out.splines)==2,len(out.splines)
reports.append({'case':'rotated scaled cubic circles tangent off-knot','junctions':1,'regions':2,'output_loops':2})

(OUTPUT_DIR/'pen_contacts_results.json').write_text(json.dumps(reports,indent=2))
print('PEN_CONTACT_TESTS_PASS',json.dumps(reports))
