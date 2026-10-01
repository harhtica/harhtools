"""Every preset draws native editable points, with no thumbnail or draw-time ID writes."""
import sys
from pathlib import Path
from unittest.mock import patch
import bpy,bmesh
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_tool as ot,outline_preview as op,outline_profiles as profiles,profile_editor as pe

class Layout:
    enabled=True
    def __init__(self):self.calls=[]
    def box(self):return self
    def row(self):return self
    def label(self,**kw):self.calls.append(('label',kw['text']))
    def prop(self,cfg,name,**kw):self.calls.append(('prop',name))
    def operator(self,name,**kw):self.calls.append(('operator',name))
    def template_icon(self,**kw):raise AssertionError('Profile thumbnails must not appear')
    def template_curveprofile(self,curve,name):
        assert name=='bevel_profile' and isinstance(curve,bpy.types.Curve)
        self.calls.append(('points',curve.as_pointer()))

def ids():return set(bpy.data.meshes),set(bpy.data.objects)
def signature():
    bm=bmesh.from_edit_mesh(bpy.context.object.data)
    return [(tuple(v.co),v.select) for v in bm.verts]
def draw_safely():
    layout=Layout()
    with patch.object(pe,'start',side_effect=AssertionError('ID writes forbidden in draw')), \
         patch.object(op,'profile_icon',side_effect=AssertionError('No raster thumbnail request')), \
         patch.object(op,'profile_points',side_effect=AssertionError('Native preparation forbidden in draw')):
        ot.draw_panel(layout,bpy.context)
    assert ('prop','snap_geometry') in layout.calls
    assert layout.calls.index(('operator','view3d.harhtools_make_outline'))<layout.calls.index(('prop','bevel_enabled'))
    return layout

ot.register();pe.register()
try:
    cfg=ot.settings();cfg.output_type='MESH';cfg.bevel_enabled=True;cfg.bevel_shape=.9
    ot.initialize_bevel_ui();assert not cfg.bevel_enabled
    cfg.bevel_enabled=True;ot.initialize_bevel_ui();assert cfg.bevel_enabled
    bpy.ops.object.mode_set(mode='EDIT');before=ids();geometry=signature();curves=set(bpy.data.curves)
    sections={}
    for name in ['ROUND','CHAMFER','CONCAVE','SQUARE','CUSTOM']+sorted(profiles.NAMES):
        cfg.bevel_profile=name;draw_safely();pe.tick()
        curve=pe.active_curve(cfg)
        assert curve is not None and curve.get('source_preset')==name
        assert not curve.get(pe.TAG) and not curve.use_fake_user
        layout=draw_safely();assert ('points',curve.as_pointer()) in layout.calls
        assert ('operator','object.harhtools_edit_profile') not in layout.calls,'Presets need no edit button'
        sections[name]=pe.serialize(curve)
        if name in profiles.NAMES:
            expected=op.profile_points(name,cfg.bevel_segments,cfg.bevel_shape)
            actual=list(reversed([tuple(p.location) for p in curve.bevel_profile.segments]+[(0.,1.)]))
            assert expected==actual,'Native point preview must match the native preset section'
        with patch.object(pe,'start',side_effect=AssertionError('Unchanged presets must reuse data')):
            draw_safely();pe.tick()
        assert ids()==before and signature()==geometry and len(set(bpy.data.curves)-curves)==1
    assert len(set(sections.values()))==19
    # Rapid switches queue only the latest profile.
    cfg.bevel_profile='TORUS';draw_safely();cfg.bevel_profile='SCOTIA';draw_safely()
    with patch.object(pe,'start',wraps=pe.start) as native:
        pe.tick();assert native.call_count==1
    assert pe.active_curve(cfg).get('source_preset')=='SCOTIA'
    cfg.bevel_profile='TORUS';draw_safely();pe.tick();draft=pe.active_curve(cfg)
    original=pe.serialize(draft);draft.bevel_profile.points[3].location.x-=.025;draft.bevel_profile.update()
    # Switch before the polling interval: edits are retained without switching
    # the user's newly chosen preset back.
    cfg.bevel_profile='SCOTIA';draw_safely();pe.tick()
    assert draft.get(pe.TAG) and draft.use_fake_user and cfg.bevel_profile=='SCOTIA'
    saved=pe.serialize(draft);cfg.bevel_profile='TORUS';draw_safely();pe.tick()
    assert pe.serialize(pe.active_curve(cfg))==original and pe.serialize(draft)==saved
    # Shape and segment controls refresh safely without becoming point edits.
    cfg.bevel_profile='CUSTOM';cfg.bevel_shape=.9;draw_safely();pe.tick();initial=pe.active_curve(cfg)
    old_shape=pe.serialize(initial);cfg.bevel_shape=.15;draw_safely();pe.tick()
    fresh=pe.active_curve(cfg);assert pe.serialize(fresh)!=old_shape and not fresh.get(pe.TAG)
    old_shape=pe.serialize(fresh);cfg.bevel_segments=17;draw_safely();pe.tick()
    assert pe.active_curve(cfg)==fresh and fresh['sample_count']==17 and pe.serialize(fresh)==old_shape
    # Preparation failure leaves all remaining controls available; no retry loop.
    cfg.bevel_profile='ROUND';draw_safely()
    with patch.object(pe,'start',side_effect=RuntimeError('Injected point editor failure')):pe.tick()
    assert ('label','Profile points unavailable') in draw_safely().calls
    assert not pe._pending
    cfg.bevel_profile='TORUS';draw_safely();pe.tick();assert pe.active_curve(cfg) is not None
    assert ids()==before and signature()==geometry
    bpy.ops.object.mode_set(mode='OBJECT');draw_safely()
    pe.load_pre();assert set(bpy.data.curves)-curves=={draft}
finally:
    if bpy.context.mode=='EDIT_MESH':bpy.ops.object.mode_set(mode='OBJECT')
    pe.unregister();ot.unregister()
assert not bpy.app.timers.is_registered(pe.tick) and not pe._pending
assert op._icons is None and not bpy.app.timers.is_registered(op._refresh_icon)
print('PROFILE_PANEL_PASS: 19 automatic native point editors, no thumbnails, read-only draw, Edit/Object Mode, exact architectural sections, coalescing, preserved edits/defaults, settings refresh and failure cleanup')
