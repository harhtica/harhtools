"""Real Blender fitting: curved containment, balanced clearance and atomic transforms."""
import math
import sys
import time
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch
from types import SimpleNamespace
import bpy
from mathutils import Matrix, Euler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import extension as ext
from extension import fit_tool as fit

scratch = Path(mkdtemp(dir=ROOT/'tests'/'_artifacts', prefix='fit_'))
ext.shortcuts._theme_path = lambda: scratch/'theme.json'
ext.shape_library._storage_override = scratch/'library'
ext.register()


def mesh(name, loops):
    verts, edges = [], []
    for loop in loops:
        first = len(verts)
        verts.extend((x, y, 0.) for x, y in loop)
        edges.extend((first+i, first+(i+1) % len(loop)) for i in range(len(loop)))
    data = bpy.data.meshes.new(name)
    data.from_pydata(verts, edges, [])
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    return obj


def circle(radius=1., center=(0., 0.), count=128):
    return [(center[0]+radius*math.cos(i*math.tau/count),
             center[1]+radius*math.sin(i*math.tau/count)) for i in range(count)]


def select(*objects):
    for obj in bpy.context.selected_objects: obj.select_set(False)
    for obj in objects: obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[-1]
    bpy.context.view_layer.update()


def signature(obj):
    return (obj.data.as_pointer(), tuple(tuple(v.co) for v in obj.data.vertices),
            tuple(tuple(e.vertices) for e in obj.data.edges))


def same(a, b, tol=1e-6):
    return all(abs(x-y) < tol for row1, row2 in zip(a, b) for x, y in zip(row1, row2))


def contained(source, target):
    boundary = fit.target_boundary(target)
    points = fit.object_points(source, bpy.context.evaluated_depsgraph_get())
    assert fit.contained(fit.hull([boundary['project'](p) for p in points]), boundary['loop'])


try:
    # Three rings in one mesh, as in the user's screenshot. Equal edge gaps
    # should recover the threefold center, which differs from bounds center.
    centers = [(math.cos(a)*1.3, math.sin(a)*1.3) for a in (math.pi/2, math.pi/2+math.tau/3, math.pi/2+2*math.tau/3)]
    loops = [circle(r, c) for c in centers for r in (.8, .65)]
    source = mesh('One mesh - three rings', loops)
    target = mesh('Circular frame', [circle(4., count=512), circle(3., count=512)])
    source.location = (7, -3, 2)
    select(source, target)
    before, target_before = signature(source), signature(target)
    target_matrix = target.matrix_world.copy()
    selection = set(bpy.context.selected_objects)
    started = time.perf_counter()
    result = fit.fit_selection(bpy.context, gap=.2)
    elapsed = time.perf_counter()-started
    assert signature(source) == before and signature(target) == target_before
    assert same(target.matrix_world, target_matrix)
    assert bpy.context.active_object == target and set(bpy.context.selected_objects) == selection
    assert result['count'] == 1 and result['opening']
    points = fit.object_points(source, bpy.context.evaluated_depsgraph_get())
    gaps = [3.-max(math.hypot(p[0], p[1]) for p in points[i*256:(i+1)*256]) for i in range(3)]
    assert max(gaps)-min(gaps) < .001, gaps
    assert .199 < min(gaps) < .202, gaps
    assert max(abs(p[2]) for p in points) < 1e-5
    contained(source, target)
    print('PASS one mesh / three rings: equal gaps', gaps, 'seconds', elapsed)

    # Several objects keep one common transform; origins need not be centered.
    parts = [mesh('Ring '+str(i), [circle(.8, c), circle(.65, c)]) for i, c in enumerate(centers)]
    select(*parts, target)
    original = {obj: obj.matrix_world.copy() for obj in parts}
    fit.fit_selection(bpy.context, gap=.2)
    transforms = [obj.matrix_world @ original[obj].inverted() for obj in parts]
    assert all(same(transforms[0], m) for m in transforms)
    combined = [p for obj in parts for p in fit.object_points(obj, bpy.context.evaluated_depsgraph_get())]
    assert max(min(math.dist(p, q) for q in points) for p in combined) < .001
    print('PASS single mesh and separate objects fit identically as one arrangement')

    # Non-proportional fit uses target plane axes, preserves data, and can fill
    # a rectangle while proportional mode leaves the expected side clearance.
    rect = mesh('Rectangle target', [[(-4,-2), (4,-2), (4,2), (-4,2)]])
    square = mesh('Square source', [[(-1,-1), (1,-1), (1,1), (-1,1)]])
    select(square, rect)
    data_before = signature(square)
    result = fit.fit_selection(bpy.context, proportional=False, gap=.25)
    assert abs(result['factors'][0]-3.75) < .06 and abs(result['factors'][1]-1.75) < .06, result
    assert signature(square) == data_before
    contained(square, rect)
    square.matrix_world = Matrix.Identity(4)
    fit.fit_selection(bpy.context, proportional=True, gap=.25)
    assert abs(square.scale.x-square.scale.y) < 1e-6
    assert abs(square.scale.x-1.75) < .001
    print('PASS proportional and independent plane-axis scale')

    # Blender matrix channels cannot represent rotated anisotropic scaling.
    # A private transformed data copy must preserve the exact result without
    # changing topology or any other user of that mesh.
    rotated = mesh('Rotated square', [[(-1,-1), (1,-1), (1,1), (-1,1)]])
    rotated.rotation_euler.z = .45
    shared = bpy.data.objects.new('Unselected linked rotated square', rotated.data)
    bpy.context.collection.objects.link(shared)
    old_data = rotated.data
    select(rotated, rect)
    fit.fit_selection(bpy.context, proportional=False, gap=.1)
    assert rotated.data != old_data and shared.data == old_data
    assert len(rotated.data.vertices) == 4 and len(rotated.data.edges) == 4
    contained(rotated, rect)
    print('PASS exact rotated non-proportional fit without remeshing or altering linked copies')

    # Curves work without conversion, even when they have no bevel or fill.
    bpy.ops.curve.primitive_bezier_circle_add(radius=1)
    curve = bpy.context.object
    curve.data.dimensions = '3D'; curve.data.fill_mode = 'FULL'; curve.data.bevel_depth = 0
    curve_data = curve.data
    select(curve, target)
    fit.fit_selection(bpy.context, gap=.3, fill=85)
    assert curve.data == curve_data and curve.data.splines[0].type == 'BEZIER'
    contained(curve, target)
    print('PASS editable Bezier curves')

    # Off-plane rotations, tiny units and shifted origins must not choose a
    # viewport plane. Negative/nonuniform target object scale is supported.
    for orientation in [(0,0,0), (0,math.pi/2,0), (.4,.7,.9)]:
        for scale in [1e-4, 1., 40.]:
            t = mesh('Transformed target', [circle(3, count=128)])
            s = mesh('Transformed source', [circle(1, count=64)])
            basis = Matrix.Translation((2.,-3.,5.)) @ Euler(orientation).to_matrix().to_4x4()
            t.matrix_world = basis @ Matrix.Diagonal((-scale,scale,scale,1.))
            s.matrix_world = basis @ Matrix.Diagonal((scale,scale,scale,1.))
            select(s, t)
            fit.fit_selection(bpy.context, gap=.1*scale)
            contained(s, t)
            fit.fit_selection(bpy.context, gap=0.)
            contained(s, t)
    print('PASS rotated / reflected planes, scale extremes and offset origins')

    # Concavity: every vertex of this envelope is inside but an edge crosses
    # the notch. Containment must not accept the bounding box or only vertices.
    notch = [(-3,-3),(3,-3),(3,3),(1,3),(1,0),(-1,0),(-1,3),(-3,3)]
    assert not fit.contained([(-2,-2),(2,-2),(2,2),(-2,2)], notch)
    concave = mesh('Concave target', [notch])
    select(square, concave)
    fit.fit_selection(bpy.context, equal_spacing=False)
    contained(square, concave)
    print('PASS complete-edge containment for concave targets')

    # Protect linked geometry and unselected children. Preserve active target
    # even when it is parented under a selected source.
    parent = mesh('Selected parent', [circle(.5)])
    child = mesh('Unselected child', [circle(.1)])
    child.parent = parent; child.location = (9, 0, 0)
    linked = bpy.data.objects.new('Linked but not selected', parent.data)
    bpy.context.collection.objects.link(linked)
    select(parent, target)
    child_matrix, linked_matrix = child.matrix_world.copy(), linked.matrix_world.copy()
    linked_signature = signature(linked)
    fit.fit_selection(bpy.context)
    assert same(child.matrix_world, child_matrix) and same(linked.matrix_world, linked_matrix)
    assert signature(linked) == linked_signature
    print('PASS unselected descendants and linked mesh users remain unchanged')

    parent_target = mesh('Frame child of selected shape', [circle(3.)])
    parent_target.parent = parent
    select(parent, parent_target)
    target_world = parent_target.matrix_world.copy()
    fit.fit_selection(bpy.context, gap=.2)
    assert same(parent_target.matrix_world, target_world)
    contained(parent, parent_target)
    print('PASS active target remains fixed even under a selected parent')

    # A transform constraint prevents the result: fail atomically and preserve
    # source matrices, target, data, selection, and all children.
    parent.matrix_world = Matrix.Translation((8,0,0))
    constraint = parent.constraints.new('LIMIT_LOCATION')
    constraint.use_min_x = True; constraint.min_x = 8
    select(parent, target)
    originals = {obj: obj.matrix_basis.copy() for obj in (parent, child, target)}
    try: fit.fit_selection(bpy.context)
    except ValueError: pass
    else: raise AssertionError('Constraint should prevent the fit')
    assert all(same(obj.matrix_basis, matrix) for obj, matrix in originals.items())
    parent.constraints.remove(constraint)
    print('PASS atomic rollback after blocked transforms')

    cfg = bpy.context.window_manager.harhtools_fit
    cfg.gap_studs = 1.5
    assert abs(cfg.gap-.42) < 1e-6
    cfg.gap = .1
    select(source, target)
    with patch.object(ext.shape_library, 'capture_shape', side_effect=AssertionError('No library saves')):
        assert bpy.ops.object.harhtools_fit_selected('EXEC_DEFAULT') == {'FINISHED'}
    assert 'UNDO' in fit.OBJECT_OT_harhtools_fit_selected.bl_options
    bpy.ops.view3d.harhtools_panel_tab(tab='FIT')
    assert bpy.context.window_manager.harhtools_panel_tab == 'FIT'
    bpy.ops.view3d.harhtools_panel_tab(tab='TRANSFORM')
    assert bpy.context.window_manager.harhtools_panel_tab == 'FIT'
    class Layout:
        def __init__(self): self.calls = []
        def row(self, **kw): return self
        def column(self, **kw): return self
        def box(self, **kw): return self
        def separator(self, **kw): pass
        def label(self, **kw): self.calls.append(('label', kw.get('text')))
        def prop(self, obj, name, **kw): self.calls.append(('prop', name))
        def operator(self, name, **kw):
            self.calls.append(('operator', name)); return SimpleNamespace()
    layout = Layout()
    with patch.object(ext.shortcuts, 'section_box', side_effect=lambda *a, **k: a[0]), \
         patch.object(fit, 'target_boundary', side_effect=AssertionError('No solver in panel draw')), \
         patch.object(ext.icons, 'icon', return_value=0):
        ext.centering.VIEW3D_PT_center_selected_to_active.draw(SimpleNamespace(layout=layout), bpy.context)
    assert ('operator', 'object.harhtools_fit_selected') in layout.calls
    assert ('operator', 'view3d.arch_shape_builder') not in layout.calls
    assert all(('prop', p) in layout.calls for p in ('proportional', 'equal_spacing', 'gap_studs', 'boundary'))
    print('PASS registered button, separate fit tab, stud input and manual-only library')
    print('FIT_TOOL_PASS')
finally:
    ext.unregister()
