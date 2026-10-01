"""Native point editor with private working copies and persistent user profiles."""
import json
import bpy
from bpy.app.handlers import persistent
from . import outline_profiles

TAG='harhtools_bevel_profile'
_pending={}
_errors={}


def preset_key(cfg):
    return json.dumps((cfg.bevel_profile,float(cfg.bevel_shape) if cfg.bevel_profile=='CUSTOM' else None))


def request_key(cfg):
    return (preset_key(cfg),cfg.bevel_segments,
            cfg.edited_profile.as_pointer() if cfg.bevel_profile=='EDITED' and cfg.edited_profile else 0)

def serialize(curve):
    if curve is None:return ''
    saved=outline_profiles.snapshot(curve.bevel_profile)
    # Selecting a control point changes highlighting, not the profile shape.
    saved['points']=[(co,h1,h2,False) for co,h1,h2,_ in saved['points']]
    return json.dumps(saved,separators=(',',':'))

def active_curve(cfg):
    if cfg.bevel_profile=='EDITED':return cfg.edited_profile
    curve=cfg.working_profile
    return curve if curve and not curve.get(TAG) and curve.get('source_key')==preset_key(cfg) else None

def poll_asset(self,curve):return bool(curve.get(TAG))

def discard_working(cfg):
    curve=cfg.working_profile;cfg.working_profile=None
    if curve and not curve.get(TAG) and curve.get('harhtools_profile_scratch'):
        bpy.data.curves.remove(curve)

def start(cfg):
    from . import outline_preview
    retain_edits(cfg)
    name=cfg.bevel_profile
    if name=='EDITED':
        if cfg.edited_profile is None:raise ValueError('Choose an edited profile first.')
        saved=json.loads(serialize(cfg.edited_profile));label=cfg.edited_profile.name
    elif name not in outline_profiles.NAMES:
        points=outline_preview.profile_points(name,max(32,cfg.bevel_segments),cfg.bevel_shape)
        saved=dict(points=[(p,'VECTOR','VECTOR',False) for p in reversed(points)],clip=True,straight=True,even=False)
    if name!='EDITED':label=dict((key,text) for key,text,_ in outline_profiles.ITEMS).get(name,name.title())
    discard_working(cfg)
    curve=bpy.data.curves.new('.Harhtools profile working copy','CURVE')
    try:
        curve.bevel_mode='PROFILE'
        if name in outline_profiles.NAMES:outline_profiles.configure(curve.bevel_profile,name,cfg.bevel_segments)
        else:outline_profiles.restore(curve.bevel_profile,saved,cfg.bevel_segments)
        curve['harhtools_profile_scratch']=True;curve['source_preset']=name
        curve['source_key']=preset_key(cfg);curve['sample_count']=cfg.bevel_segments
        curve['source_label']=label;curve['last_shape']=serialize(curve)
        cfg.working_profile=curve
        # Editing a saved profile makes a separate draft too; the original
        # user profile remains recoverable through the datablock picker.
        if name=='EDITED':cfg.edited_profile=curve
        return curve
    except Exception:
        bpy.data.curves.remove(curve);raise

def retain_edits(cfg):
    """Keep edits even if a preset switch arrives before the next timer tick."""
    current=active_curve(cfg)
    curves={curve for curve in (current,cfg.working_profile) if curve is not None}
    changed=False
    for curve in curves:
        shape=serialize(curve)
        if shape==curve.get('last_shape'):continue
        if not curve.get(TAG):
            curve[TAG]=True;curve.use_fake_user=True
            curve.name=curve.get('source_label','Profile')+' - Edited'
            if 'harhtools_profile_scratch' in curve:del curve['harhtools_profile_scratch']
        curve['last_shape']=shape
        if curve==current:
            cfg.edited_profile=curve;cfg.bevel_profile='EDITED'
        curve.bevel_profile.update();curve.bevel_profile.initialize(cfg.bevel_segments)
        curve['sample_count']=cfg.bevel_segments;changed=True
    return changed


def ensure(cfg):
    """Read-only draw helper: prepare native editor data on the next timer tick."""
    curve=active_curve(cfg)
    if cfg.bevel_profile=='EDITED' and curve is None:return None
    if curve is None or curve.get('sample_count')!=cfg.bevel_segments:
        owner=cfg.as_pointer();key=request_key(cfg)
        if _errors.get(owner)!=key:_pending[owner]=cfg
    return curve


def tick():
    redraw=False
    for wm in getattr(bpy.data,'window_managers',()):
        cfg=getattr(wm,'harhtools_outline',None)
        if cfg is None:continue
        changed=retain_edits(cfg)
        owner=cfg.as_pointer()
        if owner in _pending:
            _pending.pop(owner,None)
            try:
                curve=active_curve(cfg)
                if curve is None and cfg.bevel_profile!='EDITED':curve=start(cfg)
                if curve is not None:
                    curve.bevel_profile.initialize(cfg.bevel_segments)
                    curve['sample_count']=cfg.bevel_segments
                _errors.pop(owner,None)
            except Exception as exc:
                _errors[owner]=request_key(cfg)
                print('Harhtools profile editor:',exc)
            redraw=True
        if changed:
            from . import outline_tool
            state=bpy.app.driver_namespace.get(outline_tool.STATE_KEY)
            if state:state.request_refresh(bpy.context)
            redraw=True
    if redraw:
        from . import outline_preview
        outline_preview._redraw_panels()
    return .12

class OBJECT_OT_harhtools_edit_profile(bpy.types.Operator):
    bl_idname='object.harhtools_edit_profile';bl_label='Edit Profile Points'
    bl_description='Make an editable copy with Blender profile control points; presets stay unchanged'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        try:start(context.window_manager.harhtools_outline)
        except ValueError as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}
        return {'FINISHED'}

def draw(layout,cfg):
    if cfg.bevel_profile=='EDITED':layout.prop(cfg,'edited_profile',text='My Profile')
    curve=ensure(cfg)
    if curve:
        layout.template_curveprofile(curve,'bevel_profile')
        if curve.get(TAG):
            layout.prop(curve,'name',text='Name')
            layout.operator('object.harhtools_edit_profile',text='New Profile Copy')
        else:layout.label(text='Moving a point creates your own profile.')
    elif cfg.bevel_profile=='EDITED':layout.label(text='Choose a saved profile above.')
    elif _errors.get(cfg.as_pointer())==request_key(cfg):
        layout.label(text='Profile points unavailable',icon='ERROR')
        layout.operator('object.harhtools_edit_profile',text='Retry Profile Points')
    else:layout.label(text='Loading profile points...',icon='TIME')

@persistent
def load_pre(*_args):
    _pending.clear();_errors.clear()
    for wm in getattr(bpy.data,'window_managers',()):
        cfg=getattr(wm,'harhtools_outline',None)
        if cfg:
            # Unmodified drafts have no user-authored data to retain.
            discard_working(cfg)

def register():
    bpy.utils.register_class(OBJECT_OT_harhtools_edit_profile)
    if load_pre not in bpy.app.handlers.load_pre:bpy.app.handlers.load_pre.append(load_pre)
    if not bpy.app.timers.is_registered(tick):bpy.app.timers.register(tick,first_interval=.12,persistent=True)

def unregister():
    _pending.clear();_errors.clear()
    if bpy.app.timers.is_registered(tick):bpy.app.timers.unregister(tick)
    if load_pre in bpy.app.handlers.load_pre:bpy.app.handlers.load_pre.remove(load_pre)
    # Working copies survive code reload through the settings snapshot. They
    # have no fake user until edited, so untouched drafts do not persist.
    if OBJECT_OT_harhtools_edit_profile.is_registered:bpy.utils.unregister_class(OBJECT_OT_harhtools_edit_profile)
