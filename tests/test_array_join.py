"""Joined arrays preserve evaluated geometry/UVs and use the rotation pivot."""
import math
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch, Mock
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extension import array_core as core


def clear():
    for obj in list(bpy.data.objects):bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if not mesh.users:bpy.data.meshes.remove(mesh)


def select(objects, active=None):
    for obj in bpy.context.selected_objects:obj.select_set(False)
    for obj in objects:obj.select_set(True)
    bpy.context.view_layer.objects.active=active or objects[0]
    bpy.context.view_layer.update()


def plane(name, location=(0,0,0)):
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)],[],[(0,1,2),(0,2,3)])
    uv=mesh.uv_layers.new(name='Atlas UV')
    for loop in mesh.loops:
        p=mesh.vertices[loop.vertex_index].co
        uv.data[loop.index].uv=(p.x*.1+.4,p.y*.1+.7)
    for i in range(2):mesh.materials.append(bpy.data.materials.new(name+str(i)))
    mesh.polygons[1].material_index=1
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj)
    obj.location=location;select([obj]);return obj


def cfg(**values):
    result=dict(mode='LINEAR',orientation='WORLD',axes='X',count=3,gap=.7,fit_length=False,
                pivot='CURSOR',radial_axis='Z',radius=3,sweep=math.tau,rotate_copies=True,fit_ring=False)
    result.update(values);return NS(**result)


def signature(objects, transforms=(Matrix.Identity(4),)):
    dg=bpy.context.evaluated_depsgraph_get();vertices=[];faces=[]
    for obj in objects:
        evaluated=obj.evaluated_get(dg);mesh=evaluated.to_mesh()
        try:
            for transform in transforms:
                matrix=transform@evaluated.matrix_world
                vertices.extend(tuple(round(v,5) for v in matrix@p.co) for p in mesh.vertices)
                for face in mesh.polygons:
                    uv=mesh.uv_layers.active
                    material=evaluated.material_slots[face.material_index].material if evaluated.material_slots else None
                    corners=sorted((tuple(round(v,5) for v in matrix@mesh.vertices[mesh.loops[i].vertex_index].co),
                                    tuple(round(v,6) for v in uv.data[i].uv) if uv else ()) for i in face.loop_indices)
                    faces.append((material.original.name if material else '',tuple(corners)))
        finally:evaluated.to_mesh_clear()
    return sorted(vertices),sorted(faces)


clear()
source=plane('Source',(2,3,1));source.scale=(-1.3,.8,1)
solid=source.modifiers.new('Visible depth','SOLIDIFY');solid.thickness=.15
override=bpy.data.materials.new('Object override')
source.material_slots[1].link='OBJECT';source.material_slots[1].material=override
select([source])
snap=core.snapshot(bpy.context);plan=core.build_plan(snap,cfg(),bpy.context.scene)
expected=signature([source],(Matrix.Identity(4),*plan.transforms))
origin=source.matrix_world.translation.copy()
result=core.commit(bpy.context,snap,plan,join_generated=True)
assert len(result)==1 and len(bpy.data.objects)==1 and result[0].type=='MESH'
actual=signature(result)
if actual!=expected:
    print('VERTEX_DIFF',set(actual[0])-set(expected[0]),set(expected[0])-set(actual[0]))
    print('FACE_DIFF',list(set(actual[1])-set(expected[1]))[:3],list(set(expected[1])-set(actual[1]))[:3])
assert actual==expected,'Joined mesh changed geometry, UVs or material assignments'
assert not result[0].modifiers and (result[0].matrix_world.translation-origin).length<1e-6
assert bpy.context.view_layer.objects.active==result[0] and list(bpy.context.selected_objects)==result
print('PASS joined linear evaluated modifiers, negative scale, multi-material and atlas UV preservation')

clear()
source=plane('Radial',(4,0,2))
bpy.context.scene.cursor.location=(1,-1,2)
snap=core.snapshot(bpy.context);plan=core.build_plan(snap,cfg(mode='CIRCULAR',count=5),bpy.context.scene)
expected=signature([source],(Matrix.Identity(4),*plan.transforms))
result=core.commit(bpy.context,snap,plan,linked=True,join_generated=True)
assert len(bpy.data.objects)==1 and len(result[0].data.vertices)==24
assert signature(result)==expected
assert (result[0].matrix_world.translation-bpy.context.scene.cursor.location).length<1e-7
print('PASS circular original plus five copies and exact cursor pivot')

clear()
source=plane('Fit source')
reference=plane('Bookend',(10,0,0));select([source,reference],source)
snap=core.snapshot(bpy.context);plan=core.build_plan(snap,cfg(fit_length=True,gap=0),bpy.context.scene)
reference_signature=signature([reference])
expected=signature([source],(Matrix.Identity(4),*plan.transforms))
result=core.commit(bpy.context,snap,plan,join_generated=True)
assert len(bpy.data.objects)==2 and signature([reference])==reference_signature
assert signature(result)==expected
print('PASS Fit Length excludes its bookend reference from the join')

clear()
first=plane('First',(0,0,0));second=plane('Second',(0,3,0))
second.data.uv_layers.active.name='Different UV name'
for d in second.data.uv_layers.active.data:d.uv.x+=.2
select([first,second])
snap=core.snapshot(bpy.context);plan=core.build_plan(snap,cfg(count=2),bpy.context.scene)
expected=signature([first,second],(Matrix.Identity(4),*plan.transforms))
result=core.commit(bpy.context,snap,plan,join_generated=True)
assert signature(result)==expected
assert 'Atlas UV' in result[0].data.uv_layers and 'Different UV name' in result[0].data.uv_layers
assert result[0].data.uv_layers.active.active_render
print('PASS different named UV maps retain both explicit maps and implicit texture coordinates')

clear()
source=plane('Mesh')
curve=bpy.data.curves.new('Curve','CURVE');curve.dimensions='3D';curve.bevel_depth=.1
spline=curve.splines.new('POLY');spline.points.add(1)
spline.points[0].co=(0,3,0,1);spline.points[1].co=(1,3,0,1)
obj=bpy.data.objects.new('Curve',curve);bpy.context.collection.objects.link(obj)
select([source,obj],obj)
snap=core.snapshot(bpy.context);plan=core.build_plan(snap,cfg(count=2),bpy.context.scene)
expected_vertices=signature([source,obj],(Matrix.Identity(4),*plan.transforms))[0]
result=core.commit(bpy.context,snap,plan,join_generated=True)
assert len(bpy.data.objects)==1 and result[0].type=='MESH'
assert signature(result)[0]==expected_vertices
print('PASS mixed mesh and beveled curve sources')

clear()
curve=bpy.data.curves.new('Only curve','CURVE');curve.dimensions='3D';curve.bevel_depth=.1
spline=curve.splines.new('POLY');spline.points.add(1)
spline.points[0].co=(0,0,0,1);spline.points[1].co=(1,0,0,1)
obj=bpy.data.objects.new('Only curve',curve);bpy.context.collection.objects.link(obj);select([obj])
snap=core.snapshot(bpy.context);plan=core.build_plan(snap,cfg(count=2),bpy.context.scene)
result=core.commit(bpy.context,snap,plan,join_generated=True)
assert len(bpy.data.objects)==1 and result[0].type=='MESH'
print('PASS curve-only selection without UV maps')

clear()
source=plane('Rollback');snap=core.snapshot(bpy.context)
plan=core.build_plan(snap,cfg(),bpy.context.scene)
before=signature([source]);meshes=set(bpy.data.meshes)
fake_bpy=NS(data=bpy.data,types=bpy.types,ops=NS(object=NS(join=Mock(side_effect=RuntimeError('Simulated join failure')))))
with patch.object(core,'bpy',fake_bpy):
    try:core.commit(bpy.context,snap,plan,join_generated=True)
    except RuntimeError as exc:assert 'Simulated' in str(exc)
    else:raise AssertionError('Expected failure')
assert list(bpy.data.objects)==[source] and set(bpy.data.meshes)==meshes
assert signature([source])==before and bpy.context.object==source
print('PASS failed join restores selection and removes only staged/new objects')

# Exercise a real undoable Blender operator around generation, as the modal tool does.
class OBJECT_OT_join_array_test(bpy.types.Operator):
    bl_idname='object.join_array_test'
    bl_label='Test Joined Array'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        snap=core.snapshot(context);plan=core.build_plan(snap,cfg(count=2),context.scene)
        core.commit(context,snap,plan,join_generated=True)
        return {'FINISHED'}
bpy.utils.register_class(OBJECT_OT_join_array_test)
bpy.ops.ed.undo_push(message='Before joined array')
bpy.ops.object.join_array_test('EXEC_DEFAULT',True)
assert len(bpy.data.objects)==1 and len(bpy.context.object.data.vertices)==8
bpy.ops.ed.undo()
source=bpy.data.objects['Rollback']
assert len(bpy.data.objects)==1 and len(source.data.vertices)==4 and signature([source])==before
bpy.ops.ed.redo()
assert len(bpy.data.objects)==1 and len(bpy.context.object.data.vertices)==8
print('PASS Blender Undo and Redo restore originals and joined result')
print('ARRAY_JOIN_PASS')
