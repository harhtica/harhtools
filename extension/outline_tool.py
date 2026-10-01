"""Interactive, non-destructive planar outlines with optional geometry snapping."""
import math
import bpy
from mathutils import Vector
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty
from . import outline_geometry, outline_snap, shortcuts

STATE_KEY = 'harhtools_outline_preview'


def settings(context=None):
    return (context or bpy.context).window_manager.harhtools_outline


def _changed(_cfg, context):
    state = bpy.app.driver_namespace.get(STATE_KEY)
    if state and not getattr(state, '_updating_settings', False):
        state.refresh(context)


class HARHTOOLS_PG_outline(bpy.types.PropertyGroup):
    thickness: FloatProperty(name='Thickness', default=.05, min=.000001,
                             subtype='DISTANCE', unit='LENGTH', precision=4,
                             description='Even world-space distance from the original boundary', update=_changed)
    direction: EnumProperty(name='Direction', default='INWARD', items=[
        ('INWARD', 'Inside', 'Create a border inside the original shape'),
        ('OUTWARD', 'Outside', 'Create a border outside the original shape')], update=_changed)
    snap_geometry: BoolProperty(name='Snap to Geometry', default=False,
                                description='Snap thickness to nearby coplanar curves and mesh edges while dragging', update=_changed)
    hide_sources: BoolProperty(name='Hide Original Shapes', default=True,
                               description='Keep the original shapes recoverable but hide their filled centers after creating outlines')


def source_signature(objects):
    signatures = []
    for obj in objects:
        data = obj.data
        if obj.type == 'CURVE':
            shape = tuple((s.type, s.use_cyclic_u,
                tuple((tuple(p.co), tuple(p.handle_left), tuple(p.handle_right)) for p in s.bezier_points)
                if s.type == 'BEZIER' else tuple(tuple(p.co) for p in s.points)) for s in data.splines)
        else:
            shape = (tuple(tuple(v.co) for v in data.vertices),
                     tuple(tuple(e.vertices) for e in data.edges),
                     tuple(tuple(p.vertices) for p in data.polygons))
        signatures.append((obj.as_pointer(), data.as_pointer(),
                           tuple(value for row in obj.matrix_world for value in row), shape))
    return tuple(signatures)


def prepare_selection(context):
    if context.mode != 'OBJECT':
        raise ValueError('Use Object Mode and select the closed shapes to outline.')
    objects = [obj for obj in context.selected_objects if obj.type in {'CURVE', 'MESH'} and obj.visible_get()]
    if not objects:
        raise ValueError('Select a closed curve or planar filled shape first.')
    prepared = [outline_geometry.prepare_sources([obj]) for obj in objects]
    first = prepared[0]
    normal = Vector(first['normal']); origin = Vector(first['origin'])
    tolerance = max(item['scale'] for item in prepared) * 1e-5
    for item in prepared[1:]:
        if abs(normal.dot(Vector(item['normal']))) < 1 - 1e-6 or abs((Vector(item['origin']) - origin).dot(normal)) > tolerance:
            raise ValueError('Selected outlines must lie on the same plane.')
    return objects, prepared


def make_results(prepared, thickness, direction):
    return [outline_geometry.build_outline(item, thickness, direction=direction) for item in prepared]


def commit_outlines(context, sources, results, expected_signature, *, hide_sources=True):
    """Build all data first; cancellation/failure never leaves partial outlines."""
    if not sources or len(sources) != len(results):
        raise ValueError('Every selected source needs one valid outline result.')
    if source_signature(sources) != expected_signature:
        raise ValueError('An original shape changed. Restart Make Outline before confirming.')
    data_blocks = []; outputs = []
    old_selection = list(context.selected_objects)
    old_active = context.view_layer.objects.active
    hidden = [(obj, obj.hide_get()) for obj in sources]
    try:
        for source, result in zip(sources, results):
            data_blocks.append(outline_geometry.make_curve_data(result, name=source.name + ' Outline'))
        for source, result, data in zip(sources, results, data_blocks):
            obj = bpy.data.objects.new(source.name + ' Outline', data); outputs.append(obj)
            obj.matrix_world = result['matrix_world']
            collections = source.users_collection or (context.collection or context.scene.collection,)
            for collection in collections:
                collection.objects.link(obj)
            obj.color = source.color
            obj['harhtools_outline_thickness'] = float(result.get('thickness', settings(context).thickness))
            obj['harhtools_outline_source'] = source.name
            for material in source.data.materials:
                obj.data.materials.append(material)
        for obj in old_selection:
            obj.select_set(False)
        if hide_sources:
            for source in sources:
                source.hide_set(True)
        for obj in outputs:
            obj.select_set(True)
        context.view_layer.objects.active = outputs[-1]
        context.view_layer.update()
        return outputs
    except Exception:
        for obj in outputs:
            bpy.data.objects.remove(obj, do_unlink=True)
        for data in data_blocks:
            if data.users == 0:
                bpy.data.curves.remove(data)
        for obj, was_hidden in hidden:
            obj.hide_set(was_hidden)
        for obj in old_selection:
            obj.select_set(True)
        context.view_layer.objects.active = old_active
        raise


def _nearest_boundary(point, loops):
    best = None
    for loop in loops:
        for a, b in zip(loop, loop[1:] + loop[:1]):
            a = Vector(a); b = Vector(b); delta = b - a
            t = max(0., min(1., (point - a).dot(delta) / max(delta.length_squared, 1e-30)))
            foot = a + delta * t; distance = (point - foot).length
            if best is None or distance < best[0]:
                best = (distance, foot)
    return best


def inside_sources(point, prepared):
    return bool(source_owners_at(point, prepared, inside=True))


def source_owners_at(point, prepared, *, inside):
    owners = set()
    for index, item in enumerate(prepared):
        delta = Vector(point) - Vector(item['origin'])
        xy = (delta.dot(Vector(item['u'])), delta.dot(Vector(item['v'])))
        if outline_geometry._inside(xy, item['loops']) == inside:
            owners.add(index)
    return owners


class VIEW3D_OT_harhtools_make_outline(bpy.types.Operator):
    bl_idname = 'view3d.harhtools_make_outline'
    bl_label = 'Make Outline'
    bl_description = 'Preview an even border around selected closed shapes; drag thickness and optionally snap to nearby geometry'
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and context.active_object is not None
                and not any(bpy.app.driver_namespace.get(key) for key in
                    (STATE_KEY, 'arch_tools_shape_builder', 'harhtools_array_preview')))

    def execute(self, context):
        try:
            sources, prepared = prepare_selection(context)
            cfg = settings(context)
            results = make_results(prepared, cfg.thickness, cfg.direction)
            outputs = commit_outlines(context, sources, results, source_signature(sources), hide_sources=cfg.hide_sources)
            self.report({'INFO'}, f'Created {len(outputs)} outline(s). Shape Library saves only with +.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            return self.execute(context)
        self._done = False; self._handler = None; self._cursor_handler = None
        self._area = context.area; self._window = context.window; self._workspace = context.workspace
        self._dragging = False; self._updating_settings = False; self._results = []; self._error = ''
        self._batches = None; self._shader = None; self._snap_hit = None; self._measure = None
        self._region = next(r for r in self._area.regions if r.type == 'WINDOW')
        self._view = self._area.spaces.active.region_3d
        cfg = settings(context)
        self._original_settings = (cfg.thickness, cfg.direction, cfg.snap_geometry)
        try:
            self._sources, self._prepared = prepare_selection(context)
            # Dragging uses a lighter outline. Confirmation recomputes the
            # tighter final geometry and validates it before changing the scene.
            self._preview_prepared = [outline_geometry.prepare_sources([source], tolerance=item['scale'] * 2e-4)
                                      for source, item in zip(self._sources, self._prepared)]
            self._signature = source_signature(self._sources)
            first = self._prepared[0]
            self._origin = Vector(first['origin']); self._normal = Vector(first['normal'])
            self._world_loops = [list(loop) for item in self._prepared for loop in item['world_loops']]
            self._snap = outline_snap.OutlineSnapCache(context, self._origin, self._normal,
                max(item['scale'] for item in self._prepared), self._world_loops,
                excluded_objects=self._sources,
                source_segments=[dict(segment, owner=index) for index, item in enumerate(self._prepared)
                                 for segment in item['world_segments']])
            bpy.app.driver_namespace[STATE_KEY] = self
            self.refresh(context)
            self._handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_preview, (), 'WINDOW', 'POST_VIEW')
            self._cursor_handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_hint, (), 'WINDOW', 'POST_PIXEL')
            self._window.cursor_modal_set('CROSSHAIR')
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.finish(context, cancel=True); self.report({'ERROR'}, str(exc)); return {'CANCELLED'}

    def refresh(self, context):
        if self._done:
            return
        cfg = settings(context)
        try:
            prepared = [preview if cfg.thickness > preview['tolerance'] * 8 else precise
                        for preview, precise in zip(self._preview_prepared, self._prepared)]
            self._results = make_results(prepared, cfg.thickness, cfg.direction)
            self._error = ''
        except Exception as exc:
            self._results = []; self._error = str(exc)
        self._batches = None
        self._workspace.status_text_set('Make Outline | Drag: thickness | S: geometry snap | Enter: create | Esc: cancel'
            + (' | ' + self._error if self._error else ''))
        self._area.tag_redraw()

    def over_controls(self, event):
        return any(r.type in {'UI', 'TOOLS', 'HEADER', 'TOOL_HEADER'} and r.width > 2 and r.height > 2
                   and r.x <= event.mouse_x < r.x + r.width and r.y <= event.mouse_y < r.y + r.height
                   for r in self._area.regions)

    def _plane_point(self, xy):
        from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
        ray = region_2d_to_origin_3d(self._region, self._view, xy)
        direction = region_2d_to_vector_3d(self._region, self._view, xy)
        divisor = direction.dot(self._normal)
        if abs(divisor) < 1e-9:
            return None
        return ray + direction * ((self._origin - ray).dot(self._normal) / divisor)

    def mouse(self, context, event):
        xy = Vector((event.mouse_x - self._region.x, event.mouse_y - self._region.y))
        point = self._plane_point(xy)
        if point is None:
            return
        cfg = settings(context)
        def eligible(world):
            return source_owners_at(world, self._prepared, inside=cfg.direction == 'INWARD')
        self._snap_hit = (self._snap.query(xy, self._region, self._view, source_filter=eligible)
                          if cfg.snap_geometry else None)
        if self._snap_hit:
            candidate = Vector(self._snap_hit['world_point'])
            # A target on the opposite side cannot set an inset/outset that
            # actually touches it. Never show a false snap on that side.
            if eligible(candidate):
                point = candidate
            else:
                self._snap_hit = None
        owners = eligible(point)
        loops = [list(loop) for index in owners for loop in self._prepared[index]['world_loops']]
        nearest = _nearest_boundary(point, loops)
        if nearest is None:
            self._measure = None; self._area.tag_redraw()
            return
        distance, foot = nearest
        if self._snap_hit:
            distance = self._snap_hit['thickness']
            foot = Vector(self._snap_hit['nearest_source_point'])
        self._measure = (foot, point)
        if self._dragging and distance > 1e-6:
            if abs(distance - cfg.thickness) > max(1e-7, cfg.thickness * 1e-4):
                cfg.thickness = distance
        self._area.tag_redraw()

    def modal(self, context, event):
        if self._done:
            return {'CANCELLED'}
        if self._area.type != 'VIEW_3D' or context.mode != 'OBJECT':
            self.finish(context, cancel=True); return {'CANCELLED'}
        if self.over_controls(event):
            self._dragging = False
            return {'PASS_THROUGH'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self.finish(context, cancel=True); return {'CANCELLED'}
        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if self._error or not self._results:
                self.report({'WARNING'}, self._error or 'Choose a valid thickness first.'); return {'RUNNING_MODAL'}
            try:
                cfg = settings(context)
                results = make_results(self._prepared, cfg.thickness, cfg.direction)
                outputs = commit_outlines(context, self._sources, results, self._signature,
                                          hide_sources=cfg.hide_sources)
            except Exception as exc:
                self.report({'ERROR'}, str(exc)); return {'RUNNING_MODAL'}
            self.finish(context)
            self.report({'INFO'}, f'Created {len(outputs)} outline(s). Originals are recoverable; nothing was saved to Shape Library.')
            return {'FINISHED'}
        if event.type == 'S' and event.value == 'PRESS':
            cfg = settings(context); cfg.snap_geometry = not cfg.snap_geometry
            self.mouse(context, event); return {'RUNNING_MODAL'}
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM', 'NDOF_MOTION'}:
            self._dragging = False; return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self._dragging = True
                self.mouse(context, event)
            elif event.value == 'RELEASE':
                if self._dragging:
                    self.mouse(context, event)
                self._dragging = False
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            self.mouse(context, event); return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    def draw_preview(self):
        if self._done or bpy.context.area != self._area:
            return
        import gpu
        from gpu_extras.batch import batch_for_shader
        if self._shader is None:
            self._shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        shader = self._shader
        if self._batches is None:
            lines = []
            for result in self._results:
                matrix = result['matrix_world']
                for loop in result['border_loops']:
                    world = [matrix @ Vector((p[0], p[1], 0)) for p in loop]
                    for a, b in zip(world, world[1:] + world[:1]):
                        lines.extend((a, b))
            self._batches = batch_for_shader(shader, 'LINES', {'pos': lines}) if lines else False
        old_blend = gpu.state.blend_get(); old_depth = gpu.state.depth_test_get(); old_mask = gpu.state.depth_mask_get()
        try:
            gpu.state.blend_set('ALPHA'); gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(False)
            shader.bind(); shader.uniform_float('viewportSize', gpu.state.viewport_get()[2:])
            shader.uniform_float('lineWidth', 2 * bpy.context.preferences.system.ui_scale)
            cfg = shortcuts.settings()
            shader.uniform_float('color', (*cfg.accent_color, 1))
            if self._batches:
                self._batches.draw(shader)
            if self._measure and self._dragging:
                shader.uniform_float('color', (*cfg.light_color, 1))
                batch_for_shader(shader, 'LINES', {'pos': self._measure}).draw(shader)
        finally:
            gpu.state.blend_set(old_blend); gpu.state.depth_test_set(old_depth); gpu.state.depth_mask_set(old_mask)

    def draw_hint(self):
        if self._done or bpy.context.area != self._area:
            return
        import blf
        cfg = settings(); scale = bpy.context.preferences.system.ui_scale
        width = bpy.utils.units.to_string(bpy.context.scene.unit_settings.system, 'LENGTH', cfg.thickness,
                                         precision=4, split_unit=False)
        message = ('Cannot create: ' + self._error if self._error else
                   f'Thickness {width} | Snap {"ON" if cfg.snap_geometry else "OFF"} (S) | Drag to adjust | Enter to create')
        if self._snap_hit:
            message += ' | ' + self._snap_hit['object_name']
        blf.size(0, round(13 * scale)); blf.position(0, 20 * scale, 28 * scale, 0)
        blf.color(0, *(shortcuts.settings().remove_color if self._error else shortcuts.settings().light_color), 1)
        blf.draw(0, message)

    def finish(self, context=None, *, cancel=False):
        if getattr(self, '_done', False):
            return
        self._done = True
        for name in ('_handler', '_cursor_handler'):
            handler = getattr(self, name, None)
            if handler:
                bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW'); setattr(self, name, None)
        if bpy.app.driver_namespace.get(STATE_KEY) is self:
            bpy.app.driver_namespace.pop(STATE_KEY, None)
        try:
            self._workspace.status_text_set(None); self._window.cursor_modal_restore(); self._area.tag_redraw()
        except (ReferenceError, AttributeError):
            pass
        if cancel and context is not None:
            cfg = settings(context)
            cfg.thickness, cfg.direction, cfg.snap_geometry = self._original_settings


def cancel_running(*_args):
    state = bpy.app.driver_namespace.get(STATE_KEY)
    if state:
        state.finish()


def draw_panel(layout, context):
    box = layout.box(); box.label(text='Make Outline')
    cfg = settings(context); state = bpy.app.driver_namespace.get(STATE_KEY)
    box.prop(cfg, 'thickness'); box.prop(cfg, 'direction')
    box.prop(cfg, 'snap_geometry'); box.prop(cfg, 'hide_sources')
    row = box.row(); row.enabled = state is None
    row.operator('view3d.harhtools_make_outline', text='Make Outline', icon='MOD_SOLIDIFY')
    if context.mode != 'OBJECT':
        box.label(text='Select closed shapes in Object Mode.')
    elif state:
        box.label(text='Drag: thickness; S: snap on/off')
        box.label(text='Enter: create; Esc: cancel')
        if state._error:
            box.label(text='Reduce thickness or repair the shape.', icon='ERROR')


def register():
    for cls in (HARHTOOLS_PG_outline, VIEW3D_OT_harhtools_make_outline):
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.harhtools_outline = PointerProperty(type=HARHTOOLS_PG_outline)
    bpy.app.handlers.load_pre.append(cancel_running)


def unregister():
    cancel_running()
    if cancel_running in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(cancel_running)
    if hasattr(bpy.types.WindowManager, 'harhtools_outline'):
        del bpy.types.WindowManager.harhtools_outline
    for cls in (VIEW3D_OT_harhtools_make_outline, HARHTOOLS_PG_outline):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
