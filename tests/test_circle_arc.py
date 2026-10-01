"""Recoverable native circle/arc sliders, resolution, counts and snapping."""
import bpy,sys,math,json
from pathlib import Path
from mathutils import Euler,Matrix,Vector
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import circle_arc as ca,curve_geometry as cg
ca.register()
try:
    mesh=bpy.data.meshes.new('Circle');coords=[(2*math.cos(math.tau*i/64),2*math.sin(math.tau*i/64),0) for i in range(64)]
    mesh.from_pydata(coords,[(i,(i+1)%64) for i in range(64)],[])
    obj=bpy.data.objects.new('Circle',mesh);bpy.context.collection.objects.link(obj)
    other=bpy.data.objects.new('Linked original',mesh);bpy.context.collection.objects.link(other)
    for selected in bpy.context.selected_objects:selected.select_set(False)
    obj.select_set(True);bpy.context.view_layer.objects.active=obj
    obj.matrix_world=Matrix.Translation((.18,18,-23))@Euler((.7,.8,.9)).to_matrix().to_4x4()
    bpy.context.view_layer.update();matrix=obj.matrix_world.copy();original=[tuple(v.co) for v in mesh.vertices]
    assert bpy.ops.object.harhtools_edit_circle()=={'FINISHED'}
    cfg=obj.harhtools_circle_arc
    assert cfg.active and cfg.segments==64 and cfg.source_mesh==mesh and obj.data!=mesh
    cfg.arc_amount=math.pi/2
    assert len(obj.data.vertices)==17 and len(obj.data.edges)==16 and not cfg.error
    assert [tuple(v.co) for v in mesh.vertices]==original and other.data==mesh and obj.matrix_world==matrix
    middle=[tuple(v.co) for v in obj.data.vertices][1:-1]
    assert all(p in original for p in middle),'Uncut source samples must remain exact for snapping'
    cfg.start_angle=math.radians(17);cfg.arc_amount=math.radians(93)
    assert all(p in original for p in [tuple(v.co) for v in obj.data.vertices][1:-1])
    cfg.arc_amount=math.tau
    assert set(tuple(v.co) for v in obj.data.vertices)==set(original)
    cfg.segments=3;cfg.fill=True
    assert len(obj.data.vertices)==3 and len(obj.data.polygons)==1
    obj.data.calc_loop_triangles();assert len(obj.data.loop_triangles)==1
    cfg.segments=96
    assert len(obj.data.vertices)==96
    obj.data.calc_loop_triangles();assert len(obj.data.loop_triangles)==94
    cfg.fill=False;cfg.start_angle=0;cfg.arc_amount=math.pi/3
    assert len(obj.data.vertices)==17 and len(obj.data.edges)==16
    count=len(bpy.data.meshes)
    for n in range(3,140):cfg.segments=n
    assert len(bpy.data.meshes)==count,'Slider must not leave obsolete generated datablocks'
    ca.unregister();ca.register();cfg=obj.harhtools_circle_arc
    assert cfg.active and cfg.source_mesh==mesh and cfg.segments==139,'Controls and original must survive code reload'
    assert bpy.ops.object.harhtools_restore_circle()=={'FINISHED'}
    assert obj.data==mesh and not cfg.active and other.data==mesh
    assert [tuple(v.co) for v in mesh.vertices]==original
    curve=bpy.data.curves.new('Bezier circle','CURVE');curve.dimensions='2D';curve.resolution_u=16
    s=curve.splines.new('BEZIER');s.bezier_points.add(3);s.use_cyclic_u=True;k=4/3*math.tan(math.pi/8)
    for i,p in enumerate(s.bezier_points):
        t=math.pi/2*i;v=Vector((math.cos(t),math.sin(t),0));tangent=Vector((-math.sin(t),math.cos(t),0))
        p.co=v;p.handle_left_type='FREE';p.handle_right_type='FREE';p.handle_left=v-k*tangent;p.handle_right=v+k*tangent
    co=bpy.data.objects.new('Bezier circle',curve);bpy.context.collection.objects.link(co);bpy.context.view_layer.objects.active=co
    assert bpy.ops.object.harhtools_edit_circle()=={'FINISHED'}
    co.harhtools_circle_arc.arc_amount=math.pi;co.harhtools_circle_arc.fill=False
    assert co.data.splines[0].type=='POLY' and len(co.data.splines[0].points)==33
    assert bpy.ops.object.harhtools_restore_circle()=={'FINISHED'} and co.data==curve and curve.splines[0].type=='BEZIER'
    mesh.vertices[2].co.x+=.5
    try:ca.definition(obj)
    except ValueError:pass
    else:raise AssertionError('Noncircular edited shape must not be coerced')
    print('CIRCLE_ARC_PASS: live RNA, 64/96 grids, exact retained samples, triangle/face counts, transforms, linked data, reload, original restore and Bezier support')
finally:ca.unregister()
