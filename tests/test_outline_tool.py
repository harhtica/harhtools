"""Real outline commits and synthetic modal controls without an interactive UI."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import extension as ext
from extension import outline_tool as ot, outline_geometry as og

ARTIFACTS = ROOT / 'tests' / '_artifacts'
ARTIFACTS.mkdir(exist_ok=True)
scratch = Path(tempfile.mkdtemp(prefix='outline_tool_', dir=ARTIFACTS))
ext.shortcuts._theme_path = lambda: scratch / 'themes.json'
ext.shape_library._storage_override = scratch / 'library'
ext.register()
checks = []


def square(name, x=0):
    data = bpy.data.curves.new(name, 'CURVE'); data.dimensions = '2D'; data.fill_mode = 'BOTH'
    spline = data.splines.new('POLY'); spline.points.add(3); spline.use_cyclic_u = True
    for point, co in zip(spline.points, [(-1,-1,0,1),(1,-1,0,1),(1,1,0,1),(-1,1,0,1)]):
        point.co = co
    obj = bpy.data.objects.new(name, data); bpy.context.collection.objects.link(obj)
    obj.location.x = x
    bpy.context.view_layer.update()
    return obj


def select(*objects):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in objects:
        obj.hide_set(False); obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[-1]
    bpy.context.view_layer.update()


source = square('Outline source'); select(source)
material = bpy.data.materials.new('Outline material'); source.data.materials.append(material)
signature = ot.source_signature([source]); original = source.data
cfg = ot.settings(); cfg.thickness = .2; cfg.direction = 'INWARD'
capture = ext.shape_library.capture_shape
def forbidden(*args, **kwargs):
    raise AssertionError('Outline must never save a library preset')
ext.shape_library.capture_shape = forbidden
assert bpy.ops.view3d.harhtools_make_outline('EXEC_DEFAULT') == {'FINISHED'}
output = bpy.context.active_object
assert output.type == 'CURVE' and len(output.data.splines) == 2
assert source.hide_get() and source.data is original
assert ot.source_signature([source]) == signature
assert list(output.data.materials) == [material]
assert output.users_collection == source.users_collection
bpy.context.view_layer.update()
evaluated = output.evaluated_get(bpy.context.evaluated_depsgraph_get()); mesh = evaluated.to_mesh()
assert abs(sum(face.area for face in mesh.polygons) - 1.44) < 1e-5
evaluated.to_mesh_clear()
checks.append('operator creates a filled border, preserves materials/source and hides original')
assert not ext.shape_library._catalog
checks.append('outline creation does not capture library presets')

left = square('Left', -4); right = square('Right', 4); select(left, right)
sources, prepared = ot.prepare_selection(bpy.context)
results = ot.make_results(prepared, .1, 'OUTWARD')
created = ot.commit_outlines(bpy.context, sources, results, ot.source_signature(sources), hide_sources=False)
assert len(created) == 2 and all(o.select_get() for o in created)
assert not left.hide_get() and not right.hide_get()
assert created[0].data != created[1].data
checks.append('multiple selected shapes remain independent; keep-original option works')

hidden_collection = bpy.data.collections.new('A hidden collection')
bpy.context.scene.collection.children.link(hidden_collection); hidden_collection.hide_viewport = True
visible_collection = bpy.data.collections.new('B visible collection')
bpy.context.scene.collection.children.link(visible_collection)
multi = square('Multi collection source')
for collection in list(multi.users_collection): collection.objects.unlink(multi)
hidden_collection.objects.link(multi); visible_collection.objects.link(multi)
select(multi); assert multi.visible_get()
sources, prepared = ot.prepare_selection(bpy.context)
multi_output = ot.commit_outlines(bpy.context,sources,ot.make_results(prepared,.1,'INWARD'),
                                  ot.source_signature(sources))[0]
assert multi_output.visible_get() and set(multi_output.users_collection) == set(multi.users_collection)
checks.append('output retains all source collections and stays visible with hidden first collection')

select(left, right); sources, prepared = ot.prepare_selection(bpy.context)
results = ot.make_results(prepared, .1, 'INWARD')
signature = ot.source_signature(sources)
old_objects = set(bpy.data.objects); old_curves = set(bpy.data.curves)
real_make = og.make_curve_data; calls = []
def fail_second(*args, **kwargs):
    calls.append(True)
    if len(calls) == 2:
        raise ValueError('injected second output failure')
    return real_make(*args, **kwargs)
og.make_curve_data = fail_second
try:
    try: ot.commit_outlines(bpy.context, sources, results, signature)
    except ValueError: pass
    else: raise AssertionError('Expected batch failure')
finally: og.make_curve_data = real_make
assert set(bpy.data.objects) == old_objects and set(bpy.data.curves) == old_curves
assert all(o.select_get() and not o.hide_get() for o in sources)
checks.append('failed second output rolls back all data and restores selection/visibility')

left.data.splines[0].points[0].co.x += .1
try: ot.commit_outlines(bpy.context, sources, results, signature)
except ValueError as exc: assert 'changed' in str(exc)
else: raise AssertionError('Source changes must be rejected')
assert set(bpy.data.objects) == old_objects
checks.append('changed source cannot commit a stale preview')

fixture = square('Mouse fixture'); prepared = [og.prepare_sources([fixture])]
class Harness:
    mouse = ot.VIEW3D_OT_harhtools_make_outline.mouse
    modal = ot.VIEW3D_OT_harhtools_make_outline.modal
    over_controls = lambda self, event: False
    def __init__(self):
        self._done = False; self._dragging = True; self._error = ''
        self._region = SimpleNamespace(x=0,y=0,width=100,height=100)
        self._area = SimpleNamespace(type='VIEW_3D',tag_redraw=lambda:None)
        self._view = None; self._prepared = prepared
        self._world_loops = [list(loop) for loop in prepared[0]['world_loops']]
        self.point = Vector((.6,0,0)); self._plane_point = lambda xy:self.point
        self.hit = None; self._snap = SimpleNamespace(query=lambda *args,**kwargs:self.hit)
        self._snap_hit = None; self._measure = None
    def report(self,*args):pass

h = Harness(); event = SimpleNamespace(mouse_x=60,mouse_y=50,type='MOUSEMOVE',value='NOTHING')
cfg.direction = 'INWARD'; cfg.snap_geometry = False; cfg.thickness = .1
h.mouse(bpy.context,event)
assert abs(cfg.thickness-.4) < 1e-6
cfg.snap_geometry = True
h.hit = dict(thickness=.2,world_point=Vector((.8,0,0)),nearest_source_point=Vector((1,0,0)),object_name='Target')
h.mouse(bpy.context,event)
assert abs(cfg.thickness-.2) < 1e-6 and h._snap_hit is not None
h.hit['world_point'] = Vector((1.2,0,0))
h.mouse(bpy.context,event)
assert h._snap_hit is None and abs(cfg.thickness-.4) < 1e-6
checks.append('drag sets thickness; geometry snap is optional and cannot snap to opposite side')

overlap_a = square('Overlap A'); overlap_b = square('Overlap B', 2.1)
for p in overlap_a.data.splines[0].points: p.co.x *= 2
for p in overlap_b.data.splines[0].points: p.co.x *= .5
bpy.context.view_layer.update()
overlap_prepared = [og.prepare_sources([obj]) for obj in (overlap_a, overlap_b)]
point = Vector((1.5,0,0))
assert ot.source_owners_at(point, overlap_prepared, inside=True) == {0}
assert ot.source_owners_at(point, overlap_prepared, inside=False) == {1}
h._prepared = overlap_prepared; h.point = point; h.hit = None; cfg.snap_geometry = False
h.mouse(bpy.context,event)
assert abs(cfg.thickness-.5) < 1e-6
h._prepared = prepared
checks.append('overlapping selected objects measure only boundaries on the chosen inset/outset side')

h.hit = None; cfg.snap_geometry = False; h.point = Vector((.75,0,0))
event.type = 'LEFTMOUSE'; event.value = 'RELEASE'
assert h.modal(bpy.context,event) == {'RUNNING_MODAL'}
assert not h._dragging and abs(cfg.thickness-.25) < 1e-6
checks.append('release includes final drag position')
event.type = 'S'; event.value = 'PRESS'
assert h.modal(bpy.context,event) == {'RUNNING_MODAL'} and cfg.snap_geometry
checks.append('S key toggles geometry snapping without committing')

class Layout:
    enabled=True
    def box(self):return self
    def row(self):return self
    def label(self,*args,**kwargs):pass
    def prop(self,obj,name,*args,**kwargs):assert hasattr(obj,name),name
    def operator(self,name,*args,**kwargs):assert name=='view3d.harhtools_make_outline'
ot.draw_panel(Layout(),bpy.context)
checks.append('Make Outline panel controls resolve')
ext.shape_library.capture_shape = capture
ext.unregister(); ext.register(); ext.unregister()
assert not hasattr(bpy.types.WindowManager,'harhtools_outline')
checks.append('full package register/unregister/reregister cleans outline state')
(ARTIFACTS/'outline_tool_results.json').write_text(json.dumps(checks,indent=2))
print('OUTLINE_TOOL_PASS',json.dumps(checks))
