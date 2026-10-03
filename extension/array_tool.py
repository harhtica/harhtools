"""Group arrays adapted from the Roblox harhtools workflow."""
import math
import textwrap
import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty
from mathutils import Matrix
from . import array_core, array_inference, array_tween, array_material_preview, icons, shortcuts, display_units

STATE_KEY='harhtools_array_preview'
_tab_active=False
_history_target=None
_resume_timer=None
_last_context=None


def _discard_stale_state(state):
    """Release Python-owned handles even if Blender already freed operator RNA."""
    if bpy.app.driver_namespace.get(STATE_KEY) is state:
        bpy.app.driver_namespace.pop(STATE_KEY,None)
    try:record=object.__getattribute__(state,'__dict__')
    except (AttributeError,ReferenceError,RuntimeError,TypeError):record={}
    inactive=record.get('_inactive')
    if inactive is not None:
        try:inactive.restore()
        except (AttributeError,ReferenceError,RuntimeError):pass
    native=record.get('_native')
    if native is not None:native.clear()
    for name in ('_handler','_hud_handler'):
        handle=record.get(name)
        if handle is not None:
            try:bpy.types.SpaceView3D.draw_handler_remove(handle,'WINDOW')
            except (ReferenceError,RuntimeError,ValueError,TypeError):pass
        record[name]=None
    timer=record.get('_timer')
    if timer is not None:
        try:bpy.context.window_manager.event_timer_remove(timer)
        except (ReferenceError,RuntimeError,ValueError,TypeError):pass
    record['_timer']=None;record['_done']=True;record['_cache']=[];record['_plan']=None
    tween=record.get('_tween')
    if tween is not None:
        try:tween.clear()
        except (AttributeError,ReferenceError,RuntimeError):pass
    try:
        workspace=record.get('_workspace');area=record.get('_area')
        if workspace is not None:workspace.status_text_set(None)
        if area is not None:area.tag_redraw()
    except (AttributeError,ReferenceError,RuntimeError):pass


def preview_state():
    """Get a live preview, removing stale states left by old versions or undo."""
    state=bpy.app.driver_namespace.get(STATE_KEY)
    if state is None:return None
    try:
        if not state._done:return state
    except (AttributeError,ReferenceError,RuntimeError):pass
    _discard_stale_state(state)
    return None


def sidebar_is_active(area):
    """Only capture input/draw while this area's harhtools sidebar is visible."""
    try:
        if area.type!='VIEW_3D' or not area.spaces.active.show_region_ui:return False
        sidebar=next((region for region in area.regions if region.type=='UI'),None)
        return bool(sidebar is not None and sidebar.width>1 and sidebar.active_panel_category=='harhtools')
    except (AttributeError,ReferenceError,RuntimeError):return False


def changed(cfg,context):
    state=preview_state()
    if state:state._dirty=True
    shortcuts.redraw(context)


def fit_changed(cfg,context):
    if cfg.fit_ring and not cfg.rotate_copies:cfg.rotate_copies=True
    length_changed(cfg,context)


def length_changed(cfg,context):
    changed(cfg,context)
    state=preview_state()
    if state:state._geometry_dirty=True


def pivot_changed(cfg,context):
    length_changed(cfg,context)


def visibility_changed(cfg,context):
    state=preview_state()
    if state:
        state._inactive_dirty=True
        # A UI slider can own the event loop until its mouse button is released.
        # Disabling the effect must restore the real objects immediately anyway.
        if not cfg.hide_inactive or cfg.inactive_opacity>=100:
            state._inactive.restore()
    shortcuts.redraw(context)


def native_scene_modal(window):
    """Detect Blender's actual scene interaction, not a remembered mouse press.

    Native buttons and selection tools can consume their release event before
    our modal receives it. Tracking LEFTMOUSE ourselves therefore left fading
    suspended forever after clicking a sidebar toggle or dragging its slider.
    """
    for operator in getattr(window,'modal_operators',()):
        identifier=getattr(operator,'bl_idname','')
        if '.' in identifier:
            category,name=identifier.split('.',1);identifier=category.upper()+'_OT_'+name
        if identifier.startswith(('TRANSFORM_OT_','OBJECT_OT_','MESH_OT_','CURVE_OT_')):
            return True
        if identifier.startswith('VIEW3D_OT_') and not identifier.startswith('VIEW3D_OT_harhtools_'):
            return True
    return False


class HARHTOOLS_PG_array(bpy.types.PropertyGroup):
    deform_enabled:BoolProperty(name='Deform Copies',description='Gradually scale, move or turn whole copied groups from the unchanged original to the last copy',default=False,update=changed)
    deform_scale:FloatProperty(name='Last Copy Size',description='Uniform size of the last copy relative to the original; 50% is half size on every axis',default=50.,min=1.,max=1000.,soft_max=200.,subtype='PERCENTAGE',precision=1,update=changed)
    deform_keep_gap:BoolProperty(name='Keep Edge Gaps',description='Adjust linear copy positions to retain the Gap as their size and rotation change; additional Move offsets are applied afterward',default=True,update=changed)
    deform_ease:EnumProperty(name='Progression',items=[('LINEAR','Even','Equal changes between copies'),('SMOOTH','Smooth','Gentle change at both ends'),('EASE_IN','Slow Start','More change near the last copy'),('EASE_OUT','Slow End','More change near the original')],default='LINEAR',update=changed)
    deform_offset:FloatVectorProperty(name='Last Copy Move',description='Total additional offset by the last copy, using the array axes; follows rotation in a circular array',size=3,default=(0.,0.,0.),subtype='TRANSLATION',unit='LENGTH',update=changed)
    deform_offset_studs:FloatVectorProperty(name='Last Copy Move (studs)',size=3,precision=3,options={'SKIP_SAVE'},get=lambda self:tuple(v*display_units.factor() for v in self.deform_offset),set=lambda self,value:setattr(self,'deform_offset',tuple(v/display_units.factor() for v in value)))
    deform_rotation:FloatVectorProperty(name='Last Copy Rotate',description='Total extra rotation by the last copy around the copied group center, using the array axes',size=3,default=(0.,0.,0.),subtype='EULER',unit='ROTATION',update=changed)
    deform_extra:BoolProperty(name='Move / Rotate',description='Show optional gradual movement and rotation controls',default=False)
    show_materials:BoolProperty(name='Show Materials',description='Preview actual materials and transparent cutouts in Material Preview or Rendered view',default=True,update=length_changed)
    gap_studs:display_units.distance_property('gap','Gap',minimum=-1e10)
    radius_studs:display_units.distance_property('radius','Radius')
    resolved_radius_studs:display_units.distance_property('resolved_radius','Radius')
    mode:EnumProperty(name='Array',items=[('LINEAR','Linear','Repeat in a row'),('CIRCULAR','Circular','Repeat around a ring or arc')],default='LINEAR',update=length_changed)
    orientation:EnumProperty(name='Axes',items=[('WORLD','Global','Use the scene X, Y, and Z directions'),('ACTIVE','Last','Use the local X, Y, and Z directions of the last selected object')],default='WORLD',update=changed)
    auto_axis:BoolProperty(name='Auto Axis',description='Infer the array direction from the selection and view; click X, Y, or Z to override',default=True,update=changed)
    axes:EnumProperty(name='Axis',items=[('X','X','Repeat along X'),('Y','Y','Repeat along Y'),('Z','Z','Repeat along Z')],default='Y',update=changed)
    count:IntProperty(name='Count',description='Linear: cells per enabled axis, including source. Circular: new copies around the ring',default=6,min=2,max=1000,update=changed)
    gap:FloatProperty(name='Gap',description='Space between the group bounds; zero makes neighboring bounds touch',default=0,subtype='DISTANCE',unit='LENGTH',precision=3,update=changed)
    fit_length:BoolProperty(name='Fit Length',description='Select two objects: repeat the last selected object across the gap to the other object. Calculate the count without resizing the source',default=False,update=length_changed)
    radial_axis:EnumProperty(name='Axis',items=[('X','X','Ring lies in YZ'),('Y','Y','Ring lies in XZ'),('Z','Z','Ring lies in XY')],default='Z',update=changed)
    radius:FloatProperty(name='Radius',description='Distance from the ring center to each copied group center',default=1,min=.00001,soft_max=100,subtype='DISTANCE',unit='LENGTH',precision=3,update=changed)
    sweep:FloatProperty(name='Sweep',description='Total arc angle; negative values reverse direction. A full circle in either direction has no duplicate at the seam',default=math.tau,min=-math.tau,max=math.tau,subtype='ANGLE',unit='ROTATION',update=changed)
    pivot:EnumProperty(name='Center',items=[('BOUNDS','From Source','Start at the source; Radius places the circle center one radius away'),('ACTIVE','Last Origin','Orbit the last selected object origin, starting at the source position'),('CURSOR','3D Cursor','Orbit the 3D cursor, starting at the source position')],default='BOUNDS',update=pivot_changed)
    rotate_copies:BoolProperty(name='Rotate Copies',description='Turn each complete group with the ring',default=True,update=changed)
    fit_ring:BoolProperty(name='Fit Ring',description='At a fixed center, fit whole copies using the shape\'s angular width. From Source instead fits Radius to Count. Source geometry and the chosen center stay unchanged',default=False,update=fit_changed)
    fit_side:EnumProperty(name='Fit',items=[('INSIDE','Inside','Fit the inner edges'),('CENTER','Centers','Fit through centers'),('OUTSIDE','Outside','Fit the outer edges')],default='INSIDE',update=changed)
    linked:BoolProperty(name='Linked Copies',description='Share mesh or curve data with the source; disabled gives independent geometry',default=False,update=changed)
    join_generated:BoolProperty(name='Join Generated',description='Join the original and all copies into one mesh, keeping their visible modifiers, materials and UVs. Circular results use the rotation center as their origin',default=False,update=changed)
    resolved_radius:FloatProperty(name='Radius',description='Calculated distance from the chosen center to the source',default=0,subtype='DISTANCE',unit='LENGTH',precision=3,options={'SKIP_SAVE'})
    resolved_count:IntProperty(name='Copies',description='Whole copies that fit after the original piece',default=0,min=0,options={'SKIP_SAVE'})
    resolved_step:FloatProperty(name='Step',description='Angular width of the source; adjacent copies meet at this rotation',default=0,subtype='ANGLE',unit='ROTATION',precision=3,options={'SKIP_SAVE'})
    hide_inactive:BoolProperty(name='Hide Inactive',description='Fade unselected mesh and curve guides while Array is open. At zero opacity they are hidden; click a visible guide to select it normally',default=False,update=visibility_changed)
    inactive_opacity:FloatProperty(name='Inactive Opacity',description='Visibility of unselected mesh and curve guides while Hide Inactive is enabled; zero hides them completely',default=15,min=0,max=100,subtype='PERCENTAGE',precision=0,update=visibility_changed)
    initialized:BoolProperty(default=False,options={'SKIP_SAVE'})


def settings(context=None):return (context or bpy.context).window_manager.harhtools_array


def initialize_for_selection(context):
    cfg=settings(context)
    if cfg.initialized or context.mode!='OBJECT' or not context.selected_objects:return
    try:snap=array_core.snapshot(context)
    except ValueError:return
    low,high=array_core._bounds(snap.bounds_points)
    span=high-low
    cfg.radius=max(max(span)*1.5,.001)
    cfg.initialized=True


def selection_signature(context):
    # Outliner changes and source transforms update the preview as a new group.
    return (context.view_layer.objects.active.as_pointer() if context.view_layer.objects.active else 0,
            tuple((o.as_pointer(),o.data.as_pointer() if o.data else 0,
                   tuple(v for row in o.matrix_world for v in row),
                   tuple(v for corner in o.bound_box for v in corner)) for o in context.selected_objects))


def preview_geometry(context,snapshot):
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader=gpu.shader.from_builtin('UNIFORM_COLOR')
    cache=[]
    depsgraph=context.evaluated_depsgraph_get()
    for source,matrix in zip(snapshot.sources,snapshot.matrices):
        evaluated=source.evaluated_get(depsgraph)
        mesh=evaluated.to_mesh()
        try:
            if not mesh or not mesh.vertices:continue
            points=[tuple(v.co) for v in mesh.vertices]
            edges=[tuple(e.vertices) for e in mesh.edges]
            mesh.calc_loop_triangles()
            faces=[tuple(t.vertices) for t in mesh.loop_triangles]
            wire=batch_for_shader(shader,'LINES',{'pos':points},indices=edges) if edges else None
            fill=batch_for_shader(shader,'TRIS',{'pos':points},indices=faces) if faces else None
            cache.append((matrix.copy(),wire,fill))
        finally:evaluated.to_mesh_clear()
    if not cache:raise ValueError('The selection has no visible mesh or curve geometry.')
    return shader,cache


class InactiveGuides:
    """Session-only ghost drawing; never edit materials or mesh data.

    Native objects are restored before selection/navigation commands, history,
    saving, and closing the tool. Only originally visible mesh/curve objects
    are touched, so pre-existing hidden objects and collections remain hidden.
    """
    def __init__(self,view_layer,space):
        self.view_layer=view_layer;self.space=space
        self.hidden={};self.cache=[];self.shader=None
        self._cache_signature=None

    def restore(self,clear_cache=True):
        for obj in tuple(self.hidden.values()):
            try:
                if obj.name in self.view_layer.objects:obj.hide_set(False,view_layer=self.view_layer)
            except (ReferenceError,RuntimeError):pass
        self.hidden.clear()
        if clear_cache:self.cache=[];self.shader=None;self._cache_signature=None

    def update(self,context,cfg):
        self.restore(clear_cache=False)
        if not cfg.hide_inactive or cfg.inactive_opacity>=100 or not context.selected_objects:
            self.restore();return
        selected={obj.as_pointer() for obj in context.selected_objects}
        from types import SimpleNamespace
        objects=[obj for obj in self.view_layer.objects
                 if obj.type in {'MESH','CURVE'} and obj.as_pointer() not in selected
                 and not array_material_preview.is_preview(obj)
                 and obj.visible_get(view_layer=self.view_layer,viewport=self.space)]
        # Build before hiding so evaluation sees exactly the original geometry.
        # Failure leaves every object visible rather than losing scene geometry.
        signature=tuple((obj.as_pointer(),obj.data.as_pointer(),tuple(value for row in obj.matrix_world for value in row)) for obj in objects)
        if objects and cfg.inactive_opacity>0 and (signature!=self._cache_signature or not self.cache):
            snap=SimpleNamespace(sources=objects,matrices=[o.matrix_world.copy() for o in objects])
            try:
                self.shader,self.cache=preview_geometry(context,snap)
                self._cache_signature=signature
            except (ValueError,ReferenceError,RuntimeError):
                self.restore();return
        try:
            for obj in objects:
                self.hidden[obj.as_pointer()]=obj
                obj.hide_set(True,view_layer=self.view_layer)
        except (ReferenceError,RuntimeError):
            # A removed/read-only guide cannot strand the earlier guides hidden.
            self.restore()

    def draw(self,opacity):
        if not self.hidden or not self.shader or not self.cache or opacity<=0:return
        import gpu
        self.shader.bind()
        shading=self.space.shading
        color=tuple(shading.single_color) if shading.type=='SOLID' else (.65,.65,.65)
        for matrix,wire,fill in self.cache:
            with gpu.matrix.push_pop():
                gpu.matrix.multiply_matrix(matrix)
                if fill and shading.type!='WIREFRAME':
                    self.shader.uniform_float('color',(*color,opacity*.35));fill.draw(self.shader)
                if wire:
                    gpu.state.line_width_set(1)
                    self.shader.uniform_float('color',(*color,opacity));wire.draw(self.shader)


class VIEW3D_OT_harhtools_array(bpy.types.Operator):
    bl_idname='view3d.harhtools_array'
    bl_label='Array'
    bl_description='Preview a group array; adjust the sidebar, then Generate or Enter to create copies'
    bl_options={'UNDO'}

    @classmethod
    def poll(cls,context):
        return (context.area is not None and context.area.type=='VIEW_3D' and context.mode=='OBJECT'
                and preview_state() is None
                and not bpy.app.driver_namespace.get('arch_tools_shape_builder')
                and not bpy.app.driver_namespace.get('harhtools_outline_preview'))

    def invoke(self,context,event):
        global _tab_active,_last_context
        _tab_active=True
        _last_context=(context.window.as_pointer(),context.area.as_pointer())
        self._done=False;self._handler=None;self._hud_handler=None;self._timer=None
        self._area=context.area;self._window=context.window;self._workspace=context.workspace
        self._region=next(r for r in self._area.regions if r.type=='WINDOW')
        self._cfg=settings(context);self._dirty=True;self._request=None;self._error='';self._waiting=False
        self._axis_reason=''
        self._plan=None;self._cache=[];self._snapshot=None;self._signature=None;self._fit_batch=None
        self._tween=array_tween.TweenPreview()
        self._tween_origin=Matrix.Identity(4);self._tween_inverse=Matrix.Identity(4)
        self._tween_revision=None;self._tween_sources=None;self._tween_mode=None
        self._geometry_dirty=False;self._source_ids=set();self._committing=False
        self._inactive=InactiveGuides(context.view_layer,self._area.spaces.active)
        array_material_preview.purge()
        self._native=array_material_preview.MaterialPreview(context.scene,self._area.spaces.active)
        self._native_dirty=True;self._native_sources=None;self._saving=False
        self._inactive_dirty=True
        self._sidebar_suspended=not sidebar_is_active(self._area)
        initialize_for_selection(context)
        try:
            self.refresh(context,geometry=True)
            self._handler=bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay,(),'WINDOW','POST_VIEW')
            self._hud_handler=bpy.types.SpaceView3D.draw_handler_add(self.draw_hud,(),'WINDOW','POST_PIXEL')
            bpy.app.driver_namespace[STATE_KEY]=self
            self._timer=context.window_manager.event_timer_add(1/60,window=self._window)
            context.window_manager.modal_handler_add(self)
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.finish(context);self.report({'ERROR'},str(exc));return {'CANCELLED'}

    def refresh(self,context,geometry=False):
        self._cursor=tuple(context.scene.cursor.location)
        angular_fit=self._cfg.mode=='CIRCULAR' and self._cfg.fit_ring and self._cfg.pivot!='BOUNDS'
        geometry=geometry or (angular_fit and self._snapshot is not None and not self._snapshot.geometry_points)
        geometry=geometry or self._snapshot is None
        if geometry:
            self._inactive_dirty=True
            # Keep retrying if the selection becomes empty or invalid temporarily.
            self._geometry_dirty=True
            try:self._snapshot=array_core.snapshot(context,geometry=angular_fit)
            except ValueError as exc:
                self._snapshot=None;self._plan=None;self._cache=[];self._fit_batch=None
                self._signature=selection_signature(context);self._source_ids=set()
                self._geometry_dirty=False;self._dirty=False;self._waiting=True
                self._error=str(exc);self._axis_reason='';self._tween.clear()
                self._native.clear();self._native_dirty=True
                self._workspace.status_text_set(None if self._sidebar_suspended else 'Array | Select mesh or curve objects to begin | Esc: cancel')
                self._area.tag_redraw()
                return
            self._signature=selection_signature(context)
            self._source_ids={item.as_pointer() for source in self._snapshot.sources for item in (source,source.data)}
            initialize_for_selection(context)
        self._waiting=False
        if self._cfg.auto_axis:
            region_3d=getattr(self._area.spaces.active,'region_3d',None)
            view_rotation=region_3d.view_rotation if region_3d else None
            axis,self._axis_reason=array_inference.suggest_axis(self._snapshot,self._cfg,context.scene,view_rotation)
            field='axes' if self._cfg.mode=='LINEAR' else 'radial_axis'
            if getattr(self._cfg,field)!=axis:setattr(self._cfg,field,axis)
        else:self._axis_reason='Manual axis'
        self._dirty=False
        self._fit_batch=None
        try:
            self._plan=array_core.build_plan(self._snapshot,self._cfg,context.scene)
            if self._plan.resolved_radius is not None:self._cfg.resolved_radius=self._plan.resolved_radius
            if self._plan.ring_info:
                self._cfg.resolved_count=self._plan.ring_info['count']
                self._cfg.resolved_step=self._plan.ring_info['step']
            self._error=''
        except ValueError as exc:
            self._plan=None;self._error=str(exc)
        if geometry and self._plan:
            self._shader,self._cache=preview_geometry(context,self._plan.source_snapshot or self._snapshot)
            self._geometry_dirty=False
            source=self._plan.source_snapshot or self._snapshot
            identities=(source.pointers,source.data_pointers)
            self._native_dirty=self._native_dirty or identities!=self._native_sources
            self._native_sources=identities
            if not self._native_dirty:
                self._native.matrices=[m.copy() for m in source.matrices]
        if self._plan and self._plan.fit_info:
            self._fit_batch=fit_marker(self._shader,self._plan)
        if self._plan:
            source=self._plan.source_snapshot or self._snapshot
            low,high=array_core._bounds(source.bounds_points)
            self._tween_origin=Matrix.Translation((low+high)*.5)
            self._tween_inverse=self._tween_origin.inverted()
            transforms=[self._tween_inverse @ matrix @ self._tween_origin for matrix in self._plan.transforms]
            identities=(source.pointers,source.data_pointers)
            revision=(tuple(tuple(value for row in matrix for value in row) for matrix in source.matrices),
                      tuple(tuple(point) for point in source.bounds_points))
            source_edit=(geometry and identities==self._tween_sources and revision!=self._tween_revision
                         and self._cfg.mode==self._tween_mode)
            self._tween.retarget(transforms,(identities,revision),
                                 mode=self._cfg.mode,fitted=bool(self._plan.fit_info))
            # Source edits replace the cached mesh/frame immediately. Parameter
            # changes tween; reusing an old pose with a new frame would jump.
            if source_edit:self._tween.settle()
            self._tween_sources=identities;self._tween_mode=self._cfg.mode;self._tween_revision=revision
        else:
            self._tween.clear();self._native.clear()
        self._workspace.status_text_set(None if self._sidebar_suspended else 'Array | Click to select | Shift + wheel: axis | Enter / Ctrl+A: apply | Esc: cancel')
        self._area.tag_redraw()

    def over_controls(self,event):
        return not (self._region.x<=event.mouse_x<self._region.x+self._region.width
                    and self._region.y<=event.mouse_y<self._region.y+self._region.height) or any(
            r.type!='WINDOW' and r.width>2 and r.height>2
            and r.x<=event.mouse_x<r.x+r.width and r.y<=event.mouse_y<r.y+r.height for r in self._area.regions)

    def generate(self,context):
        try:
            self._inactive.restore()
            self._native.clear();self._native_dirty=True
            self.refresh(context,geometry=self._geometry_dirty or selection_signature(context)!=self._signature)
            if self._error:raise ValueError(self._error)
            self._committing=True
            joined=self._cfg.join_generated
            copies=array_core.commit(context,self._snapshot,self._plan,linked=self._cfg.linked and not joined,join_generated=joined)
        except Exception as exc:
            self._error=str(exc);self.report({'ERROR'},str(exc));return {'RUNNING_MODAL'}
        finally:self._committing=False
        count=len(copies)
        self.finish(context)
        self.report({'INFO'},'Joined the original and copies into one mesh' if joined else f'Created {count} array objects; originals kept')
        return {'FINISHED'}

    def modal(self,context,event):
        if self._done:return {'CANCELLED'}
        try:valid=self._area.type=='VIEW_3D' and context.mode=='OBJECT' and self._region.width>0
        except ReferenceError:valid=False
        if not valid:
            self.finish(context);return {'CANCELLED'}
        if self._request=='CANCEL':self.finish(context);return {'CANCELLED'}
        if not sidebar_is_active(self._area):
            if not self._sidebar_suspended:
                self._sidebar_suspended=True
                self._inactive.restore();self._inactive_dirty=True
                self._native.clear();self._native_dirty=True
                self._workspace.status_text_set(None);self._area.tag_redraw()
            return {'PASS_THROUGH'}
        if self._sidebar_suspended:
            self._sidebar_suspended=False
            self._geometry_dirty=True;self._dirty=True;self._inactive_dirty=True
        if self._request=='GENERATE':
            self._request=None;return self.generate(context)
        if event.type=='TIMER':
            try:
                if self._inactive.view_layer!=context.view_layer:
                    self._inactive.restore()
                    self._inactive=InactiveGuides(context.view_layer,self._area.spaces.active)
                    self._inactive_dirty=True;self._geometry_dirty=True
                geometry=self._geometry_dirty or selection_signature(context)!=self._signature
                if geometry or self._dirty:self.refresh(context,geometry)
                elif (self._cfg.pivot=='CURSOR' and self._cfg.mode=='CIRCULAR'
                      and tuple(context.scene.cursor.location)!=self._cursor):self.refresh(context)
                if self._inactive_dirty and not native_scene_modal(self._window):
                    self._inactive.update(context,self._cfg)
                    self._inactive_dirty=False
                    self._area.tag_redraw()
                self.update_material_preview(context)
            except (ValueError,ReferenceError,RuntimeError) as exc:
                self._error=str(exc);self._plan=None;self._tween.clear();self._native.clear();self._area.tag_redraw()
            if self._tween.active():self._area.tag_redraw()
            return {'PASS_THROUGH'}
        # Sidebar controls do not start a scene-selection drag. Keep the fade
        # visible while scrubbing opacity, even when a native button consumes
        # its mouse release. Other editors are restored before native actions.
        over_sidebar=any(r.type=='UI' and r.width>2 and r.height>2
                         and r.x<=event.mouse_x<r.x+r.width and r.y<=event.mouse_y<r.y+r.height
                         for r in self._area.regions)
        if over_sidebar:return {'PASS_THROUGH'}
        if not self.over_controls(event):
            if event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE'} and event.shift:
                cycle_axis(self._cfg,1 if event.type=='WHEELUPMOUSE' else -1)
                self.refresh(context)
                return {'RUNNING_MODAL'}
            if event.type in {'MIDDLEMOUSE','WHEELUPMOUSE','WHEELDOWNMOUSE','TRACKPADPAN','TRACKPADZOOM','NDOF_MOTION'}:
                return {'PASS_THROUGH'}
        # Restore real objects before Blender handles an input event. This lets
        # native selection and transforms work even on a faded guide, and keeps
        # temporary hide flags out of native operators' undo snapshots.
        if event.type not in {'MOUSEMOVE','INBETWEEN_MOUSEMOVE'}:
            self._inactive.restore(clear_cache=False);self._inactive_dirty=True
        # Allow fields, popup menus and other sidebar controls to finish their input.
        if self.over_controls(event):return {'PASS_THROUGH'}
        keyconfig=context.window_manager.keyconfigs.active
        right_select=getattr(getattr(keyconfig,'preferences',None),'select_mouse','LEFT')=='RIGHT'
        if (event.type=='ESC' or (event.type=='RIGHTMOUSE' and not right_select)) and event.value=='PRESS':
            self.finish(context);return {'CANCELLED'}
        if shortcuts.confirm_event(event):return self.generate(context)
        if event.type=='MOUSEMOVE':return {'PASS_THROUGH'}
        # Let Blender handle selection, box select, and transforms normally.
        # The next timer tick rebuilds the preview from the new selection.
        return {'PASS_THROUGH'}

    def update_material_preview(self,context):
        enabled=(self._cfg.show_materials and self._area.spaces.active.shading.type in {'MATERIAL','RENDERED'}
                 and self._plan and not self._saving and not self._sidebar_suspended)
        if not enabled:
            self._native.clear();self._native_dirty=True
            return
        if self._native_dirty:
            self._native.rebuild(context,self._plan.source_snapshot or self._snapshot)
            self._native_dirty=False
        self._native.sync(self._tween.sample(),self._tween_origin,self._tween_inverse)

    def draw_overlay(self):
        if self._done or bpy.context.area!=self._area or not sidebar_is_active(self._area):return
        import gpu
        color=shortcuts.settings().accent_color
        old_blend=gpu.state.blend_get();old_depth=gpu.state.depth_test_get()
        old_mask=gpu.state.depth_mask_get();old_width=gpu.state.line_width_get()
        gpu.state.blend_set('ALPHA');gpu.state.depth_test_set('LESS_EQUAL');gpu.state.depth_mask_set(False)
        try:
            inactive=getattr(self,'_inactive',None)
            if inactive:inactive.draw(self._cfg.inactive_opacity/100)
            if not self._plan:return
            self._shader.bind()
            tween=getattr(self,'_tween',None)
            frames=tween.sample() if tween else [(matrix,1.0) for matrix in self._plan.transforms]
            # Native surfaces already show the material, including alpha holes.
            # Drawing the old pink triangles over them would fill those holes.
            for transform,alpha in ([] if self._native.ready else frames):
                if alpha<=.001:continue
                if tween:transform=self._tween_origin @ transform @ self._tween_inverse
                for source_matrix,wire,fill in self._cache:
                    with gpu.matrix.push_pop():
                        gpu.matrix.multiply_matrix(transform @ source_matrix)
                        if fill:
                            self._shader.uniform_float('color',(*color,.07*alpha));fill.draw(self._shader)
                        if wire:
                            gpu.state.line_width_set(1.4)
                            self._shader.uniform_float('color',(*color,.8*alpha));wire.draw(self._shader)
            if self._fit_batch:
                gpu.state.depth_test_set('NONE');gpu.state.line_width_set(1.4)
                self._shader.uniform_float('color',(*color,.8));self._fit_batch.draw(self._shader)
        finally:
            gpu.state.blend_set(old_blend);gpu.state.depth_test_set(old_depth)
            gpu.state.depth_mask_set(old_mask);gpu.state.line_width_set(old_width)

    def draw_hud(self):
        if self._done or bpy.context.area!=self._area or not sidebar_is_active(self._area):return
        import blf
        cfg=shortcuts.settings();scale=bpy.context.preferences.system.ui_scale
        if self._error:message=self._error
        elif not self._plan.new_object_count:message='No whole copies fit in this sweep  |  ESC to cancel' if self._plan.ring_info else 'No copies fit between these objects  |  ESC to cancel'
        else:message=f'{self._plan.new_object_count} new objects  |  SHIFT + wheel: axis  |  ENTER / CTRL+A to apply  |  ESC to cancel'
        blf.size(0,12*scale)
        width,_=blf.dimensions(0,message)
        x=max(12*scale,(self._region.width-width)*.5);y=22*scale
        blf.position(0,x+scale,y-scale,0);blf.color(0,.02,.02,.02,.95);blf.draw(0,message)
        blf.position(0,x,y,0);blf.color(0,*cfg.light_color,1);blf.draw(0,message)

    def finish(self,context=None):
        if self._done:return
        self._done=True
        if getattr(self,'_inactive',None):self._inactive.restore()
        if getattr(self,'_native',None):self._native.clear()
        for attr in ('_handler','_hud_handler'):
            handle=getattr(self,attr,None)
            if handle:bpy.types.SpaceView3D.draw_handler_remove(handle,'WINDOW');setattr(self,attr,None)
        if self._timer:
            try:(context or bpy.context).window_manager.event_timer_remove(self._timer)
            except (ReferenceError,RuntimeError):pass
            self._timer=None
        if bpy.app.driver_namespace.get(STATE_KEY) is self:bpy.app.driver_namespace.pop(STATE_KEY,None)
        self._cache=[];self._fit_batch=None
        if getattr(self,'_tween',None):self._tween.clear()
        try:self._workspace.status_text_set(None);self._area.tag_redraw()
        except ReferenceError:pass

    def cancel(self,context):self.finish(context)


class VIEW3D_OT_harhtools_array_action(bpy.types.Operator):
    bl_idname='view3d.harhtools_array_action'
    bl_label='Array Action'
    action:EnumProperty(items=[('GENERATE','Generate','Create the previewed copies'),('CANCEL','Cancel','Discard the preview')])
    @classmethod
    def poll(cls,context):return preview_state() is not None
    def execute(self,context):
        state=preview_state()
        if state:state._request=self.action
        return {'FINISHED'}


def axis_status(context):
    try:
        snap=array_core.snapshot(context)
        return array_core.axis_availability(snap,settings(context),context.scene)
    except (ValueError,ReferenceError) as exc:
        return {axis:(False,str(exc)) for axis in 'XYZ'}


class VIEW3D_OT_harhtools_array_axis(bpy.types.Operator):
    bl_idname='view3d.harhtools_array_axis'
    bl_label='Array Axis'
    axis:EnumProperty(items=[('AUTO','Auto','Infer direction from the selection and view')]+[(axis,axis,'') for axis in 'XYZ'])

    @classmethod
    def description(cls,context,properties):
        if properties.axis=='AUTO':
            state=preview_state()
            reason=(state._axis_reason+'. ') if state and state._axis_reason else ''
            return reason+'Choose the axis from the shape, view, or direction to the Fit target'
        allowed,reason=axis_status(context).get(properties.axis,(False,'Select an axis.'))
        return f'Use {properties.axis} manually' if allowed else f'Use {properties.axis} manually. {reason}'

    def execute(self,context):
        cfg=settings(context)
        cfg.auto_axis=self.axis=='AUTO'
        if self.axis!='AUTO':
            if cfg.mode=='LINEAR':cfg.axes=self.axis
            else:cfg.radial_axis=self.axis
        ensure_preview(context)
        return {'FINISHED'}


class VIEW3D_OT_harhtools_array_mode(bpy.types.Operator):
    bl_idname='view3d.harhtools_array_mode'
    bl_label='Array Mode'
    mode:EnumProperty(items=[('LINEAR','Linear','Repeat in a row'),('CIRCULAR','Circular','Repeat around the source')])

    def execute(self,context):
        settings(context).mode=self.mode
        ensure_preview(context)
        return {'FINISHED'}


def cycle_axis(cfg,direction=1):
    """Wheel changes are explicit overrides, just like clicking X/Y/Z."""
    field='axes' if cfg.mode=='LINEAR' else 'radial_axis'
    axis=getattr(cfg,field)
    cfg.auto_axis=False
    setattr(cfg,field,'XYZ'[('XYZ'.index(axis)+direction)%3])


def ensure_preview(context):
    """Start from an explicit tool click or a scheduled history recovery."""
    global _tab_active
    _tab_active=True
    if preview_state() is not None:return True
    if not VIEW3D_OT_harhtools_array.poll(context):return False
    return bpy.ops.view3d.harhtools_array('INVOKE_DEFAULT')=={'RUNNING_MODAL'}


def stop_preview(context=None):
    """Discard a preview and restore scene visibility immediately."""
    state=preview_state()
    if state is not None:
        try:state.finish(context)
        except (AttributeError,ReferenceError,RuntimeError):_discard_stale_state(state)


def set_tab_active(context,active):
    """Call from the sidebar tab operator; do not call during UI drawing."""
    global _tab_active,_history_target
    _tab_active=bool(active)
    if _tab_active:return ensure_preview(context)
    _history_target=None
    stop_preview(context)
    return False


def fit_marker(shader,plan):
    from gpu_extras.batch import batch_for_shader
    from mathutils import Vector
    info=plan.fit_info;axis=info['axis'];start=info['start'];end=info['end']
    candidates=[]
    for basis in (Vector((0,0,1)),Vector((0,1,0)),Vector((1,0,0))):
        direction=plan.frame.to_3x3() @ basis
        direction-=axis*direction.dot(axis)
        if direction.length<.001:continue
        direction.normalize()
        projections=[point.dot(direction) for point in plan.source_snapshot.bounds_points]
        candidates.append((max(projections)-min(projections),direction))
    cross=max(candidates,key=lambda item:item[0])[1]*max(info['length']*.025,.00001)
    points=[tuple(start),tuple(end),tuple(start-cross),tuple(start+cross),tuple(end-cross),tuple(end+cross)]
    return batch_for_shader(shader,'LINES',{'pos':points})


def format_length(context,value):
    return display_units.format_length(context,value)


def _toggle_label(layout,cfg,property_name,label,icon=None,enabled=True):
    """A consistent compact toggle, followed by readable unboxed text."""
    row=layout.row(align=False);row.enabled=enabled
    button=row.row(align=False);button.ui_units_x=2.2
    kwargs={'text':'On' if getattr(cfg,property_name) else 'Off','toggle':True}
    if icon:kwargs['icon']=icon
    button.prop(cfg,property_name,**kwargs)
    row.label(text=label)


def draw_direction(layout,context):
    cfg=settings(context)
    column=layout.column(align=False);column.scale_y=shortcuts.CONTROL_HEIGHT
    column.operator('view3d.harhtools_array_axis',text='Auto Axis',depress=cfg.auto_axis).axis='AUTO'
    selected_axis=cfg.axes if cfg.mode=='LINEAR' else cfg.radial_axis
    axes=column.row(align=False)
    for axis in 'XYZ':
        axes.operator('view3d.harhtools_array_axis',text=axis,depress=selected_axis==axis).axis=axis
    row=column.row(align=False)
    for value,label in [('WORLD','Global'),('ACTIVE','Last')]:row.prop_enum(cfg,'orientation',value,text=label)


def draw_pattern(layout,context):
    cfg=settings(context);state=preview_state()
    column=layout.column(align=False);column.scale_y=shortcuts.CONTROL_HEIGHT
    row=column.row(align=False)
    for value,label in [('LINEAR','Linear'),('CIRCULAR','Circular')]:
        row.operator('view3d.harhtools_array_mode',text=label,depress=cfg.mode==value).mode=value
    if cfg.mode=='LINEAR':
        _toggle_label(column,cfg,'fit_length','Fit Length')
        if cfg.fit_length:
            display_units.draw(column,cfg,'gap',context,text='Min Gap')
            selected=context.selected_objects;active=context.view_layer.objects.active
            if len(selected)==2 and active in selected:
                target=next(obj for obj in selected if obj!=active)
                column.label(text='Repeat: '+active.name[:24])
                column.label(text='To: '+target.name[:28])
            else:
                column.label(text='Select 2; repeat the last selected',icon='INFO')
            if state and state._plan and state._plan.fit_info:
                info=state._plan.fit_info
                column.label(text=f"{info['count']} copies fit")
                column.label(text='Gap: '+format_length(context,info['gap']))
        else:
            column.prop(cfg,'count')
            display_units.draw(column,cfg,'gap',context)
    else:
        angular_fit=cfg.fit_ring and cfg.pivot!='BOUNDS'
        row=column.row();row.enabled=not angular_fit
        row.prop(cfg,'resolved_count' if angular_fit else 'count',text='Copies' if angular_fit else 'Count')
        column.label(text='Center')
        row=column.row(align=False)
        for value,label in [('BOUNDS','Source'),('ACTIVE','Last'),('CURSOR','3D Cursor')]:
            row.prop_enum(cfg,'pivot',value,text=label)
        row=column.row()
        computed=cfg.pivot!='BOUNDS' or cfg.fit_ring
        row.enabled=not computed
        display_units.draw(row,cfg,'resolved_radius' if computed else 'radius',context,text='Radius')
        column.prop(cfg,'sweep')
        _toggle_label(column,cfg,'rotate_copies','Rotate Copies',enabled=not cfg.fit_ring)
        _toggle_label(column,cfg,'fit_ring','Fit Ring')
        if angular_fit:
            row=column.row();row.enabled=False;row.prop(cfg,'resolved_step',text='Step')
            if state and state._plan and state._plan.ring_info:
                remaining=state._plan.ring_info['remainder']
                if remaining>0:
                    column.label(text=f'{math.degrees(remaining):.2f}\N{DEGREE SIGN} left open')
        if cfg.fit_ring and cfg.pivot=='BOUNDS':
            row=column.row(align=False)
            for value,label in [('INSIDE','Inside'),('CENTER','Centers'),('OUTSIDE','Outside')]:row.prop_enum(cfg,'fit_side',value,text=label)
    _toggle_label(column,cfg,'linked','Linked Copies',enabled=not cfg.join_generated)


def draw_visibility(layout,context):
    cfg=settings(context)
    column=layout.column(align=False);column.scale_y=shortcuts.CONTROL_HEIGHT
    column.enabled=bool(context.selected_objects)
    _toggle_label(column,cfg,'show_materials','Show Materials')
    _toggle_label(column,cfg,'hide_inactive','Hide Inactive',icon='HIDE_ON' if cfg.hide_inactive else 'HIDE_OFF')
    opacity=column.row();opacity.enabled=cfg.hide_inactive
    opacity.prop(cfg,'inactive_opacity',text='Opacity',slider=True)


def draw_deform(layout,context):
    cfg=settings(context)
    paused=array_core.deformation_paused(cfg)
    _toggle_label(layout,cfg,'deform_enabled','Deform Copies',enabled=not paused)
    if paused:
        layout.label(text='Deform pauses while Fit is on.')
        return
    if not cfg.deform_enabled:return
    layout.prop(cfg,'deform_scale',slider=True)
    layout.prop(cfg,'deform_ease')
    if cfg.mode=='LINEAR':layout.prop(cfg,'deform_keep_gap')
    layout.prop(cfg,'deform_extra',toggle=True)
    if cfg.deform_extra:
        display_units.draw(layout,cfg,'deform_offset',context)
        layout.prop(cfg,'deform_rotation')
    layout.label(text='Original size stays unchanged.')


def draw_actions(layout,context):
    cfg=settings(context);state=preview_state()
    column=layout.column(align=False);column.scale_y=shortcuts.CONTROL_HEIGHT
    _toggle_label(column,cfg,'join_generated','Join Generated')
    if cfg.join_generated:
        column.label(text='Original + copies in one mesh')
        if cfg.mode=='CIRCULAR':column.label(text='Origin at rotation center')
    if state:
        if state._error:
            error=column.column(align=True);error.alert=not state._waiting
            for line in textwrap.wrap(state._error,30):error.label(text=line)
        elif state._plan and not (cfg.mode=='LINEAR' and cfg.fit_length):
            column.label(text=f'{state._plan.new_object_count:,} copies → 1 mesh' if cfg.join_generated else f'{state._plan.new_object_count:,} new objects')
        row=column.row(align=False)
        generate=row.row();generate.enabled=bool(state._plan and state._plan.new_object_count and not state._error)
        generate.operator('view3d.harhtools_array_action',text='Generate',icon='CHECKMARK').action='GENERATE'
        row.operator('view3d.harhtools_array_action',text='Cancel',icon='X').action='CANCEL'
    else:
        if bpy.app.driver_namespace.get('arch_tools_shape_builder'):column.label(text='Finish Shape Builder first',icon='INFO')
        elif context.mode!='OBJECT':column.label(text='Switch to Object Mode',icon='INFO')


def draw_panel(layout,context):
    layout.label(text='Array',icon_value=icons.icon('array'))
    for title,key,draw in [('Direction','ARRAY_DIRECTION',draw_direction),
                           ('Pattern','ARRAY_PATTERN',draw_pattern),
                           ('Deform','ARRAY_DEFORM',draw_deform),
                           ('Visibility','ARRAY_VISIBILITY',draw_visibility)]:
        body=shortcuts.section_box(layout,context,title,key)
        if body is not None:draw(body,context)
    draw_actions(layout,context)


@persistent
def cancel_running(*_args):
    global _tab_active,_history_target,_last_context
    _tab_active=False;_history_target=None;_last_context=None
    stop_preview()


@persistent
def history_pre(*_args):
    """Release RNA/GPU references before Blender replaces undo data."""
    global _history_target
    state=preview_state()
    _history_target=None
    if state and not state._done and _tab_active:
        _history_target=(state._window.as_pointer(),state._area.as_pointer())
    elif _tab_active and _last_context:
        # Undoing Generate should reopen the restored source's preview too.
        _history_target=_last_context
    stop_preview()


def _resume_history():
    global _history_target,_resume_timer
    _resume_timer=None
    target=_history_target;_history_target=None
    if not target or not _tab_active:return None
    win_id,area_id=target
    for window in bpy.context.window_manager.windows:
        if window.as_pointer()!=win_id:continue
        for area in window.screen.areas:
            if area.as_pointer()!=area_id or area.type!='VIEW_3D':continue
            region=next((r for r in area.regions if r.type=='WINDOW'),None)
            if region is None:return None
            with bpy.context.temp_override(window=window,area=area,region=region):
                # Native interactions/history restore our temporary hide flags
                # before Blender captures/replaces state. Trust the checkpoint:
                # a formerly visible guide may intentionally be hidden there.
                if bpy.context.mode=='OBJECT':ensure_preview(bpy.context)
            return None
    return None


@persistent
def history_post(*_args):
    global _resume_timer
    array_material_preview.purge()
    if _history_target and _tab_active and not bpy.app.timers.is_registered(_resume_history):
        _resume_timer=_resume_history
        bpy.app.timers.register(_resume_history,first_interval=.08)


@persistent
def save_pre(*_args):
    state=preview_state()
    if state:
        state._inactive.restore()
        state._saving=True;state._native.clear();state._native_dirty=True
    array_material_preview.purge()


@persistent
def save_post(*_args):
    state=preview_state()
    if state:state._inactive_dirty=True;state._saving=False


@persistent
def source_updated(_scene,depsgraph):
    state=preview_state()
    if not state or state._done or state._committing:return
    inactive_ids=set()
    inactive=getattr(state,'_inactive',None)
    if inactive:
        for obj in inactive.hidden.values():
            try:inactive_ids.update((obj.as_pointer(),obj.data.as_pointer()))
            except ReferenceError:pass
    for update in depsgraph.updates:
        if not (update.is_updated_geometry or update.is_updated_transform):continue
        pointer=update.id.original.as_pointer()
        if pointer in state._source_ids:
            state._geometry_dirty=True
            if update.is_updated_geometry:state._native_dirty=True
        if pointer in inactive_ids:
            inactive._cache_signature=None
            state._inactive_dirty=True


_CLASSES=(HARHTOOLS_PG_array,VIEW3D_OT_harhtools_array,VIEW3D_OT_harhtools_array_action,VIEW3D_OT_harhtools_array_axis,VIEW3D_OT_harhtools_array_mode)


def register():
    cancel_running()
    for cls in _CLASSES:bpy.utils.register_class(cls)
    bpy.types.WindowManager.harhtools_array=PointerProperty(type=HARHTOOLS_PG_array)
    for handlers,callback in _handler_pairs():
        if callback not in handlers:handlers.append(callback)
    if source_updated not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(source_updated)


def unregister():
    cancel_running()
    if bpy.app.timers.is_registered(_resume_history):bpy.app.timers.unregister(_resume_history)
    if source_updated in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(source_updated)
    for handlers,callback in _handler_pairs():
        if callback in handlers:handlers.remove(callback)
    if hasattr(bpy.types.WindowManager,'harhtools_array'):del bpy.types.WindowManager.harhtools_array
    for cls in reversed(_CLASSES):
        if cls.is_registered:bpy.utils.unregister_class(cls)


def _handler_pairs():
    return ((bpy.app.handlers.load_pre,cancel_running),
            (bpy.app.handlers.undo_pre,history_pre),(bpy.app.handlers.redo_pre,history_pre),
            (bpy.app.handlers.undo_post,history_post),(bpy.app.handlers.redo_post,history_post),
            (bpy.app.handlers.save_pre,save_pre),(bpy.app.handlers.save_post,save_post))
