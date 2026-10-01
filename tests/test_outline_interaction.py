"""Actual modal/RNA outline callbacks with deterministic input and fake UI timers.

Checks event coalescing and final-setting correctness. This is not a rendered
viewport/FPS benchmark; timing reports only Python event dispatch in this fixture.
"""
import json
import math
from pathlib import Path
import sys
import time
from types import FunctionType, SimpleNamespace
from unittest.mock import patch

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extension import outline_tool as ot

OUTPUT = ROOT / 'tests' / '_artifacts'
OUTPUT.mkdir(exist_ok=True)
CHECKS = []
STATS = {}
CLOCK = [0.0]


def event(kind='MOUSEMOVE', value='NOTHING', x=800):
    return SimpleNamespace(type=kind, value=value, mouse_x=x, mouse_y=500,
                           shift=False, ctrl=False, alt=False, oskey=False)


class Manager:
    def __init__(self):
        self.added = []; self.removed = []; self.handlers = []
    def __getattr__(self, name):
        return getattr(bpy.context.window_manager, name)
    def event_timer_add(self, seconds, window=None):
        token = object(); self.added.append((token, seconds)); return token
    def event_timer_remove(self, token):
        self.removed.append(token)
    def modal_handler_add(self, operator):
        self.handlers.append(operator)


class FakeSnap:
    def __init__(self, *args, **kwargs):
        self.queries = 0
        self.boundaries = args[4]
    def query(self, *args, **kwargs):
        self.queries += 1
        return None
    def nearest_source(self, point, allowed_owners=None):
        return ot._nearest_boundary(point, self.boundaries)


class Harness:
    pass


# Invoke initializes every production state field; bind all actual operator
# methods so tests do not silently replace queue/flush/cache behavior.
for name, method in vars(ot.VIEW3D_OT_harhtools_make_outline).items():
    if isinstance(method, FunctionType):
        setattr(Harness, name, method)


def plane_point(self, xy):
    return Vector((xy[0] / 1000, 0, 0))


Harness._plane_point = plane_point
Harness.report = lambda self, levels, text: self.reports.append((levels, text))

data = bpy.data.curves.new('Interaction square', 'CURVE')
data.dimensions = '2D'; data.fill_mode = 'BOTH'
spline = data.splines.new('POLY'); spline.points.add(3); spline.use_cyclic_u = True
for p, co in zip(spline.points, ((-1,-1,0,1), (1,-1,0,1), (1,1,0,1), (-1,1,0,1))):
    p.co = co
source = bpy.data.objects.new('Interaction square', data)
bpy.context.collection.objects.link(source)
for obj in bpy.context.selected_objects:
    obj.select_set(False)
source.select_set(True); bpy.context.view_layer.objects.active = source
bpy.context.view_layer.update()

manager = Manager()
status_messages = []
redraws = []
region = SimpleNamespace(type='WINDOW', x=0, y=0, width=1000, height=1000)
view = SimpleNamespace(perspective_matrix=Matrix.Identity(4))
area = SimpleNamespace(type='VIEW_3D', regions=[region],
    spaces=SimpleNamespace(active=SimpleNamespace(region_3d=view)), tag_redraw=lambda: redraws.append(True))
window = SimpleNamespace(cursor_modal_set=lambda *a: None, cursor_modal_restore=lambda: None)
workspace = SimpleNamespace(status_text_set=lambda text: status_messages.append(text))
context = SimpleNamespace(mode='OBJECT', area=area, window=window, workspace=workspace,
    window_manager=manager, selected_objects=[source], active_object=source,
    view_layer=bpy.context.view_layer, preferences=bpy.context.preferences,
    scene=bpy.context.scene, collection=bpy.context.collection,
    evaluated_depsgraph_get=bpy.context.evaluated_depsgraph_get)
draw_handlers = []
def add_draw(*args):
    handle = object(); draw_handlers.append(handle); return handle
def remove_draw(handle, region_type):
    draw_handlers.remove(handle)
fake_bpy = SimpleNamespace(app=bpy.app, context=context, utils=bpy.utils,
    types=SimpleNamespace(SpaceView3D=SimpleNamespace(draw_handler_add=add_draw, draw_handler_remove=remove_draw)))

real_make = ot.make_results
build_calls = []
commit_calls = []
def counted_make(prepared, thickness, direction):
    build_calls.append((prepared, float(thickness), direction))
    return real_make(prepared, thickness, direction)
def counted_commit(ctx, sources, results, signature, **kwargs):
    commit_calls.append((results, signature, kwargs))
    return [source]


def invoke():
    cfg = ot.settings(context)
    cfg.thickness = .1; cfg.direction = 'INWARD'; cfg.snap_geometry = True
    h = Harness(); h.reports = []
    assert h.invoke(context, event()) == {'RUNNING_MODAL'}
    assert h._timer is not None
    assert abs(manager.added[-1][1] - 1/30) < 1e-9
    return h


def tick(h):
    CLOCK[0] += ot.PREVIEW_INTERVAL + 1e-8
    return h.modal(context, event('TIMER'))


ot.register()
try:
    timer = bpy.context.window_manager.event_timer_add(1/30, window=bpy.context.window)
    assert isinstance(timer, bpy.types.Timer)
    bpy.context.window_manager.event_timer_remove(timer)
    assert not hasattr(event('TIMER'), 'timer'), 'Real Blender events do not expose a timer identity'
    CHECKS.append('Blender timer add/remove APIs work; simulated TIMER has only real Event fields')
    with patch.object(ot, 'bpy', fake_bpy), patch.object(ot.outline_snap, 'OutlineSnapCache', FakeSnap), \
         patch.object(ot, 'make_results', counted_make), patch.object(ot, 'commit_outlines', counted_commit), \
         patch.object(ot.time, 'monotonic', lambda: CLOCK[0]):
        cfg = ot.settings(context)
        h = invoke()
        real_flush = h.flush_pending
        cadence_calls = []
        def simulated_work(ctx):
            cadence_calls.append(CLOCK[0])
            CLOCK[0] += .008  # A solve consumes part of the 33ms frame budget.
        h.flush_pending = simulated_work
        first_start = CLOCK[0]
        h.modal(context, event('TIMER'))
        CLOCK[0] = first_start + ot.PREVIEW_INTERVAL + 1e-6
        h.modal(context, event('TIMER'))
        assert len(cadence_calls) == 2, 'Deadline after solve-end incorrectly halves normal timer cadence'
        h.flush_pending = real_flush
        CHECKS.append('nonzero solve duration does not halve the 30Hz timer cadence')
        start_builds = len(build_calls); start_queries = h._snap.queries
        started = time.perf_counter()
        for index in range(500):
            assert h.modal(context, event(x=100 + index)) == {'RUNNING_MODAL'}
        STATS['idle_500_events_ms'] = (time.perf_counter() - started) * 1000
        assert len(build_calls) == start_builds and h._snap.queries == start_queries
        CHECKS.append('idle hover performs no snap query or geometry rebuild')

        h.modal(context, event('LEFTMOUSE', 'PRESS', 800))
        tick(h)  # Establish the next allowed refresh deadline before the burst.
        start_builds = len(build_calls); start_queries = h._snap.queries
        started = time.perf_counter()
        for index in range(500):
            h.modal(context, event(x=100 + index))
        STATS['drag_500_events_ms'] = (time.perf_counter() - started) * 1000
        assert len(build_calls) == start_builds and h._snap.queries == start_queries
        pending = h._pending_mouse
        assert h.modal(context, event('TIMER')) == {'PASS_THROUGH'}
        assert h._pending_mouse == pending and len(build_calls) == start_builds
        tick(h)
        assert h._pending_mouse is None
        assert h._snap.queries == start_queries + 1 and len(build_calls) == start_builds + 1
        assert abs(cfg.thickness - .401) < 1e-5
        STATS['queued_drag_events_per_build'] = 500
        CHECKS.append('500 drag events coalesce to one newest-pointer update; extra early TIMER events are gated')

        h.modal(context, event('MOUSEMOVE', x=550))
        h.modal(context, event('LEFTMOUSE', 'RELEASE', 650))
        assert not h._dragging and h._pending_mouse is None
        assert abs(cfg.thickness - .35) < 1e-5
        assert abs(build_calls[-1][1] - .35) < 1e-5
        CHECKS.append('mouse release flushes its final coordinate before preview settles')

        start_builds = len(build_calls)
        for value in (.12, .13, .14):
            cfg.thickness = value
        assert len(build_calls) == start_builds
        tick(h)
        assert len(build_calls) == start_builds + 1 and abs(build_calls[-1][1] - .14) < 1e-6
        start_builds = len(build_calls)
        cfg.snap_geometry = not cfg.snap_geometry
        tick(h)
        assert len(build_calls) == start_builds
        CHECKS.append('RNA slider changes coalesce; toggling snap does not rebuild unchanged geometry')

        cfg.thickness = 1.2
        tick(h)
        assert h._error and not h._results
        error = h._error; start_builds = len(build_calls)
        for _ in range(30):
            h.request_refresh(context)
            tick(h)
        assert len(build_calls) == start_builds and h._error == error
        CHECKS.append('identical invalid thickness reuses its error instead of rebuilding each tick')

        cfg.thickness = .2  # No preview tick: cached error still belongs to 1.2.
        assert h._error
        start_builds = len(build_calls); token = h._timer
        assert h.modal(context, event('RET', 'PRESS')) == {'FINISHED'}
        assert len(build_calls) == start_builds + 1
        assert build_calls[-1][0] is h._prepared and abs(build_calls[-1][1] - .2) < 1e-6
        assert commit_calls[-1][0][0]['thickness'] == build_calls[-1][1]
        assert manager.removed.count(token) == 1 and not draw_handlers
        CHECKS.append('Enter validates current precise geometry despite a stale preview error and removes the timer')

        h = invoke()
        h.modal(context, event('LEFTMOUSE', 'PRESS', 800))
        h.modal(context, event('MOUSEMOVE', x=700))
        start_builds = len(build_calls)
        assert h.modal(context, event('RET', 'PRESS')) == {'FINISHED'}
        assert len(build_calls) == start_builds + 1, 'Confirmation must skip an unnecessary preview rebuild'
        assert abs(commit_calls[-1][0][0]['thickness'] - .3) < 1e-5
        CHECKS.append('Enter flushes a queued drag coordinate and commits only the precise final geometry')

        h = invoke(); token = h._timer
        h.modal(context, event('LEFTMOUSE', 'PRESS', 800))
        h.modal(context, event('MOUSEMOVE', x=700))
        with patch.object(h, 'over_controls', return_value=True):
            assert h.modal(context, event('ESC', 'PRESS')) == {'CANCELLED'}
        assert manager.removed.count(token) == 1 and not draw_handlers
        assert bpy.app.driver_namespace.get(ot.STATE_KEY) is None
        assert abs(cfg.thickness - .1) < 1e-6
        CHECKS.append('Escape over sidebar cancels queued work, removes timer/handlers and restores settings')
finally:
    state = bpy.app.driver_namespace.get(ot.STATE_KEY)
    if state is not None:
        with patch.object(ot, 'bpy', fake_bpy):
            state.finish(context, cancel=True)
    ot.unregister()


# Compare cached ownership against the original full even-odd scan for a dense
# curved outline with a hole and a separate island, under a 3D plane transform.
transform = Matrix.Translation((3.0, -2.0, 4.0)) @ Euler((.4, .8, .2)).to_matrix().to_4x4() @ Matrix.Diagonal((1.4, .8, 1., 1.))
dense_loops = [
    [((2 + .3*math.cos(4*t))*math.cos(t), (2 + .3*math.cos(4*t))*math.sin(t))
     for t in (2*math.pi*i/2048 for i in range(2048))],
    [(.35*math.cos(t), .35*math.sin(t)) for t in (2*math.pi*i/256 for i in range(256))],
    [(5+.5*math.cos(t), .5*math.sin(t)) for t in (2*math.pi*i/128 for i in range(128))],
]
dense_data = bpy.data.curves.new('Dense ownership fixture', 'CURVE'); dense_data.dimensions = '2D'
for loop in dense_loops:
    s = dense_data.splines.new('POLY'); s.points.add(len(loop)-1); s.use_cyclic_u = True
    for p, co in zip(s.points, loop):
        p.co = (*co, 0, 1)
dense = bpy.data.objects.new('Dense ownership fixture', dense_data)
bpy.context.collection.objects.link(dense); dense.matrix_world = transform
bpy.context.view_layer.update()
prepared = ot.outline_geometry.prepare_sources([dense])
world_points = [transform @ Vector((-2.6 + (x+.37)*.14, -2.6 + (y+.29)*.14, 0))
                for x in range(60) for y in range(39)]
expected = []
for point in world_points:
    delta = point - Vector(prepared['origin'])
    xy = (delta.dot(Vector(prepared['u'])), delta.dot(Vector(prepared['v'])))
    expected.append(ot.outline_geometry._inside(xy, prepared['loops']))
started = time.perf_counter()
for point, inside in zip(world_points, expected):
    assert ot.source_owners_at(point, [prepared], inside=True) == ({0} if inside else set())
    assert ot.source_owners_at(point, [prepared], inside=False) == (set() if inside else {0})
STATS['ownership_grid_2340_points_ms'] = (time.perf_counter()-started)*1000
CHECKS.append('cached ownership matches exact even-odd scan across dense hole/island geometry and transformed plane')
cache = prepared['_harhtools_inside_index']
with patch.object(ot.outline_geometry, '_inside', side_effect=AssertionError('Full scan must not run after indexing')):
    started = time.perf_counter()
    for index in range(20000):
        point = world_points[index % len(world_points)]
        assert ot.source_owners_at(point, [prepared], inside=True) == ({0} if expected[index % len(expected)] else set())
    STATS['ownership_20000_cached_queries_ms'] = (time.perf_counter()-started)*1000
assert prepared['_harhtools_inside_index'] is cache
STATS['ownership_source_points'] = sum(map(len, prepared['loops']))
CHECKS.append('20,000 ownership queries reuse the same index without a full boundary scan')

report = dict(checks=CHECKS, timings=STATS,
    scope='Actual modal methods and registered RNA callbacks, fake UI timer/GPU handles; no viewport FPS claim')
(OUTPUT / 'outline_interaction_results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
print('OUTLINE_INTERACTION_PASS', json.dumps(report))
