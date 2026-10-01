"""Run once to add a button in 3D View > N sidebar > harhtools.

In Object Mode, select the objects to move, then select the target LAST.
Click Center to Active. The active object stays in place. Each other selected
object moves independently, keeping its rotation, scale, mesh, and origin offset.
Center Shapes to Active matches the shapes' bounding-box centers.
Match Origins to Active moves the objects so their origins coincide with the
active object's origin; it does not reposition an origin relative to its mesh.
The completion message shows the actual distance and world X/Y/Z movement for
each object, using the scene units (or BU when no unit system is configured).
Small red/purple text appears at the target center for one second. Its size
tracks the target's on-screen size. Full movement details remain in the Info log.
Ctrl+Z undoes a button click. Running this file only installs the button.
"""
import bpy
from mathutils import Vector
from bpy.props import EnumProperty
import time
from . import icons, shortcuts, array_tool, shape_library, outline_tool, live_reload, fit_tool


_NOTICE_KEY = 'arch_tools_center_notification'
NOTICE_RED = (1.0, 0.22, 0.28, 1.0)
NOTICE_PURPLE = (0.78, 0.44, 1.0, 1.0)


def clear_notification(*_args):
    state = bpy.app.driver_namespace.pop(_NOTICE_KEY, None)
    if state:
        bpy.types.SpaceView3D.draw_handler_remove(state['handle'], 'WINDOW')
        if bpy.app.timers.is_registered(state['tick']):
            bpy.app.timers.unregister(state['tick'])
        if state['cleanup'] in bpy.app.handlers.load_pre:
            bpy.app.handlers.load_pre.remove(state['cleanup'])
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D': area.tag_redraw()


def show_notification(context, text, color, method='BOUNDS', duration=1.0):
    """One small, zoom-aware line at the actual world-space centering target."""
    if bpy.app.background:
        return
    import blf
    import gpu
    from bpy_extras.view3d_utils import location_3d_to_region_2d

    clear_notification()
    area = context.area if context.area and context.area.type == 'VIEW_3D' else next(
        (a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
    target = context.active_object
    if area is None or target is None:
        return
    depsgraph = context.evaluated_depsgraph_get()
    anchor = object_center(target, depsgraph, method).copy()
    evaluated = target.evaluated_get(depsgraph)
    corners = [evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box]
    area_pointer = area.as_pointer()
    deadline = time.monotonic() + duration
    ui_scale = context.preferences.system.ui_scale

    def draw():
        ctx = bpy.context
        if not ctx.area or ctx.area.as_pointer() != area_pointer:
            return
        region, view = ctx.region, ctx.region_data
        if region is None or view is None:
            return
        point = location_3d_to_region_2d(region, view, anchor)
        if point is None or not (0 <= point.x <= region.width and 0 <= point.y <= region.height):
            return
        projected = [p for corner in corners
                     if (p := location_3d_to_region_2d(region, view, corner)) is not None]
        span = max((max(p[i] for p in projected)-min(p[i] for p in projected)
                    for i in range(2)), default=0) if projected else 0
        # Gentle zoom scaling, capped to stay small even very close to the shape.
        size = min(14.0, max(8.0, 10.0*(max(span,1)/(180*ui_scale))**.35))*ui_scale
        fade = min(1.0, max(0.0, (deadline-time.monotonic())/.25))
        old_blend = gpu.state.blend_get()
        gpu.state.blend_set('ALPHA')
        try:
            blf.size(0,size)
            width, _ = blf.dimensions(0,text)
            blf.position(0,point.x-width/2,point.y+7*ui_scale,0)
            blf.color(0,*color[:3],color[3]*fade)
            blf.draw(0,text)
        finally:
            blf.color(0,1,1,1,1)
            gpu.state.blend_set(old_blend)

    def tick():
        if time.monotonic() >= deadline:
            state = bpy.app.driver_namespace.pop(_NOTICE_KEY, None)
            if state:
                bpy.types.SpaceView3D.draw_handler_remove(state['handle'], 'WINDOW')
                if state['cleanup'] in bpy.app.handlers.load_pre:
                    bpy.app.handlers.load_pre.remove(state['cleanup'])
            for window in bpy.context.window_manager.windows:
                for a in window.screen.areas:
                    if a.type == 'VIEW_3D': a.tag_redraw()
            return None
        for window in bpy.context.window_manager.windows:
            for a in window.screen.areas:
                if a.type == 'VIEW_3D' and a.as_pointer() == area_pointer: a.tag_redraw()
        return .033

    handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
    bpy.app.driver_namespace[_NOTICE_KEY] = {'handle':handle,'tick':tick,'cleanup':clear_notification}
    bpy.app.handlers.load_pre.append(clear_notification)
    bpy.app.timers.register(tick, first_interval=.05)
    area.tag_redraw()


def object_center(obj, depsgraph, method):
    if method == 'ORIGIN':
        return obj.matrix_world.translation.copy()
    evaluated = obj.evaluated_get(depsgraph)
    # Measure visible geometry in one shared coordinate system. A local
    # bounding-box center depends on an object's local axes; identical outlines
    # with differently rotated mesh coordinates can otherwise move apart.
    if evaluated.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
        mesh = evaluated.to_mesh()
        try:
            if mesh is not None and mesh.vertices:
                matrix = evaluated.matrix_world
                first = matrix @ mesh.vertices[0].co
                lower, upper = first.copy(), first.copy()
                for vertex in mesh.vertices:
                    point = matrix @ vertex.co
                    for axis in range(3):
                        lower[axis] = min(lower[axis], point[axis])
                        upper[axis] = max(upper[axis], point[axis])
                return (lower + upper) * 0.5
        finally:
            evaluated.to_mesh_clear()
    corners = evaluated.bound_box
    if all(tuple(corner) == (-1.0, -1.0, -1.0) for corner in corners):
        return evaluated.matrix_world.translation.copy()
    local_center = sum((Vector(corner) for corner in corners), Vector()) / 8.0
    return evaluated.matrix_world @ local_center


def parent_depth(obj):
    count = 0
    while obj.parent:
        obj = obj.parent
        count += 1
    return count


def format_length(scene, value, signed=False):
    units = scene.unit_settings
    magnitude = abs(value)
    if units.system == 'NONE':
        text = f'{magnitude:.6g} BU'
    else:
        text = bpy.utils.units.to_string(
            units.system, 'LENGTH', magnitude * units.scale_length, precision=5)
    if signed and value != 0:
        text = ('+' if value > 0 else '-') + text
    return text


def format_move(scene, delta):
    offsets = ', '.join(f'{axis} {format_length(scene,value,signed=True)}'
                        for axis, value in zip('XYZ', delta))
    return f'{format_length(scene,delta.length)} ({offsets})'


def center_selection(context, method='BOUNDS'):
    active = context.view_layer.objects.active
    selected = list(context.selected_objects)
    if context.mode != 'OBJECT' or active not in selected or len(selected) < 2:
        raise ValueError('In Object Mode, select at least two objects; select the target last.')
    if any(not obj.is_editable for obj in selected):
        raise ValueError('The selected objects must be editable.')
    context.view_layer.update()
    depsgraph = context.evaluated_depsgraph_get()
    anchor = object_center(active, depsgraph, method)
    # Ignore sub-micron numerical jitter at ordinary scene coordinates.
    center_epsilon = max(1e-7, max(abs(x) for x in anchor) * 1e-7)
    original_world = {obj: obj.matrix_world.copy() for obj in selected}
    original_basis = {obj: obj.matrix_basis.copy() for obj in selected}
    desired = {}
    for obj in selected:
        matrix = original_world[obj].copy()
        if obj != active:
            delta = anchor - object_center(obj, depsgraph, method)
            if max(abs(x) for x in delta) > center_epsilon:
                matrix.translation += delta
        desired[obj] = matrix
    ordered = sorted(selected, key=parent_depth)
    try:
        # Parents first; restore the active object's world transform too if a
        # selected parent moved it. Children then receive their own final target.
        for obj in ordered:
            if any(abs(obj.matrix_world[r][c] - desired[obj][r][c]) > 1e-9
                   for r in range(4) for c in range(4)):
                obj.matrix_world = desired[obj]
                context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        tolerance = max(1e-5, max(abs(x) for x in anchor) * 2e-6)
        for obj in selected:
            expected = original_world[obj] if obj == active else desired[obj]
            if ((object_center(obj, depsgraph, method) - anchor).length > tolerance
                    or any(abs(obj.matrix_world[r][c] - expected[r][c]) > tolerance
                           for r in range(4) for c in range(4))):
                raise ValueError('A constraint, driver, or parent transform prevented centering; no moves were kept.')
    except Exception:
        for obj in ordered:
            obj.matrix_basis = original_basis[obj]
        context.view_layer.update()
        raise
    return len(selected) - 1


class OBJECT_OT_center_selected_to_active(bpy.types.Operator):
    bl_idname = 'object.center_selected_to_active'
    bl_label = 'Center to Active'
    bl_description = 'Move the other selected objects to the active object center, preserving rotation and scale'
    bl_options = {'REGISTER', 'UNDO'}

    center_method: EnumProperty(
        name='Center Using',
        items=[('BOUNDS', 'Bounds', 'Match the visible shapes bounding-box centers'),
               ('ORIGIN', 'Origins', 'Match the object origins')],
        default='BOUNDS',
    )

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and context.active_object is not None
                and not bpy.app.driver_namespace.get(array_tool.STATE_KEY)
                and context.active_object in context.selected_objects
                and len(context.selected_objects) > 1)

    @classmethod
    def description(cls, context, properties):
        if properties.center_method == 'ORIGIN':
            return 'Move the other selected objects so their origins match the active object origin; keep rotation and scale'
        return 'Move the other selected shapes so their bounding-box centers match the active shape center; keep rotation and scale'

    def execute(self, context):
        try:
            context.view_layer.update()
            active = context.active_object
            before = {obj: obj.matrix_world.translation.copy()
                      for obj in context.selected_objects if obj != active}
            count = center_selection(context, self.center_method)
            moves = [(obj.name, obj.matrix_world.translation - position)
                     for obj, position in before.items()]
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        moved = [(name,delta) for name,delta in moves if delta.length_squared > 0]
        if not moved:
            self.report({'INFO'}, f'ALREADY CENTERED to {active.name} | No movement')
            show_notification(context, 'ALREADY CENTERED', NOTICE_RED, method=self.center_method)
            return {'CANCELLED'}  # No unnecessary undo step for a no-op.
        lines = [(f'{name}: ' if count > 1 else '') +
                 (format_move(context.scene,delta) if delta.length_squared > 0 else 'ALREADY CENTERED')
                 for name,delta in moves]
        self.report({'INFO'}, f'Centered {len(moved)} object(s) to {active.name} | Moved ' + '; '.join(lines))
        distances = [delta.length for _,delta in moved]
        if len(moved) == 1:
            short_message = 'MOVED ' + format_length(context.scene,distances[0])
        else:
            short_message = (f'MOVED {len(moved)} | ' + format_length(context.scene,min(distances))
                             + ' - ' + format_length(context.scene,max(distances)))
        show_notification(context, short_message, NOTICE_PURPLE, method=self.center_method)
        return {'FINISHED'}


class VIEW3D_OT_harhtools_panel_tab(bpy.types.Operator):
    bl_idname='view3d.harhtools_panel_tab'
    bl_label='harhtools Tab'
    bl_description='Open Shape Builder, Fit / Align, Array, your shape library, or settings'
    tab: EnumProperty(items=[('TOOLS','Shape Builder','Build shapes from selected outlines'),
                            ('TRANSFORM','Transform','Legacy alignment tab'),
                            ('FIT','Fit / Align','Fit arrangements into frames and align shapes'),
                            ('ARRAY','Array','Repeat and fit selected shapes'),
                            ('LIBRARY','Shape Library','Reuse your saved shapes'),
                            ('SETTINGS','Settings','Shortcuts and color themes')])

    @classmethod
    def description(cls,context,properties):
        return {'TOOLS':'Shape Builder','TRANSFORM':'Fit / Align', 'FIT':'Fit / Align — fit arrangements and balance gaps',
                'ARRAY':'Array — repeat and fit shapes','LIBRARY':'Shape Library — saved shapes',
                'SETTINGS':'Settings — shortcuts and colors'}.get(properties.tab,'harhtools')

    def execute(self,context):
        context.window_manager.harhtools_panel_tab={'LIBRARY':'TOOLS','TRANSFORM':'FIT'}.get(self.tab,self.tab)
        array_tool.set_tab_active(context,self.tab=='ARRAY')
        if context.area:context.area.tag_redraw()
        return {'FINISHED'}


class VIEW3D_PT_center_selected_to_active(bpy.types.Panel):
    bl_label = 'harhtools'
    bl_idname = 'VIEW3D_PT_center_selected_to_active'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'harhtools'

    def draw(self, context):
        tab=context.window_manager.harhtools_panel_tab
        if tab=='LIBRARY':tab='TOOLS'  # Older saved scripts still open this page.
        if tab=='TRANSFORM':tab='FIT'
        row=self.layout.row()
        rail=row.column(align=False);rail.ui_units_x=1.6
        tool_rail=rail.column(align=False);tool_rail.scale_y=1.3
        for key,icon in [('TOOLS','shape'),('FIT','bounds'),('ARRAY','array')]:
            tool_rail.operator('view3d.harhtools_panel_tab',text='',icon_value=icons.icon(icon),depress=tab==key).tab=key
            tool_rail.separator(factor=.2)
        content=row.column()
        content.prop(context.window_manager,'harhtools_distance_units')
        if tab=='ARRAY':
            array_tool.draw_panel(content,context)
        elif tab=='SETTINGS':
            content.label(text='Settings')
            content.label(text='1 Roblox stud = 0.28 m; scene scale is respected.')
            update_box=content.box()
            update_box.label(text='Harhtools '+context.window_manager.harhtools_live_reload_version)
            update_box.prop(context.window_manager,'harhtools_live_reload_enabled')
            update_box.label(text=live_reload.status())
            shortcuts.draw_shortcuts(content,context,compact=True)
        elif tab=='FIT':
            content.label(text='Fit / Align')
            fit_tool.draw_panel(content,context)
            from . import display_units
            if context.active_object:
                content.label(text='Selected object size')
                for axis,value in zip('XYZ',context.active_object.dimensions):
                    content.label(text=axis+': '+display_units.format_length(context,value))
            draw_center_box(content,context)
        else:
            from . import circle_arc,edit_arc
            if context.mode=='EDIT_MESH':edit_arc.draw_panel(content,context)
            else:circle_arc.draw_panel(content,context)
            for index,section in enumerate(shortcuts.section_order(shortcuts.settings(context),'TOOLS')):
                if index:content.separator(factor=.4)
                {'BUILDER':draw_builder_box,'LIBRARY':shape_library.draw_panel}[section](content,context)
                if section=='BUILDER':
                    content.separator(factor=.4)
                    outline_tool.draw_panel(content,context)
        # Separate footer below the entire content, so Settings stays at the
        # bottom even when the Library or Settings page is taller than Tools.
        self.layout.separator(factor=.45)
        footer=self.layout.row(align=False)
        gear=footer.column(align=False);gear.ui_units_x=1.6;gear.scale_y=1.3
        gear.operator('view3d.harhtools_panel_tab',text='',icon_value=icons.icon('gear'),depress=tab=='SETTINGS').tab='SETTINGS'
        footer.column().label(text='')


def draw_builder_box(layout,context):
    if not getattr(bpy.types,'VIEW3D_OT_arch_shape_builder',None):return
    state=bpy.app.driver_namespace.get('arch_tools_shape_builder');active=bool(state)
    box=shortcuts.section_box(layout,context,'Shape Builder','BUILDER','TOOLS',icons.icon('shape'))
    if box is None:return
    wm=context.window_manager
    controls=box.column(align=True);controls.enabled=not active
    controls.prop(wm,'arch_shape_builder_edit_mode',text='Work on')
    output=controls.row(align=True);output.enabled=wm.arch_shape_builder_edit_mode!='EDGES'
    output.prop(wm,'arch_shape_builder_output_type',text='Result')
    if wm.arch_shape_builder_edit_mode=='EDGES':
        box.label(text='Alt-drag trims; click restores.')
    else:
        box.label(text='Click: separate fill; drag: merge touched.')
        box.label(text='Alt-click/drag removes touched regions.')
    box.label(text='Enter / Ctrl+A applies; Esc cancels.')
    row=box.row(align=False);row.scale_y=shortcuts.CONTROL_HEIGHT
    row.enabled=not bool(bpy.app.driver_namespace.get(array_tool.STATE_KEY) or bpy.app.driver_namespace.get(outline_tool.STATE_KEY))
    row.operator('view3d.arch_shape_builder',text='On',depress=active)
    mode=('REMOVE' if state._alt else 'ADD') if state else context.window_manager.arch_shape_builder_mode
    row=box.split(factor=.5,align=False);row.scale_y=shortcuts.CONTROL_HEIGHT;row.enabled=active
    row.column(align=False).operator('view3d.harhtools_shape_mode',text='Add',icon_value=icons.icon('add'),depress=active and mode=='ADD').mode='ADD'
    row.column(align=False).operator('view3d.harhtools_shape_mode',text='Remove',icon_value=icons.icon('remove'),depress=active and mode=='REMOVE').mode='REMOVE'
    row=box.row(align=False);row.scale_y=shortcuts.CONTROL_HEIGHT;row.enabled=not active
    row.prop(context.window_manager,'arch_shape_builder_gap_snap')
    row=box.row(align=False)
    curve_input=any(o.type=='CURVE' for o in context.selected_objects)
    row.enabled=not curve_input and not active
    row.prop(context.window_manager,'arch_shape_builder_cut_guides')
    if curve_input:box.label(text='Original curve guides stay unchanged.')


def draw_center_box(layout,context):
    box=shortcuts.section_box(layout,context,'Align','CENTER','TRANSFORM',icons.icon('align'))
    if box is None:return
    column=box.column(align=False)
    column.enabled=not bool(bpy.app.driver_namespace.get('arch_tools_shape_builder') or bpy.app.driver_namespace.get(array_tool.STATE_KEY))
    column.scale_y=shortcuts.CONTROL_HEIGHT
    column.operator('object.center_selected_to_active',text='Center Shapes to Last',icon_value=icons.icon('bounds')).center_method='BOUNDS'
    column.operator('object.center_selected_to_active',text='Match Origins to Last',icon_value=icons.icon('origin')).center_method='ORIGIN'


def register_panel_tab():
    if not hasattr(bpy.types.WindowManager,'harhtools_panel_tab'):
        bpy.types.WindowManager.harhtools_panel_tab=EnumProperty(
            name='harhtools Tab',items=[('TOOLS','Shape Builder',''),('TRANSFORM','Transform',''),('FIT','Fit / Align',''),
                                      ('ARRAY','Array',''),('LIBRARY','Shape Library',''),('SETTINGS','Settings','')],
            default='TOOLS',options={'SKIP_SAVE'})
    previous=getattr(bpy.types,'VIEW3D_OT_harhtools_panel_tab',None)
    if previous:bpy.utils.unregister_class(previous)
    bpy.utils.register_class(VIEW3D_OT_harhtools_panel_tab)


def register():
    clear_notification()
    register_panel_tab()
    for cls in (OBJECT_OT_center_selected_to_active,VIEW3D_PT_center_selected_to_active):
        previous=getattr(bpy.types,cls.__name__,None)
        if previous:bpy.utils.unregister_class(previous)
        bpy.utils.register_class(cls)


def unregister():
    clear_notification()
    for cls in (VIEW3D_PT_center_selected_to_active,OBJECT_OT_center_selected_to_active,VIEW3D_OT_harhtools_panel_tab):
        previous=getattr(bpy.types,cls.__name__,None)
        if previous:bpy.utils.unregister_class(previous)
    if hasattr(bpy.types.WindowManager,'harhtools_panel_tab'):
        del bpy.types.WindowManager.harhtools_panel_tab
