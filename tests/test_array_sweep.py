"""Signed circular sweeps reverse order while preserving fit size and pivots."""
import math
import sys
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace as NS
import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import extension as ext
from extension import array_core as core

for obj in list(bpy.data.objects): bpy.data.objects.remove(obj,do_unlink=True)
bpy.ops.mesh.primitive_cube_add(size=2,location=(4,3,2))
source = bpy.context.object
source.rotation_euler = (.2,.3,.4)
bpy.context.view_layer.update()
bpy.context.scene.cursor.location = (-1,-2,-3)
snap = core.snapshot(bpy.context,geometry=True)
original = source.matrix_world.copy()

def cfg(**kwargs):
    values = dict(mode='CIRCULAR',orientation='WORLD',count=5,radial_axis='Z',
                  sweep=math.pi,rotate_copies=True,pivot='BOUNDS',radius=9,
                  fit_ring=False,fit_side='CENTER',deform_enabled=False)
    values.update(kwargs)
    return NS(**values)

def plan(**kwargs): return core.build_plan(snap,cfg(**kwargs),bpy.context.scene)

def matrix_near(a,b):
    assert all(abs(x-y)<5e-5 for aa,bb in zip(a,b) for x,y in zip(aa,bb)), (a,b)

for pivot in ('BOUNDS','CURSOR'):
    for axis in 'XYZ':
        for orientation in ('WORLD','ACTIVE'):
            for magnitude in (.001,math.pi,math.radians(355),math.tau):
                options = dict(pivot=pivot,radial_axis=axis,orientation=orientation)
                positive = plan(sweep=magnitude,**options)
                negative = plan(sweep=-magnitude,**options)
                assert positive.pivot == negative.pivot
                assert positive.resolved_radius == negative.resolved_radius
                assert positive.new_object_count == negative.new_object_count == 5
                for a,b in zip(positive.transforms,negative.transforms): matrix_near(a.inverted(),b)
                if magnitude==math.tau:
                    assert (negative.transforms[-1] @ source.location-source.location).length > .1
print('PASS opposite rotations on all axes, active orientation, partial/full sweeps and no seam duplicate')

for side in ('INSIDE','CENTER','OUTSIDE'):
    for magnitude in (.001,math.pi,math.radians(355),math.tau):
        positive = plan(sweep=magnitude,fit_ring=True,fit_side=side)
        negative = plan(sweep=-magnitude,fit_ring=True,fit_side=side)
        assert positive.resolved_radius == negative.resolved_radius > 0
        assert positive.pivot == negative.pivot
        # The very large radius at .001 radians magnifies float inversion error.
        for i,transform in enumerate(negative.transforms,1):
            angle = (-magnitude/(6 if magnitude==math.tau else 5))*i
            expected = Matrix.Translation(negative.pivot) @ Matrix.Rotation(angle,4,negative.axis) @ Matrix.Translation(-negative.pivot)
            matrix_near(transform,expected)
print('PASS Fit Ring from Source retains radius, center and all three boundary choices')

# A known 60-degree construction footprint at a fixed pivot fits in both directions.
points = [(r*math.cos(a),r*math.sin(a),0) for r in (3,4) for a in (0,math.pi/3)]
for magnitude in (math.pi,math.radians(250),math.tau):
    positive = core.angular_fit(points,Vector(),Vector((0,0,1)),magnitude)
    negative = core.angular_fit(points,Vector(),Vector((0,0,1)),-magnitude)
    for name in ('count','total','remainder','closes'): assert positive[name]==negative[name]
    assert abs(negative['step']+math.pi/3)<1e-7
    assert negative['count']==int(magnitude/(math.pi/3)+1e-6)-1
for pivot in ('CURSOR','ACTIVE'):
    # Use an off-center active origin so it is a valid fixed rotation center.
    fitted_snap = core.Snapshot(snap.sources,snap.matrices,snap.bounds_points,
        Matrix.Identity(4),snap.active_source,snap.pointers,snap.data_pointers,
        snap.per_source_bounds,tuple(points))
    bpy.context.scene.cursor.location = (0,0,0)
    positive = core.build_plan(fitted_snap,cfg(pivot=pivot,fit_ring=True,sweep=math.tau),bpy.context.scene)
    negative = core.build_plan(fitted_snap,cfg(pivot=pivot,fit_ring=True,sweep=-math.tau),bpy.context.scene)
    assert negative.new_object_count==5 and negative.ring_info['step']<0
    for a,b in zip(positive.transforms,negative.transforms): matrix_near(a.inverted(),b)
print('PASS fixed Cursor/Last Origin fits use signed steps and identical counts/remainders')

for rotate in (True,False):
    negative = plan(sweep=-math.pi,rotate_copies=rotate)
    for transform in negative.transforms:
        if not rotate: matrix_near(transform.to_3x3().to_4x4(),Matrix.Identity(4))
    made = core.commit(bpy.context,snap,negative,linked=True)
    assert len(made)==5
    for obj,transform in zip(made,negative.transforms):
        matrix_near(obj.matrix_world,transform@original)
        assert obj.data==source.data
    for obj in made: bpy.data.objects.remove(obj,do_unlink=True)
assert source.matrix_world==original
for sweep in (0,math.tau+.1,-math.tau-.1,float('nan')):
    try: plan(sweep=sweep)
    except ValueError: pass
    else: raise AssertionError(f'Invalid sweep accepted: {sweep}')
print('PASS negative sweep generation, Rotate Copies off, source preservation and invalid inputs')

scratch = Path(mkdtemp(dir=ROOT/'tests'/'_artifacts',prefix='sweep_'))
ext.shortcuts._theme_path = lambda:scratch/'theme.json'
ext.shape_library._storage_override = scratch/'library'
ext.register()
try:
    settings = ext.array_tool.settings()
    settings.sweep = -math.tau
    assert abs(settings.sweep+math.tau)<1e-6
    settings.sweep = -.001
    assert abs(settings.sweep+.001)<1e-7
finally: ext.unregister()
print('ARRAY_SWEEP_PASS')
