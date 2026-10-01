"""Draw callbacks cannot allocate IDs; deferred native icons work in Edit Mode."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import bpy,bmesh
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_tool as ot,outline_preview as op,outline_profiles as profiles

class Layout:
    enabled=True
    def __init__(self):self.calls=[]
    def box(self):return self
    def row(self):return self
    def label(self,**kw):self.calls.append(('label',kw['text']))
    def prop(self,cfg,name,**kw):self.calls.append(('prop',name))
    def operator(self,name,**kw):self.calls.append(('operator',name))
    def template_icon(self,**kw):self.calls.append(('icon',kw['icon_value']))

def ids():return set(bpy.data.meshes),set(bpy.data.objects)
def signature():
    bm=bmesh.from_edit_mesh(bpy.context.object.data)
    return [(tuple(v.co),v.select) for v in bm.verts]
def draw_safely():
    layout=Layout()
    # Model Blender's read-only draw context: even asking for native samples
    # or constructing a preview collection here is a regression.
    with patch.object(op,'profile_points',side_effect=AssertionError('ID writes forbidden in draw')), \
         patch.object(op.bpy.utils.previews,'new',side_effect=AssertionError('No preview allocation in draw')):
        ot.draw_panel(layout,bpy.context)
    assert ('prop','snap_geometry') in layout.calls
    assert ('operator','view3d.harhtools_make_outline') in layout.calls
    assert layout.calls.index(('operator','view3d.harhtools_make_outline'))<layout.calls.index(('prop','bevel_enabled'))
    return layout
def pump():
    assert bpy.app.timers.is_registered(op._refresh_icon)
    bpy.app.timers.unregister(op._refresh_icon);op._refresh_icon()

ot.register()
try:
    cfg=ot.settings();cfg.output_type='MESH';cfg.bevel_enabled=True
    ot.initialize_bevel_ui();assert not cfg.bevel_enabled
    cfg.bevel_enabled=True;ot.initialize_bevel_ui();assert cfg.bevel_enabled
    bpy.ops.object.mode_set(mode='EDIT');before=ids();geometry=signature()
    pixels=[]
    for name in profiles.NAMES:
        cfg.bevel_profile=name;draw_safely();pump()
        assert op._error_key is None and op._icon_key[0]==name
        pixels.append(hash(tuple(op._icons['profile'].image_pixels_float)))
        draw_safely();assert not bpy.app.timers.is_registered(op._refresh_icon)
        assert ids()==before and signature()==geometry
    assert len(set(pixels))==14
    # One pending timer uses the latest choice, without showing a stale icon.
    cfg.bevel_profile='TORUS';draw_safely();cfg.bevel_profile='SCOTIA';draw_safely()
    assert op.profile_icon(cfg)==0
    with patch.object(op,'profile_points',wraps=op.profile_points) as native:
        pump();assert native.call_count==1 and native.call_args.args[0]=='SCOTIA'
    cfg.bevel_profile='BEAK';draw_safely()
    with patch.object(op,'profile_points',side_effect=RuntimeError('Injected thumbnail failure')):pump()
    assert ('label','Profile preview unavailable') in draw_safely().calls
    assert not bpy.app.timers.is_registered(op._refresh_icon)
    cfg.bevel_profile='TORUS';draw_safely();pump();assert op._error_key is None
    cfg.bevel_profile='SCOTIA';draw_safely();op.clear()
    assert not bpy.app.timers.is_registered(op._refresh_icon) and op._icons is None
    assert ids()==before and signature()==geometry
    bpy.ops.object.mode_set(mode='OBJECT');draw_safely();pump()
finally:
    if bpy.context.mode=='EDIT_MESH':bpy.ops.object.mode_set(mode='OBJECT')
    ot.unregister()
assert not bpy.app.timers.is_registered(op._refresh_icon) and op._icons is None
print('PROFILE_PANEL_PASS: 14 deferred native thumbnails, read-only draw, Edit/Object Mode, coalescing, failure recovery and cleanup')
