"""Headless regression of real modal/mouse methods and multi-fill transactions.

No UI or GPU is used. Only screen projection, redraw/status and animation hooks
are replaced. Region building, per-event modal logic and output creation are real.
"""
import bpy
import hashlib
import json
import sys
import traceback
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / '_artifacts'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
from types import SimpleNamespace
from mathutils import Vector
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extension import shape_builder as sb, fill_groups as fg

RESULTS = []
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

# Four unit cells sharing three interior dividers. Different clicks must retain
# the common boundary; only a gesture explicitly crossing it may merge owners.
verts = [(x, y, 0) for x in range(5) for y in range(2)]
edges = [(2*x, 2*x+1) for x in range(5)]
edges += [(2*x+y, 2*(x+1)+y) for x in range(4) for y in range(2)]
mesh = bpy.data.meshes.new('Modal regression source')
mesh.from_pydata(verts, edges, [])
source = bpy.data.objects.new('Modal regression source', mesh)
bpy.context.collection.objects.link(source)
source.select_set(True)
bpy.context.view_layer.objects.active = source
bpy.context.view_layer.update()
arr, names = sb.build_pen_arrangement(bpy.context, gap_snap=0)
cell_ids = [sb.region_at_world(arr, Vector((x+.5, .5, 0))) for x in range(4)]
assert len(set(cell_ids)) == 4 and min(cell_ids) >= 0, cell_ids
A, B, C, D = cell_ids


def source_digest():
    return hashlib.sha256(repr((list(source.matrix_world),
        [tuple(v.co) for v in source.data.vertices],
        [tuple(e.vertices) for e in source.data.edges],
        [tuple(p.vertices) for p in source.data.polygons])).encode()).hexdigest()


SOURCE_DIGEST = source_digest()
cfg = SimpleNamespace(remove_modifier='ALT', confirm_key='RET', cancel_key='ESC', undo_key='Z')
# mouse() intentionally consults the real WindowManager to support live sidebar
# changes. Register only that test property; no add-on or user settings are saved.
if not hasattr(bpy.types.WindowManager, 'arch_shape_builder_edit_mode'):
    bpy.types.WindowManager.arch_shape_builder_edit_mode = bpy.props.EnumProperty(
        items=[('REGIONS', 'Regions', ''), ('EDGES', 'Edges', '')], default='REGIONS')
bpy.context.window_manager.arch_shape_builder_edit_mode = 'REGIONS'


class Harness:
    modal = sb.VIEW3D_OT_arch_shape_builder.modal
    mouse = sb.VIEW3D_OT_arch_shape_builder.mouse
    over_controls = sb.VIEW3D_OT_arch_shape_builder.over_controls

    def __init__(self, groups=()):
        self._region = SimpleNamespace(type='WINDOW', x=0, y=0, width=800, height=600)
        self._area = SimpleNamespace(type='VIEW_3D', regions=[self._region], tag_redraw=lambda: None)
        self._done = False
        self._selected = fg.selected_regions(groups)
        self._groups = fg.copy_groups(groups)
        self._stroke_groups = fg.snapshot_groups(groups)
        self._stroke_hits = set()
        self._hover = self._hover_edge = -1
        self._painting = self._navigation = self._edge_mode = self._touched = False
        self._retained_edges = set(range(len(arr['edge_fragments'])))
        self._history = []
        self._last_xy = None
        self._dirty = True
        self._mode = 'ADD'
        self._alt_held = self._alt = False
        self._adding = True
        self._cursor_xy = None
        self._trail = []
        self._feedback = {}
        self._comets = {}
        self._comet_paths = {}
        self._arr = arr
        self._sources = names
        self._guide_snapshot = sb.guide_selection_snapshot(bpy.context)
        self.feedback_calls = []
        self.status_updates = 0
        self.reports = []

    def hit(self, x, y):
        return sb.region_at_world(self._arr, Vector((x/100-1, y/100-1, 0)))

    def update_status(self):
        self.status_updates += 1

    def mark_feedback(self, rid, adding):
        self.feedback_calls.append((rid, adding))
        self._feedback[rid] = (0, adding)

    def finish(self):
        self._done = True

    def report(self, level, message):
        self.reports.append((list(level), message))


ctx = SimpleNamespace(window=SimpleNamespace(modal_operators=[]), window_manager=bpy.context.window_manager)


def event(kind, value='NOTHING', x=150, y=150, alt=False, ctrl=False):
    return SimpleNamespace(type=kind, value=value, mouse_x=x, mouse_y=y,
                           alt=alt, ctrl=ctrl, shift=False, oskey=False)


def send(h, *events):
    for e in events:
        result = h.modal(ctx, e)
        assert result == {'RUNNING_MODAL'}, (e.type, e.value, result)


def click(h, cell, alt=False):
    x = 150 + 100*cell
    send(h, event('LEFTMOUSE', 'PRESS', x=x, alt=alt),
         event('LEFTMOUSE', 'RELEASE', x=x, alt=alt))


def drag(h, first, last, alt=False):
    send(h, event('LEFTMOUSE', 'PRESS', x=150+100*first, alt=alt),
         event('MOUSEMOVE', x=150+100*last, alt=alt),
         event('LEFTMOUSE', 'RELEASE', x=150+100*last, alt=alt))


def snapshot_data():
    return ({o.as_pointer() for o in bpy.data.objects},
            {m.as_pointer() for m in bpy.data.meshes},
            {c.as_pointer() for c in bpy.data.curves})


def select_source():
    for o in bpy.context.selected_objects:
        o.select_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source


def run_case(name, fn):
    try:
        evidence = fn() or {}
        assert source_digest() == SOURCE_DIGEST, 'Source geometry changed'
        RESULTS.append(dict(case=name, passed=True, evidence=evidence))
    except Exception as exc:
        RESULTS.append(dict(case=name, passed=False, error=str(exc), traceback=traceback.format_exc()))


def separate_clicks():
    h = Harness()
    click(h, 0)
    click(h, 1)
    assert h._groups == [{A}, {B}], h._groups
    assert len(h._history) == 2
    assert not h._painting
    return {'groups': [sorted(g) for g in h._groups], 'undo_strokes': len(h._history)}


def hover_is_readonly():
    h = Harness([{A, B}, {C}])
    old = fg.snapshot_groups(h._groups)
    send(h, event('MOUSEMOVE', x=450), event('MOUSEMOVE', x=250),
         event('MOUSEMOVE', x=350, alt=True), event('MOUSEMOVE', x=450, alt=False))
    assert fg.snapshot_groups(h._groups) == old
    assert h._selected == {A, B, C}
    assert not h.feedback_calls and not h._history
    assert not h._stroke_hits
    return {'no_fills_added_erased_or_merged': True, 'feedback_calls': 0}


def drag_touched_only():
    h = Harness([{A}, {B}, {C}, {D}])
    drag(h, 0, 1)
    assert h._groups == [{A, B}, {C}, {D}], h._groups
    assert h._stroke_hits == {A, B}
    # A hit on one member of an existing fill retains the complete owner.
    click(h, 1)
    assert h._groups == [{A, B}, {C}, {D}], h._groups
    assert fg.group_for_region(h._groups, B) == {A, B}
    return {'only_touched_fills_merged': True, 'whole_existing_group_retained': True}


def erase_one_fill():
    h = Harness([{A, B}, {C}, {D}])
    click(h, 1, alt=True)
    assert h._groups == [{C}, {D}], h._groups
    assert h._selected == {C, D}
    assert set(h.feedback_calls) == {(A, False), (B, False)}
    send(h, event('Z', 'PRESS', ctrl=True))
    assert h._groups == [{A, B}, {C}, {D}]
    assert not h._painting and not h._feedback and not h._stroke_hits
    return {'whole_hit_fill_erased': True, 'untouched_fills_preserved': 2, 'undo_restores_stroke': True}


def undo_drag():
    h = Harness([{A}, {B}, {C}, {D}])
    drag(h, 0, 1)
    send(h, event('Z', 'PRESS', ctrl=True))
    assert h._groups == [{A}, {B}, {C}, {D}]
    assert not h._history and not h._painting
    return {'pre_gesture_ownership_restored': True}


def drag_new_fill():
    h = Harness()
    drag(h, 0, 2)
    assert h._groups == [{A, B, C}], h._groups
    assert len(h._history) == 1
    return {'continuous_drag_creates_one_fill': True, 'regions': 3}


def output_validation_rollback(output_type):
    select_source()
    before = snapshot_data()
    calls = []
    target = sb.curve_geometry if output_type == 'CURVE' else sb
    name = 'curve_data' if output_type == 'CURVE' else 'make_shape_mesh'
    real = getattr(target, name)
    def fail_second(*a, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('injected second output validation failure')
        return real(*a, **kw)
    with patch.object(target, name, fail_second), patch.object(sb, 'cut_original_guides') as cut:
        try:
            sb.commit_fill_groups(bpy.context, arr, [{A}, {B}], output_type=output_type, cut_guides=True)
            raise AssertionError('Commit should have failed')
        except RuntimeError as exc:
            assert 'injected second output' in str(exc)
        assert not cut.called, 'Guides cut before every output validated'
    assert len(calls) == 2
    assert snapshot_data() == before, 'Leaked partial output datablock/object'
    assert list(bpy.context.selected_objects) == [source]
    return {'type': output_type, 'no_partial_objects_or_datablocks': True, 'guide_cut_calls': 0}


def cut_once():
    select_source()
    calls = []
    def spy(context, expected):
        calls.append([o.name for o in context.selected_objects])
        assert context.selected_objects[:] == [source]
        return {'finished': True}
    before = snapshot_data()
    with patch.object(sb, 'cut_original_guides', spy):
        outputs = sb.commit_fill_groups(bpy.context, arr, [{A}, {B}], output_type='CURVE', cut_guides=True)
    assert len(calls) == 1 and len(outputs) == 2
    assert set(bpy.context.selected_objects) == set(outputs)
    assert bpy.context.view_layer.objects.active == outputs[-1]
    for o in outputs:
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.curves.remove(data)
    select_source()
    assert snapshot_data() == before
    return {'cut_calls': 1, 'cut_selection': calls[0], 'outputs': 2}


def cut_failure_rollback():
    select_source()
    before = snapshot_data()
    calls = []
    def fail(context, expected):
        calls.append([o.name for o in context.selected_objects])
        raise RuntimeError('injected cut validation failure')
    with patch.object(sb, 'cut_original_guides', fail):
        try:
            sb.commit_fill_groups(bpy.context, arr, [{A}, {B}], output_type='CURVE', cut_guides=True)
            raise AssertionError('Cut should have failed')
        except RuntimeError as exc:
            assert 'injected cut' in str(exc)
    assert len(calls) == 1
    assert snapshot_data() == before
    assert list(bpy.context.selected_objects) == [source]
    return {'linked_outputs_removed': True, 'datablocks_removed': True, 'source_selection_preserved': True}


with patch.object(sb.shortcuts, 'settings', lambda *a, **kw: cfg), \
     patch.object(sb.shortcuts, 'remove_held', lambda e, *a: e.alt):
    run_case('actual modal: adjacent clicks create separate fills', separate_clicks)
    run_case('actual modal: hover and modifier hover do not modify fills', hover_is_readonly)
    run_case('actual modal: drag merges only touched owners; existing fill is whole', drag_touched_only)
    run_case('actual modal: erase one whole fill and undo that stroke', erase_one_fill)
    run_case('actual modal: undo merge restores prior groups', undo_drag)
    run_case('actual modal: continuous drag creates one new fill', drag_new_fill)

run_case('commit: second curve output failure rolls back earlier data', lambda: output_validation_rollback('CURVE'))
run_case('commit: second mesh output failure rolls back earlier data', lambda: output_validation_rollback('MESH'))
run_case('commit: two outputs cut original guides only once', cut_once)
run_case('commit: cut validation failure rolls back linked outputs', cut_failure_rollback)

report = dict(passed=all(row['passed'] for row in RESULTS), tests=RESULTS,
              arrangement_regions=len(arr['regions']), source_unchanged=source_digest() == SOURCE_DIGEST,
              methodology='Real modal(), mouse(), region arrangement and commit methods. Only projection/UI animation hooks mocked. No GPU/UI use.')
path = OUTPUT_DIR / 'modal_gesture_regression_results.json'
path.write_text(json.dumps(report, indent=2))
print('MODAL_GESTURE_REGRESSION', json.dumps(report))
if not report['passed']:
    raise RuntimeError('Modal gesture regression failed: inspect ' + str(path))
