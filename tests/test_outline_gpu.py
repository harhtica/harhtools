"""Actual outline draw methods with fake GPU/BLF APIs and real RNA properties.

This checks submitted geometry, uniform/property reads and cleanup behavior;
it does not render pixels or claim interactive viewport/GPU verification.
"""
import bpy
import hashlib
import json
import sys
import traceback
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extension import outline_tool as ot

CREATED = []
DRAWN = []
FONT = []
SHADERS = []
FAIL = {'batch': False, 'draw': False, 'uniform': False, 'font': False}
RESULTS = []


class Shader:
    def __init__(self, name):
        self.name = name
        self.uniforms = {}
        SHADERS.append(self)

    def bind(self):
        pass

    def uniform_float(self, key, value):
        if FAIL['uniform']:
            raise RuntimeError('injected uniform failure')
        self.uniforms[key] = tuple(value) if hasattr(value, '__iter__') else value


class Batch:
    def __init__(self, mode, data):
        if FAIL['batch']:
            raise RuntimeError('injected allocation failure')
        self.mode = mode
        self.data = {key: tuple(tuple(p) for p in value) for key, value in data.items()}
        CREATED.append(self)

    def draw(self, shader):
        if FAIL['draw']:
            raise RuntimeError('injected draw failure')
        DRAWN.append((self, dict(shader.uniforms)))


class State:
    def __init__(self):
        self.blend, self.depth, self.mask = 'ADDITIVE', 'LESS_EQUAL', True

    def blend_get(self): return self.blend
    def depth_test_get(self): return self.depth
    def depth_mask_get(self): return self.mask
    def blend_set(self, value): self.blend = value
    def depth_test_set(self, value): self.depth = value
    def depth_mask_set(self, value): self.mask = value
    def viewport_get(self): return (0, 0, 1280, 720)


gpu = ModuleType('gpu')
gpu.shader = SimpleNamespace(from_builtin=Shader)
gpu.state = State()
extras = ModuleType('gpu_extras')
extras.__path__ = []
batch_module = ModuleType('gpu_extras.batch')
batch_module.batch_for_shader = lambda shader, mode, data: Batch(mode, data)
extras.batch = batch_module
blf = ModuleType('blf')
blf.dimensions=lambda *args:(180,16)


def font(method, *args):
    if FAIL['font']:
        raise RuntimeError('injected font failure')
    FONT.append((method, args))


for method in ('size', 'position', 'color', 'draw'):
    setattr(blf, method, lambda *args, _method=method: font(_method, *args))


class Area:
    def __init__(self):
        self.type = 'VIEW_3D'
        self.redraws = 0

    def tag_redraw(self):
        self.redraws += 1


theme = SimpleNamespace(accent_color=(.8, .25, .45), light_color=(.95, .9, 1), remove_color=(1, .12, .15))
fake_context = SimpleNamespace(area=None, mode='OBJECT',
    preferences=SimpleNamespace(system=SimpleNamespace(ui_scale=1.25)),
    scene=bpy.context.scene, window_manager=bpy.context.window_manager)


def fixture(offset=0.0):
    return {'matrix_world': Matrix.Translation(Vector((1+offset, 2, 3))),
            'border_loops': [[(-1,-1),(1,-1),(1,1),(-1,1)],
                             [(-.8,-.8),(-.8,.8),(.8,.8),(.8,-.8)]]}


class Harness:
    draw_preview = ot.VIEW3D_OT_harhtools_make_outline.draw_preview
    draw_hint = ot.VIEW3D_OT_harhtools_make_outline.draw_hint
    refresh = ot.VIEW3D_OT_harhtools_make_outline.refresh

    def __init__(self):
        self._done = False
        self._area = Area()
        fake_context.area = self._area
        self._results = [fixture()]
        self._batches = self._shader = None
        self._error = ''
        self._measure = None
        self._dragging = False
        self._snap_hit = None
        self._preview_prepared = [{'tolerance': .00001}]
        self._prepared = [{'tolerance': .000001}]
        self.status = []
        self._workspace = SimpleNamespace(status_text_set=self.status.append)


def state_tuple():
    return gpu.state.blend, gpu.state.depth, gpu.state.mask


def frame(method):
    DRAWN.clear()
    before = state_tuple()
    method()
    assert state_tuple() == before, 'GPU state leaked'
    return list(DRAWN)


def run(name, fn):
    for key in FAIL:
        FAIL[key] = False
    try:
        evidence = fn()
        RESULTS.append(dict(case=name, passed=True, evidence=evidence))
    except Exception as exc:
        RESULTS.append(dict(case=name, passed=False, error=str(exc), traceback=traceback.format_exc()))
    finally:
        for key in FAIL:
            FAIL[key] = False


def geometry_cache():
    h = Harness()
    created = len(CREATED)
    draws = frame(h.draw_preview)
    assert len(CREATED) == created+1 and len(draws) == 1
    batch = h._batches
    assert batch.mode == 'LINES' and len(batch.data['pos']) == 16
    expected = []
    for loop in h._results[0]['border_loops']:
        points = [h._results[0]['matrix_world'] @ Vector((*p,0)) for p in loop]
        expected.extend(tuple(p) for a,b in zip(points,points[1:]+points[:1]) for p in (a,b))
    assert batch.data['pos'] == tuple(expected), 'World matrix or hole outline omitted'
    assert draws[0][1]['viewportSize'] == (1280,720)
    assert draws[0][1]['lineWidth'] == 2.5
    frame(h.draw_preview)
    assert h._batches is batch and len(CREATED) == created+1
    with patch.object(ot, 'make_results', return_value=[fixture(1)]):
        h.refresh(fake_context)
    assert h._batches is None
    frame(h.draw_preview)
    assert h._batches is not batch and len(CREATED) == created+2
    assert h._area.redraws == 1 and h.status
    return {'hole_and_outer_outline_submitted': True, 'unchanged_redraw_allocations': 0,
            'actual_refresh_invalidates_batch': True, 'world_transform_applied': True}


def measurement_and_theme():
    h = Harness()
    frame(h.draw_preview)
    saved = h._batches
    h._measure = (Vector((0,0,0)),Vector((.5,0,0)))
    h._dragging = True
    draws = frame(h.draw_preview)
    assert len(draws) == 2 and h._batches is saved
    assert draws[1][0].data['pos'] == ((0.,0.,0.),(.5,0.,0.))
    assert draws[0][1]['color'] == (*theme.accent_color,1)
    assert draws[1][1]['color'] == (*theme.light_color,1)
    h._dragging = False
    assert len(frame(h.draw_preview)) == 1
    return {'measurement_drawn_only_during_drag': True, 'theme_properties_resolve': True}


def shaded_bevel():
    h=Harness();h._surface={'pos':[(0,0,0),(1,0,0),(0,1,-.2)],'color':[(.8,.8,.8,1)]*3}
    draws=frame(h.draw_preview)
    assert [draw[0].mode for draw in draws]==['TRIS','LINES']
    assert h._surface_shader.name=='SMOOTH_COLOR' and h._surface_batch.data['pos'][2][2]==-.2
    count=len(CREATED);batch=h._surface_batch;frame(h.draw_preview)
    assert h._surface_batch is batch and len(CREATED)==count
    FAIL['draw']=True
    try:frame(h.draw_preview)
    except RuntimeError:pass
    else:raise AssertionError('Expected draw failure')
    finally:FAIL['draw']=False
    assert state_tuple()==('ADDITIVE','LESS_EQUAL',True)
    return {'shaded_depth_geometry_before_lines':True,'cached_gpu_buffers':True,'restored_depth_blend_and_mask':True}


def failure_cleanup():
    for stage in ('batch','uniform','draw'):
        h = Harness()
        before = state_tuple()
        FAIL[stage] = True
        try:
            h.draw_preview()
            raise AssertionError('Expected injected '+stage+' failure')
        except RuntimeError as exc:
            assert 'injected' in str(exc)
        finally:
            FAIL[stage] = False
        assert state_tuple() == before, 'State leaked after '+stage
    return {'allocation_uniform_and_draw_failures_restore_state': True}


def empty_and_error():
    h = Harness()
    h._results = []
    before = len(CREATED)
    assert not frame(h.draw_preview)
    assert h._batches is False and len(CREATED) == before
    with patch.object(ot, 'make_results', side_effect=ValueError('Inset collapses this shape')):
        h.refresh(fake_context)
    assert not h._results and h._error == 'Inset collapses this shape'
    assert not frame(h.draw_preview)
    FONT.clear()
    h.draw_hint()
    text = next(args[1] for method,args in FONT if method == 'draw')
    color = next(args[1:] for method,args in FONT if method == 'color')
    assert text == 'Cannot create: Inset collapses this shape'
    assert color == (*theme.remove_color,1)
    return {'empty_preview_creates_no_batch': True, 'geometry_error_displays_error_hint': True}


def guards():
    h = Harness()
    for area,done in ((None,False),(Area(),False),(h._area,True)):
        fake_context.area = area
        h._done = done
        old = len(CREATED),len(SHADERS),len(FONT),len(DRAWN)
        h.draw_preview()
        h.draw_hint()
        assert old == (len(CREATED),len(SHADERS),len(FONT),len(DRAWN))
    return {'no_context_foreign_area_and_finished_session_are_noops': True,
            'scope':'WINDOW callbacks guarded by originating area; no actual viewport invocation'}


def hint_real_properties():
    h = Harness()
    cfg = bpy.context.window_manager.harhtools_outline
    assert {'thickness','direction','snap_geometry','hide_sources'} <= set(cfg.bl_rna.properties.keys())
    cfg.thickness = .125
    cfg.snap_geometry = True
    h._snap_hit = {'object_name':'Nearby target'}
    FONT.clear()
    h.draw_hint()
    text = next(args[1] for method,args in FONT if method == 'draw')
    assert text.startswith('Thickness ') and 'Snap ON (S)' in text and text.endswith(' | Nearby target')
    assert next(args[1] for method,args in FONT if method == 'size') == 16
    cfg.snap_geometry = False
    h._snap_hit = None
    FONT.clear()
    h.draw_hint()
    assert 'Snap OFF (S)' in next(args[1] for method,args in FONT if method == 'draw')
    before = state_tuple()
    FAIL['font'] = True
    try:
        h.draw_hint()
        raise AssertionError('Expected injected font failure')
    except RuntimeError as exc:
        assert 'injected font' in str(exc)
    finally:
        FAIL['font'] = False
    assert state_tuple() == before
    return {'real_registered_RNA_properties_used': True, 'units_and_snap_name_rendered': True,
            'font_failure_has_no_GPU_state_effect': True}


def snap_feedback():
    from bpy_extras import view3d_utils
    hit={'target_world_points':[(0,0,0),(1,0,0)],'world_point':(.4,0,0)}
    region=SimpleNamespace(width=1000,height=800)
    with patch.object(view3d_utils,'location_3d_to_region_2d',lambda r,v,p:Vector((400+100*p.x,400+100*p.y))), \
         patch.object(ot.outline_pick,'bpy',SimpleNamespace(context=fake_context)):
        before=state_tuple();DRAWN.clear()
        ot.outline_pick.draw_feedback(hit,region,None,'Snap target · border · 0.25 studs',[(.4,-1,0),(.4,0,0)])
        assert state_tuple()==before and len(DRAWN)==3
        assert DRAWN[0][0].data['pos'][:2]==((400.,400.,0.),(500.,400.,0.))
        assert len(DRAWN[1][0].data['pos'])==10,'Target edge plus diamond marker'
        assert DRAWN[1][1]['color']==(.15,1.,.8,1.)
        assert DRAWN[2][0].data['pos']==((440.,300.,0.),(440.,400.,0.))
        FAIL['draw']=True
        try:ot.outline_pick.draw_feedback(hit,region,None,'test')
        except RuntimeError:pass
        else:raise AssertionError('Expected draw failure')
        finally:FAIL['draw']=False
        assert state_tuple()==before
    return {'target_edge_diamond_measurement_label':True,'high_contrast_understroke':True,'GPU_state_restored':True}


ot.register()
try:
    with patch.dict(sys.modules, {'gpu':gpu,'gpu_extras':extras,'gpu_extras.batch':batch_module,'blf':blf}), \
         patch.object(ot, 'bpy', SimpleNamespace(context=fake_context,utils=bpy.utils,app=bpy.app)), \
         patch.object(ot.shortcuts, 'settings', lambda *a,**kw:theme):
        run('preview geometry cache and actual refresh invalidation', geometry_cache)
        run('measurement and theme uniforms', measurement_and_theme)
        run('native bevel surface drawing and cache', shaded_bevel)
        run('GPU state restoration under injected failures', failure_cleanup)
        run('empty and failed outline preview', empty_and_error)
        run('draw callback guards', guards)
        run('hint uses actual registered settings and unit formatter', hint_real_properties)
        run('visible target edge, snap marker and distance feedback', snap_feedback)
finally:
    ot.unregister()

report = dict(passed=all(r['passed'] for r in RESULTS), tests=RESULTS,
              source_sha256=hashlib.sha256(Path(ot.__file__).read_bytes()).hexdigest(),
              scope='Actual outline draw/refresh methods with fake GPU/BLF and context; real registered RNA settings. No real viewport, pixel or GPU timing claim.')
out = ROOT/'tests'/'_artifacts'
out.mkdir(exist_ok=True)
(out/'outline_gpu_results.json').write_text(json.dumps(report,indent=2))
print('OUTLINE_GPU_TESTS',json.dumps(report))
if not report['passed']:
    raise RuntimeError('Outline GPU mock tests failed')
