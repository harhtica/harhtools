"""Editable harhtools key bindings and Shape Builder controls."""
import bpy
import json
import math
import uuid
from pathlib import Path
from bpy.app.handlers import persistent
from bpy.props import EnumProperty, PointerProperty, FloatVectorProperty, FloatProperty, BoolProperty, StringProperty

# Use Blender's keyboard event identifiers so the event picker remains native.
_KEYS=[(p.identifier,'Enter' if p.identifier=='RET' else p.name,p.description) for p in bpy.types.Event.bl_rna.properties['type'].enum_items
       if p.identifier in {'RET','NUMPAD_ENTER','ESC','SPACE','TAB','BACK_SPACE','DEL','HOME','END','PAGE_UP','PAGE_DOWN'}
       or len(p.identifier)==1 and p.identifier.isalpha()
       or p.identifier.startswith('F') and p.identifier[1:].isdigit()]

_THEMES={
    'PINK':((1,.60,.76),(1,.94,.98),(1,.30,.52)),
    'LAVENDER':((.72,.58,1),(.95,.91,1),(.93,.38,.75)),
    'BLUE':((.38,.70,1),(.88,.96,1),(1,.46,.56)),
    'MINT':((.40,.90,.73),(.89,1,.95),(1,.52,.43)),
    'ROYAL_PURPLE':((.43,.16,.88),(.94,.87,1),(1,.44,.67)),
    'PEACH':((1,.68,.48),(1,.96,.88),(.90,.30,.44)),
    'OCEAN':((.14,.73,.82),(.86,.98,1),(1,.48,.39)),
    'GOLD':((1,.76,.26),(1,.97,.85),(.97,.35,.43)),
    'ROSE':((.91,.35,.56),(1,.92,.95),(.78,.19,.36)),
    'MONO':((.76,.79,.84),(.97,.98,1),(.94,.48,.52)),
}
# Preserve the original RNA enum numbers so existing preferences migrate.
_THEME_LABELS=[('PINK','Pink',0),('LAVENDER','Lavender',1),('BLUE','Blue',2),('MINT','Mint',3),
               ('ROYAL_PURPLE','Royal Purple',5),('PEACH','Peach',6),('OCEAN','Ocean',7),
               ('GOLD','Gold',8),('ROSE','Rose',9),('MONO','Monochrome',10)]
_THEME_ITEMS=[]
_THEME_ITEM_HISTORY=[]
_saved_themes={}
_stored_current=None
_pending_store=None
_store_error=''
_updating=False
_CAPTURE_KEY='harhtools_shortcut_capture'
_SECTION_DRAG_KEY='harhtools_section_drag'
CONTROL_HEIGHT=1.15
_SECTION_PAIRS={'TOOLS':('BUILDER','LIBRARY'),'TRANSFORM':('CENTER',),'SETTINGS':('SHORTCUTS','COLORS')}


def _theme_path():
    # User configuration survives extension upgrades and uninstall/reinstall.
    return Path(bpy.utils.user_resource('CONFIG'))/'harhtools'/'color_themes.json'


def _rebuild_theme_items():
    items=[(key,label,'',number) for key,label,number in _THEME_LABELS]
    items.append(('CUSTOM','Custom','Edited colors; save with a name below',4))
    if _saved_themes:items.append(None)
    items.extend((key,item['name'],'Saved custom theme',item['number']) for key,item in _saved_themes.items())
    # Blender retains pointers to callback enum strings. Keep old strings alive
    # when a theme is renamed or deleted, as well as the currently drawn list.
    _THEME_ITEM_HISTORY.extend(item for item in items if item)
    _THEME_ITEMS[:]=items


def theme_items(_cfg,_context):return _THEME_ITEMS


def _valid_colors(colors):
    if not isinstance(colors,(list,tuple)) or len(colors)!=3:raise ValueError('Invalid theme colors')
    result=[]
    for color in colors:
        if not isinstance(color,(list,tuple)) or len(color)!=3:raise ValueError('Invalid theme color')
        values=[float(value) for value in color]
        if not all(math.isfinite(value) and 0<=value<=1 for value in values):raise ValueError('Invalid color range')
        result.append(values)
    return result


def _valid_opacity(value):
    value=float(value)
    if not math.isfinite(value) or not 0<=value<=100:raise ValueError('Invalid opacity')
    return value


def _load_theme_store():
    global _saved_themes,_stored_current,_store_error
    _saved_themes={};_stored_current=None;_store_error=''
    path=_theme_path()
    if path.exists():
        try:
            if path.stat().st_size>2_000_000:raise ValueError('Theme file is too large')
            data=json.loads(path.read_text(encoding='utf8'))
            if data.get('version')!=1:raise ValueError('Unsupported theme file version')
            used_numbers=set()
            for item in data.get('themes',[]):
                key=item['id'];number=int(item['number']);name=str(item['name']).strip()[:64]
                if not key.startswith('USER_') or number<1000 or number in used_numbers or not name:continue
                _saved_themes[key]={'id':key,'number':number,'name':name,
                                    'colors':_valid_colors(item['colors']),'opacity':_valid_opacity(item.get('opacity',50))}
                used_numbers.add(number)
            current=data.get('current')
            if isinstance(current,dict):
                current['colors']=_valid_colors(current['colors'])
                current['opacity']=_valid_opacity(current.get('opacity',50))
                _stored_current=current
        except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
            _store_error=str(exc)
    _rebuild_theme_items()


def _theme_snapshot(cfg):
    return {'preset':cfg.theme_preset,'colors':[list(cfg.accent_color),list(cfg.light_color),list(cfg.remove_color)],
            'opacity':cfg.preview_opacity,'name':cfg.custom_theme_name,'edit_id':cfg.custom_theme_id}


def _flush_theme_store():
    global _pending_store,_stored_current,_store_error
    if _pending_store is None:return None
    try:
        path=_theme_path();path.parent.mkdir(parents=True,exist_ok=True)
        data={'version':1,'themes':list(_saved_themes.values()),'current':_pending_store}
        temporary=path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8')
        temporary.replace(path)
        _stored_current=_pending_store;_pending_store=None;_store_error=''
    except (OSError,ValueError) as exc:
        _store_error=str(exc)
        print('harhtools: could not save color themes:',exc)
    return None


def _schedule_theme_save(cfg):
    global _pending_store
    if _updating:return
    _pending_store=_theme_snapshot(cfg)
    if not bpy.app.timers.is_registered(_flush_theme_store):
        bpy.app.timers.register(_flush_theme_store,first_interval=.4)


def _restore_theme_settings(cfg):
    global _updating
    if not _stored_current:return
    current=_stored_current
    _updating=True
    try:
        key=current.get('preset','CUSTOM')
        cfg.theme_preset=key if key in _THEMES or key in _saved_themes or key=='CUSTOM' else 'CUSTOM'
        cfg.accent_color,cfg.light_color,cfg.remove_color=current['colors']
        cfg.preview_opacity=current['opacity']
        cfg.custom_theme_name=str(current.get('name','My Theme'))[:64]
        key=current.get('edit_id','')
        cfg.custom_theme_id=key if key in _saved_themes else ''
    finally:_updating=False


def theme_name_changed(cfg,_context):
    _schedule_theme_save(cfg)


def opacity_changed(cfg,context):
    redraw(context)
    _schedule_theme_save(cfg)


@persistent
def cancel_section_drag(*_args):
    drag=bpy.app.driver_namespace.get(_SECTION_DRAG_KEY)
    if drag:drag.finish(restore=True)

def redraw(context=None):
    context=context or bpy.context
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type=='VIEW_3D':area.tag_redraw()

def redraw_preview(cfg,context):
    redraw(context)

def apply_toggle(cfg,context=None):
    context=context or bpy.context
    for config in (context.window_manager.keyconfigs.addon,context.window_manager.keyconfigs.user):
        if not config:continue
        for km in config.keymaps:
            for item in km.keymap_items:
                if item.idname=='view3d.arch_shape_builder':
                    item.type=cfg.toggle_key;item.value='PRESS';item.any=False;item.active=True
                    item.shift=cfg.toggle_shift;item.ctrl=cfg.toggle_ctrl
                    item.alt=cfg.toggle_alt;item.oskey=cfg.toggle_oskey;item.key_modifier='NONE'
    redraw(context)

def toggle_changed(cfg,context):
    if not _updating:apply_toggle(cfg,context)

def refresh_theme(cfg,context):
    if _updating:return
    from . import icons
    icons.register(pink=tuple(cfg.accent_color),white=tuple(cfg.light_color))
    if context and context.window_manager:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type=='VIEW_3D':area.tag_redraw()

def set_preset(cfg,context):
    global _updating
    if _updating:return
    if cfg.theme_preset=='CUSTOM':
        _schedule_theme_save(cfg)
        return
    saved=_saved_themes.get(cfg.theme_preset)
    colors=saved['colors'] if saved else _THEMES.get(cfg.theme_preset)
    if colors is None:return
    _updating=True
    try:
        cfg.accent_color,cfg.light_color,cfg.remove_color=colors
        cfg.custom_theme_id=cfg.theme_preset if saved else ''
        cfg.custom_theme_name=saved['name'] if saved else 'My Theme'
        if saved:cfg.preview_opacity=saved['opacity']
    finally:_updating=False
    refresh_theme(cfg,context)
    _schedule_theme_save(cfg)

def set_custom(cfg,context):
    if _updating:return
    cfg.theme_preset='CUSTOM'
    refresh_theme(cfg,context)
    _schedule_theme_save(cfg)

def _properties():
    return {
        'theme_preset':EnumProperty(name='Color Theme',items=theme_items,default=0,update=set_preset),
        'custom_theme_name':StringProperty(name='Name',description='Name for your saved color theme',default='My Theme',maxlen=64,update=theme_name_changed),
        'custom_theme_id':StringProperty(default='',options={'HIDDEN'}),
        'accent_color':FloatVectorProperty(name='Main Color',subtype='COLOR_GAMMA',size=3,min=0,max=1,default=_THEMES['PINK'][0],update=set_custom),
        'light_color':FloatVectorProperty(name='Highlight / Text',subtype='COLOR_GAMMA',size=3,min=0,max=1,default=_THEMES['PINK'][1],update=set_custom),
        'remove_color':FloatVectorProperty(name='Remove Preview',subtype='COLOR_GAMMA',size=3,min=0,max=1,default=_THEMES['PINK'][2],update=set_custom),
        'remove_modifier':EnumProperty(name='Hold to Remove',items=[('ALT','Alt',''),('SHIFT','Shift',''),('CTRL','Ctrl','')],default='ALT'),
        'confirm_key':EnumProperty(name='Confirm',items=_KEYS,default='RET'),
        'cancel_key':EnumProperty(name='Cancel',items=_KEYS,default='ESC'),
        'undo_key':EnumProperty(name='Undo Stroke (Ctrl + key)',items=_KEYS,default='Z'),
        'toggle_key':EnumProperty(name='Toggle on',items=_KEYS,default='Q',update=toggle_changed),
        'toggle_shift':BoolProperty(default=True,update=toggle_changed),
        'toggle_ctrl':BoolProperty(default=False,update=toggle_changed),
        'toggle_alt':BoolProperty(default=False,update=toggle_changed),
        'toggle_oskey':BoolProperty(default=False,update=toggle_changed),
        'preview_opacity':FloatProperty(name='Opacity',description='Preview fill strength; lower values make the unconfirmed fill more transparent',
                                       subtype='PERCENTAGE',default=50,min=0,max=100,precision=0,update=opacity_changed),
        'tools_first':EnumProperty(items=[('BUILDER','Shape Builder','','NONE',0),('LIBRARY','Shape Library','','NONE',2)],default='BUILDER',update=redraw_preview),
        'settings_first':EnumProperty(items=[('SHORTCUTS','Shape Builder Shortcuts',''),('COLORS','Color Theme','')],default='SHORTCUTS',update=redraw_preview),
    }

class HARHTOOLS_PG_shortcuts(bpy.types.PropertyGroup):
    __annotations__=_properties()

class HARHTOOLS_AP_preferences(bpy.types.AddonPreferences):
    bl_idname=__package__
    __annotations__=_properties()
    def draw(self,context):draw_shortcuts(self.layout,context)

def settings(context=None):
    context=context or bpy.context
    addon=context.preferences.addons.get(__package__)
    return addon.preferences if addon else context.window_manager.harhtools_shortcuts

def key_label(key):
    return {'RET':'Enter','NUMPAD_ENTER':'Numpad Enter','ESC':'Esc','BACK_SPACE':'Backspace'}.get(key,key.title())

def remove_held(event,context=None):
    modifier=settings(context).remove_modifier
    return bool(getattr(event,modifier.lower(),False))

def chord_label(cfg):
    parts=[label for attr,label in [('toggle_ctrl','Ctrl'),('toggle_shift','Shift'),('toggle_alt','Alt'),('toggle_oskey','OS')]
           if getattr(cfg,attr)]
    return '+'.join(parts+[key_label(cfg.toggle_key)])


def set_binding(cfg,action,event,context=None):
    global _updating
    if action=='TOGGLE':
        _updating=True
        try:
            cfg.toggle_key=event.type
            for name in ('shift','ctrl','alt','oskey'):setattr(cfg,'toggle_'+name,bool(getattr(event,name,False)))
        finally:_updating=False
        apply_toggle(cfg,context)
    elif action=='REMOVE':cfg.remove_modifier=event.type.split('_')[-1]
    else:setattr(cfg,{'CONFIRM':'confirm_key','CANCEL':'cancel_key','UNDO':'undo_key'}[action],event.type)
    redraw(context)


def reset_binding(cfg,action,context=None):
    global _updating
    defaults={'TOGGLE':{'toggle_key':'Q','toggle_shift':True,'toggle_ctrl':False,'toggle_alt':False,'toggle_oskey':False},
              'REMOVE':{'remove_modifier':'ALT'},'CONFIRM':{'confirm_key':'RET'},
              'CANCEL':{'cancel_key':'ESC'},'UNDO':{'undo_key':'Z'}}
    _updating=True
    try:
        for name,value in defaults[action].items():setattr(cfg,name,value)
    finally:_updating=False
    if action=='TOGGLE':apply_toggle(cfg,context)
    redraw(context)


class VIEW3D_OT_harhtools_reset_key(bpy.types.Operator):
    bl_idname='view3d.harhtools_reset_key'
    bl_label='Reset Shortcut'
    bl_description='Restore this shortcut to its default key'
    action:EnumProperty(items=[(i,i.title(),'') for i in ('TOGGLE','REMOVE','CONFIRM','CANCEL','UNDO')])

    def execute(self,context):
        capture=bpy.app.driver_namespace.get(_CAPTURE_KEY)
        if capture:capture.finish(context)
        reset_binding(settings(context),self.action,context)
        return {'FINISHED'}


class VIEW3D_OT_harhtools_save_theme(bpy.types.Operator):
    bl_idname='view3d.harhtools_save_theme'
    bl_label='Save Color Theme'
    bl_description='Save these colors and opacity with this name; saved themes survive Blender restarts and extension updates'
    as_new:BoolProperty(default=False,options={'HIDDEN'})

    def execute(self,context):
        global _updating
        cfg=settings(context)
        name=cfg.custom_theme_name.strip()
        if not name:
            self.report({'WARNING'},'Give your theme a name first')
            return {'CANCELLED'}
        key='' if self.as_new else cfg.custom_theme_id
        if key not in _saved_themes:key='USER_'+uuid.uuid4().hex
        if any(item['name'].casefold()==name.casefold() and other!=key for other,item in _saved_themes.items()):
            if self.as_new:
                base=name;index=2
                names={item['name'].casefold() for item in _saved_themes.values()}
                while name.casefold() in names:name=f'{base} {index}';index+=1
            else:
                self.report({'WARNING'},'That theme name is already used; choose a different name')
                return {'CANCELLED'}
        number=_saved_themes[key]['number'] if key in _saved_themes else max([999]+[item['number'] for item in _saved_themes.values()])+1
        _saved_themes[key]={'id':key,'name':name,'number':number,
                            'colors':[list(cfg.accent_color),list(cfg.light_color),list(cfg.remove_color)],'opacity':cfg.preview_opacity}
        _rebuild_theme_items()
        _updating=True
        try:
            cfg.theme_preset=key;cfg.custom_theme_id=key;cfg.custom_theme_name=name
        finally:_updating=False
        _schedule_theme_save(cfg);_flush_theme_store();redraw(context)
        if _store_error:
            self.report({'ERROR'},'Could not save color theme: '+_store_error)
            return {'CANCELLED'}
        self.report({'INFO'},'Theme saved: '+name)
        return {'FINISHED'}


class VIEW3D_OT_harhtools_delete_theme(bpy.types.Operator):
    bl_idname='view3d.harhtools_delete_theme'
    bl_label='Delete Saved Theme'
    bl_description='Remove this saved preset while keeping its current colors'

    def execute(self,context):
        global _updating
        cfg=settings(context);key=cfg.custom_theme_id
        if key not in _saved_themes:return {'CANCELLED'}
        _updating=True
        try:cfg.theme_preset='CUSTOM';cfg.custom_theme_id=''
        finally:_updating=False
        del _saved_themes[key];_rebuild_theme_items()
        _schedule_theme_save(cfg);_flush_theme_store();redraw(context)
        if _store_error:
            self.report({'ERROR'},'Could not update saved themes: '+_store_error)
            return {'CANCELLED'}
        return {'FINISHED'}


class VIEW3D_OT_harhtools_capture_key(bpy.types.Operator):
    bl_idname='view3d.harhtools_capture_key'
    bl_label='Change harhtools Shortcut'
    bl_description='Click, then press the new key; right-click cancels. Toggle on accepts modifiers and applies in both modes'
    action: EnumProperty(items=[(i,i.title(),'') for i in ('TOGGLE','REMOVE','CONFIRM','CANCEL','UNDO')])

    def invoke(self,context,event):
        if bpy.app.driver_namespace.get(_CAPTURE_KEY):return {'CANCELLED'}
        self._workspace=context.workspace
        bpy.app.driver_namespace[_CAPTURE_KEY]=self
        self._workspace.status_text_set('harhtools: press a new '+('modifier (Alt / Shift / Ctrl)' if self.action=='REMOVE' else 'key')+' | right-click to cancel')
        context.window_manager.modal_handler_add(self);redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self,context,event):
        if bpy.app.driver_namespace.get(_CAPTURE_KEY) is not self:return {'CANCELLED'}
        if event.type=='RIGHTMOUSE' and event.value=='PRESS':self.finish(context);return {'CANCELLED'}
        if event.value!='PRESS':return {'RUNNING_MODAL'}
        if event.type=='ESC' and self.action!='CANCEL':self.finish(context);return {'CANCELLED'}
        allowed=({'LEFT_ALT','RIGHT_ALT','LEFT_SHIFT','RIGHT_SHIFT','LEFT_CTRL','RIGHT_CTRL'}
                 if self.action=='REMOVE' else {item[0] for item in _KEYS})
        if event.type not in allowed:return {'RUNNING_MODAL'}
        set_binding(settings(context),self.action,event,context)
        self.finish(context);return {'FINISHED'}

    def finish(self,context=None):
        if bpy.app.driver_namespace.get(_CAPTURE_KEY) is self:bpy.app.driver_namespace.pop(_CAPTURE_KEY,None)
        state=bpy.app.driver_namespace.get('arch_tools_shape_builder')
        if state:state.update_status()
        else:self._workspace.status_text_set(None)
        redraw(context)

    def cancel(self,context):self.finish(context)


def section_order(cfg,group):
    if len(_SECTION_PAIRS[group])==1:return _SECTION_PAIRS[group]
    first=getattr(cfg,group.lower()+'_first')
    if first not in _SECTION_PAIRS[group]:return _SECTION_PAIRS[group]
    return (first, next(section for section in _SECTION_PAIRS[group] if section!=first))


class VIEW3D_OT_harhtools_move_section(bpy.types.Operator):
    bl_idname='view3d.harhtools_move_section'
    bl_label='Move Section'
    bl_description='Drag up or down to reorder this box within its tab; Esc or right-click cancels'
    group:EnumProperty(items=[('TOOLS','Tools',''),('TRANSFORM','Transform',''),('SETTINGS','Settings','')])
    section:EnumProperty(items=[(s,s.title(),'') for s in ('BUILDER','CENTER','LIBRARY','SHORTCUTS','COLORS')])

    def invoke(self,context,event):
        if bpy.app.driver_namespace.get(_SECTION_DRAG_KEY):return {'CANCELLED'}
        if self.section not in _SECTION_PAIRS[self.group]:return {'CANCELLED'}
        if len(_SECTION_PAIRS[self.group])<2:return {'CANCELLED'}
        self._cfg=settings(context);self._property=self.group.lower()+'_first'
        self._original=getattr(self._cfg,self._property)
        self._pending=self._original
        self._start_y=event.mouse_y;self._threshold=24*context.preferences.system.ui_scale
        self._area=context.area;self._area_type=context.area.type
        self._window=context.window;self._workspace=context.workspace
        self._preview=None
        if not bpy.app.background:
            from .section_drag import SectionDragPreview
            title={'BUILDER':'Shape Builder','CENTER':'Align','LIBRARY':'Shape Library','SHORTCUTS':'Shape Builder Shortcuts','COLORS':'Color Theme'}[self.section]
            self._preview=SectionDragPreview(context,event,title,self._cfg.accent_color,self.section==self._original)
        bpy.app.driver_namespace[_SECTION_DRAG_KEY]=self
        self._window.cursor_modal_set('SCROLL_Y')
        self._workspace.status_text_set('Drag up/down to move section | Release to place | Esc / right-click to cancel')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self,context,event):
        if bpy.app.driver_namespace.get(_SECTION_DRAG_KEY) is not self:return {'CANCELLED'}
        if not self._area or self._area.type!=self._area_type:
            self.finish(context,restore=True);return {'CANCELLED'}
        if event.type in {'ESC','RIGHTMOUSE'} and event.value=='PRESS':
            self.finish(context,restore=True);return {'CANCELLED'}
        if event.type=='MOUSEMOVE':
            dy=event.mouse_y-self._start_y
            first=self._original
            if self.section==first and dy < -self._threshold:
                first=next(s for s in _SECTION_PAIRS[self.group] if s!=self.section)
            elif self.section!=first and dy > self._threshold:first=self.section
            # Keep the pressed grip stationary until mouse release. Rebuilding
            # the native button under the cursor mid-drag breaks repeat drags.
            self._pending=first
            if self._preview:self._preview.update(event.mouse_y,first!=self._original)
        if event.type=='LEFTMOUSE' and event.value=='RELEASE':
            self.finish(context);return {'FINISHED','PASS_THROUGH'}
        return {'RUNNING_MODAL'}

    def finish(self,context=None,restore=False):
        if self._preview:
            self._preview.close();self._preview=None
        setattr(self._cfg,self._property,self._original if restore else self._pending)
        if bpy.app.driver_namespace.get(_SECTION_DRAG_KEY) is self:
            bpy.app.driver_namespace.pop(_SECTION_DRAG_KEY,None)
            self._window.cursor_modal_restore()
            state=bpy.app.driver_namespace.get('arch_tools_shape_builder')
            if state:state.update_status()
            else:self._workspace.status_text_set(None)
        redraw(context)

    def cancel(self,context):self.finish(context,restore=True)


def grip_property(section):return 'harhtools_grip_'+section.lower()


def grip_getter(section):
    def get(_wm):
        drag=bpy.app.driver_namespace.get(_SECTION_DRAG_KEY)
        return bool(drag and drag.section==section)
    return get


def grip_setter(group,section):
    def set(_wm,value):
        # A boolean icon receives mouse PRESS, whereas an operator button waits
        # for RELEASE. Start the modal here so this is a real hold-and-drag grip.
        if value and not bpy.app.driver_namespace.get(_SECTION_DRAG_KEY):
            context=bpy.context
            if context.area and context.window:
                bpy.ops.view3d.harhtools_move_section('INVOKE_DEFAULT',group=group,section=section)
    return set


_COLLAPSIBLE_SECTIONS=('BUILDER','CENTER','LIBRARY','SHORTCUTS','COLORS',
                       'ARRAY_DIRECTION','ARRAY_PATTERN','ARRAY_VISIBILITY','LIBRARY_PLACEMENT')


def expanded_property(section):return 'harhtools_expanded_'+section.lower()


class VIEW3D_OT_harhtools_toggle_section(bpy.types.Operator):
    bl_idname='view3d.harhtools_toggle_section'
    bl_label='Expand or Collapse Section'
    bl_description='Show or fold the controls in this section'
    bl_options={'INTERNAL'}
    section:EnumProperty(items=[(key,key.replace('_',' ').title(),'') for key in _COLLAPSIBLE_SECTIONS])

    def execute(self,context):
        wm=context.window_manager;prop=expanded_property(self.section)
        setattr(wm,prop,not getattr(wm,prop))
        redraw(context)
        return {'FINISHED'}


def section_header(box,title,group,section,icon_value=0,context=None):
    context=context or bpy.context
    wm=context.window_manager;prop=expanded_property(section)
    expanded=getattr(wm,prop,True)
    header=box.row(align=False)
    title_row=header.row(align=True)
    title_row.operator('view3d.harhtools_toggle_section',text='',
                       icon='TRIA_DOWN' if expanded else 'TRIA_RIGHT',emboss=False).section=section
    title_row.label(text=title,icon_value=icon_value)
    if group in _SECTION_PAIRS and len(_SECTION_PAIRS[group])>1:
        grip=header.row(align=False);grip.alignment='RIGHT'
        drag=bpy.app.driver_namespace.get(_SECTION_DRAG_KEY)
        grip.alert=bool(drag and drag.section==section)
        grip.prop(wm,grip_property(section),text='',icon='GRIP',emboss=False,toggle=True)
    return expanded


def section_box(layout,context,title,section,group=None,icon_value=0):
    """Collapsible sections inside the sidebar's content column and icon rail."""
    box=layout.box()
    if not section_header(box,title,group,section,icon_value,context):return None
    body=box.column(align=False)
    body.use_property_decorate=False
    return body


def draw_binding_box(layout,context,cfg):
    capture=bpy.app.driver_namespace.get(_CAPTURE_KEY)
    box=section_box(layout,context,'Shape Builder Shortcuts','SHORTCUTS','SETTINGS')
    if box is None:return
    for action,label,value in [('TOGGLE','Toggle on',chord_label(cfg)),
                               ('REMOVE','Remove',cfg.remove_modifier.title()),
                               ('CONFIRM','Confirm',key_label(cfg.confirm_key)),
                               ('CANCEL','Esc / Right click',key_label(cfg.cancel_key)),
                               ('UNDO','Undo','Ctrl+'+key_label(cfg.undo_key))]:
        split=box.split(factor=.51,align=False);split.scale_y=CONTROL_HEIGHT
        split.label(text=label)
        listening=bool(capture and capture.action==action)
        controls=split.split(factor=.26,align=False)
        reset=controls.row(align=False)
        reset.operator('view3d.harhtools_reset_key',text='',icon='LOOP_BACK').action=action
        key=controls.row(align=False)
        key.operator('view3d.harhtools_capture_key',text='Press key...' if listening else value,depress=listening).action=action


def draw_color_box(layout,context,cfg):
    box=section_box(layout,context,'Color Theme','COLORS','SETTINGS')
    if box is None:return
    column=box.column(align=False);column.scale_y=CONTROL_HEIGHT;column.use_property_decorate=False
    column.prop(cfg,'theme_preset',text='')
    if cfg.theme_preset=='CUSTOM' or cfg.theme_preset in _saved_themes:
        column.prop(cfg,'custom_theme_name',text='Name')
        row=column.row(align=False)
        saved=cfg.custom_theme_id in _saved_themes
        row.operator('view3d.harhtools_save_theme',text='Save Changes' if saved else 'Save Theme',icon='FILE_TICK')
        if saved:
            row.operator('view3d.harhtools_save_theme',text='',icon='DUPLICATE').as_new=True
            row.operator('view3d.harhtools_delete_theme',text='',icon='X')
    for prop,label in [('accent_color','Main'),('light_color','Highlight'),('remove_color','Remove')]:
        split=column.split(factor=.45,align=False);split.label(text=label);split.prop(cfg,prop,text='')
    column.prop(cfg,'preview_opacity',text='Opacity',slider=True)
    if _store_error:
        row=column.row();row.alert=True
        row.label(text='Theme could not be saved',icon='ERROR')


def draw_shortcuts(layout,context,compact=False):
    cfg=settings(context)
    for index,section in enumerate(section_order(cfg,'SETTINGS')):
        if index:layout.separator(factor=.5)
        {'SHORTCUTS':draw_binding_box,'COLORS':draw_color_box}[section](layout,context,cfg)
    if context.preferences.addons.get(__package__):
        row=layout.row();row.scale_y=CONTROL_HEIGHT
        row.operator('wm.save_userpref',text='Save Settings',icon='FILE_TICK')


class VIEW3D_PT_harhtools_shortcuts(bpy.types.Panel):
    bl_label='Settings'
    bl_idname='VIEW3D_PT_harhtools_shortcuts'
    bl_space_type='VIEW_3D'
    bl_region_type='HEADER'
    bl_ui_units_x=14
    def draw(self,context):draw_shortcuts(self.layout,context,compact=True)

_CLASSES=(HARHTOOLS_PG_shortcuts,HARHTOOLS_AP_preferences,VIEW3D_OT_harhtools_capture_key,VIEW3D_OT_harhtools_reset_key,
          VIEW3D_OT_harhtools_save_theme,VIEW3D_OT_harhtools_delete_theme,VIEW3D_OT_harhtools_move_section,
          VIEW3D_OT_harhtools_toggle_section,VIEW3D_PT_harhtools_shortcuts)
def register():
    _load_theme_store()
    for cls in _CLASSES:
        previous=cls if cls.is_registered else getattr(bpy.types,cls.__name__,None)
        if previous:bpy.utils.unregister_class(previous)
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.harhtools_shortcuts=PointerProperty(type=HARHTOOLS_PG_shortcuts)
    for section in _COLLAPSIBLE_SECTIONS:
        setattr(bpy.types.WindowManager,expanded_property(section),BoolProperty(
            name='Expand Section',description='Show or collapse this section',default=True))
    _restore_theme_settings(settings())
    for group,sections in _SECTION_PAIRS.items():
        for section in sections:
            setattr(bpy.types.WindowManager,grip_property(section),BoolProperty(
                name='Move Section',description='Hold and drag up/down to reorder this box; Esc or right-click cancels',
                get=grip_getter(section),set=grip_setter(group,section),options={'SKIP_SAVE'}))
    if cancel_section_drag not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(cancel_section_drag)

def unregister():
    if bpy.app.timers.is_registered(_flush_theme_store):
        bpy.app.timers.unregister(_flush_theme_store)
    _flush_theme_store()
    if cancel_section_drag in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(cancel_section_drag)
    drag=bpy.app.driver_namespace.get(_SECTION_DRAG_KEY)
    if drag:drag.finish(restore=True)
    capture=bpy.app.driver_namespace.get(_CAPTURE_KEY)
    if capture:capture.finish()
    for sections in _SECTION_PAIRS.values():
        for section in sections:
            if hasattr(bpy.types.WindowManager,grip_property(section)):
                delattr(bpy.types.WindowManager,grip_property(section))
    if hasattr(bpy.types.WindowManager,'harhtools_shortcuts'):del bpy.types.WindowManager.harhtools_shortcuts
    for section in _COLLAPSIBLE_SECTIONS:
        if hasattr(bpy.types.WindowManager,expanded_property(section)):
            delattr(bpy.types.WindowManager,expanded_property(section))
    for cls in reversed(_CLASSES):
        previous=cls if cls.is_registered else getattr(bpy.types,cls.__name__,None)
        if previous:bpy.utils.unregister_class(previous)

