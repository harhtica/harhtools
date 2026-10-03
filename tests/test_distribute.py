"""Spacing/alignment moves real geometry without rescaling or changing UVs."""
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extension import distribute as tool, display_units

display_units.register()
tool.register()


def clear():
    if bpy.context.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    for obj in list(bpy.data.objects): bpy.data.objects.remove(obj, do_unlink=True)


def select(objects, active=None):
    for obj in bpy.context.selected_objects: obj.select_set(False)
    for obj in objects: obj.select_set(True)
    bpy.context.view_layer.objects.active = active or objects[0]
    bpy.context.view_layer.update()


def mesh_object(name, intervals, shifts=None):
    vertices, faces = [], []
    for n, (lo, hi) in enumerate(intervals):
        x = shifts[n] if shifts else 0
        start = len(vertices)
        vertices.extend([(x-1,0,lo),(x+1,0,lo),(x+1,0,hi),(x-1,0,hi)])
        faces.append(tuple(range(start,start+4)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    uv = mesh.uv_layers.new(name='Atlas')
    for i, loop in enumerate(uv.data): loop.uv = ((i%4)*.123, (i//4)*.117)
    obj = bpy.data.objects.new(name, mesh); bpy.context.collection.objects.link(obj)
    return obj


def uv_signature(obj):
    return tuple(tuple(d.uv) for d in obj.data.uv_layers.active.data)


def coordinates(obj):
    if obj.mode == 'EDIT':
        return [v.co.copy() for v in bmesh.from_edit_mesh(obj.data).verts]
    return [v.co.copy() for v in obj.data.vertices]


def check_gaps(axis='Z', expected=None, parts='ISLANDS', space='WORLD'):
    pieces = tool.collect(bpy.context, parts)
    v = tool.axes(space, bpy.context.active_object)['XYZ'.index(axis)]
    bounds = sorted((min(p.dot(v) for p in piece.points),max(p.dot(v) for p in piece.points)) for piece in pieces)
    gaps = [b[0]-a[1] for a,b in zip(bounds,bounds[1:])]
    assert max(gaps)-min(gaps)<1e-5, gaps
    if expected is not None: assert abs(gaps[0]-expected)<1e-5, gaps


clear()
obj = mesh_object('Four joined pieces', [(0,3),(4,6),(8,9.5),(12,13)])
select([obj]); before=coordinates(obj); uv=uv_signature(obj)
count, gap, axis = tool.distribute(bpy.context)
assert (count,axis)==(4,'Z') and abs(gap-5.5/3)<1e-6
check_gaps(expected=5.5/3)
after=coordinates(obj)
assert before[:4]==after[:4] and before[-4:]==after[-4:]
for start in range(0,16,4):
    for i in range(4): assert ((after[start+i]-after[start])-(before[start+i]-before[start])).length<1e-6
assert uv_signature(obj)==uv and len(obj.data.polygons)==4
print('PASS unequal sizes, joined mesh, fixed ends, rigid translations and unchanged UVs')

# Unselected linked users and their shape keys must not be modified.
clear()
obj=mesh_object('Keys',[(0,1),(2,4),(8,9)]); select([obj])
obj.shape_key_add(name='Basis'); key=obj.shape_key_add(name='Raised')
for v in key.data: v.co.y += .25
other=bpy.data.objects.new('Unselected linked',obj.data); bpy.context.collection.objects.link(other)
old=coordinates(other); old_data=other.data
tool.distribute(bpy.context)
assert obj.data!=old_data and coordinates(other)==old
for base,raised in zip(obj.data.shape_keys.key_blocks[0].data,obj.data.shape_keys.key_blocks[1].data):
    assert (raised.co-base.co-Vector((0,.25,0))).length<1e-6
check_gaps()
print('PASS linked data isolation and shape key relative offsets')

# Edit Mode: a single selected vertex identifies each entire island.
clear()
obj=mesh_object('Edit pieces',[(0,1),(2,4),(8,9),(20,21)]); select([obj]); old=coordinates(obj); uv=uv_signature(obj)
bpy.ops.object.mode_set(mode='EDIT'); bm=bmesh.from_edit_mesh(obj.data); bm.verts.ensure_lookup_table()
for f in bm.faces: f.select_set(False)
for e in bm.edges: e.select_set(False)
for v in bm.verts: v.select_set(False)
for i in (0,4,8): bm.verts[i].select=True
bmesh.update_edit_mesh(obj.data)
selected_before=[v.select for v in bm.verts]
tool.distribute(bpy.context)
assert bpy.context.mode=='EDIT_MESH' and [v.select for v in bm.verts]==selected_before
check_gaps(expected=2.5)
assert coordinates(obj)[12:]==old[12:] and coordinates(obj)[:4]==old[:4]
bpy.ops.object.mode_set(mode='OBJECT'); assert uv_signature(obj)==uv
print('PASS partial selection moves whole islands, leaves unselected island, preserves Edit Mode')

# Whole objects use evaluated boundaries (including modifier thickness).
clear()
objects=[mesh_object(str(i),[interval]) for i,interval in enumerate([(0,1),(2,4),(8,9)])]
for obj in objects:
    mod=obj.modifiers.new('Volume','SOLIDIFY'); mod.thickness=.5
select(objects)
tool.distribute(bpy.context,parts='OBJECTS'); check_gaps(expected=2.5,parts='OBJECTS')
assert all(len(o.modifiers)==1 for o in objects)
print('PASS separate objects with evaluated modifiers')

# Parent transforms, negative scale and active local direction.
clear()
obj=mesh_object('Rotated',[(0,1),(2,4),(8,9)])
obj.matrix_world=Matrix.Translation((10,20,30))@Matrix.Rotation(.61,4,'Y')@Matrix.Diagonal((-1,2,1.7,1))
select([obj]); before=coordinates(obj); tool.distribute(bpy.context,axis='Z',space='ACTIVE')
check_gaps(axis='Z',space='ACTIVE')
assert coordinates(obj)[:4]==before[:4] and coordinates(obj)[-4:]==before[-4:]
print('PASS rotated and nonuniform negative-scaled mesh')

# Align center and edges, default Auto straightens cross axes but preserves row position.
clear()
obj=mesh_object('Crooked row',[(0,3),(4,6),(8,9.5),(12,13)],shifts=[-.2,.1,-.1,.3]); select([obj])
before=coordinates(obj); uv=uv_signature(obj)
count,axis=tool.align(bpy.context)
assert count==4 and axis=='X/Y'
pieces=tool.collect(bpy.context)
assert max(p.center.x for p in pieces)-min(p.center.x for p in pieces)<1e-6
assert all(abs(a.z-b.z)<1e-6 for a,b in zip(before,coordinates(obj)))
tool.align(bpy.context,axis='Z',method='MIN')
assert len({round(min(v.z for v in p.points),5) for p in tool.collect(bpy.context)})==1
tool.align(bpy.context,axis='Z',method='MAX')
assert len({round(max(v.z for v in p.points),5) for p in tool.collect(bpy.context)})==1
assert uv==uv_signature(obj)
print('PASS auto alignment and explicit minimum/maximum edges')

# Multi-object Edit Mode alignment keeps each selected mesh rigid, including UVs.
clear()
objects=[mesh_object(str(i),[interval],shifts=[shift])
         for i,(interval,shift) in enumerate(zip([(0,1),(2,4),(8,9)],[-.3,.2,.5]))]
select(objects); before={o:coordinates(o) for o in objects}; uv={o:uv_signature(o) for o in objects}
bpy.ops.object.mode_set(mode='EDIT')
tool.align(bpy.context,axis='X')
assert bpy.context.mode=='EDIT_MESH'
pieces=tool.collect(bpy.context)
assert max(p.center.x for p in pieces)-min(p.center.x for p in pieces)<1e-6
tool.distribute(bpy.context,axis='Z'); check_gaps(expected=2.5)
bpy.ops.object.mode_set(mode='OBJECT')
for o in objects:
    assert uv_signature(o)==uv[o]
    after=coordinates(o)
    assert all(((after[i]-after[0])-(before[o][i]-before[o][0])).length<1e-6 for i in range(4))
print('PASS multi-object Edit Mode alignment, spacing and rigid UV-mapped pieces')

# Whole Objects intentionally keeps the internal arrangement together.
clear()
objects=[mesh_object(str(i),[(start,start+1),(start+2,start+3)]) for i,start in enumerate((0,5,14))]
select(objects); before={o:coordinates(o) for o in objects}
tool.distribute(bpy.context,parts='OBJECTS'); check_gaps(expected=4,parts='OBJECTS')
assert all(coordinates(o)==before[o] for o in objects)
print('PASS Whole Objects retains each internal multi-island arrangement')

# Whole-object parenting: moving a selected parent must not drag other objects.
clear()
objects=[mesh_object(str(i),[interval]) for i,interval in enumerate([(0,1),(2,4),(8,9)])]
child=mesh_object('Unselected child',[(22,23)]); child.parent=objects[1]
select(objects); child_matrix=child.matrix_world.copy()
tool.distribute(bpy.context,parts='OBJECTS'); check_gaps(expected=2.5,parts='OBJECTS')
assert child.matrix_world==child_matrix
print('PASS preserves unselected child world position')

# A blocked transform rolls back both modified island meshes and object transforms.
clear()
obj=mesh_object('Joined rollback',[(0,1),(2,4),(10,11)])
end=mesh_object('Blocked middle',[(6,7)])
constraint=end.constraints.new('LIMIT_LOCATION')
constraint.use_min_z=True; constraint.use_max_z=True; constraint.min_z=0; constraint.max_z=0
select([obj,end]); before=coordinates(obj); basis=end.matrix_basis.copy()
try: tool.distribute(bpy.context)
except ValueError: pass
else: raise AssertionError('Expected constraint to reject movement')
assert coordinates(obj)==before and end.matrix_basis==basis
print('PASS atomic rollback for constraints')

# Undo / redo from the actual registered operator in Object Mode.
clear()
obj=mesh_object('Undo pieces',[(0,1),(2,4),(8,9)]); select([obj]); before=coordinates(obj)
bpy.context.preferences.edit.use_global_undo=True
bpy.ops.ed.undo_push(message='Before spacing')
assert bpy.ops.object.harhtools_even_spacing('EXEC_DEFAULT',True,axis='Z')=={'FINISHED'}
after=coordinates(obj); assert after!=before
bpy.ops.ed.undo(); obj=bpy.data.objects['Undo pieces']; assert coordinates(obj)==before
bpy.ops.ed.redo(); obj=bpy.data.objects['Undo pieces']; assert coordinates(obj)==after
print('PASS actual operator Undo / Redo')

# Active object is a fixed reference, including all islands in a joined target.
for method in ('CENTER','MIN','MAX'):
    clear()
    source=mesh_object('Source',[(0,1),(3,5)],shifts=[-3,2])
    target=mesh_object('Active joined reference',[(10,11),(18,20)],shifts=[7,9])
    select([source,target],target)
    target_before=coordinates(target); matrix=target.matrix_world.copy(); uv=uv_signature(source)
    count,axis=tool.align(bpy.context,axis='Z',method=method,to_active=True)
    assert count==2 and axis=='Z'
    for p in tool.collect(bpy.context):
        if p.obj!=source: continue
        lo,hi=min(v.z for v in p.points),max(v.z for v in p.points)
        value=lo if method=='MIN' else hi if method=='MAX' else (lo+hi)/2
        assert abs(value-({'MIN':10,'MAX':20,'CENTER':15}[method]))<1e-6
    assert coordinates(target)==target_before and target.matrix_world==matrix
    assert uv_signature(source)==uv
print('PASS active joined reference remains fixed for center/min/max alignment')

# Auto follows the moving row, not an off-axis reference's remote position.
clear()
source=mesh_object('Row',[(0,1),(3,4),(8,9)],shifts=[-.1,.1,.2])
target=mesh_object('Off-axis reference',[(0,1)],shifts=[100])
select([source,target],target); before=coordinates(source); target_before=coordinates(target)
count,axis=tool.align(bpy.context,to_active=True)
assert count==3 and axis=='X/Y'
assert coordinates(target)==target_before
assert all(abs(a.z-b.z)<1e-6 for a,b in zip(before,coordinates(source)))
assert all(abs(p.center.x-100)<1e-5 for p in tool.collect(bpy.context) if p.obj==source)
print('PASS Auto active-reference alignment preserves the moving row direction')

# One moving object can be centered onto a rotated target with Auto.
clear()
source=mesh_object('Single source',[(0,1)])
target=mesh_object('Rotated target',[(0,4)])
target.matrix_world=Matrix.Translation((5,7,12))@Matrix.Rotation(.7,4,'Y')
select([source,target],target); matrix=target.matrix_world.copy()
count,axis=tool.align(bpy.context,space='ACTIVE',to_active=True)
assert count==1 and axis=='X/Y/Z' and target.matrix_world==matrix
pieces=tool.collect(bpy.context,minimum=2)
for direction in tool.axes('ACTIVE',target):
    centers=[(min(v.dot(direction) for v in p.points)+max(v.dot(direction) for v in p.points))/2 for p in pieces]
    assert abs(centers[0]-centers[1])<1e-5
print('PASS Auto centers single object to rotated active reference')

# Active vertex, edge and face all resolve to their whole disconnected island.
for element_type in ('VERT','EDGE','FACE'):
    clear()
    obj=mesh_object('Active edit island',[(0,1),(3,4),(8,9)],shifts=[0,2,4]); select([obj])
    uv=uv_signature(obj); before=coordinates(obj)
    bpy.ops.object.mode_set(mode='EDIT'); bm=bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    for f in bm.faces: f.select_set(True)
    bm.select_history.clear()
    element=(bm.verts[4] if element_type=='VERT' else
             next(e for e in bm.edges if {v.index for v in e.verts}=={4,5}) if element_type=='EDGE' else bm.faces[1])
    bm.select_history.add(element)
    tool.align(bpy.context,axis='X',to_active=True)
    assert coordinates(obj)[4:8]==before[4:8]
    assert all(abs(p.center.x-2)<1e-6 for p in tool.collect(bpy.context))
    assert bm.select_history.active==element and bpy.context.mode=='EDIT_MESH'
    bpy.ops.object.mode_set(mode='OBJECT'); assert uv_signature(obj)==uv
print('PASS active vertex/edge/face reference in Edit Mode without changing reference or UVs')

# Ambiguous box-selection must not silently choose a reference island.
clear()
obj=mesh_object('Ambiguous edit reference',[(0,1),(3,4)],shifts=[0,3]); select([obj])
bpy.ops.object.mode_set(mode='EDIT'); bm=bmesh.from_edit_mesh(obj.data)
for f in bm.faces: f.select_set(True)
bm.select_history.clear(); bm.faces.active=None; before=coordinates(obj)
try: tool.align(bpy.context,axis='X',to_active=True)
except ValueError as exc: assert 'reference piece last' in str(exc)
else: raise AssertionError('Expected an explicit active reference')
assert coordinates(obj)==before
bpy.ops.object.mode_set(mode='OBJECT')
print('PASS ambiguous active island reports how to select it and keeps geometry unchanged')

# The public operator forwards the toggle and participates in real Undo/Redo.
clear()
source=mesh_object('Undo source',[(0,1)],shifts=[0])
target=mesh_object('Undo reference',[(0,1)],shifts=[5]); select([source,target],target)
bpy.ops.ed.undo_push(message='Before active alignment')
assert bpy.ops.object.harhtools_align_pieces('EXEC_DEFAULT',True,axis='X',to_active=True)=={'FINISHED'}
assert abs(source.matrix_world.translation.x-5)<1e-6 and target.matrix_world.translation.x==0
bpy.ops.ed.undo(); source=bpy.data.objects['Undo source']; assert source.matrix_world.translation.x==0
bpy.ops.ed.redo(); source=bpy.data.objects['Undo source']; assert abs(source.matrix_world.translation.x-5)<1e-6
print('PASS active-reference operator toggle and Undo/Redo')

tool.unregister(); display_units.unregister()
print('ALL SPACING AND ALIGNMENT TESTS PASSED')
