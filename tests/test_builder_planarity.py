"""Small translated circles remain planar; real depth is still rejected."""
import bpy,sys,math
from pathlib import Path
from mathutils import Matrix,Euler,Vector
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import shape_builder as sb,curve_geometry as cg
for obj in bpy.context.selected_objects:obj.select_set(False)
objects=[]
for j,offset in enumerate((0,-.01,-.012,-.014,-.016,-.018)):
    mesh=bpy.data.meshes.new('Translated circle')
    coords=[(.01*math.cos(math.tau*i/64),.01*math.sin(math.tau*i/64),0) for i in range(64)]
    mesh.from_pydata(coords,[(i,(i+1)%64) for i in range(64)],[])
    obj=bpy.data.objects.new('Translated circle',mesh);bpy.context.collection.objects.link(obj)
    obj.location=(.18,18+offset,-23);obj.select_set(True);objects.append(obj)
bpy.context.view_layer.objects.active=objects[0];bpy.context.view_layer.update()
before=[tuple(tuple(v.co) for v in obj.data.vertices) for obj in objects]
primitives,_=cg.collect(bpy.context);points=[p for s in primitives for p in s['cp']]
basis=sb.planar_basis(points);assert abs(basis[3].z)> .999999
arr,names=sb.build_pen_arrangement(bpy.context);assert arr['regions'] and len(names)==6
assert before==[tuple(tuple(v.co) for v in obj.data.vertices) for obj in objects]
transform=Matrix.Translation((1234.5,-987.65,456.789))@Euler((.7,-.4,.9)).to_matrix().to_4x4()
for i,obj in enumerate(objects):
    for vertex in obj.data.vertices:vertex.co.x+=i*.005
    obj.matrix_world=transform
bpy.context.view_layer.update();primitives,_=cg.collect(bpy.context)
sb.planar_basis([p for s in primitives for p in s['cp']])
objects[-1].data.vertices[0].co.z=.001
bpy.context.view_layer.update();primitives,_=cg.collect(bpy.context)
try:sb.planar_basis([p for s in primitives for p in s['cp']])
except ValueError as exc:assert 'flat plane' in str(exc)
else:raise AssertionError('Actual depth must not be projected away')
print('BUILDER_PLANARITY_PASS: six saved-style 64-vertex circles, actual regions, distant tilted world transforms, source preservation and real-depth rejection')
