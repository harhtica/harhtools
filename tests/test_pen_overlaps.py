"""Shared baselines and partial Bezier duplicates must remain usable pen paths."""
import bpy,sys,math
from pathlib import Path
from types import SimpleNamespace
from mathutils import Vector,Matrix
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import shape_builder as sb,curve_geometry as cg,outline_tool as ot

def mesh_arch(name,x,reverse=False):
    mesh=bpy.data.meshes.new(name)
    points=[(x+math.cos(math.pi*i/32),math.sin(math.pi*i/32),0) for i in range(33)]
    points[0]=(x+1,0,0);points[-1]=(x-1,0,0)
    if reverse:points.reverse()
    mesh.from_pydata(points,[(i,(i+1)%33) for i in range(33)],[])
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj)
    return obj

def arrangement(objects):
    bpy.context.view_layer.update()
    return sb.build_pen_arrangement(SimpleNamespace(mode='OBJECT',selected_objects=objects))[0]

def native_area(data,arr):
    obj=bpy.data.objects.new('QA output',data);bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.update();evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
    area=sum(p.area for p in mesh.polygons);evaluated.to_mesh_clear();bpy.data.objects.remove(obj,do_unlink=True);bpy.data.curves.remove(data)
    return area

objects=[mesh_arch('Half circle '+str(i),x) for i,x in enumerate((0,1,1.2,1.4,1.6,1.8))]
before=ot.source_signature(objects);arr=arrangement(objects)
assert len(arr['regions'])==21,len(arr['regions'])
assert len(arr['junctions'])==25,len(arr['junctions'])
assert min(r['area'] for r in arr['regions'])>.0001
baseline=[];length=0
for run in arr['edge_fragments']:
    if all(abs(arr['world'][v].z)<1e-6 and abs(arr['world'][v].y)<1e-6 for edge in run for v in edge):
        baseline.append(run);length+=sum((arr['world'][a]-arr['world'][b]).length for a,b in run)
assert abs(length-3.8)<1e-5,length
assert len(baseline)==11,len(baseline)
trimmed=[run for run in arr['edge_fragments'] if run not in baseline]
data=cg.curve_data(arr,edge_runs=trimmed)
assert all(not s.use_cyclic_u for s in data.splines)
assert all((p.handle_right-p.co).length<10 for s in data.splines for p in s.bezier_points)
assert len(data.splines)==6,len(data.splines)
bpy.data.curves.remove(data)
union=cg.curve_data(arr,set(range(len(arr['regions']))))
area=native_area(union,arr);expected=sum(r['area'] for r in arr['regions'])
assert abs(area-expected)/expected<1e-5,(area,expected)
# A full reversed duplicate must not add cells, edges or duplicate baseline.
duplicate=mesh_arch('Reverse duplicate',1.2,reverse=True)
again=arrangement(objects+[duplicate])
assert len(again['regions'])==len(arr['regions'])
assert len(again['constraint_edges'])==len(arr['constraint_edges'])
# Tiny, translated and rotated construction from the reported workflow.
transform=Matrix.Translation((.18,18,-23))@Matrix.Rotation(math.pi/2,4,'Y')@Matrix.Scale(.01,4)
for obj in objects:obj.matrix_world=transform
tiny=arrangement(objects);assert len(tiny['regions'])==21
assert abs(sum(r['area'] for r in tiny['regions'])/expected-.0001)<1e-8
for obj in objects:obj.matrix_world=Matrix.Identity(4)
bpy.context.view_layer.update();assert ot.source_signature(objects)==before

def cubic(name,cp):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D'
    s=data.splines.new('BEZIER');s.bezier_points.add(1)
    a,b=s.bezier_points
    for p in s.bezier_points:p.handle_left_type=p.handle_right_type='FREE'
    a.co=cp[0];a.handle_left=cp[0];a.handle_right=cp[1]
    b.co=cp[3];b.handle_left=cp[2];b.handle_right=cp[3]
    obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj);return obj

cp=((0.,0.,0.),(.2,1.8,0.),(2.1,-.3,0.),(2.5,.8,0.))
portions=[cubic('First',cg.subcurve(cp,0,.7)),cubic('Reversed last',cg.subcurve(cp,1,.3)),
          cubic('Middle',cg.subcurve(cp,.2,.8))]
before=ot.source_signature(portions);partial=arrangement(portions)
assert not partial['regions'] and len(partial['edge_fragments'])==1
data=cg.curve_data(partial,edge_runs=partial['edge_fragments'])
assert len(data.splines)==1 and not data.splines[0].use_cyclic_u
# Retained output lies on the original curve, not an interpolated sliver boundary.
for spline in data.splines:
    for a,b in zip(spline.bezier_points,spline.bezier_points[1:]):
        controls=[tuple(partial['origin']+partial['u']*p.x+partial['v']*p.y) for p in (a.co,a.handle_right,b.handle_left,b.co)]
        for k in range(11):
            point=cg.evaluate(controls,k/10);t=cg.nearest_parameter([p[:2] for p in cp],point[:2])
            assert math.dist(point,cg.evaluate(cp,t))<2e-6
bpy.data.curves.remove(data);assert ot.source_signature(portions)==before
# A third wire crosses the shared interval and must still split it once.
middle=cg.evaluate(cp,.5);cross=cubic('Crossing',cg.line((middle[0],-1,0),(middle[0],2,0)))
crossed=arrangement(portions+[cross])
assert len(crossed['junctions'])==1 and len(crossed['edge_fragments'])==4
assert not crossed['regions']
# Collinear handles can have different speeds, including zero endpoint tangents.
lines=[cubic('Line',cg.line((0,0,0),(3,0,0))),cubic('Slow line',((1,0,0),(1,0,0),(4,0,0),(4,0,0)))]
linear=arrangement(lines)
assert not linear['regions'] and len(linear['edge_fragments'])==1
assert abs(sum((linear['world'][a]-linear['world'][b]).length for a,b in linear['constraint_edges'])-4)<1e-5
print('PEN_OVERLAPS_PASS: six overlapping closed semicircles, 21 regions, unique baseline, six trimmed arcs, native union area, duplicates, transformed tiny guides, partial/reversed cubics, crossing and nonuniform line handles')
