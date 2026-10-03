"""Real Blender material/UV preview copies and their transient lifecycle."""
import sys
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace
import bpy
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import extension as ext
from extension import array_material_preview as preview, array_core, array_tool
scratch = Path(mkdtemp(dir=ROOT/'tests'/'_artifacts',prefix='array_materials_'))
ext.shortcuts._theme_path=lambda:scratch/'theme.json'
ext.shape_library._storage_override=scratch/'library'
ext.register()

try:
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_plane_add()
    source=bpy.context.object
    mat=bpy.data.materials.new('Textured cutout');mat.use_nodes=True
    image=bpy.data.images.new('Cutout',width=2,height=2,alpha=True)
    image.pixels[:]=[1,0,0,1, 0,1,0,1, 0,0,1,1, 0,0,0,0]
    tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image
    shader=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    mat.node_tree.links.new(tex.outputs['Color'],shader.inputs['Base Color'])
    mat.node_tree.links.new(tex.outputs['Alpha'],shader.inputs['Alpha'])
    source.data.materials.append(mat)
    original_uv=[tuple(d.uv) for d in source.data.uv_layers.active.data]
    source_matrix=source.matrix_world.copy()
    snap=array_core.snapshot(bpy.context)
    pool=preview.MaterialPreview(bpy.context.scene,SimpleNamespace(local_view=None))
    pool.rebuild(bpy.context,snap)
    poses=[(Matrix.Translation((i*3,0,0)),1.) for i in range(1,4)]
    identity=Matrix.Identity(4)
    pool.sync(poses,identity,identity)
    assert len(pool.objects)==3 and len(pool.meshes)==1 and pool.ready
    ids=[o.as_pointer() for o in pool.objects];mesh_id=pool.meshes[0].as_pointer()
    for obj,(matrix,_) in zip(pool.objects,poses):
        assert obj.matrix_world==matrix@source_matrix
        assert obj.data.materials[0]==mat
        assert [tuple(d.uv) for d in obj.data.uv_layers.active.data]==original_uv
        assert obj.hide_select and obj.hide_render and not obj.select_get()
        assert obj.data!=source.data and preview.is_preview(obj)
    pool.sync(poses,identity,identity)
    assert ids==[o.as_pointer() for o in pool.objects] and mesh_id==pool.meshes[0].as_pointer()
    assigned=dict(pool.assigned)
    pool.sync(poses,identity,identity)
    assert all(pool.assigned[key] is value for key,value in assigned.items())
    # Source transforms and genuine mesh edits retain the same visible objects.
    pool.rebuild(bpy.context,snap)
    assert pool.ready and ids==[o.as_pointer() for o in pool.objects]
    assert all(obj.data==pool.meshes[0] for obj in pool.objects)
    assert len([m for m in bpy.data.meshes if preview.is_preview(m)])==1
    pool.sync(poses[:1],identity,identity)
    assert len(pool.objects)==1 and pool.objects[0].as_pointer()==ids[0]
    print('PASS real alpha material, UVs, shared surface, exact placement and idle object reuse')

    # Object-level material overrides survive evaluated mesh creation.
    override=bpy.data.materials.new('Object override')
    source.material_slots[0].link='OBJECT';source.material_slots[0].material=override
    pool.rebuild(bpy.context,array_core.snapshot(bpy.context))
    pool.sync(poses,identity,identity)
    assert all(obj.data.materials[0]==override for obj in pool.objects)
    source.material_slots[0].material=mat
    pool.rebuild(bpy.context,array_core.snapshot(bpy.context))
    pool.sync(poses,identity,identity)
    print('PASS object material overrides')

    # An actual scratch file save must contain no preview objects or meshes.
    state=SimpleNamespace(_done=False,_native=pool,_saving=False,_native_dirty=False,_committing=True,
        _inactive=SimpleNamespace(restore=lambda:None),_inactive_dirty=False)
    bpy.app.driver_namespace[array_tool.STATE_KEY]=state
    bpy.ops.wm.save_as_mainfile(filepath=str(scratch/'without_previews.blend'),copy=True)
    assert not any(preview.is_preview(o) for o in bpy.data.objects)
    assert not any(preview.is_preview(m) for m in bpy.data.meshes)
    assert state._native_dirty and not state._saving
    with bpy.data.libraries.load(str(scratch/'without_previews.blend')) as (data,_):
        assert all('Array Preview' not in n for n in data.objects)
        assert all('Array Preview' not in n for n in data.meshes)
    bpy.app.driver_namespace.pop(array_tool.STATE_KEY,None)
    pool.rebuild(bpy.context,snap);pool.sync(poses,identity,identity)
    # History can restore tagged IDs after Python references have gone stale.
    array_tool.history_post()
    assert not any(preview.is_preview(o) for o in bpy.data.objects)
    pool.clear()
    print('PASS real save exclusion and cleanup of undo-restored preview IDs')

    # Generate uses the unchanged sources, producing only requested final copies.
    cfg=SimpleNamespace(mode='LINEAR',orientation='WORLD',axes='X',count=4,gap=1.,fit_length=False)
    plan=array_core.build_plan(snap,cfg,bpy.context.scene)
    made=array_core.commit(bpy.context,snap,plan,linked=True)
    assert len(made)==3
    assert all(obj.data==source.data and obj.material_slots[0].material==mat for obj in made)
    assert source.matrix_world==source_matrix
    assert [tuple(d.uv) for d in source.data.uv_layers.active.data]==original_uv
    assert not any(preview.is_preview(o) for o in bpy.data.objects)
    print('PASS generation retains source textures without preview duplicates')
    print('ARRAY_MATERIAL_PREVIEW_PASS')
finally:
    bpy.app.driver_namespace.pop(array_tool.STATE_KEY,None)
    preview.purge()
    ext.unregister()
