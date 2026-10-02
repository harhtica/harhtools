"""Real outline commits and synthetic modal controls without an interactive UI."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import bpy
from mathutils import Vector, Matrix, Euler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import extension as ext
from extension import outline_tool as ot, outline_geometry as og, outline_snap as osnap

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
cfg = ot.settings(); cfg.thickness = .2; cfg.direction = 'INWARD'; cfg.output_type = 'CURVE'
assert cfg.bl_rna.properties['output_type'].default == 'MESH'
assert cfg.bl_rna.properties['join_style'].default == 'MITER'
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

mesh_source = square('Mesh border source'); select(mesh_source)
mesh_source.data.materials.append(material)
mesh_signature = ot.source_signature([mesh_source])
cfg.output_type = 'MESH'; cfg.direction = 'OUTWARD'; cfg.join_style = 'MITER'
assert bpy.ops.view3d.harhtools_make_outline('EXEC_DEFAULT') == {'FINISHED'}
mesh_output = bpy.context.active_object
assert mesh_output.type == 'MESH' and len(mesh_output.data.polygons) == 4
assert all(len(face.vertices) == 4 and face.normal.z > .999 for face in mesh_output.data.polygons)
assert len(mesh_output.data.vertices) == 8 and len(mesh_output.data.edges) == 12
assert abs(sum(face.area for face in mesh_output.data.polygons) - 1.76) < 1e-5
assert list(mesh_output.data.materials) == [material] and mesh_output.users_collection == mesh_source.users_collection
assert mesh_output.data.uv_layers and mesh_source.hide_get()
assert ot.source_signature([mesh_source]) == mesh_signature and not ext.shape_library._catalog
checks.append('Sharp Mesh Border creates four connected quads, keeps materials/UVs/source and saves no preset')
bevel_source=square('Bevel border source');select(bevel_source)
cfg.bevel_enabled=True;cfg.bevel_profile='ROUND'
assert bpy.ops.view3d.harhtools_make_outline('EXEC_DEFAULT')=={'FINISHED'}
beveled=bpy.context.active_object
assert [m.type for m in beveled.modifiers]==['SOLIDIFY','BEVEL']
assert len(beveled.data.polygons)==4 and len(beveled.data.vertices)==8
assert not ext.shape_library._catalog
checks.append('Add Bevel creates editable native modifiers on the clean mesh border')
cfg.bevel_enabled=False
cfg.output_type = 'CURVE'; cfg.direction = 'INWARD'

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

from extension import outline_mesh as om
old_meshes = set(bpy.data.meshes)
real_mesh_make = om.make_mesh_data; calls.clear()
def fail_second_mesh(*args, **kwargs):
    calls.append(True)
    if len(calls) == 2:
        raise ValueError('injected second mesh failure')
    return real_mesh_make(*args, **kwargs)
om.make_mesh_data = fail_second_mesh
try:
    try:
        ot.commit_outlines(bpy.context, sources, ot.make_results(prepared, .1, 'OUTWARD', 'MITER'),
                           signature, output_type='MESH')
    except ValueError: pass
    else: raise AssertionError('Expected mesh batch failure')
finally:
    om.make_mesh_data = real_mesh_make
assert set(bpy.data.objects) == old_objects and set(bpy.data.meshes) == old_meshes
assert all(o.select_get() and not o.hide_get() for o in sources)
checks.append('failed second mesh rolls back new meshes without altering source visibility/selection')

left.data.splines[0].points[0].co.x += .1
try: ot.commit_outlines(bpy.context, sources, results, signature)
except ValueError as exc: assert 'changed' in str(exc)
else: raise AssertionError('Source changes must be rejected')
assert set(bpy.data.objects) == old_objects
checks.append('changed source cannot commit a stale preview')

# Coordinates stay planar under a shared affine transform even when each
# object's center rounds differently in Blender's float32 Vector interface.
far_matrix = (Matrix.Translation((1234.567, -876.543, 987.654))
              @ Euler((.71, -.48, .93)).to_matrix().to_4x4()
              @ Matrix.Diagonal((1.6, .72, 1.3, 1.0)))
far_left = square('Far tilted left'); far_right = square('Far tilted right')
for obj, shift in ((far_left, -4), (far_right, 4)):
    for p in obj.data.splines[0].points:
        p.co.x += shift
    obj.matrix_world = far_matrix
select(far_left, far_right)
far_sources, far_prepared = ot.prepare_selection(bpy.context)
assert len(far_prepared) == 2
left_owner = far_sources.index(far_left); right_owner = far_sources.index(far_right)
checks.append('translated tilted nonuniformly scaled objects keep their shared plane')

def far_world(point):
    return og._world_point(far_left.matrix_world, point)

# Probe near an edge, not merely at the center: casting world positions back
# to float32 can move either probe across that edge at this translation.
assert ot.source_owners_at(far_world((-3.000002, 0, 0)), far_prepared, inside=True) == {left_owner}
assert ot.source_owners_at(far_world((-2.999998, 0, 0)), far_prepared, inside=True) == set()
assert ot.source_owners_at(far_world((4, 0, 0)), far_prepared, inside=True) == {right_owner}
assert ot.source_owners_at(far_world((0, 0, 0)), far_prepared, inside=False) == {left_owner, right_owner}
first = far_prepared[0]
far_cache = osnap.OutlineSnapCache(bpy.context, first['_origin64'], first['_normal64'],
    max(item['scale'] for item in far_prepared),
    [loop for item in far_prepared for loop in item['world_loops']],
    excluded_objects=far_sources, lazy_targets=True,
    source_segments=[dict(segment, owner=index) for index, item in enumerate(far_prepared)
                     for segment in item['world_segments']])
distance, foot = far_cache.nearest_source(far_world((-3.25, 0, 0)), allowed_owners={left_owner})
assert abs(distance - .4) < 2e-6, distance
# The display foot is a Blender Vector; permit its final float32 storage
# rounding while requiring the computed thickness above to remain precise.
assert sum((a-b)**2 for a,b in zip(foot, far_world((-3, 0, 0)))) < (2e-4)**2
checks.append('precise translated ownership and original-source snap distances agree')

saved_matrix = far_right.matrix_world.copy()
normal = far_prepared[right_owner]['_normal64']
shifted = saved_matrix.copy()
shifted.translation = tuple(saved_matrix.translation[i] + .01 * normal[i] for i in range(3))
far_right.matrix_world = shifted; bpy.context.view_layer.update()
try:
    try: ot.prepare_selection(bpy.context)
    except ValueError as exc: assert 'same plane' in str(exc), str(exc)
    else: raise AssertionError('Separate real-depth planes must still be rejected')
finally:
    far_right.matrix_world = saved_matrix; bpy.context.view_layer.update()
checks.append('translated multi-object selection still rejects actual depth separation')

fixture = square('Mouse fixture'); prepared = [og.prepare_sources([fixture])]
class Harness:
    mouse = ot.VIEW3D_OT_harhtools_make_outline.mouse
    modal = ot.VIEW3D_OT_harhtools_make_outline.modal
    queue_pointer = ot.VIEW3D_OT_harhtools_make_outline.queue_pointer
    flush_pending = ot.VIEW3D_OT_harhtools_make_outline.flush_pending
    over_controls = lambda self, event: False
    def __init__(self):
        self._done = False; self._dragging = True; self._error = ''
        self._pending_mouse = None; self._last_mouse = None; self._preview_dirty = False
        self._region = SimpleNamespace(x=0,y=0,width=100,height=100)
        self._area = SimpleNamespace(type='VIEW_3D',tag_redraw=lambda:None)
        self._view = None; self._prepared = prepared
        self._world_loops = [list(loop) for loop in prepared[0]['world_loops']]
        self.point = Vector((.6,0,0)); self._plane_point = lambda xy:self.point
        self.hit = None; self._snap = SimpleNamespace(query=lambda *args,**kwargs:self.hit,
            nearest_source=lambda point,allowed_owners:ot._nearest_boundary(point,
                [list(loop) for i in allowed_owners for loop in self._prepared[i]['world_loops']]))
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
    def template_icon(self,**kwargs):assert bpy.app.background or kwargs['icon_value']>0
    def operator(self,name,*args,**kwargs):assert name in {'view3d.harhtools_make_outline','view3d.harhtools_copy_thickness','object.harhtools_border_bevel','object.harhtools_edit_profile'}
ot.draw_panel(Layout(),bpy.context)
cfg.output_type='MESH';cfg.bevel_enabled=True
for preset in ('ROUND','CHAMFER','CONCAVE','SQUARE','CUSTOM'):
    cfg.bevel_profile=preset;ot.draw_panel(Layout(),bpy.context)
checks.append('Make Outline and bevel profile panel controls resolve')
ext.shape_library.capture_shape = capture
ext.unregister(); ext.register(); ext.unregister()
assert not hasattr(bpy.types.WindowManager,'harhtools_outline')
checks.append('full package register/unregister/reregister cleans outline state')
(ARTIFACTS/'outline_tool_results.json').write_text(json.dumps(checks,indent=2))
print('OUTLINE_TOOL_PASS',json.dumps(checks))
