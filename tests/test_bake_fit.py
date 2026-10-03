"""Blender regression tests for bake size/alpha alignment and target protection."""
import sys
from pathlib import Path
from tempfile import mkdtemp
import bpy
import numpy as np
from mathutils import Matrix, Euler, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import extension as ext
from extension import bake_fit as bake, fit_tool as fit
scratch = Path(mkdtemp(dir=ROOT/'tests'/'_artifacts', prefix='bake_fit_'))
ext.shortcuts._theme_path = lambda: scratch/'theme.json'
ext.shape_library._storage_override = scratch/'library'
ext.register()


def mesh(name, verts, edges=(), faces=()):
    data = bpy.data.meshes.new(name)
    data.from_pydata(verts, edges, faces)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    return obj


def plane(name='Bake'):
    obj = mesh(name, [(-2,-1,0),(2,-1,0),(2,1,0),(-2,1,0)], faces=[(0,1,2,3)])
    uv = obj.data.uv_layers.new()
    for item, value in zip(uv.data, [(0,0),(1,0),(1,1),(0,1)]): item.uv = value
    return obj


def select(*objects):
    for obj in bpy.context.selected_objects: obj.select_set(False)
    for obj in objects: obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[-1]
    bpy.context.view_layer.update()


def signature(obj):
    return ([list(r) for r in obj.matrix_world], [tuple(v.co) for v in obj.data.vertices],
        [tuple(e.vertices) for e in obj.data.edges], [tuple(p.vertices) for p in obj.data.polygons])


def measure(source, target, alpha=False):
    dg = bpy.context.evaluated_depsgraph_get()
    tp = fit.object_points(target, dg)
    inv = bake.frame(target, tp).inverted()
    points = bake.alpha_points(source, bake.uv_mapping(source))[0] if alpha else fit.object_points(source, dg)
    return bake.bounds([tuple(inv @ Vector(p)) for p in points]), bake.bounds([tuple(inv @ Vector(p)) for p in tp])


def assert_match(source, target, alpha=False, proportional=False):
    (lo,hi),(tl,th) = measure(source,target,alpha)
    assert np.max(np.abs((lo+hi)[:2]-(tl+th)[:2])) < 3e-5
    if proportional:
        assert min(np.abs((hi-lo)[:2]-(th-tl)[:2])) < 3e-5
        assert np.all((hi-lo)[:2] <= (th-tl)[:2]+3e-5)
    else:
        assert np.max(np.abs(lo[:2]-tl[:2])) < 3e-5, (lo,tl)
        assert np.max(np.abs(hi[:2]-th[:2])) < 3e-5, (hi,th)


try:
    # Branched guides, disconnected triangles and thickness all work: this is
    # evaluated size matching, not loop detection or fitting inside a hole.
    target = mesh('Original with depth and branches',
        [(-3,-4,-.2),(3,-4,-.2),(3,4,-.2),(-3,4,-.2),(0,0,.4),(0,1,.1)],
        [(4,0),(4,1),(4,5)], [(0,1,2),(0,2,3)])
    source = plane()
    for rotation in [(0,0,0),(.3,.7,.4),(0,1.570796,1.2)]:
        target.matrix_world = Matrix.Translation((5,3,-2)) @ Euler(rotation).to_matrix().to_4x4()
        source.matrix_world = Matrix.Translation((-8,2,7)) @ Euler((.7,-.2,.5)).to_matrix().to_4x4()
        select(source,target)
        before = signature(target)
        uv_before = [tuple(d.uv) for d in source.data.uv_layers.active.data]
        result = bake.fit_selection(bpy.context, use_alpha=False)
        assert_match(source,target)
        assert signature(target) == before
        assert [tuple(d.uv) for d in source.data.uv_layers.active.data] == uv_before
        assert bpy.context.active_object == target and set(bpy.context.selected_objects) == {source,target}
        matrix = source.matrix_world.copy()
        bake.fit_selection(bpy.context, use_alpha=False)
        assert np.max(np.abs(np.array(source.matrix_world)-np.array(matrix))) < 3e-5
    print('PASS depth, branches, arbitrary orientation, target/UV protection and repeated fitting')

    source.matrix_world = Matrix.Identity(4)
    select(source,target)
    result = bake.fit_selection(bpy.context, proportional=True, use_alpha=False, depth='CENTER')
    assert abs(result['factors'][0]-result['factors'][1]) < 1e-7
    assert_match(source,target,proportional=True)
    (lo,hi),(tl,th) = measure(source,target)
    assert abs((lo[2]+hi[2])-(tl[2]+th[2])) < 3e-5
    print('PASS optional proportional fit and center depth')

    # Only the assigned crop matters; a separate alpha island elsewhere in
    # the same atlas must never influence the fitted size.
    source = plane('Atlas bake')
    for item, value in zip(source.data.uv_layers.active.data, [(0,0),(.5,0),(.5,.5),(0,.5)]): item.uv = value
    image = bpy.data.images.new('Atlas alpha',width=64,height=64,alpha=True)
    pixels = np.zeros((64,64,4),dtype=np.float32)
    pixels[8:24,4:28,:] = 1.
    pixels[40:60,40:60,:] = 1.
    image.pixels.foreach_set(pixels.ravel())
    mat = bpy.data.materials.new('Bake material'); mat.use_nodes = True
    source.data.materials.append(mat)
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage'); tex.image = image
    shader = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    mat.node_tree.links.new(tex.outputs['Alpha'],shader.inputs['Alpha'])
    select(source,target)
    before_uv = [tuple(d.uv) for d in source.data.uv_layers.active.data]
    result = bake.fit_selection(bpy.context)
    assert_match(source,target,alpha=True)
    assert result['notes'] == ['Visible alpha within the plane UV crop']
    assert [tuple(d.uv) for d in source.data.uv_layers.active.data] == before_uv
    assert len(source.data.vertices) == 4 and len(source.data.polygons) == 1
    (lo,hi),(tl,th) = measure(source,target)
    assert (hi-lo)[0] > (th-tl)[0]*1.2
    print('PASS atlas alpha crop, transparent margins, original material and UV preservation')

    # A shape can be rotated inside its mesh while the object axes stay still.
    # The alpha silhouette must supply that missing in-plane orientation.
    angle = .43
    turn = Matrix.Rotation(angle,4,'Z')
    polygon = [(-1,-1,0),(1,-1,0),(1,0,0),(0,2,0),(-1,0,0)]
    arrow = mesh('Applied rotation target', [tuple(turn @ Vector(p)) for p in polygon], faces=[(0,1,2,3,4)])
    arrow.matrix_world = Matrix.Translation((3,-2,5)) @ Euler((.2,.7,.6)).to_matrix().to_4x4()
    source = plane('Rotated silhouette bake')
    source.data.materials.append(mat)
    yy,xx = np.meshgrid(np.linspace(-1.5,2.5,64,endpoint=False)+2/64,
                        np.linspace(-1.5,1.5,64,endpoint=False)+1.5/64,indexing='ij')
    occupancy = (np.abs(xx)<=1)&(yy>=-1)&(yy<=2)&((yy<=0)|(np.abs(xx)<=(2-yy)*.5))
    pixels[:,:,:] = 0; pixels[:,:,3] = occupancy
    image.pixels.foreach_set(pixels.ravel())
    select(source,arrow)
    result = bake.fit_selection(bpy.context)
    assert 'Rotation matched to visible silhouette' in result['notes']
    mapping = bake.uv_mapping(source)[0]
    actual_up = Vector(mapping[1]).normalized()
    expected_up = (arrow.matrix_world.to_3x3() @ (turn.to_3x3() @ Vector((0,1,0)))).normalized()
    assert actual_up.dot(expected_up) > .9995, (actual_up,expected_up)
    before = np.array(source.matrix_world)
    bake.fit_selection(bpy.context)
    assert np.max(np.abs(np.array(source.matrix_world)-before)) < 1e-4
    print('PASS silhouette rotation with applied geometry rotation and repeat fit stability')

    # Target modifiers must contribute to the bounds, and linked source data
    # and children must be protected when nonuniform fitting introduces shear.
    source = plane('Rotated linked plane')
    source.rotation_euler = (.2,.4,.7)
    linked = bpy.data.objects.new('Unselected linked copy', source.data)
    bpy.context.collection.objects.link(linked)
    child = plane('Unselected child'); child.parent = source; child.location = (4,5,6)
    select(source,target)
    child_before, linked_before = signature(child), signature(linked)
    old_data = linked.data
    bake.fit_selection(bpy.context, use_alpha=False, align_rotation=False)
    assert np.max(np.abs(np.array(signature(child)[0])-np.array(child_before[0]))) < 3e-5
    assert signature(linked) == linked_before and linked.data == old_data
    assert_match(source,target)
    print('PASS unselected children, linked meshes, and free scaling without rotation alignment')

    source = plane('Modifier test')
    solidify = target.modifiers.new('Evaluated depth','SOLIDIFY'); solidify.thickness = .5
    select(source,target)
    bake.fit_selection(bpy.context,use_alpha=False,depth='FRONT',offset=.02)
    (lo,hi),(tl,th) = measure(source,target)
    assert min(abs(lo[2]-th[2]-.02),abs(lo[2]-tl[2]+.02)) < 1e-5
    target.modifiers.remove(solidify)
    print('PASS evaluated target modifier bounds and surface offset')

    source = plane('Constrained bake')
    source.location = (50,0,0)
    constraint = source.constraints.new('LIMIT_LOCATION')
    constraint.use_min_x = True; constraint.min_x = 50
    select(source,target)
    before = signature(source)
    try: bake.fit_selection(bpy.context,use_alpha=False)
    except ValueError: pass
    else: raise AssertionError('Constraint must roll back')
    assert signature(source) == before
    print('PASS atomic rollback for a blocked constraint')

    source = plane('Operator bake'); select(source,target)
    cfg = bpy.context.window_manager.harhtools_fit
    assert cfg.mode == 'BOUNDS' and not cfg.bake_proportional
    cfg.use_alpha = False
    cfg.offset_studs = .1
    assert abs(cfg.offset-.028) < 1e-6
    assert bpy.ops.object.harhtools_fit_selected('EXEC_DEFAULT') == {'FINISHED'}
    assert_match(source,target)
    assert 'UNDO' in fit.OBJECT_OT_harhtools_fit_selected.bl_options
    print('BAKE_FIT_PASS')
finally:
    ext.unregister()
