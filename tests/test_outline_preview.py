"""Native bevel preview geometry and UI thumbnails without scene residue."""
import bpy,json,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_preview as op,outline_geometry as og
mesh=bpy.data.meshes.new('Preview source');mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)],[(0,1),(1,2),(2,3),(3,0)],[])
source=bpy.data.objects.new('Preview source',mesh);bpy.context.collection.objects.link(source);bpy.context.view_layer.update()
result=og.build_outline(og.prepare_sources([source]),.2,join_style='MITER')
def ids():return (set(bpy.data.scenes),set(bpy.data.objects),set(bpy.data.meshes),bpy.context.scene,bpy.context.view_layer)
before=ids();surfaces=[]
for name in ('ROUND','CHAMFER','CONCAVE','SQUARE','CUSTOM'):
    surface=op.surface([result],dict(depth=.2,width=.04,profile=name,segments=6,custom_shape=.9))
    assert len(surface['pos'])==len(surface['color']) and len(surface['pos'])%3==0
    assert min(p[2] for p in surface['pos'])<-.19 and max(p[2] for p in surface['pos'])<.001
    assert all(len(c)==4 and c[3]==1 for c in surface['color'])
    assert ids()==before
    surfaces.append(str(surface['pos']))
assert len(set(surfaces))==5
real_make=op.outline_mesh.make_mesh_data;calls=[]
def fail_second(*args):
    calls.append(True)
    if len(calls)==2:raise RuntimeError('Injected second mesh failure')
    return real_make(*args)
with patch.object(op.outline_mesh,'make_mesh_data',side_effect=fail_second):
    try:op.surface([result,result],dict(depth=.2,width=.04))
    except RuntimeError:pass
    else:raise AssertionError('Expected failure')
assert ids()==before
icons=[];profiles=[]
for name in ('ROUND','CHAMFER','CONCAVE','SQUARE','CUSTOM'):
    cfg=SimpleNamespace(bevel_profile=name,bevel_segments=6,bevel_shape=.9)
    op.profile_icon(cfg);assert bpy.app.timers.is_registered(op._refresh_icon)
    bpy.app.timers.unregister(op._refresh_icon);op._refresh_icon()
    icon=op.profile_icon(cfg);preview=op._icons['profile'];pixels=tuple(preview.image_pixels_float)
    assert tuple(preview.image_size)==(160,160) and len(pixels)==160*160*4
    assert bpy.app.background or icon>0
    with patch.object(op,'profile_points',side_effect=AssertionError('Thumbnail must reuse cached native profile')):
        assert op.profile_icon(cfg)==icon and tuple(preview.image_pixels_float)==pixels
    icons.append(pixels);profiles.append(op.profile_points(name,6,.9))
assert len({str(p) for p in profiles})==5 and len({hash(p) for p in icons})==5
op.clear();assert op._icons is None and ids()==before
print('OUTLINE_PREVIEW_PASS: 5 native shaded surfaces, 5 cached native profile icons, complete scratch cleanup on success/failure')
