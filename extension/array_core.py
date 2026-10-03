"""Pure array planning and transactional object creation.

Spacing and active orientation adapt harhtools' Roblox Arrange module. Rings
keep the original as the first slot. Preview rendering lives in array_tool.py.
"""
from dataclasses import dataclass
import math

import bpy
from mathutils import Euler, Matrix, Vector


MAX_NEW_OBJECTS = 10000
_AXES = {'X': Vector((1, 0, 0)), 'Y': Vector((0, 1, 0)), 'Z': Vector((0, 0, 1))}


@dataclass
class Snapshot:
    sources: tuple
    matrices: tuple
    bounds_points: tuple
    active_matrix: Matrix
    active_source: object
    pointers: tuple
    data_pointers: tuple
    per_source_bounds: tuple = ()
    geometry_points: tuple = ()


@dataclass
class Plan:
    transforms: tuple
    pivot: Vector
    axis: object
    resolved_radius: object
    new_object_count: int
    frame: Matrix
    source_snapshot: object = None
    fit_info: object = None
    ring_info: object = None


def _bounds(points):
    if not points:
        raise ValueError('The selected objects have no visible geometry.')
    return (Vector(tuple(min(p[i] for p in points) for i in range(3))),
            Vector(tuple(max(p[i] for p in points) for i in range(3))))


def _geometry_point(matrix, point):
    # Keep these sums as Python doubles. mathutils vectors round world-space
    # coordinates to floats, losing seam angles far from the scene origin.
    return tuple(sum(float(matrix[i][j]) * point[j] for j in range(3)) + matrix[i][3]
                 for i in range(3))


def snapshot(context, *, geometry=False):
    """Read selected geometry and evaluated bounds without changing the scene."""
    if context.mode != 'OBJECT':
        raise ValueError('Switch to Object Mode to array the selected objects.')
    sources = tuple(context.selected_objects)
    if not sources:
        raise ValueError('Select at least one mesh or curve to array.')
    unsupported = [o.name for o in sources if o.type not in {'MESH', 'CURVE'}]
    if unsupported:
        raise ValueError('Array supports mesh and curve objects; deselect ' + ', '.join(unsupported[:3]) + '.')
    active = context.view_layer.objects.active
    if active not in sources:
        active = sources[-1]
    depsgraph = context.evaluated_depsgraph_get()
    matrices, points, per_source, geometry_points = [], [], [], []
    for obj in sources:
        evaluated = obj.evaluated_get(depsgraph)
        matrix = evaluated.matrix_world.copy()
        corners = tuple(Vector(c) for c in evaluated.bound_box)
        if all(tuple(c) == (-1.0, -1.0, -1.0) for c in corners):
            raise ValueError(f'{obj.name} has no evaluated bounds to array.')
        matrices.append(matrix)
        world_corners = tuple(matrix @ c for c in corners)
        points.extend(world_corners)
        per_source.append(world_corners)
        if geometry:
            # Finishing modifiers can push corner miters a tiny distance past
            # an authored seam. Fit the construction footprint so a 60-degree
            # module still repeats six times after beveling/adding depth.
            # Deformations, generators and shape keys need evaluated geometry.
            finishing = {'BEVEL', 'SOLIDIFY', 'WEIGHTED_NORMAL', 'NORMAL_EDIT', 'TRIANGULATE'}
            authored = (obj.type == 'MESH' and not obj.data.shape_keys
                        and all(mod.type in finishing for mod in obj.modifiers if mod.show_viewport))
            if authored:
                geometry_points.extend(_geometry_point(matrix, vertex.co) for vertex in obj.data.vertices)
            else:
                mesh = evaluated.to_mesh()
                try:
                    if mesh:
                        geometry_points.extend(_geometry_point(matrix, vertex.co) for vertex in mesh.vertices)
                finally:
                    evaluated.to_mesh_clear()
    if not all(math.isfinite(x) for point in points for x in point):
        raise ValueError('The selection contains invalid geometry coordinates.')
    return Snapshot(sources, tuple(matrices), tuple(points),
                    active.evaluated_get(depsgraph).matrix_world.copy(), active,
                    tuple(o.as_pointer() for o in sources),
                    tuple(o.data.as_pointer() for o in sources), tuple(per_source), tuple(geometry_points))


def _finite(value, label):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number.')
    return value


def _capacity(groups, source_count):
    total = groups * source_count
    if total > MAX_NEW_OBJECTS:
        raise ValueError(f'This array would create {total:,} objects; lower Count to stay within {MAX_NEW_OBJECTS:,}.')
    return total


def _linear_axis(cfg):
    axes = [axis for axis in _AXES if axis in cfg.axes]
    if not axes:
        raise ValueError('Choose one axis for the linear array.')
    if len(axes) != 1:
        raise ValueError('Choose only one axis for the linear array.')
    return axes[0]


def _fit_plan(snap, cfg, frame):
    """Fit active-source copies between its facing edge and a fixed bookend."""
    if len(snap.sources) != 2 or snap.active_source not in snap.sources:
        raise ValueError('Fit Length needs exactly two objects; select the object to repeat last.')
    axis_name = _linear_axis(cfg)
    axis_index = 'XYZ'.index(axis_name)
    gap = _finite(cfg.gap, 'Minimum Gap')
    if gap < 0:
        raise ValueError('Minimum Gap cannot be negative in Fit Length.')
    source_index = snap.sources.index(snap.active_source)
    target_index = 1 - source_index
    per_source = snap.per_source_bounds
    if len(per_source) != 2:
        raise ValueError('Fit Length needs fresh source bounds; start a new preview.')
    inverse = frame.transposed()
    source_low, source_high = _bounds(tuple(inverse @ p for p in per_source[source_index]))
    target_low, target_high = _bounds(tuple(inverse @ p for p in per_source[target_index]))
    source_center = (source_low + source_high) * .5
    target_center = (target_low + target_high) * .5
    width = source_high[axis_index] - source_low[axis_index]
    target_width = target_high[axis_index] - target_low[axis_index]
    delta = target_center[axis_index] - source_center[axis_index]
    tolerance = max(width, target_width, abs(delta), gap, 1e-6) * 1e-7
    if width <= tolerance:
        raise ValueError(f'The last selected object has no usable width along {axis_name}; choose another axis.')
    direction = 1 if delta >= 0 else -1
    start_coordinate = source_high[axis_index] if direction > 0 else source_low[axis_index]
    end_coordinate = target_low[axis_index] if direction > 0 else target_high[axis_index]
    length = direction * (end_coordinate - start_coordinate)
    if length < -tolerance:
        raise ValueError(f'The two objects overlap along {axis_name}; move the target beyond the source before fitting.')
    length = max(length, 0)
    stride = width + gap
    count = max(0, math.floor((length - gap + tolerance) / stride))
    # The tolerance stabilizes counts at equal boundaries, but it must never
    # squeeze a source wider than the interval or make its even gaps negative.
    while count and (count * width > length or (length - count * width) / (count + 1) < gap - tolerance):
        count -= 1
    _capacity(count, 1)
    resolved_gap = (length - count * width) / (count + 1)
    direction_world = frame.to_3x3() @ (_AXES[axis_name] * direction)
    start_local = source_center.copy()
    end_local = source_center.copy()
    start_local[axis_index] = start_coordinate
    end_local[axis_index] = end_coordinate
    start, end = frame @ start_local, frame @ end_local
    transforms = tuple(Matrix.Translation(direction_world * (width + resolved_gap) * i)
                       for i in range(1, count + 1))
    source_only = Snapshot(
        (snap.sources[source_index],), (snap.matrices[source_index],),
        tuple(per_source[source_index]), snap.active_matrix.copy(), snap.active_source,
        (snap.pointers[source_index],), (snap.data_pointers[source_index],),
        (tuple(per_source[source_index]),))
    info = dict(count=count, length=length, gap=resolved_gap, minimum_gap=gap,
                start=start, end=end, axis=direction_world,
                target_name=snap.sources[target_index].name,
                message='' if count else 'No full copies fit between these objects.')
    return Plan(transforms, frame @ source_center, direction_world, None, count,
                frame, source_snapshot=source_only, fit_info=info)


def angular_fit(points, pivot, axis, sweep):
    """Fit complete angular footprints without moving/scaling the first piece.

    A full turn can close only if the piece's span divides it. Any remainder
    stays empty instead of spreading/overlapping the pieces to disguise it.
    """
    if not points:
        raise ValueError('Fit Ring needs fresh geometry; restart the preview.')
    radial = _AXES['X'] if abs(axis.x) < .9 else _AXES['Y']
    radial = (radial - axis * radial.dot(axis)).normalized()
    tangent = axis.cross(radial)
    projected = [sum((float(point[i])-pivot[i])*radial[i] for i in range(3)) for point in points]
    across = [sum((float(point[i])-pivot[i])*tangent[i] for i in range(3)) for point in points]
    extent = max((math.hypot(x, y) for x, y in zip(projected, across)), default=0)
    tolerance = max(extent * 1e-7, 1e-10)
    angles = sorted(math.atan2(y, x) % math.tau for x, y in zip(projected, across)
                    if math.hypot(x, y) > tolerance)
    if len(angles) < 2:
        raise ValueError('The source has no angular width around this axis.')
    gaps = [b-a for a, b in zip(angles, angles[1:])]
    gaps.append(angles[0] + math.tau - angles[-1])
    span = math.tau - max(gaps)
    # Blender stores mesh positions as floats. Allow less than 0.006 degrees
    # around a complete seam (not per copy), including far-offset modeling.
    angular_tolerance = 1e-4
    if span <= angular_tolerance:
        raise ValueError('The source has no usable angular width around this axis.')
    magnitude = abs(sweep)
    slots = max(0, math.floor((magnitude + angular_tolerance) / span))
    copies = max(0, slots - 1)
    remainder = max(0.0, magnitude - slots * span)
    if remainder < angular_tolerance:
        remainder = 0.0
    return dict(count=copies, total=slots, step=math.copysign(span, sweep), remainder=remainder,
                closes=remainder == 0.0 and slots > 0)


def _base_plan(snap, cfg, scene):
    """Return group transforms; no datablocks or source properties are changed."""
    orientation = getattr(cfg, 'orientation', 'WORLD')
    if orientation not in {'WORLD', 'ACTIVE'}:
        raise ValueError('Choose Global or Last orientation.')
    frame = (snap.active_matrix.to_quaternion().to_matrix().to_4x4()
             if orientation == 'ACTIVE' else Matrix.Identity(4))
    inverse = frame.transposed()
    if cfg.mode == 'LINEAR' and getattr(cfg, 'fit_length', False):
        return _fit_plan(snap, cfg, frame)
    count = int(cfg.count)
    angular_fitting = (cfg.mode == 'CIRCULAR' and getattr(cfg, 'fit_ring', False)
                       and getattr(cfg, 'pivot', 'BOUNDS') != 'BOUNDS')
    if count < 2 and not angular_fitting:
        raise ValueError('Count must be at least 2.')
    low, high = _bounds(tuple(inverse @ p for p in snap.bounds_points))
    center, span = (low + high) * .5, high - low
    anchor = frame @ center

    if cfg.mode == 'LINEAR':
        axis = _linear_axis(cfg)
        total = _capacity(count - 1, len(snap.sources))
        gap = _finite(cfg.gap, 'Gap')
        stride = span['XYZ'.index(axis)] + gap
        if abs(stride) <= 1e-8:
            raise ValueError(f'{axis} spacing is zero; increase Gap or choose an axis with visible width.')
        direction = frame.to_3x3() @ _AXES[axis]
        transforms = [Matrix.Translation(direction * stride * i) for i in range(1, count)]
        return Plan(tuple(transforms), anchor, None, None, total, frame)

    if cfg.mode != 'CIRCULAR':
        raise ValueError('Choose Linear or Circular array mode.')
    total = _capacity(count, len(snap.sources)) if not angular_fitting else 0
    axis_name = cfg.radial_axis
    if axis_name not in _AXES:
        raise ValueError('Choose X, Y or Z for the circular axis.')
    sweep = _finite(cfg.sweep, 'Sweep')
    magnitude = abs(sweep)
    if magnitude == 0 or magnitude > math.tau + 1e-6:
        raise ValueError('Sweep must be between -360 and 360 degrees, excluding zero.')
    full = math.isclose(magnitude, math.tau, rel_tol=0, abs_tol=1e-6)
    # The unchanged original is slot zero. Count is the number of NEW copies.
    step = 0.0 if angular_fitting else (math.copysign(math.tau / (count + 1), sweep) if full else (sweep / count))
    pivot_mode = getattr(cfg, 'pivot', 'BOUNDS')
    axis = frame.to_3x3() @ _AXES[axis_name]
    axis.normalize()
    if pivot_mode == 'BOUNDS':
        radius = _finite(cfg.radius, 'Radius')
    elif pivot_mode in {'ACTIVE', 'CURSOR'}:
        pivot = (snap.active_matrix.translation.copy() if pivot_mode == 'ACTIVE'
                 else scene.cursor.location.copy())
        offset = anchor - pivot
        radial_offset = offset - axis * offset.dot(axis)
        radius = radial_offset.length
        tolerance = max(span.length, offset.length, 1e-9) * 1e-6
        if radius <= tolerance:
            raise ValueError(f'The source lies on the {axis_name} center axis; move the center or choose Offset from Source.')
    else:
        raise ValueError('Choose From Source, Last Origin or 3D Cursor for the center.')
    if pivot_mode == 'BOUNDS' and getattr(cfg, 'fit_ring', False):
        if not cfg.rotate_copies:
            raise ValueError('Enable Rotate Copies to fit the ring edges.')
        # These axes match Arrange.fitCircleRadius exactly: X pushes along Z,
        # Y and Z push along X; the tangent is Z for Y, otherwise Y.
        width = span.z if axis_name == 'Y' else span.y
        depth = span.z if axis_name == 'X' else span.x
        if width <= 1e-8:
            raise ValueError('The selection has no width along the ring tangent; choose another axis.')
        # A partial arc also has a gap between its last and first slots.
        # On a nearly closed arc that gap can be smaller than the regular
        # step, and it is those end copies that determine the fitted radius.
        fit_step = abs(step) if full else min(abs(step), math.tau - magnitude)
        tangent = math.tan(min(fit_step, math.pi) * .5)
        if tangent <= 1e-8:
            raise ValueError('The sweep is too small to fit a ring.')
        side = cfg.fit_side
        if side not in {'INSIDE', 'CENTER', 'OUTSIDE'}:
            raise ValueError('Choose Inside, Center or Outside for Fit Ring.')
        shift = {'INSIDE': depth * .5, 'CENTER': 0, 'OUTSIDE': -depth * .5}[side]
        # Keep degenerate/outside solutions positive without importing a
        # fixed Roblox stud-size floor into Blender's arbitrary scene units.
        minimum_radius = max(width, depth) * 1e-6
        radius = max(width / (2 * tangent) + shift, minimum_radius)
    if radius <= 0:
        raise ValueError('Radius must be greater than 0.')
    if pivot_mode == 'BOUNDS':
        radial = frame.to_3x3() @ (_AXES['Z'] if axis_name == 'X' else _AXES['X']) * radius
        if getattr(cfg, 'flip_bend', False):
            # Put the center on the other side of the unchanged source. Reverse
            # the rotation as well, so the row keeps its initial travel direction
            # while its curvature changes sign. No geometry is mirrored.
            radial.negate()
            step = -step
        pivot = anchor - radial
    ring_info = None
    if angular_fitting:
        if not cfg.rotate_copies:
            raise ValueError('Enable Rotate Copies to fit the ring edges.')
        ring_info = angular_fit(snap.geometry_points, pivot, axis, sweep)
        count, step = ring_info['count'], ring_info['step']
        total = _capacity(count, len(snap.sources))
    transforms = []
    for i in range(1, count + 1):
        rotation = Matrix.Rotation(step * i, 4, axis)
        if cfg.rotate_copies:
            transform = Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot)
        else:
            # Keep every source's orientation AND the group's internal layout.
            # The original anchor begins the ring, including its axial offset.
            destination = pivot + rotation.to_3x3() @ (anchor - pivot)
            transform = Matrix.Translation(destination - anchor)
        transforms.append(transform)
    return Plan(tuple(transforms), pivot, axis, radius, total, frame, ring_info=ring_info)


def deformation_paused(cfg):
    return (cfg.mode == 'LINEAR' and getattr(cfg, 'fit_length', False)
            or cfg.mode == 'CIRCULAR' and getattr(cfg, 'fit_ring', False))


def _deform_weight(t, style):
    if style == 'LINEAR': return t
    if style == 'SMOOTH': return t * t * (3 - 2 * t)
    if style == 'EASE_IN': return t * t
    if style == 'EASE_OUT': return 1 - (1 - t) ** 2
    raise ValueError('Choose a valid deformation progression.')


def build_plan(snap, cfg, scene):
    """Build exact preview/commit poses, including optional gradual group changes."""
    plan = _base_plan(snap, cfg, scene)
    if (not getattr(cfg, 'deform_enabled', False) or deformation_paused(cfg)
            or not plan.transforms):
        return plan
    end_scale = _finite(getattr(cfg, 'deform_scale', 50.), 'Last Copy Size') / 100
    if end_scale <= 0:
        raise ValueError('Last Copy Size must be greater than zero.')
    offset = Vector(tuple(_finite(v, 'Move') for v in getattr(cfg, 'deform_offset', (0, 0, 0))))
    rotation = Vector(tuple(_finite(v, 'Rotate') for v in getattr(cfg, 'deform_rotation', (0, 0, 0))))
    if end_scale == 1 and offset.length_squared == 0 and rotation.length_squared == 0:
        return plan
    style = getattr(cfg, 'deform_ease', 'LINEAR')
    frame, inverse = plan.frame, plan.frame.transposed()
    low, high = _bounds(tuple(inverse @ p for p in snap.bounds_points))
    anchor = frame @ ((low + high) * .5)
    to_center, from_center = Matrix.Translation(anchor), Matrix.Translation(-anchor)
    keep_gap = cfg.mode == 'LINEAR' and getattr(cfg, 'deform_keep_gap', True)
    if keep_gap:
        direction = frame.to_3x3() @ _AXES[_linear_axis(cfg)]
        previous_high = max(p.dot(direction) for p in snap.bounds_points)
        gap = _finite(cfg.gap, 'Gap')
    transforms = []
    for i, base in enumerate(plan.transforms, 1):
        t = _deform_weight(i / len(plan.transforms), style)
        scale = 1 + (end_scale - 1) * t
        shape = (to_center @ frame @ Euler(tuple(rotation * t), 'XYZ').to_matrix().to_4x4()
                 @ Matrix.Scale(scale, 4) @ inverse @ from_center)
        if keep_gap:
            # Measure each changed group before its additional Move offset.
            # This preserves the requested edge gap even when height or twist changes.
            projections = [(shape @ p).dot(direction) for p in snap.bounds_points]
            distance = previous_high + gap - min(projections)
            base = Matrix.Translation(direction * distance)
            previous_high = max(projections) + distance
        move = Matrix.Translation(frame.to_3x3() @ (offset * t))
        # In circular arrays the change follows each copy's own rotated frame.
        transforms.append(base @ move @ shape)
    plan.transforms = tuple(transforms)
    return plan


def axis_availability(snap, cfg, scene):
    """Geometric axis choices without constructing copies or checking capacity.

    Global setup errors (selection count, invalid Gap, etc.) stay in the normal
    plan error rather than making every axis button look geometrically invalid.
    """
    result = {name: (True, '') for name in _AXES}
    orientation = getattr(cfg, 'orientation', 'WORLD')
    if orientation not in {'WORLD', 'ACTIVE'}:
        return result
    frame = (snap.active_matrix.to_quaternion().to_matrix().to_4x4()
             if orientation == 'ACTIVE' else Matrix.Identity(4))
    inverse = frame.transposed()
    try:
        low, high = _bounds(tuple(inverse @ p for p in snap.bounds_points))
    except ValueError:
        return result
    center, span = (low + high) * .5, high - low
    if cfg.mode == 'LINEAR':
        try:
            gap = _finite(cfg.gap, 'Gap')
        except ValueError:
            return result
        if getattr(cfg, 'fit_length', False):
            if (len(snap.sources) != 2 or snap.active_source not in snap.sources
                    or len(snap.per_source_bounds) != 2 or gap < 0):
                return result
            source_index = snap.sources.index(snap.active_source)
            source_low, source_high = _bounds(tuple(inverse @ p for p in snap.per_source_bounds[source_index]))
            target_low, target_high = _bounds(tuple(inverse @ p for p in snap.per_source_bounds[1-source_index]))
            for index, name in enumerate('XYZ'):
                width = source_high[index] - source_low[index]
                target_width = target_high[index] - target_low[index]
                delta = (target_low[index] + target_high[index] - source_low[index] - source_high[index]) * .5
                tolerance = max(width, target_width, abs(delta), gap, 1e-6) * 1e-7
                if width <= tolerance:
                    result[name] = (False, f'The source has no usable width along {name}.')
                    continue
                length = (target_low[index] - source_high[index] if delta >= 0
                          else source_low[index] - target_high[index])
                if length < -tolerance:
                    result[name] = (False, f'The selected objects overlap along {name}.')
                elif length < width or (length - width) * .5 < gap - tolerance:
                    result[name] = (False, f'No full copies fit along {name}.')
        else:
            for index, name in enumerate('XYZ'):
                if abs(span[index] + gap) <= 1e-8:
                    result[name] = (False, f'{name} spacing is zero; increase Gap.')
    elif cfg.mode == 'CIRCULAR':
        pivot_mode = getattr(cfg, 'pivot', 'BOUNDS')
        if pivot_mode in {'ACTIVE', 'CURSOR'}:
            pivot = (snap.active_matrix.translation.copy() if pivot_mode == 'ACTIVE'
                     else scene.cursor.location.copy())
            offset = frame @ center - pivot
            tolerance = max(span.length, offset.length, 1e-9) * 1e-6
            for name, basis in _AXES.items():
                axis = frame.to_3x3() @ basis
                axis.normalize()
                if (offset - axis * offset.dot(axis)).length <= tolerance:
                    result[name] = (False, f'The source lies on the {name} center axis.')
        elif pivot_mode == 'BOUNDS' and getattr(cfg, 'fit_ring', False):
            for name in _AXES:
                width = span.z if name == 'Y' else span.y
                if width <= 1e-8:
                    result[name] = (False, f'The source has no width along the {name} ring tangent.')
    return result


def _validate_sources(snap):
    live = {o.as_pointer(): o for o in bpy.data.objects}
    for obj, pointer, data_pointer in zip(snap.sources, snap.pointers, snap.data_pointers):
        try:
            valid = (pointer in live and live[pointer] == obj and obj.data is not None
                     and obj.data.as_pointer() == data_pointer)
        except ReferenceError:
            valid = False
        if not valid:
            raise ValueError('An array source was removed or replaced. Cancel and start a new preview.')


def _remap_pointers(owner, mapping):
    """Keep copied modifiers/constraints pointing within each repeated group."""
    for prop in owner.bl_rna.properties:
        if prop.type != 'POINTER' or prop.is_readonly:
            continue
        try:
            value = getattr(owner, prop.identifier)
            if isinstance(value, bpy.types.Object) and value in mapping:
                setattr(owner, prop.identifier, mapping[value])
        except (AttributeError, TypeError):
            pass
    # Geometry Nodes object inputs are ID properties, not RNA properties.
    try:
        for key in owner.keys():
            value = owner[key]
            if isinstance(value, bpy.types.Object) and value in mapping:
                owner[key] = mapping[value]
    except TypeError:
        pass


def _remap_drivers(owner, mapping):
    animation = owner.animation_data
    if not animation:
        return
    for fcurve in animation.drivers:
        for variable in fcurve.driver.variables:
            for target in variable.targets:
                if isinstance(target.id, bpy.types.Object) and target.id in mapping:
                    target.id = mapping[target.id]


def _restore_selection(context, selected, active):
    for obj in tuple(context.selected_objects):
        obj.select_set(False)
    for obj in selected:
        try:
            obj.select_set(True)
        except (ReferenceError, RuntimeError):
            pass
    try:
        context.view_layer.objects.active = active
    except (ReferenceError, RuntimeError):
        pass


def _join_generated(context, snap, plan, copies):
    """Stage evaluated surfaces before replacing the source and its copies.

    Joining evaluated meshes retains modifiers, UVs and object material overrides
    for every piece, including mixed mesh/curve selections. An empty active mesh
    anchors the result at the circular pivot (or the linear source origin).
    """
    if any(source.library or source.override_library for source in snap.sources):
        raise ValueError('Make the sources local before using Join Generated.')
    collection = context.collection or context.scene.collection
    staged, meshes = [], []
    keep = None
    try:
        mesh = bpy.data.meshes.new('Array Result')
        meshes.append(mesh)
        result = bpy.data.objects.new(snap.active_source.name + ' Array', mesh)
        staged.append(result)
        collection.objects.link(result)
        origin = plan.pivot if plan.axis is not None else snap.active_matrix.translation
        result.matrix_world = Matrix.Translation(origin)
        depsgraph = context.evaluated_depsgraph_get()
        expected_vertices = 0
        uv_active = uv_render = None
        render_layers = []
        for source in (*snap.sources, *copies):
            evaluated = source.evaluated_get(depsgraph)
            mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True,
                                                 depsgraph=depsgraph)
            if mesh is None:
                raise ValueError(f'{source.name}: could not create the joined surface.')
            meshes.append(mesh)
            expected_vertices += len(mesh.vertices)
            if mesh.uv_layers and (uv_active is None or source == snap.active_source):
                uv_active = mesh.uv_layers.active.name
                uv_render = next((uv.name for uv in mesh.uv_layers if uv.active_render), uv_active)
            render_layers.append((mesh, next((uv for uv in mesh.uv_layers if uv.active_render),
                                              mesh.uv_layers.active)))
            # new_from_object can expose evaluated material IDs. Use originals
            # and bake object-linked slots into the resulting mesh slots.
            material_indices = [face.material_index for face in mesh.polygons]
            mesh.materials.clear()
            for slot in evaluated.material_slots:
                mesh.materials.append(slot.material.original if slot.material else None)
            for face, index in zip(mesh.polygons, material_indices):
                face.material_index = index
            part = bpy.data.objects.new('Array Join Part', mesh)
            staged.append(part)
            collection.objects.link(part)
            part.matrix_world = evaluated.matrix_world.copy()
        # Implicit texture coordinates use one render UV map after a join. If
        # sources name that map differently, preserve both their named maps and
        # a shared render map so their textures continue to use the right UVs.
        if len({uv.name for _, uv in render_layers if uv is not None}) > 1:
            used_names = {uv.name for mesh, _ in render_layers for uv in mesh.uv_layers}
            shared = 'Array UV'
            while shared in used_names:
                shared += '_'
            for mesh, uv in render_layers:
                coordinates = [tuple(d.uv) for d in uv.data] if uv is not None else None
                layer = mesh.uv_layers.new(name=shared)
                if layer is None:
                    raise ValueError('Join Generated needs a free UV map slot to preserve these textures.')
                if coordinates:
                    for point, coordinate in zip(layer.data, coordinates):
                        point.uv = coordinate
            uv_active = uv_render = shared
        context.view_layer.update()
        _restore_selection(context, staged, result)
        with context.temp_override(object=result, active_object=result,
                                   selected_objects=staged, selected_editable_objects=staged):
            status = bpy.ops.object.join()
        if status != {'FINISHED'} or len(result.data.vertices) != expected_vertices:
            raise ValueError('Could not join every array piece; the original objects were kept.')
        if uv_active and uv_active in result.data.uv_layers:
            result.data.uv_layers.active = result.data.uv_layers[uv_active]
        if uv_render and uv_render in result.data.uv_layers:
            result.data.uv_layers[uv_render].active_render = True
        # All fallible geometry construction is complete before consuming sources.
        for obj in (*copies, *snap.sources):
            bpy.data.objects.remove(obj, do_unlink=True)
        keep = result
        return [result]
    finally:
        for obj in reversed(staged):
            try:
                if obj != keep:
                    bpy.data.objects.remove(obj, do_unlink=True)
            except ReferenceError:
                pass  # Blender's Join already removed the staging parts.
        for mesh in meshes:
            try:
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            except ReferenceError:
                pass


def commit(context, snap, plan, linked=False, join_generated=False):
    """Create a complete array or roll back every newly created datablock.

    The caller's modal operator owns the single Blender undo boundary. Sources
    stay unchanged unless Join Generated replaces them with one evaluated mesh.
    """
    _validate_sources(snap)
    if plan.source_snapshot is not None:
        snap = plan.source_snapshot
        _validate_sources(snap)
    _capacity(len(plan.transforms), len(snap.sources))
    if not plan.transforms:
        raise ValueError('The array contains no new copies.')
    if context.mode != 'OBJECT':
        raise ValueError('Return to Object Mode before confirming the array.')
    before_selected, before_active = tuple(context.selected_objects), context.view_layer.objects.active
    made, made_data, expected_matrices = [], [], []
    collection = context.collection or context.scene.collection
    try:
        for transform in plan.transforms:
            mapping, data_mapping = {}, {}
            for source in snap.sources:
                copy = source.copy()
                made.append(copy)
                mapping[source] = copy
                if not linked:
                    if source.data not in data_mapping:
                        data = source.data.copy()
                        made_data.append(data)
                        data_mapping[source.data] = data
                    copy.data = data_mapping[source.data]
                collection.objects.link(copy)
                copy.hide_select = False
            for source, saved_matrix in zip(snap.sources, snap.matrices):
                copy = mapping[source]
                if source.parent in mapping:
                    copy.parent = mapping[source.parent]
                for modifier in copy.modifiers:
                    _remap_pointers(modifier, mapping)
                for constraint in copy.constraints:
                    _remap_pointers(constraint, mapping)
                    for target in getattr(constraint, 'targets', ()):
                        _remap_pointers(target, mapping)
                _remap_drivers(copy, mapping)
                if not linked:
                    _remap_drivers(copy.data, mapping)
            # Parents must be assigned first; update before setting children so
            # matrix_world derives their local transforms from the copied parent.
            pending = set(snap.sources)
            while pending:
                ready = [s for s in snap.sources if s in pending and s.parent not in pending]
                if not ready:
                    raise ValueError('The selected hierarchy contains a parenting cycle.')
                for source in ready:
                    matrix = snap.matrices[snap.sources.index(source)]
                    expected = transform @ matrix
                    mapping[source].matrix_world = expected
                    expected_matrices.append((mapping[source], expected))
                    pending.remove(source)
                context.view_layer.update()
        # A copied constraint/driver or a nonuniform external parent can prevent
        # Blender from representing the requested world transform. Do not accept
        # an array which looks different from its preview: fail transactionally.
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        for obj, expected in expected_matrices:
            actual = obj.evaluated_get(depsgraph).matrix_world
            if any(not math.isfinite(a) or abs(a - e) > 1e-5 + 1e-6 * max(abs(a), abs(e))
                   for row_a, row_e in zip(actual, expected) for a, e in zip(row_a, row_e)):
                raise ValueError(f'{obj.name}: constraints, drivers or parenting override the array position. '
                                 'Resolve those transforms before generating; no copies were kept.')
        if join_generated:
            made = _join_generated(context, snap, plan, made)
            for data in made_data:
                if data.users == 0:
                    if isinstance(data, bpy.types.Mesh):
                        bpy.data.meshes.remove(data)
                    elif isinstance(data, bpy.types.Curve):
                        bpy.data.curves.remove(data)
            made_data.clear()
        _restore_selection(context, made, made[-1])
        return made
    except Exception:
        for obj in reversed(made):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except ReferenceError:
                pass
        for data in reversed(made_data):
            try:
                if data.users == 0:
                    if isinstance(data, bpy.types.Mesh):
                        bpy.data.meshes.remove(data)
                    elif isinstance(data, bpy.types.Curve):
                        bpy.data.curves.remove(data)
            except ReferenceError:
                pass
        _restore_selection(context, before_selected, before_active)
        raise
