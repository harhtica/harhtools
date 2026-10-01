"""Headless geometric/cache tests; no viewport control, drawing, or file saves."""
import bpy
import hashlib
import json
import math
import sys
import traceback
import statistics
import time
from pathlib import Path
from types import SimpleNamespace
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extension.outline_snap import OutlineSnapCache, nearest_on_cubic, nearest_on_segment, _point

REGION = SimpleNamespace(width=1000, height=1000)
VIEW = SimpleNamespace(perspective_matrix=Matrix.Diagonal((.25, .25, .25, 1)))
SQUARE = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]
RESULTS = []


def reset():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def wire(name, points, edges=None, collection=None):
    data = bpy.data.meshes.new(name)
    data.from_pydata(points, edges or [(0, 1)], [])
    obj = bpy.data.objects.new(name, data)
    (collection or bpy.context.collection).objects.link(obj)
    return obj


def curve(name, cp, bevel=.0):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = '3D'
    data.bevel_depth = bevel
    data.resolution_u = 1
    spline = data.splines.new('BEZIER')
    spline.bezier_points.add(1)
    a, b = spline.bezier_points
    a.handle_left_type = a.handle_right_type = b.handle_left_type = b.handle_right_type = 'FREE'
    a.co, a.handle_left, a.handle_right = cp[0], cp[0], cp[1]
    b.co, b.handle_left, b.handle_right = cp[3], cp[2], cp[3]
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    return obj


def source_square():
    source = wire('original source', SQUARE, [(0, 1), (1, 2), (2, 3), (3, 0)])
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    return source


def cache(**kwargs):
    bpy.context.view_layer.update()
    return OutlineSnapCache(bpy.context, (0, 0, 0), (0, 0, 1), 2, [SQUARE], **kwargs)


def screen(world, view=VIEW):
    clip = view.perspective_matrix @ Vector((*world, 1))
    return (500*(1+clip.x/clip.w), 500*(1+clip.y/clip.w))


def digest():
    values = []
    for o in bpy.data.objects:
        if o.type == 'MESH':
            values.append((o.name, [tuple(v.co) for v in o.data.vertices], [tuple(e.vertices) for e in o.data.edges]))
        elif o.type == 'CURVE':
            values.append((o.name, [(tuple(p.co), tuple(p.handle_left), tuple(p.handle_right)) for s in o.data.splines for p in s.bezier_points]))
    return hashlib.sha256(repr(values).encode()).hexdigest()


def debug(snap, mouse):
    nearest = snap._nearest_screen(mouse, snap._targets[0]['cp'])
    samples = snap._projected_samples[0]
    return dict(nearest=nearest, source_nearest=tuple(map(str,snap.nearest_source(snap._world(nearest[1])))),
                tile=(math.floor(mouse[0]/snap._tile), math.floor(mouse[1]/snap._tile)),
                target_in_tile=list(snap._grid.get((math.floor(mouse[0]/snap._tile), math.floor(mouse[1]/snap._tile)),())),
                coarse=min(nearest_on_segment(mouse,a,b)[2] for (_,a),(_,b) in zip(samples,samples[1:])), radius=snap._radius)


def run(name, fn):
    reset()
    try:
        evidence = fn()
        RESULTS.append(dict(case=name, passed=True, evidence=evidence))
    except Exception as exc:
        RESULTS.append(dict(case=name, passed=False, error=str(exc), traceback=traceback.format_exc()))


def exclusions_and_uniform_distance():
    source = source_square()
    wire('target', [(1.5, -2, 0), (1.5, 2, 0)])
    wire('excluded original circle', [(1.5, -2, 0), (1.5, 2, 0)])
    hidden = wire('hidden', [(1.5, -2, 0), (1.5, 2, 0)])
    hidden.hide_set(True)
    locked = wire('locked object', [(1.5, -2, 0), (1.5, 2, 0)])
    locked.hide_select = True
    locked_collection = bpy.data.collections.new('locked reference collection')
    bpy.context.scene.collection.children.link(locked_collection)
    locked_collection.hide_select = True
    wire('locked through collection', [(1.5, -2, 0), (1.5, 2, 0)], collection=locked_collection)
    text_data = bpy.data.curves.new('reference label', 'FONT')
    text_data.body = 'REFERENCE'
    text = bpy.data.objects.new('reference label', text_data)
    bpy.context.collection.objects.link(text)
    before = digest()
    snap = cache(excluded_objects=['excluded original circle'])
    assert snap.stats['target_segments'] == 1, snap.stats
    hit = snap.query(screen((1.5, .2, 0)), REGION, VIEW)
    assert hit and hit['object_name'] == 'target', hit
    assert abs(hit['thickness']-.5) < 1e-7
    assert (hit['nearest_source_point']-Vector((1, .2, 0))).length < 1e-6
    assert snap.query((900, 900), REGION, VIEW) is None
    assert snap.query((-1, 500), REGION, VIEW) is None
    assert digest() == before
    return dict(targets=snap.stats['target_segments'], thickness=hit['thickness'], source_unchanged=True)


def plane_rejection():
    source_square()
    wire('off plane', [(1.5, -2, .001), (1.5, 2, .001)])
    curve('off-plane handles', [(1.5, -1, 0), (2, -.3, .01), (1, .3, .01), (1.5, 1, 0)])
    snap = cache()
    assert snap.stats['target_segments'] == 0
    assert snap.query(screen((1.5, 0, 0)), REGION, VIEW) is None
    wire('within numeric epsilon', [(1.5, -2, 1e-6), (1.5, 2, 1e-6)])
    bpy.context.view_layer.update()
    snap.rebuild_targets()
    hit = snap.query(screen((1.5, 0, 0)), REGION, VIEW)
    assert hit and abs(hit['world_point'].z) < 1e-12
    edge_on = SimpleNamespace(perspective_matrix=Matrix(((.25, 0, 0, 0), (0, 0, .25, 0), (0, .25, 0, 0), (0, 0, 0, 1))))
    assert snap.query((687.5, 500), REGION, edge_on) is None
    return {'off_plane_endpoints_and_handles_rejected': True, 'tiny_noise_projected_to_plane': True, 'edge_on_rejected': True}


def bezier_refinement():
    source_square()
    cp = [(1.3, -.8, 0), (2.6, -.6, 0), (.8, .5, 0), (1.8, .9, 0)]
    target = curve('true cubic', cp, bevel=.2)
    before = digest()
    snap = cache()
    assert snap.stats['target_segments'] == 1, 'Bevel edges or fill tessellation became targets'
    t = .371234
    expected = _point(tuple(tuple(p) for p in cp), t)
    hit = snap.query(screen(expected), REGION, VIEW)
    assert hit and hit['object_name'] == target.name, debug(snap,screen(expected))
    assert abs(hit['target_parameter']-t) < 2e-6, hit
    assert hit['pixel_distance'] < 2e-5, hit
    assert (hit['world_point']-Vector(expected)).length < 1e-6
    # Full rational-cubic refinement also supports perspective projection.
    perspective = SimpleNamespace(perspective_matrix=Matrix(((.25, 0, 0, 0), (0, .25, 0, 0), (0, 0, .25, 0), (.15, .03, 0, 1))))
    hit2 = snap.query(screen(expected, perspective), REGION, perspective)
    assert hit2 and abs(hit2['target_parameter']-t) < 3e-6, hit2
    assert hit2['pixel_distance'] < 3e-5
    assert digest() == before
    return {'cubic_parameter': hit['target_parameter'], 'parameter_error': abs(hit['target_parameter']-t),
            'perspective_parameter_error': abs(hit2['target_parameter']-t), 'bevel_not_used': True}


def exact_source_curve_distance():
    source_square()
    k = 4/3*math.tan(math.pi/8)
    controls = []
    for quadrant in range(4):
        angle = quadrant*math.pi/2
        def rotate(x, y):
            return (x*math.cos(angle)-y*math.sin(angle), x*math.sin(angle)+y*math.cos(angle), 0)
        controls.append([rotate(1, 0), rotate(1, k), rotate(k, 1), rotate(0, 1)])
    # The source polyline is deliberately coarse. Exact complete segments must
    # supersede its chords, which would report ~0.493 rather than 0.2.
    diamond = [[(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)]]
    bpy.context.view_layer.update()
    snap = OutlineSnapCache(bpy.context, (0, 0, 0), (0, 0, 1), 2, diamond,
                            source_segments=[{'kind': 'BEZIER', 'cp': cp} for cp in controls])
    distance, nearest = snap.nearest_source((1.2/math.sqrt(2), 1.2/math.sqrt(2), 0))
    assert abs(distance-.2) < 1e-8, distance
    assert (nearest-Vector((1/math.sqrt(2), 1/math.sqrt(2), 0))).length < 1e-6
    return {'uniform_true_boundary_distance': distance, 'coarse_source_chords_ignored': True}


def arbitrary_world_plane():
    loop = [(0, 18+x, -23+y) for x, y, _ in SQUARE]
    source = wire('YZ source', loop, [(0, 1), (1, 2), (2, 3), (3, 0)])
    source.select_set(True)
    wire('YZ target', [(0, 19.5, -25), (0, 19.5, -21)])
    wire('parallel wrong plane', [(.01, 19.5, -25), (.01, 19.5, -21)])
    bpy.context.view_layer.update()
    snap = OutlineSnapCache(bpy.context, (0, 18, -23), (1, 0, 0), 2, [loop])
    view = SimpleNamespace(perspective_matrix=Matrix(((0, .25, 0, -4.5), (0, 0, .25, 5.75), (.25, 0, 0, 0), (0, 0, 0, 1))))
    hit = snap.query((687.5, 500), REGION, view)
    assert hit and hit['object_name'] == 'YZ target', hit
    assert abs(hit['thickness']-.5) < 1e-7
    assert (hit['nearest_source_point']-Vector((0, 19, -23))).length < 1e-6
    return {'translated_YZ_plane_supported': True, 'thickness': hit['thickness']}


def cache_lifecycle():
    source_square()
    wire('cache target', [(1.5, -2, 0), (1.5, 2, 0)])
    snap = cache()
    first = snap.query((687.5, 500), REGION, VIEW)
    assert first
    # A context exposing no scene, object list or dependency graph proves query
    # is not secretly scanning the scene on every mouse movement.
    snap.context = SimpleNamespace(preferences=bpy.context.preferences)
    for i in range(100):
        assert snap.query((687.5, 490+i*.2), REGION, VIEW), debug(snap,(687.5,490+i*.2))
    assert snap.stats['target_rebuilds'] == 1 and snap.stats['projection_rebuilds'] == 1
    different = SimpleNamespace(perspective_matrix=VIEW.perspective_matrix.copy())
    different.perspective_matrix[0][3] = .01
    assert snap.query((692.5, 500), REGION, different)
    assert snap.stats['projection_rebuilds'] == 2 and snap.stats['target_rebuilds'] == 1
    return {'queries_without_scene_access': 101, 'target_builds': 1, 'view_change_projection_rebuilds': 2}


def cubic_global_nearest():
    cp = ((-1, 0), (2, 3), (-2, 3), (1, 0))
    for point in ((0, 1), (-.5, 2.2), (1.1, .2), (0, 4)):
        nearest, t, distance = nearest_on_cubic(point, cp)
        dense = min(sum((a-b)**2 for a, b in zip(point, _point(cp, i/10000))) for i in range(10001))
        assert distance <= dense+1e-10, (point, t, distance, dense)
    return {'global_cubic_minimum_vs_10001_samples': '4 difficult queries passed'}


def target_liveness():
    source_square()
    collection = bpy.data.collections.new('dynamic target collection')
    bpy.context.scene.collection.children.link(collection)
    target = wire('dynamic target', [(1.5, -2, 0), (1.5, 2, 0)], collection=collection)
    snap = cache()
    query = lambda: snap.query((687.5, 500), REGION, VIEW)
    assert query()
    target.hide_set(True)
    assert query() is None
    target.hide_set(False)
    assert query()
    target.hide_select = True
    assert query() is None
    target.hide_select = False
    target.select_set(True)
    assert query() is None
    target.select_set(False)
    collection.hide_select = True
    assert query() is None
    collection.hide_select = False
    assert query()
    target.location.x = .1
    bpy.context.view_layer.update()
    assert query() is None, 'Transformed target retained obsolete cached snap point'
    target.location.x = 0
    bpy.context.view_layer.update()
    assert query()
    bpy.data.objects.remove(target, do_unlink=True)
    assert query() is None
    assert snap.stats['target_rebuilds'] == 1
    return {'hidden_locked_selected_transformed_deleted_targets_skipped': True, 'scene_rescans': 0}


def poly_and_zero_distance():
    source_square()
    data = bpy.data.curves.new('poly target', 'CURVE')
    data.dimensions = '3D'
    s = data.splines.new('POLY')
    s.points.add(1)
    s.points[0].co, s.points[1].co = (1.5, -2, 0, 1), (1.5, 2, 0, 1)
    obj = bpy.data.objects.new('poly target', data)
    bpy.context.collection.objects.link(obj)
    snap = cache()
    hit = snap.query((687.5, 500), REGION, VIEW)
    assert hit and hit['object_name'] == obj.name and abs(hit['thickness']-.5) < 1e-9
    bpy.data.objects.remove(obj, do_unlink=True)
    wire('coincident source boundary', [(1, -1, 0), (1, 1, 0)])
    bpy.context.view_layer.update()
    snap.rebuild_targets()
    assert snap.query((625, 500), REGION, VIEW) is None
    return {'native_poly_spline_supported': True, 'zero_thickness_snap_rejected': True}


def edited_target_geometry():
    source_square()
    target = wire('editable target', [(1.5,-2,0),(1.5,2,0),(-5,-5,0),(5,5,0)], [(0,1)])
    snap = cache()
    assert snap.query((687.5,500), REGION, VIEW)
    target.data.vertices[0].co.x += .2
    target.data.update()
    bpy.context.view_layer.update()
    assert snap.query((687.5,500), REGION, VIEW) is None
    bpy.data.objects.remove(target, do_unlink=True)
    target = curve('editable cubic', [(1.5,-1,0),(2,-.3,0),(1,.3,0),(1.5,1,0)])
    bpy.context.view_layer.update()
    snap.rebuild_targets()
    assert snap.query((687.5,500), REGION, VIEW)
    target.data.splines[0].bezier_points[0].handle_right.x += .1
    bpy.context.view_layer.update()
    assert snap.query((687.5,500), REGION, VIEW) is None
    return {'changed_mesh_endpoint_and_curve_handle_invalidate_cached_targets': True}


def geometry_module_contract():
    from extension import outline_geometry
    source = source_square()
    wire('contract target', [(1.5, -2, 0), (1.5, 2, 0)])
    bpy.context.view_layer.update()
    prepared = outline_geometry.prepare_sources([source])
    snap = OutlineSnapCache(bpy.context, prepared['origin'], prepared['normal'], prepared['scale'],
                            prepared['world_loops'], excluded_objects=prepared['source_names'],
                            source_segments=prepared['world_segments'])
    hit = snap.query((687.5, 500), REGION, VIEW)
    assert hit and abs(hit['thickness']-.5) < 1e-6
    return {'prepare_sources_exact_segment_contract': True, 'thickness': hit['thickness']}


def cpu_baseline():
    source_square()
    k = 4/3*math.tan(math.pi/8)
    queries = []
    for i in range(12):
        cx, cy, r = 1.5+.6*(i%3), -1.2+.8*(i//3), .22
        data = bpy.data.curves.new('benchmark circle', 'CURVE')
        data.dimensions = '3D'
        s = data.splines.new('BEZIER')
        s.bezier_points.add(3)
        s.use_cyclic_u = True
        for j, p in enumerate(s.bezier_points):
            angle = j*math.pi/2
            v = Vector((math.cos(angle), math.sin(angle), 0))
            t = Vector((-math.sin(angle), math.cos(angle), 0))
            p.co = Vector((cx, cy, 0))+r*v
            p.handle_left_type = p.handle_right_type = 'FREE'
            p.handle_left, p.handle_right = p.co-r*k*t, p.co+r*k*t
        obj = bpy.data.objects.new('benchmark circle '+str(i), data)
        bpy.context.collection.objects.link(obj)
        a, b = s.bezier_points[:2]
        cp = [tuple(a.co), tuple(a.handle_right), tuple(b.handle_left), tuple(b.co)]
        queries.extend(screen(_point(cp, .1+.08*j)) for j in range(10))
    started = time.perf_counter()
    snap = cache()
    snap.query(queries[0], REGION, VIEW)
    build_ms = (time.perf_counter()-started)*1000
    samples = []
    for _ in range(3):
        started = time.perf_counter()
        for xy in queries:
            assert snap.query(xy, REGION, VIEW)
        samples.append((time.perf_counter()-started)*1000/len(queries))
    assert snap.stats['target_segments'] == 48 and snap.stats['target_rebuilds'] == 1
    return {'native_target_circles': 12, 'cubic_segments': 48, 'queries_per_pass': 120,
            'median_warm_query_ms': round(statistics.median(samples), 5),
            'initial_target_and_projection_build_ms': round(build_ms, 3),
            'scope': 'Headless CPU only; no viewport/FPS claim'}


def overlapping_source_owners():
    loop_a = [(-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)]
    loop_b = [(1.6, -1, 0), (2.6, -1, 0), (2.6, 1, 0), (1.6, 1, 0)]
    segments = []
    for owner, loop in enumerate((loop_a, loop_b)):
        obj = wire('overlap source '+str(owner), loop, [(0,1),(1,2),(2,3),(3,0)])
        obj.select_set(True)
        segments.extend({'kind':'LINE', 'cp':[a,b], 'owner':owner}
                        for a,b in zip(loop, loop[1:]+loop[:1]))
    wire('inside A outside B', [(1.5, -.5, 0), (1.5, .5, 0)])
    bpy.context.view_layer.update()
    snap = OutlineSnapCache(bpy.context, (0,0,0), (0,0,1), 4,
                            [loop_a,loop_b], source_segments=segments)
    unrestricted = snap.query((687.5,500), REGION, VIEW)
    assert abs(unrestricted['thickness']-.1)<1e-7
    eligible = lambda p: ({0} if -2<p.x<2 and -2<p.y<2 else set()) | ({1} if 1.6<p.x<2.6 and -1<p.y<1 else set())
    hit = snap.query((687.5,500), REGION, VIEW, source_filter=eligible)
    assert hit and abs(hit['thickness']-.5)<1e-7, hit
    assert (hit['nearest_source_point']-Vector((2,0,0))).length < 1e-7
    assert snap.nearest_source((1.5,0,0), allowed_owners=set()) is None
    assert snap.query((687.5,500), REGION, VIEW, source_filter=lambda p:set()) is None
    # A closer target on the wrong side must not mask a slightly farther valid
    # target inside the same pixel tolerance.
    target = bpy.data.objects['inside A outside B']
    bpy.data.objects.remove(target, do_unlink=True)
    wire('nearer wrong side', [(2.02,-.5,0),(2.02,.5,0)])
    wire('farther valid side', [(1.96,-.5,0),(1.96,.5,0)])
    bpy.context.view_layer.update()
    snap.rebuild_targets()
    hit = snap.query(screen((2.01,0,0)), REGION, VIEW, source_filter=lambda p: {0} if p.x<2 else set())
    assert hit and hit['object_name']=='farther valid side', hit
    return {'overlap_inset_distance': .5, 'wrong_side_nearest_does_not_mask_valid_target': True}


run('visible selectable target filtering and constant thickness', exclusions_and_uniform_distance)
run('off-plane and edge-on snap rejection', plane_rejection)
run('true target cubic refinement, including perspective', bezier_refinement)
run('exact source cubic distance supersedes sampled chords', exact_source_curve_distance)
run('arbitrary translated source plane', arbitrary_world_plane)
run('no scene scan during mouse queries; projection invalidation', cache_lifecycle)
run('global nearest cubic source point', cubic_global_nearest)
run('cached target liveness and selection restrictions', target_liveness)
run('native poly curve and nonzero thickness', poly_and_zero_distance)
run('edited target endpoints and control handles', edited_target_geometry)
run('geometry module exact boundary contract', geometry_module_contract)
run('real Bezier target CPU query baseline', cpu_baseline)
run('per-source side ownership and competing target filter', overlapping_source_owners)

report = {'passed': all(r['passed'] for r in RESULTS), 'tests': RESULTS,
          'scope': 'Background Blender geometry and projection tests. No UI or GPU interaction.'}
out = ROOT/'tests'/'_artifacts'
out.mkdir(exist_ok=True)
(out/'outline_snap_results.json').write_text(json.dumps(report, indent=2))
print('OUTLINE_SNAP_TESTS', json.dumps(report))
if not report['passed']:
    raise RuntimeError('Outline snap tests failed')
