"""Progressive array transforms, textured previews and committed geometry agree."""
import math
import sys
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace as NS
import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import extension as ext
from extension import array_core as core, array_tween as tween, array_material_preview as preview


def select(objects):
    for obj in bpy.context.selected_objects: obj.select_set(False)
    for obj in objects: obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.context.view_layer.update()


def clear():
    for obj in list(bpy.data.objects): bpy.data.objects.remove(obj, do_unlink=True)


def plane(name, location=(0, 0, 0)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-2,-1,0), (2,-1,0), (2,1,0), (-2,1,0)], [], [(0,1,2,3)])
    uv = mesh.uv_layers.new(name='Atlas')
    for loop in mesh.loops:
        p = mesh.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = (.6 + p.x*.05, .4 + p.y*.1)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    select([obj])
    return obj


def config(**kwargs):
    values = dict(mode='LINEAR', axes='Y', orientation='WORLD', count=4, gap=.3,
        fit_length=False, fit_ring=False, pivot='CURSOR', radial_axis='Z', radius=8,
        sweep=math.tau, rotate_copies=True, fit_side='CENTER', deform_enabled=True,
        deform_scale=25., deform_keep_gap=True, deform_ease='LINEAR',
        deform_offset=(0,0,0), deform_rotation=(0,0,0))
    values.update(kwargs)
    return NS(**values)


def near(a, b, tol=3e-5):
    assert (Vector(a)-Vector(b)).length < tol, (a, b)


def matrix_near(a, b):
    for aa, bb in zip(a, b): near(aa, bb)


def plan_for(objects, **kwargs):
    select(objects)
    snap = core.snapshot(bpy.context)
    return snap, core.build_plan(snap, config(**kwargs), bpy.context.scene)


def signature(objects, transforms=(Matrix.Identity(4),)):
    corners = []
    for obj in objects:
        for transform in transforms:
            matrix = transform @ obj.matrix_world
            for loop in obj.data.loops:
                p = matrix @ obj.data.vertices[loop.vertex_index].co
                uv = obj.data.uv_layers.active.data[loop.index].uv
                corners.append((tuple(round(v,4) for v in p), tuple(round(v,5) for v in uv)))
    return sorted(corners)


clear()
source = plane('Off-center original', (5,3,2))
original = signature([source])
snap, plan = plan_for([source])
for index, transform in enumerate(plan.transforms):
    expected = 1 - .25*(index+1)
    near(transform.to_scale(), (expected,)*3)
    near((transform @ source.matrix_world.translation).xz, (5,2))
all_poses = [Matrix.Identity(4), *plan.transforms]
for first, second in zip(all_poses, all_poses[1:]):
    upper = max((first @ p).y for p in snap.bounds_points)
    lower = min((second @ p).y for p in snap.bounds_points)
    assert abs(lower-upper-.3) < 2e-5
assert signature([source]) == original
print('PASS 100/75/50/25 percent uniform taper around group center and equal edge gaps')

for values in ({'deform_enabled':False}, {'deform_scale':100.}):
    cfg = config(**values)
    old = core._base_plan(snap, cfg, bpy.context.scene)
    new = core.build_plan(snap, cfg, bpy.context.scene)
    assert all(a == b for a,b in zip(old.transforms, new.transforms))
snap, plan = plan_for([source], deform_keep_gap=False)
near(plan.transforms[-1] @ source.matrix_world.translation, (5,9.9,2))
for style, first_size in [('LINEAR',.75), ('SMOOTH',1-.75*7/27),
                          ('EASE_IN',1-.75/9), ('EASE_OUT',1-.75*5/9)]:
    _, plan = plan_for([source], deform_ease=style)
    assert abs(plan.transforms[0].to_scale().x-first_size) < 1e-6
    near(plan.transforms[-1].to_scale(), (.25,)*3)
print('PASS unchanged legacy/no-op positions, optional fixed spacing and easing endpoints')

# Local axes, a rotated multi-object group and progressive twist use one group center.
source.rotation_euler = (.1,.2,.7)
other = plane('Second piece', (8,3,2))
snap, plan = plan_for([source,other], orientation='ACTIVE', deform_rotation=(0,0,.8))
direction = plan.frame.to_3x3() @ Vector((0,1,0))
previous = Matrix.Identity(4)
distance = (source.matrix_world.translation-other.matrix_world.translation).length
for i, transform in enumerate(plan.transforms, 1):
    low = min((transform @ p).dot(direction) for p in snap.bounds_points)
    high = max((previous @ p).dot(direction) for p in snap.bounds_points)
    assert abs(low-high-.3) < 3e-5
    changed = ((transform @ source.matrix_world.translation) -
               (transform @ other.matrix_world.translation)).length
    assert abs(changed-distance*(1-.25*i)) < 2e-5
    previous = transform
print('PASS rotated active axes, twisting groups, internal proportions and retained gaps')

snap, plan = plan_for([source,other], orientation='ACTIVE', deform_keep_gap=False,
    deform_offset=(1,2,3), deform_rotation=(.2,.3,.4))
base = core._base_plan(snap, config(orientation='ACTIVE'), bpy.context.scene)
local_points = [plan.frame.transposed() @ p for p in snap.bounds_points]
lo, hi = core._bounds(local_points)
center = plan.frame @ ((lo+hi)*.5)
near(plan.transforms[-1] @ center,
     base.transforms[-1] @ center + plan.frame.to_3x3() @ Vector((1,2,3)))
near(plan.transforms[-1].to_scale(), (.25,)*3)
print('PASS additional movement follows selected axes and rotation keeps the group center')

clear()
source = plane('Orbit source', (7,1,2))
bpy.context.scene.cursor.location = (1,1,2)
for rotate in (True,False):
    snap, plan = plan_for([source], mode='CIRCULAR', rotate_copies=rotate, count=3)
    center = source.matrix_world.translation
    for i, transform in enumerate(plan.transforms,1):
        # 3 new copies + original: quarter-circle steps, original remains unchanged.
        angle = i*math.pi/2
        near(transform @ center, (1+6*math.cos(angle),1+6*math.sin(angle),2))
        near(transform.to_scale(), (1-.25*i,)*3)
    near(plan.pivot, bpy.context.scene.cursor.location)
for fit_values in [dict(mode='CIRCULAR',fit_ring=True,pivot='BOUNDS'),
                   dict(fit_length=True)]:
    objects = [source]
    if fit_values.get('fit_length'):
        objects.append(plane('Bookend', (7,20,2)))
    snap, plan = plan_for(objects, **fit_values)
    base = core._base_plan(snap, config(**fit_values), bpy.context.scene)
    assert all(a == b for a,b in zip(plan.transforms,base.transforms))
print('PASS circular anchor/pivot, both rotation modes, and unchanged fit operations')

# Intermediate animation must scale too, and end exactly at the commit transform.
motion = tween.TweenPreview()
snap, plan = plan_for([source], mode='CIRCULAR', count=3)
motion.retarget(plan.transforms, 'test', mode='CIRCULAR', now=0.)
for matrix, opacity in motion.sample(now=.08):
    assert .25 < matrix.to_scale().x < 1
    assert matrix.determinant() > 0 and 0 <= opacity <= 1
for (matrix,_), target in zip(motion.sample(now=1.), plan.transforms): matrix_near(matrix,target)
grown = core.build_plan(snap, config(mode='CIRCULAR',count=3,deform_scale=180.), bpy.context.scene)
motion.retarget(grown.transforms, 'test', mode='CIRCULAR', now=1.)
for matrix, _ in motion.sample(now=1.08): assert matrix.determinant() > 0
for (matrix,_), target in zip(motion.sample(now=2.), grown.transforms): matrix_near(matrix,target)
print('PASS tweened scale/rotation with positive scale and exact final poses')

scratch = Path(mkdtemp(dir=ROOT/'tests'/'_artifacts', prefix='deform_'))
ext.shortcuts._theme_path = lambda: scratch/'theme.json'
ext.shape_library._storage_override = scratch/'library'
ext.register()
try:
    cfg = ext.array_tool.settings()
    cfg.deform_enabled = True
    cfg.deform_scale = 25
    cfg.deform_offset_studs = (1,2,3)
    near(cfg.deform_offset_studs, (1,2,3))
    near(cfg.deform_offset, Vector((1,2,3))/ext.display_units.factor())
    assert hasattr(bpy.context.window_manager,'harhtools_expanded_array_deform')
    ext.array_tool.changed(cfg, bpy.context)
    original = signature([source])
    pool = preview.MaterialPreview(bpy.context.scene, NS(local_view=None))
    pool.rebuild(bpy.context, snap)
    pool.sync([(t,1.) for t in plan.transforms], Matrix.Identity(4), Matrix.Identity(4))
    assert signature(pool.objects) == signature([source], plan.transforms)
    ids = [o.as_pointer() for o in pool.objects]
    pool.sync([(t,1.) for t in grown.transforms], Matrix.Identity(4), Matrix.Identity(4))
    assert ids == [o.as_pointer() for o in pool.objects]
    assert signature([source]) == original
    pool.clear()
    copies = core.commit(bpy.context,snap,plan,linked=True)
    assert all(o.data == source.data for o in copies)
    assert signature(copies) == signature([source], plan.transforms)
    assert signature([source]) == original
    for obj in copies: bpy.data.objects.remove(obj,do_unlink=True)
    select([source])
    expected = signature([source],(Matrix.Identity(4),*plan.transforms))
    result = core.commit(bpy.context,snap,plan,join_generated=True)
    assert signature(result) == expected
    near(result[0].matrix_world.translation, bpy.context.scene.cursor.location)
    print('PASS registered controls, stud conversions, stable previews, linked and joined geometry/UVs')
finally:
    preview.purge()
    ext.unregister()
print('ARRAY_DEFORM_PASS')
