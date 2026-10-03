"""Opposite curvature preserves starting direction, original geometry and fitting."""
import math
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace as NS
import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import extension as ext
from extension import array_core as core, array_material_preview as preview

for obj in list(bpy.data.objects): bpy.data.objects.remove(obj,do_unlink=True)
bpy.ops.mesh.primitive_cube_add(size=2,location=(4,3,2))
source = bpy.context.object
source.rotation_euler = (.2,.3,.4)
source.scale = (1,2,.4)
bpy.context.view_layer.update()
bpy.context.scene.cursor.location = (-1,-2,-3)
snap = core.snapshot(bpy.context,geometry=True)
original = source.matrix_world.copy()
uv = [tuple(d.uv) for d in source.data.uv_layers.active.data]

def cfg(**kwargs):
    values = dict(mode='CIRCULAR',orientation='WORLD',count=5,radial_axis='Z',
                  sweep=math.radians(115),rotate_copies=True,pivot='BOUNDS',radius=9,
                  fit_ring=False,fit_side='OUTSIDE',deform_enabled=False,flip_bend=False)
    values.update(kwargs)
    return NS(**values)

def plan(**kwargs): return core.build_plan(snap,cfg(**kwargs),bpy.context.scene)

def near(a,b,tol=8e-5): assert (Vector(a)-Vector(b)).length<tol,(a,b)

def matrix_near(a,b):
    for aa,bb in zip(a,b): near(aa,bb)

for axis in 'XYZ':
    for orientation in ('WORLD','ACTIVE'):
        for fit in (False,True):
            for side in ('INSIDE','CENTER','OUTSIDE'):
                for sweep in (math.radians(115),-math.radians(115),math.tau,-math.tau):
                    options = dict(radial_axis=axis,orientation=orientation,fit_ring=fit,fit_side=side,sweep=sweep)
                    normal, flipped = plan(**options), plan(flip_bend=True,**options)
                    assert normal.resolved_radius==flipped.resolved_radius
                    assert normal.new_object_count==flipped.new_object_count==5
                    inverse = normal.frame.transposed()
                    low,high = core._bounds(tuple(inverse@p for p in snap.bounds_points))
                    anchor = normal.frame@((low+high)*.5)
                    radial = (anchor-normal.pivot).normalized()
                    tangent = normal.axis.cross(radial)
                    near((normal.pivot+flipped.pivot)*.5,anchor)
                    for a,b in zip(normal.transforms,flipped.transforms):
                        first,second = a@anchor-anchor,b@anchor-anchor
                        assert abs(first.dot(tangent)-second.dot(tangent))<8e-5
                        assert abs(first.dot(radial)+second.dot(radial))<8e-5
                        assert abs(second.dot(normal.axis))<8e-5
                        matrix_near(a.to_3x3().transposed(),b.to_3x3())
                        assert b.determinant()>0
print('PASS opposite curvature with same travel direction, every axis/frame, fit boundary and signed sweep')

# A saved Source-only option must not move an explicit cursor/origin center.
for pivot in ('CURSOR','ACTIVE'):
    for fit in (False,True):
        # An off-center active origin is needed to define a usable orbit.
        offset_snap = replace(snap,active_matrix=Matrix.Identity(4))
        normal = core.build_plan(offset_snap,cfg(pivot=pivot,fit_ring=fit),bpy.context.scene)
        flipped = core.build_plan(offset_snap,cfg(pivot=pivot,fit_ring=fit,flip_bend=True),bpy.context.scene)
        assert normal.pivot==flipped.pivot
        assert normal.transforms==flipped.transforms
print('PASS explicit Cursor/Last Origin centers remain unchanged')

for rotate in (False,True):
    normal = plan(rotate_copies=rotate)
    flipped = plan(rotate_copies=rotate,flip_bend=True)
    if not rotate:
        for transform in flipped.transforms: matrix_near(transform.to_3x3(),Matrix.Identity(3))
    pool = preview.MaterialPreview(bpy.context.scene,NS(local_view=None))
    pool.rebuild(bpy.context,snap)
    pool.sync([(t,1.) for t in flipped.transforms],Matrix.Identity(4),Matrix.Identity(4))
    expected = [obj.matrix_world.copy() for obj in pool.objects]
    pool.clear()
    copies = core.commit(bpy.context,snap,flipped,linked=True)
    for obj,matrix in zip(copies,expected):
        matrix_near(obj.matrix_world,matrix)
        assert obj.data==source.data
    for obj in copies: bpy.data.objects.remove(obj,do_unlink=True)
assert source.matrix_world==original
assert [tuple(d.uv) for d in source.data.uv_layers.active.data]==uv
print('PASS preview matches generation, optional rotation, original matrix and UV preservation')

flipped = plan(flip_bend=True,fit_ring=True)
expected = sorted(tuple(round(x,4) for x in (t@original)@v.co)
    for t in (Matrix.Identity(4),*flipped.transforms) for v in source.data.vertices)
joined = core.commit(bpy.context,snap,flipped,join_generated=True)[0]
actual = sorted(tuple(round(x,4) for x in joined.matrix_world@v.co) for v in joined.data.vertices)
assert actual==expected
near(joined.matrix_world.translation,flipped.pivot)
print('PASS joined geometry uses flipped center as origin')

scratch = Path(mkdtemp(dir=ROOT/'tests'/'_artifacts',prefix='bend_'))
ext.shortcuts._theme_path = lambda:scratch/'theme.json'
ext.shape_library._storage_override = scratch/'library'
ext.register()
try:
    settings = ext.array_tool.settings()
    assert settings.flip_bend is False
    settings.flip_bend = True
    assert settings.flip_bend is True
finally: ext.unregister()
print('ARRAY_BEND_PASS')
