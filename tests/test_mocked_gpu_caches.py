"""Call real overlay/cursor methods with instrumented fake GPU and font APIs.

Checks drawing coverage and object reuse/invalidation, not rendered pixels,
hardware timings, or the actual interactive Blender viewport.
"""
import bpy
import collections
import hashlib
import json
import sys
import traceback
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / '_artifacts'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from mathutils import Matrix, Quaternion, Vector
import bpy_extras.view3d_utils as projection

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extension import shape_builder as sb, fill_groups as fg

points = [Vector((x, y, 0)) for x in range(5) for y in range(2)]
edges = [(2*x, 2*x+1) for x in range(5)]
edges += [(2*x+y, 2*(x+1)+y) for x in range(4) for y in range(2)]
arr = sb.build_arrangement(points, edges)
arr['edge_fragments'] = sb.curve_geometry.edge_fragments(arr)
A, B, C, D = [sb.region_at_world(arr, Vector((x+.5, .5, 0))) for x in range(4)]
assert len({A, B, C, D}) == 4 and arr['junctions']

CREATED = []
DRAWN = []
FONT_CALLS = []


class Shader:
    def __init__(self, name):
        self.name = name
        self.uniforms = {}

    def bind(self):
        pass

    def uniform_float(self, name, value):
        self.uniforms[name] = tuple(value) if hasattr(value, '__iter__') else value


class Batch:
    def __init__(self, mode, data):
        self.mode = mode
        self.data = {key: tuple(tuple(p) for p in value) for key, value in data.items()}
        CREATED.append(self)

    def draw(self, shader):
        DRAWN.append((self, dict(shader.uniforms)))


class State:
    def __init__(self):
        self.blend, self.depth, self.mask = 'NONE', 'LESS_EQUAL', True

    def blend_get(self): return self.blend
    def depth_test_get(self): return self.depth
    def depth_mask_get(self): return self.mask
    def blend_set(self, value): self.blend = value
    def depth_test_set(self, value): self.depth = value
    def depth_mask_set(self, value): self.mask = value
    def viewport_get(self): return (0, 0, 800, 600)


gpu = ModuleType('gpu')
gpu.shader = SimpleNamespace(from_builtin=Shader)
gpu.state = State()
gpu_extras = ModuleType('gpu_extras')
gpu_extras.__path__ = []
batch_module = ModuleType('gpu_extras.batch')
batch_module.batch_for_shader = lambda shader, mode, data: Batch(mode, data)
gpu_extras.batch = batch_module
blf = ModuleType('blf')
for method in ['size', 'color', 'position', 'draw']:
    setattr(blf, method, lambda *a, _name=method, **kw: FONT_CALLS.append((_name, a)))
blf.dimensions = lambda font, text: (len(text)*7, 14)

cfg = SimpleNamespace(preview_opacity=50, accent_color=(.8, .3, .5),
                      remove_color=(1, .1, .2), light_color=(.9, .9, 1),
                      remove_modifier='ALT', confirm_key='RET')
fake_context = SimpleNamespace(area=None, preferences=SimpleNamespace(system=SimpleNamespace(ui_scale=1.0)))
clock = [10.2]


class Harness:
    draw_overlay = sb.VIEW3D_OT_arch_shape_builder.draw_overlay
    draw_cursor = sb.VIEW3D_OT_arch_shape_builder.draw_cursor
    draw_comets = sb.VIEW3D_OT_arch_shape_builder.draw_comets
    preview_boundaries = sb.VIEW3D_OT_arch_shape_builder.preview_boundaries
    projection_cache = sb.VIEW3D_OT_arch_shape_builder.projection_cache

    def __init__(self, groups, hover):
        self._done = False
        self._arr = arr
        self._groups = fg.copy_groups(groups)
        self._selected = fg.selected_regions(groups)
        self._hover = hover
        self._hover_edge = -1
        self._alt = self._edge_mode = self._painting = self._navigation = False
        self._retained_edges = set(range(len(arr['edge_fragments'])))
        self._dirty = True
        self._shader = self._cursor_shader = self._comet_shader = None
        self._selected_batch = self._hover_batch = None
        self._feedback = {}
        self._feedback_batches = {}
        self._comets = {}
        self._comet_paths = {}
        self._outline_key = self._hover_outline_key = None
        self._outline = []
        self._hover_outline = []
        self._projection_key = None
        self._projected = {}
        self._screen_line_cache = {}
        self._junction_batches = None
        self._cursor_xy = None
        self._trail = []
        self._region = SimpleNamespace(type='WINDOW', x=0, y=0, width=800, height=600)
        self._view = SimpleNamespace(perspective_matrix=Matrix.Diagonal((.2, .2, .2, 1)),
                                     view_rotation=Quaternion())
        self._area = SimpleNamespace(as_pointer=lambda: 100, regions=[self._region])
        fake_context.area = self._area


def region_positions(ids):
    return collections.Counter(tuple(arr['world'][v])
        for rid in ids for i in arr['regions'][rid]['triangles'] for v in arr['triangles'][i])


def frame(method):
    DRAWN.clear()
    before = (gpu.state.blend, gpu.state.depth, gpu.state.mask)
    method()
    assert (gpu.state.blend, gpu.state.depth, gpu.state.mask) == before, 'GPU state not restored'
    return list(DRAWN)


def drawn_positions(draws):
    return sum((collections.Counter(batch.data['pos']) for batch, uniforms in draws
                if uniforms.get('color', (0, 0, 0, 0))[3] > 0), collections.Counter())


RESULTS = []


def run(name, fn):
    try:
        evidence = fn()
        RESULTS.append(dict(case=name, passed=True, evidence=evidence))
    except Exception as exc:
        RESULTS.append(dict(case=name, passed=False, error=str(exc), traceback=traceback.format_exc()))


def merged_feedback_coverage():
    h = Harness([{A, B}, {C}], B)
    h._feedback[B] = (10.0, True)
    draws = frame(h.draw_overlay)
    assert drawn_positions(draws) == region_positions({A, B, C}), 'Part of merged hovered fill disappeared or doubled'
    assert h._hover_batch is None  # The hovered atomic B is in the feedback layer.
    assert collections.Counter(h._selected_batch.data['pos']) == region_positions({A,C})
    assert collections.Counter(h._feedback_batches[B].data['pos']) == region_positions({B})
    h._alt = True
    h._dirty = True
    draws = frame(h.draw_overlay)
    assert drawn_positions(draws) == region_positions({A, B, C}), 'Remove hover lost unaffected merged member'
    h._feedback.clear();h._dirty=True
    frame(h.draw_overlay)
    assert collections.Counter(h._hover_batch.data['pos']) == region_positions({B})
    assert collections.Counter(h._selected_batch.data['pos']) == region_positions({A,C})
    return {'all_three_selected_regions_drawn_once': True,
            'merged_nonfeedback_member_kept_visible': True,
            'add_and_remove_hover_covered': True}


def feedback_reused():
    h = Harness([{A, B}], B)
    h._feedback[B] = (10.0, True)
    frame(h.draw_overlay)
    cached = h._feedback_batches[B]
    made = len(CREATED)
    clock[0] = 10.25
    frame(h.draw_overlay)
    assert h._feedback_batches[B] is cached and len(CREATED) == made
    # Another redraw/reaction may rebuild base/hover fills, but not immutable
    # feedback geometry. A later event for the same region also uses its batch.
    h._hover = A
    h._dirty = True
    h._feedback[B] = (10.1, True)
    frame(h.draw_overlay)
    assert h._feedback_batches[B] is cached
    h._feedback.clear()
    h._dirty = True
    draws = frame(h.draw_overlay)
    assert drawn_positions(draws) == region_positions({A, B})
    return {'same_feedback_batch_during_animation_and_later_event': True,
            'unchanged_frame_batch_allocations': 0,
            'persistent_fill_restored_after_feedback': True}


def cursor_reuse_and_invalidation():
    h = Harness([{A}, {B}, {C}], A)
    frame(h.draw_overlay)
    real_projection = projection.location_3d_to_region_2d
    with patch.object(projection, 'location_3d_to_region_2d', wraps=real_projection) as project:
        frame(h.draw_cursor)
        selected = h._screen_line_cache['selected'][2]
        hover = h._screen_line_cache['hover'][2]
        markers = tuple(h._junction_batches)
        assert selected is not None and hover is not None and all(markers)
        calls = project.call_count
        made = len(CREATED)
        frame(h.draw_cursor)
        assert project.call_count == calls and len(CREATED) == made
        assert h._screen_line_cache['selected'][2] is selected
        assert tuple(h._junction_batches) == markers
        # View navigation changes screen-space coordinates and all relevant GPU
        # batches while leaving the world-space source arrangement untouched.
        h._view.perspective_matrix[0][3] += .05
        frame(h.draw_cursor)
        assert project.call_count > calls
        assert h._screen_line_cache['selected'][2] is not selected
        assert h._screen_line_cache['hover'][2] is not hover
        assert all(a is not b for a, b in zip(h._junction_batches, markers))
        selected = h._screen_line_cache['selected'][2]
        hover = h._screen_line_cache['hover'][2]
        markers = tuple(h._junction_batches)
        calls = project.call_count
        # Fill ownership removes a seam; screen geometry changes but immutable
        # world vertices and junction positions should retain projection caches.
        old_edges = len(h._outline)
        h._groups = [{A, B}, {C}]
        h._selected = {A, B, C}
        h._dirty = True
        frame(h.draw_overlay)
        assert len(h._outline) < old_edges
        frame(h.draw_cursor)
        assert h._screen_line_cache['selected'][2] is not selected
        assert h._screen_line_cache['hover'][2] is hover
        assert tuple(h._junction_batches) == markers
        assert project.call_count == calls
        # Moving inside an earlier merged owner keeps selection cached but
        # previews the new atomic region, so its internal guide remains usable.
        selected = h._screen_line_cache['selected'][2]
        hover = h._screen_line_cache['hover'][2]
        h._hover = B
        h._dirty = True
        frame(h.draw_overlay)
        frame(h.draw_cursor)
        assert h._screen_line_cache['selected'][2] is selected
        assert h._screen_line_cache['hover'][2] is not hover
        # Viewport resize and UI scale affect stroke/marker geometry as well.
        h._region.width += 100
        frame(h.draw_cursor)
        assert h._screen_line_cache['selected'][2] is not selected
        markers = tuple(h._junction_batches)
        selected = h._screen_line_cache['selected'][2]
        fake_context.preferences.system.ui_scale = 1.5
        frame(h.draw_cursor)
        assert h._screen_line_cache['selected'][2] is not selected
        assert all(a is not b for a, b in zip(h._junction_batches, markers))
        fake_context.preferences.system.ui_scale = 1.0
    return {'unchanged_frame_new_batches': 0, 'unchanged_frame_projections': 0,
            'view_change_rebuilt_lines_and_junctions': True,
            'ownership_change_rebuilt_lines_only': True,
            'atomic_hover_changes_without_rebuilding_selected_lines': True,
            'resize_and_ui_scale_invalidated_screen_geometry': True}


with patch.dict(sys.modules, {'gpu': gpu, 'gpu_extras': gpu_extras,
                             'gpu_extras.batch': batch_module, 'blf': blf}), \
     patch.object(sb, 'bpy', SimpleNamespace(context=fake_context)), \
     patch.object(sb.shortcuts, 'settings', lambda *a, **kw: cfg), \
     patch.object(sb.shortcuts, 'key_label', lambda key: 'Enter'), \
     patch.object(sb.time, 'monotonic', lambda: clock[0]):
    run('actual overlay: merged feedback preserves all fill coverage', merged_feedback_coverage)
    run('actual overlay: feedback batches reused and persistent fill restored', feedback_reused)
    run('actual cursor: screen geometry cached and invalidated correctly', cursor_reuse_and_invalidation)

report = dict(passed=all(r['passed'] for r in RESULTS), tests=RESULTS,
              source_sha256=hashlib.sha256(Path(sb.__file__).read_bytes()).hexdigest(),
              scope='Actual draw_overlay/draw_cursor methods with fake GPU/font APIs and context; real boundary/projection math. No actual viewport, pixel, or GPU timing claim.')
path = OUTPUT_DIR / 'mocked_gpu_cache_results.json'
path.write_text(json.dumps(report, indent=2))
print('MOCKED_GPU_CACHE_REGRESSION', json.dumps(report))
if not report['passed']:
    raise RuntimeError('Mocked GPU cache regression failed: ' + str(path))
