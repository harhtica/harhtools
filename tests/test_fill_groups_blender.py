"""Real three-circle regions: group ownership, outputs, and shared seams."""
import bpy,sys,math,json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / '_artifacts'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import fill_groups as fg,shape_builder as sb,curve_geometry as cg,shape_library

for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)

def circle(name,x,y,r):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D'
    spline=data.splines.new('BEZIER');spline.bezier_points.add(3);spline.use_cyclic_u=True
    k=4/3*math.tan(math.pi/8)
    for i,p in enumerate(spline.bezier_points):
        angle=i*math.pi/2;radial=Vector((math.cos(angle),math.sin(angle),0));tangent=Vector((-math.sin(angle),math.cos(angle),0))
        p.co=Vector((x,y,0))+r*radial;p.handle_left_type=p.handle_right_type='FREE'
        p.handle_left=p.co-r*k*tangent;p.handle_right=p.co+r*k*tangent
    obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj);obj.select_set(True)

circle('Cap',0,2.065,.45);circle('Left shoulder',-.3,1.12,.65);circle('Right shoulder',.3,1.12,.65)
arr,_=sb.build_pen_arrangement(bpy.context)
assert len(arr['regions'])>=6,len(arr['regions'])
adjacent=None
for edge,triangles in arr['edge_faces'].items():
    owners={arr['tri_region'][t] for t in triangles}-{ -1 }
    if len(owners)==2:adjacent=sorted(owners);break
assert adjacent is not None
a,b=adjacent;c=next(r for r in range(len(arr['regions'])) if r not in adjacent)

def output_objects(groups,name):
    original_capture=shape_library.capture_created_shape
    def prohibited_capture(*args,**kwargs):raise AssertionError('Fill confirmation must not auto-save a library preset.')
    shape_library.capture_created_shape=prohibited_capture
    try:result=sb.commit_fill_groups(bpy.context,arr,groups)
    finally:shape_library.capture_created_shape=original_capture
    for index,obj in enumerate(result):obj.name=f'{name}_{index+1}'
    assert all(obj.select_get() for obj in result)
    return result

reports=[]
separate=fg.gesture_groups(fg.gesture_groups([],[a]),[b])
objects=output_objects(separate,'SeparateClicks')
assert len(objects)==2 and all(o.type=='CURVE' for o in objects)
reports.append({'case':'separate clicks on adjacent cells','fill_groups':len(separate),'output_objects':len(objects)})

outlines=fg.boundary_edges_for_groups(arr,separate)
keys=lambda edges:{tuple(sorted(e)) for e in edges}
shared=keys(outlines[0])&keys(outlines[1]);assert shared
merged=fg.gesture_groups([],[a,b]);objects=output_objects(merged,'OneDrag')
assert len(objects)==1 and len(objects[0].data.splines)==1
assert not shared.intersection(keys(fg.boundary_edges_for_groups(arr,merged)[0]))
reports.append({'case':'one drag across same cells','fill_groups':1,'output_objects':1,'interior_seam_removed':True})

three=[{a},{b},{c}];snapshot=fg.snapshot_groups(three)
bridge=fg.gesture_groups(snapshot,[a,b]);objects=output_objects(bridge,'Bridge')
assert bridge==[{a,b},{c}] and len(objects)==2
assert keys(fg.boundary_edges_for_groups(arr,bridge)[1])==keys(fg.boundary_edges_for_groups(arr,[{c}])[0])
assert fg.restore_groups(snapshot)==three
reports.append({'case':'drag merges touched fills, leaves third untouched','output_objects':2,'unrelated_boundary_unchanged':True,'undo_restores_three_groups':True})

assert fg.gesture_groups(bridge,[a])==bridge
assert fg.group_for_region(bridge,b)=={a,b}
erased=fg.gesture_groups(bridge,[b],erase=True,neighbors=fg.region_neighbors(arr))
assert erased==[{a},{c}]
assert fg.group_for_region(bridge,b,erase=True)=={b}
objects=output_objects(erased,'RemovedSection')
assert len(objects)==2
assert keys(fg.boundary_edges_for_groups(arr,[{a}])[0])==keys(fg.boundary_edges_for_groups(arr,erased)[0])
assert fg.gesture_groups([], [a],erase=True)==[]
reports.append({'case':'erase cuts only the hit region out of a merged fill','erase_result_groups':2,'initial_erase_stays_empty':True})
reports.append({'case':'real grouped commit selects every output and never auto-saves library presets','passed':True})

(OUTPUT_DIR/'fill_groups_blender_results.json').write_text(json.dumps({'source':'Actual cap and two shoulder Bezier circles','regions':len(arr['regions']),'checks':reports},indent=2))
print('FILL_GROUPS_BLENDER_PASS',json.dumps(reports))
