"""Interactive, non-destructive planar outlines with optional geometry snapping."""
import math
import time
import bpy
from mathutils import Vector
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from . import outline_geometry, outline_snap, outline_profiles, shortcuts, display_units, profile_editor

STATE_KEY = 'harhtools_outline_preview'
PREVIEW_INTERVAL = 1 / 30


def settings(context=None):
    return (context or bpy.context).window_manager.harhtools_outline


def _changed(_cfg, context):
    state = bpy.app.driver_namespace.get(STATE_KEY)
    if state and not getattr(state, '_updating_settings', False):
        state.request_refresh(context)


def _snap_changed(_cfg, context):
    state = bpy.app.driver_namespace.get(STATE_KEY)
    if state:
        state.request_pointer(context)


def _profile_changed(cfg,context):
    if cfg.bevel_profile in outline_profiles.NAMES and cfg.bevel_segments<32:
        cfg.bevel_segments=32
    _changed(cfg,context)


class HARHTOOLS_PG_outline(bpy.types.PropertyGroup):
    bevel_ui_ready:BoolProperty(default=False,options={'HIDDEN'})
    edited_profile:PointerProperty(type=bpy.types.Curve,name='My Profile',poll=profile_editor.poll_asset,update=_changed)
    working_profile:PointerProperty(type=bpy.types.Curve,options={'SKIP_SAVE'})
    thickness_studs:display_units.distance_property('thickness','Thickness')
    bevel_depth_studs:display_units.distance_property('bevel_depth','Depth')
    bevel_width_studs:display_units.distance_property('bevel_width','Bevel Width')
    thickness: FloatProperty(name='Thickness', default=.05, min=.000001,
                             subtype='DISTANCE', unit='LENGTH', precision=4,
                             description='Even world-space distance from the original boundary', update=_changed)
    direction: EnumProperty(name='Direction', default='INWARD', items=[
        ('INWARD', 'Inside', 'Create a border inside the original shape'),
        ('OUTWARD', 'Outside', 'Create a border outside the original shape')], update=_changed)
    join_style: EnumProperty(name='Corners', default='MITER', items=[
        ('MITER', 'Sharp', 'Intersect offset edges to keep pointed corners sharp'),
        ('ROUND', 'Round', 'Use circular joins where corners open')], update=_changed)
    output_type: EnumProperty(name='Result', default='MESH', items=[
        ('MESH', 'Mesh Border', 'Connected border faces ready for mesh editing and extrusion'),
        ('CURVE', 'Curve Outline', 'A filled outline with sampled Poly spline boundaries')], update=_changed)
    snap_geometry: BoolProperty(name='Snap to Geometry', default=False,
                                description='Snap thickness to nearby coplanar curves and mesh edges while dragging', update=_snap_changed)
    hide_sources: BoolProperty(name='Hide Original Shapes', default=True,
                               description='Keep the original shapes recoverable but hide their filled centers after creating outlines')
    bevel_enabled: BoolProperty(name='Add Bevel', default=False,
                                description='Preview and add editable depth and perimeter bevel modifiers', update=_changed)
    bevel_depth: FloatProperty(name='Depth', default=.005, min=.000001, subtype='DISTANCE', unit='LENGTH', precision=4, update=_changed)
    bevel_width: FloatProperty(name='Bevel Width', default=.0003, min=.000001, subtype='DISTANCE', unit='LENGTH', precision=4, update=_changed)
    bevel_segments: IntProperty(name='Segments', default=6, min=1, max=128, soft_max=64, update=_changed)
    bevel_profile: EnumProperty(name='Profile', default='ROUND', items=[
        ('ROUND','Rounded','Circular edge profile'),('CHAMFER','Chamfer','Single flat bevel face'),
        ('CONCAVE','Concave','Inward-curved profile'),('SQUARE','Soft Square','Fuller convex profile'),
        ('CUSTOM','Custom','Adjust the native bevel shape value')]+outline_profiles.ITEMS+[
        ('EDITED','My Profile','An editable copy; built-in presets remain unchanged')], update=_profile_changed)
    bevel_shape: FloatProperty(name='Shape', default=.5, min=0, max=1, update=_changed)


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
    normal = first.get('_normal64', first['normal'])
    origin = first.get('_origin64', first['origin'])
    tolerance = max(item['scale'] for item in prepared) * 1e-5
    for item in prepared[1:]:
        other_normal = item.get('_normal64', item['normal'])
        other_origin = item.get('_origin64', item['origin'])
        alignment = math.fsum(a * b for a, b in zip(normal, other_normal))
        separation = math.fsum((a - b) * n for a, b, n in zip(other_origin, origin, normal))
        if abs(alignment) < 1 - 1e-6 or abs(separation) > tolerance:
            raise ValueError('Selected outlines must lie on the same plane.')
    return objects, prepared


def make_results(prepared, thickness, direction, join_style='ROUND'):
    return [outline_geometry.build_outline(item, thickness, direction=direction, join_style=join_style) for item in prepared]


def commit_outlines(context, sources, results, expected_signature, *, hide_sources=True, output_type='CURVE', bevel_options=None):
    """Build all data first; cancellation/failure never leaves partial outlines."""
    if not sources or len(sources) != len(results):
        raise ValueError('Every selected source needs one valid outline result.')
    if source_signature(sources) != expected_signature:
        raise ValueError('An original shape changed. Restart Make Outline before confirming.')
    if output_type == 'MESH':
        from . import outline_mesh
        create_data = outline_mesh.make_mesh_data
    elif output_type == 'CURVE':
        create_data = outline_geometry.make_curve_data
    else:
        raise ValueError('Outline result must be Mesh Border or Curve Outline.')
    data_blocks = []; outputs = []
    old_selection = list(context.selected_objects)
    old_active = context.view_layer.objects.active
    hidden = [(obj, obj.hide_get()) for obj in sources]
    try:
        for source, result in zip(sources, results):
            data_blocks.append(create_data(result, name=source.name + ' Outline'))
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
        if bevel_options is not None:
            if output_type!='MESH':raise ValueError('Add Bevel requires Mesh Border output.')
            from . import outline_bevel
            outline_bevel.apply(outputs,**bevel_options)
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
                (bpy.data.meshes if isinstance(data, bpy.types.Mesh) else bpy.data.curves).remove(data)
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


def bevel_options(cfg):
    if not cfg.bevel_enabled or cfg.output_type!='MESH':return None
    from . import outline_bevel
    return outline_bevel.options(cfg)


class OBJECT_OT_harhtools_border_bevel(bpy.types.Operator):
    bl_idname='object.harhtools_border_bevel'
    bl_label='Update Border Bevel'
    bl_description='Add or update editable depth and bevel profiles on selected flat mesh borders'
    bl_options={'REGISTER','UNDO'}

    @classmethod
    def poll(cls,context):
        return context.mode=='OBJECT' and any(obj.type=='MESH' for obj in context.selected_objects) and not bpy.app.driver_namespace.get(STATE_KEY)

    def execute(self,context):
        from . import outline_bevel
        try:
            objects=[obj for obj in context.selected_objects if obj.type=='MESH']
            outline_bevel.apply(objects,**outline_bevel.options(settings(context)))
            self.report({'INFO'},f'Updated {len(objects)} border bevel(s). Depth and bevel modifiers remain editable.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


def _inside_index(item):
    """Index immutable prepared boundaries by height for frequent snap picking."""
    cached = item.get('_harhtools_inside_index')
    if cached is not None:
        return cached
    points = [point for loop in item['loops'] for point in loop]
    xmin = min(p[0] for p in points); xmax = max(p[0] for p in points)
    ymin = min(p[1] for p in points); ymax = max(p[1] for p in points)
    count = min(128, max(8, math.ceil(math.sqrt(len(points)))))
    step = max((ymax - ymin) / count, 1e-30)
    buckets = [[] for _ in range(count)]
    for loop in item['loops']:
        for a, b in zip(loop, loop[1:] + loop[:1]):
            if a[1] == b[1]:
                continue
            low = max(0, min(count - 1, int((min(a[1], b[1]) - ymin) / step)))
            high = max(0, min(count - 1, int((max(a[1], b[1]) - ymin) / step)))
            edge = (a[0], a[1], b[0], b[1])
            for index in range(low, high + 1):
                buckets[index].append(edge)
    cached = (xmin, xmax, ymin, ymax, step, buckets)
    item['_harhtools_inside_index'] = cached
    return cached


def _inside_prepared(xy, item):
    xmin, xmax, ymin, ymax, step, buckets = _inside_index(item)
    x, y = xy
    if x < xmin or x > xmax or y < ymin or y > ymax:
        return False
    index = min(len(buckets) - 1, max(0, int((y - ymin) / step)))
    inside = False
    for ax, ay, bx, by in buckets[index]:
        if (ay > y) != (by > y) and ax + (y - ay) * (bx - ax) / (by - ay) > x:
            inside = not inside
    return inside


def source_owners_at(point, prepared, *, inside):
    owners = set()
    for index, item in enumerate(prepared):
        origin = item.get('_origin64', item['origin'])
        delta = tuple(float(p) - o for p, o in zip(point, origin))
        u, v = item.get('_u64', item['u']), item.get('_v64', item['v'])
        xy = (math.fsum(a * b for a, b in zip(delta, u)),
              math.fsum(a * b for a, b in zip(delta, v)))
        if _inside_prepared(xy, item) == inside:
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
            results = make_results(prepared, cfg.thickness, cfg.direction, cfg.join_style)
            outputs = commit_outlines(context, sources, results, source_signature(sources),
                                      hide_sources=cfg.hide_sources, output_type=cfg.output_type, bevel_options=bevel_options(cfg))
            self.report({'INFO'}, f'Created {len(outputs)} outline(s). Shape Library saves only with +.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            return self.execute(context)
        self._done = False; self._handler = None; self._cursor_handler = None
        self._timer = None; self._wm = context.window_manager
        self._pending_mouse = None; self._last_mouse = None
        self._preview_dirty = True; self._preview_key = None
        self._next_tick = 0.0
        self._area = context.area; self._window = context.window; self._workspace = context.workspace
        self._dragging = False; self._updating_settings = False; self._results = []; self._error = ''
        self._batches = None; self._shader = None; self._snap_hit = None; self._measure = None
        self._surface = None; self._surface_batch = None; self._surface_shader = None
        self._outline_key = None
        self._region = next(r for r in self._area.regions if r.type == 'WINDOW')
        self._view = self._area.spaces.active.region_3d
        cfg = settings(context)
        self._original_settings = {name:getattr(cfg,name) for name in ('thickness','direction','snap_geometry','join_style','output_type',
            'bevel_enabled','bevel_depth','bevel_width','bevel_segments','bevel_profile','bevel_shape')}
        try:
            self._sources, self._prepared = prepare_selection(context)
            # Dragging uses a lighter outline. Confirmation recomputes the
            # tighter final geometry and validates it before changing the scene.
            self._preview_prepared = [outline_geometry.prepare_sources([source], tolerance=item['scale'] * 5e-4)
                                      for source, item in zip(self._sources, self._prepared)]
            self._signature = source_signature(self._sources)
            for item in self._prepared:
                _inside_index(item)
            first = self._prepared[0]
            self._origin = Vector(first['origin']); self._normal = Vector(first['normal'])
            self._world_loops = [list(loop) for item in self._prepared for loop in item['world_loops']]
            self._snap = outline_snap.OutlineSnapCache(context,
                first.get('_origin64', first['origin']), first.get('_normal64', first['normal']),
                max(item['scale'] for item in self._prepared), self._world_loops,
                excluded_objects=self._sources, lazy_targets=not cfg.snap_geometry,
                source_segments=[dict(segment, owner=index) for index, item in enumerate(self._prepared)
                                 for segment in item['world_segments']])
            bpy.app.driver_namespace[STATE_KEY] = self
            self.refresh(context)
            self._handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_preview, (), 'WINDOW', 'POST_VIEW')
            self._cursor_handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_hint, (), 'WINDOW', 'POST_PIXEL')
            self._window.cursor_modal_set('CROSSHAIR')
            self._timer = self._wm.event_timer_add(PREVIEW_INTERVAL, window=self._window)
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.finish(context, cancel=True); self.report({'ERROR'}, str(exc)); return {'CANCELLED'}

    def request_refresh(self, context):
        if not self._done:
            self._preview_dirty = True
            self._area.tag_redraw()

    def request_pointer(self, context):
        if self._done:
            return
        self._snap_hit = None; self._measure = None
        if self._dragging and self._last_mouse is not None:
            self._pending_mouse = self._last_mouse
        self._area.tag_redraw()

    def queue_pointer(self, event):
        self._pending_mouse = (event.mouse_x, event.mouse_y)
        self._last_mouse = self._pending_mouse

    def flush_pending(self, context, *, preview=True):
        pending = self._pending_mouse
        self._pending_mouse = None
        if pending is not None:
            from types import SimpleNamespace
            self.mouse(context, SimpleNamespace(mouse_x=pending[0], mouse_y=pending[1]))
        if preview and self._preview_dirty:
            self.refresh(context)

    def refresh(self, context):
        if self._done:
            return
        cfg = settings(context)
        outline_key = (float(cfg.thickness), cfg.direction, cfg.join_style)
        bevel = bevel_options(cfg)
        key = (outline_key, tuple(sorted(bevel.items())) if bevel else None)
        self._preview_dirty = False
        if key == getattr(self, '_preview_key', None):
            return  # Identical valid or invalid widths do not need another solve.
        self._preview_key = key
        try:
            if outline_key != getattr(self,'_outline_key',None):
                prepared = [preview if cfg.thickness > preview['tolerance'] * 8 else precise
                            for preview, precise in zip(self._preview_prepared, self._prepared)]
                self._results = make_results(prepared, cfg.thickness, cfg.direction, cfg.join_style)
                self._outline_key = outline_key
            self._surface = None
            if bevel:
                from . import outline_preview
                self._surface = outline_preview.surface(self._results,bevel)
            self._error = ''
        except Exception as exc:
            self._results = []; self._surface = None; self._outline_key=None; self._error = str(exc)
        self._batches = None; self._surface_batch=None
        self._workspace.status_text_set('Make Outline | Drag: thickness | S: geometry snap | Enter / Ctrl+A: apply | Esc: cancel'
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
            owners = eligible(candidate)
            if owners:
                point = candidate
            else:
                self._snap_hit = None
        if self._snap_hit:
            distance = self._snap_hit['thickness']
            foot = Vector(self._snap_hit['nearest_source_point'])
        else:
            owners = eligible(point)
            nearest = self._snap.nearest_source(point, allowed_owners=owners) if owners else None
            if nearest is None:
                self._measure = None; self._area.tag_redraw()
                return
            distance, foot = nearest
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
        if event.type == 'TIMER':
            # Blender Event does not expose its originating Timer. Coalesce by
            # elapsed time, and pass timer events on to other listeners.
            now = time.monotonic()
            if now >= self._next_tick:
                self._next_tick = now + PREVIEW_INTERVAL
                self.flush_pending(context)
            return {'PASS_THROUGH'}
        if event.type == 'ESC' and event.value == 'PRESS':
            self.finish(context, cancel=True); return {'CANCELLED'}
        if self.over_controls(event):
            self._dragging = False
            self._pending_mouse = None
            return {'PASS_THROUGH'}
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            self.finish(context, cancel=True); return {'CANCELLED'}
        if shortcuts.confirm_event(event):
            try:
                # A typed value or final mouse move may still be queued. Always
                # validate the CURRENT precise shape, not a stale preview error.
                self.flush_pending(context, preview=False)
                cfg = settings(context)
                results = make_results(self._prepared, cfg.thickness, cfg.direction, cfg.join_style)
                outputs = commit_outlines(context, self._sources, results, self._signature,
                                          hide_sources=cfg.hide_sources, output_type=cfg.output_type, bevel_options=bevel_options(cfg))
            except Exception as exc:
                self._error = str(exc)
                self.report({'ERROR'}, self._error); return {'RUNNING_MODAL'}
            self.finish(context)
            self.report({'INFO'}, f'Created {len(outputs)} outline(s). Originals are recoverable; nothing was saved to Shape Library.')
            return {'FINISHED'}
        if event.type == 'S' and event.value == 'PRESS':
            cfg = settings(context); cfg.snap_geometry = not cfg.snap_geometry
            if self._dragging:
                self.queue_pointer(event)
            return {'RUNNING_MODAL'}
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM', 'NDOF_MOTION'}:
            self._dragging = False; self._pending_mouse = None; return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self._dragging = True
                self.queue_pointer(event)
                self.flush_pending(context)
            elif event.value == 'RELEASE':
                if self._dragging:
                    self.queue_pointer(event)
                    self.flush_pending(context)
                self._dragging = False
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            if self._dragging:
                self.queue_pointer(event)
            return {'RUNNING_MODAL'}
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
            if getattr(self,'_surface',None):
                if getattr(self,'_surface_shader',None) is None:self._surface_shader=gpu.shader.from_builtin('SMOOTH_COLOR')
                if getattr(self,'_surface_batch',None) is None:
                    self._surface_batch=batch_for_shader(self._surface_shader,'TRIS',self._surface)
                gpu.state.blend_set('NONE');gpu.state.depth_test_set('LESS_EQUAL');gpu.state.depth_mask_set(True)
                self._surface_shader.bind();self._surface_batch.draw(self._surface_shader)
            gpu.state.blend_set('ALPHA'); gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(False)
            shader.bind(); shader.uniform_float('viewportSize', gpu.state.viewport_get()[2:])
            shader.uniform_float('lineWidth', (1 if getattr(self,'_surface',None) else 2) * bpy.context.preferences.system.ui_scale)
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
        width = display_units.format_length(bpy.context,cfg.thickness)
        message = ('Cannot create: ' + self._error if self._error else
                   f'Thickness {width} | Snap {"ON" if cfg.snap_geometry else "OFF"} (S) | Drag to adjust | Enter / Ctrl+A to apply')
        if self._snap_hit:
            message += ' | ' + self._snap_hit['object_name']
        blf.size(0, round(13 * scale)); blf.position(0, 20 * scale, 28 * scale, 0)
        blf.color(0, *(shortcuts.settings().remove_color if self._error else shortcuts.settings().light_color), 1)
        blf.draw(0, message)

    def finish(self, context=None, *, cancel=False):
        if getattr(self, '_done', False):
            return
        self._done = True
        timer = getattr(self, '_timer', None)
        if timer is not None:
            self._wm.event_timer_remove(timer)
            self._timer = None
        self._pending_mouse = None
        self._surface=None;self._surface_batch=None;self._surface_shader=None
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
            # Preset selection can choose a starting detail count; restore the
            # user's explicit segment count after that callback has run.
            for name,value in sorted(self._original_settings.items(),key=lambda row:row[0]!='bevel_profile'):
                setattr(cfg,name,value)


def cancel_running(*_args):
    state = bpy.app.driver_namespace.get(STATE_KEY)
    if state:
        state.finish()


def draw_panel(layout, context):
    box = layout.box(); box.label(text='Make Outline')
    cfg = settings(context); state = bpy.app.driver_namespace.get(STATE_KEY)
    display_units.draw(box,cfg,'thickness',context); box.prop(cfg, 'direction')
    box.prop(cfg, 'join_style'); box.prop(cfg, 'output_type')
    box.prop(cfg, 'snap_geometry'); box.prop(cfg, 'hide_sources')
    row = box.row(); row.enabled = state is None
    row.operator('view3d.harhtools_make_outline', text='Make Outline', icon='MOD_SOLIDIFY')
    if cfg.output_type=='MESH':
        box.prop(cfg,'bevel_enabled')
        if cfg.bevel_enabled:
            display_units.draw(box,cfg,'bevel_depth',context);display_units.draw(box,cfg,'bevel_width',context);box.prop(cfg,'bevel_profile')
            if cfg.bevel_profile=='CUSTOM':box.prop(cfg,'bevel_shape')
            if cfg.bevel_profile!='CHAMFER':box.prop(cfg,'bevel_segments')
            profile_editor.draw(box,cfg)
            box.operator('object.harhtools_border_bevel',text='Update Selected Border')
            if state:box.label(text='Live bevel · Enter / Ctrl+A to keep')
    if context.mode != 'OBJECT':
        box.label(text='Select closed shapes in Object Mode.')
    elif state:
        box.label(text='Drag: thickness; S: snap on/off')
        box.label(text='Enter / Ctrl+A: apply; Esc: cancel')
        if state._error:
            box.label(text='Reduce thickness or repair the shape.', icon='ERROR')


def initialize_bevel_ui():
    if bpy.app.driver_namespace.get(STATE_KEY):return .5
    for manager in getattr(bpy.data,'window_managers',()):
        cfg=getattr(manager,'harhtools_outline',None)
        if cfg is not None and not cfg.bevel_ui_ready:
            cfg.bevel_enabled=False;cfg.bevel_ui_ready=True
    return None


def register():
    for cls in (HARHTOOLS_PG_outline, VIEW3D_OT_harhtools_make_outline, OBJECT_OT_harhtools_border_bevel):
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.harhtools_outline = PointerProperty(type=HARHTOOLS_PG_outline)
    bpy.app.handlers.load_pre.append(cancel_running)
    bpy.app.timers.register(initialize_bevel_ui,first_interval=.2)


def unregister():
    if bpy.app.timers.is_registered(initialize_bevel_ui):bpy.app.timers.unregister(initialize_bevel_ui)
    cancel_running()
    # Never import during teardown: a failed registration may have removed
    # the package root while leaving this child loaded.
    import sys
    preview = sys.modules.get(__package__ + '.outline_preview')
    if preview is not None:
        preview.clear()
    if cancel_running in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(cancel_running)
    if hasattr(bpy.types.WindowManager, 'harhtools_outline'):
        del bpy.types.WindowManager.harhtools_outline
    for cls in (OBJECT_OT_harhtools_border_bevel, VIEW3D_OT_harhtools_make_outline, HARHTOOLS_PG_outline):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
