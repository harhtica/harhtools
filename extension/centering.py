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
from . import icons


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


class VIEW3D_PT_center_selected_to_active(bpy.types.Panel):
    bl_label = 'harhtools'
    bl_idname = 'VIEW3D_PT_center_selected_to_active'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'harhtools'

    def draw_header(self, context):
        self.layout.label(text='', icon_value=icons.icon('heart'))

    def draw(self, context):
        layout = self.layout.box()
        state=bpy.app.driver_namespace.get('arch_tools_shape_builder')
        if getattr(bpy.types,'VIEW3D_OT_arch_shape_builder',None):
            row=layout.row();row.scale_y=1.25
            row.operator('view3d.arch_shape_builder',text='Shape Builder  (Active)' if state else 'Shape Builder  (Shift+M)',icon_value=icons.icon('shape'),depress=bool(state))
            mode=('REMOVE' if state._alt else 'ADD') if state else context.window_manager.arch_shape_builder_mode
            row=layout.row(align=True);row.alignment='CENTER'
            row.operator('view3d.harhtools_shape_mode',text='Add',icon_value=icons.icon('add'),depress=mode=='ADD').mode='ADD'
            row.operator('view3d.harhtools_shape_mode',text='Remove',icon_value=icons.icon('remove'),depress=mode=='REMOVE').mode='REMOVE'
            row=layout.row();row.enabled=not bool(state)
            row.prop(context.window_manager,'arch_shape_builder_gap_snap')
            layout.separator()
        layout.label(text='Center to active',icon_value=icons.icon('heart'))
        column=layout.column(align=True);column.enabled=not bool(state)
        column.operator('object.center_selected_to_active', text='Center Shapes to Active', icon_value=icons.icon('bounds')).center_method = 'BOUNDS'
        column.operator('object.center_selected_to_active', text='Match Origins to Active', icon_value=icons.icon('origin')).center_method = 'ORIGIN'
        row=layout.row();row.scale_y=.8
        row.label(text='Select the target last.')


def register():
    clear_notification()
    for cls in (OBJECT_OT_center_selected_to_active,VIEW3D_PT_center_selected_to_active):
        previous=getattr(bpy.types,cls.__name__,None)
        if previous:bpy.utils.unregister_class(previous)
        bpy.utils.register_class(cls)


def unregister():
    clear_notification()
    for cls in (VIEW3D_PT_center_selected_to_active,OBJECT_OT_center_selected_to_active):
        previous=getattr(bpy.types,cls.__name__,None)
        if previous:bpy.utils.unregister_class(previous)
