"""Fit a selected arrangement inside an active planar boundary, without remeshing."""
import math
import random
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty
from mathutils import Matrix, Vector
from mathutils.geometry import tessellate_polygon
from . import outline_geometry as og, display_units


def hull(points):
    points = sorted(set(points))
    def side(a, b, c): return og._cross(og._sub(b, a), og._sub(c, a))
    def half(values):
        result = []
        for p in values:
            while len(result) > 1 and side(result[-2], result[-1], p) <= 1e-14:
                result.pop()
            result.append(p)
        return result
    result = half(points)[:-1] + half(reversed(points))[:-1]
    if len(result) < 3 or abs(og._area(result)) < 1e-12:
        raise ValueError('The selected shapes need width and height in the active outline plane.')
    return result


def centroid(loop):
    weights = [og._cross(a, b) for a, b in zip(loop, loop[1:] + loop[:1])]
    total = 3 * sum(weights)
    return tuple(sum((a[i]+b[i])*w for a, b, w in
                    zip(loop, loop[1:]+loop[:1], weights))/total for i in range(2))


def span(loop):
    return tuple(max(p[i] for p in loop)-min(p[i] for p in loop) for i in range(2))


def convex(loop):
    return all(og._cross(og._sub(b, a), og._sub(c, b)) >= -1e-12
               for a, b, c in zip(loop, loop[1:]+loop[:1], loop[2:]+loop[:2]))


def inside(point, loop, epsilon=2e-8):
    return og._contains(point, loop) or any(
        og._point_segment_sq(point, a, b) <= epsilon**2
        for a, b in zip(loop, loop[1:]+loop[:1]))


def contained(envelope, loop, is_convex=None, epsilon=2e-8):
    """Test whole edges as well as vertices, including concave target notches."""
    if is_convex is None: is_convex = convex(loop)
    if is_convex:
        for a, b in zip(loop, loop[1:]+loop[:1]):
            d = og._sub(b, a)
            if min(og._cross(d, og._sub(p, a)) for p in envelope) < -epsilon*math.hypot(*d):
                return False
        return True
    splits = [{0., 1.} for _ in envelope]
    # Broad phase avoids comparing every pair of dense boundary edges.
    for one, two in og._candidates(og._edges([envelope], 0)+og._edges([loop], 1), epsilon):
        if one[4] == two[4]: continue
        source, target = (one, two) if one[4] == 0 else (two, one)
        a, b, c, d = source[7], source[8], target[7], target[8]
        ab, cd = og._sub(b, a), og._sub(d, c)
        den = og._cross(ab, cd)
        if abs(den) > 1e-15:
            t = og._cross(og._sub(c, a), cd)/den
            u = og._cross(og._sub(c, a), ab)/den
            if -epsilon <= t <= 1+epsilon and -epsilon <= u <= 1+epsilon:
                splits[source[6]].add(max(0., min(1., t)))
        elif abs(og._cross(og._sub(c, a), ab)) <= epsilon*math.hypot(*ab):
            denom = og._dot(ab, ab)
            if denom:
                for p in (c, d):
                    t = og._dot(og._sub(p, a), ab)/denom
                    if 0 < t < 1: splits[source[6]].add(t)
    for a, b, cuts in zip(envelope, envelope[1:]+envelope[:1], splits):
        values = sorted(cuts)
        for lo, hi in zip(values, values[1:]):
            point = og._add(a, og._mul(og._sub(b, a), (lo+hi)*.5))
            if not inside(point, loop, epsilon): return False
    return True


def target_boundary(active, boundary='OPENING'):
    prepared = og.prepare_sources([active])
    loops = prepared['world_loops']
    depths = prepared['depths']
    candidates = [i for i, depth in enumerate(depths) if depth == 1] if boundary == 'OPENING' else []
    if not candidates: candidates = [i for i, depth in enumerate(depths) if depth == 0]
    index = max(candidates, key=lambda i: abs(og._area(prepared['loops'][i])))
    normal = prepared['_normal64']
    # Stable target object axes, rather than the viewport or a farthest vertex.
    axes = [tuple(active.matrix_world[j][i] for j in range(3)) for i in range(3)]
    axes = [og._sub3(a, tuple(og._dot3(a, normal)*n for n in normal)) for a in axes]
    axis_size = max(og._dot3(a, a) for a in axes)
    usable = [i for i, a in enumerate(axes) if og._dot3(a, a) > max(1e-24, axis_size*1e-10)]
    if not usable: raise ValueError('The active object has a collapsed transform.')
    u = og._unit3(axes[usable[0]])
    v = og._unit3(og._cross3(normal, u))
    origin = prepared['_origin64']
    scale = prepared['scale']
    def project(p):
        delta = og._sub3(p, origin)
        return (og._dot3(delta, u)/scale, og._dot3(delta, v)/scale)
    loop = [project(p) for p in loops[index]]
    if og._area(loop) < 0: loop.reverse()
    anchor = centroid(loop)
    if not inside(anchor, loop):
        triangles = tessellate_polygon([[Vector(p) for p in loop]])
        triangle = max(triangles, key=lambda t: abs(og._area([tuple(p)[:2] for p in t])))
        anchor = tuple(sum(p[i] for p in triangle)/3 for i in range(2))
    return dict(loop=loop, origin=origin, u=u, v=v, normal=normal, scale=scale,
                anchor=anchor, project=project, convex=convex(loop),
                opening=depths[index] == 1)


def object_points(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        if mesh is None or not mesh.vertices:
            raise ValueError(f'{obj.name}: no visible mesh or curve geometry to fit.')
        if len(mesh.vertices) > 500000:
            raise ValueError(f'{obj.name}: reduce evaluated geometry below 500,000 vertices before fitting.')
        return [og._world_point(evaluated.matrix_world, vertex.co) for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def feasible_center(rows, scale, gap, preferred):
    """Randomized incremental 2D half-plane feasibility; no external solver."""
    point = preferred
    for index, (nx, ny, bound, support) in enumerate(rows):
        limit = bound-support*scale-gap
        if nx*point[0]+ny*point[1] <= limit+1e-11: continue
        base = (nx*limit, ny*limit)
        direction = (-ny, nx)
        lower, upper = -float('inf'), float('inf')
        for ax, ay, other_bound, other_support in rows[:index]:
            remaining = other_bound-other_support*scale-gap-ax*base[0]-ay*base[1]
            coefficient = ax*direction[0]+ay*direction[1]
            if abs(coefficient) < 1e-12:
                if remaining < -1e-10: return None
            elif coefficient > 0: upper = min(upper, remaining/coefficient)
            else: lower = max(lower, remaining/coefficient)
            if lower > upper+1e-10: return None
        along = og._dot(og._sub(preferred, base), direction)
        point = og._add(base, og._mul(direction, max(lower, min(upper, along))))
    return point


def balanced_fit(rows, gap, preferred, fill):
    rows = list(rows)
    random.Random(4921).shuffle(rows)
    if feasible_center(rows, 0., gap, preferred) is None:
        raise ValueError('The requested gap is larger than the frame opening. Reduce Gap.')
    lo, hi = 0., 1.
    for _ in range(36):
        mid = (lo+hi)*.5
        if feasible_center(rows, mid, gap, preferred) is None: hi = mid
        else: lo = mid
    factor = lo*fill*(1-2e-5)
    # With the fitted size fixed, maximize the minimum clearance. This balances
    # the three outer circle contacts rather than centering their bounding box.
    low_gap, high_gap = gap, gap+4.
    best = feasible_center(rows, factor, low_gap, preferred)
    for _ in range(32):
        mid = (low_gap+high_gap)*.5
        center = feasible_center(rows, factor, mid, preferred)
        if center is None: high_gap = mid
        else: low_gap, best = mid, center
    return factor, best


def solve(points, target, proportional=True, fill=100., equal_spacing=True, gap=0.):
    envelope = hull([target['project'](p) for p in points])
    center = centroid(envelope)
    relative = [og._sub(p, center) for p in envelope]
    source_span, target_span = span(envelope), span(target['loop'])
    # Reserve room for Blender's float32 world matrices, especially tiny work
    # far from the origin. Keep this distinct from the user's requested gap.
    precision = max(2e-6, max(abs(x) for x in target['origin'])/target['scale']*3e-7)
    margin = max(0., gap)/target['scale']+precision
    if min(target_span) <= 2*margin:
        raise ValueError('The requested gap is larger than the frame opening. Reduce Gap.')
    ratio = [(target_span[i]-2*margin)/source_span[i] for i in range(2)]
    if proportional: ratio = [min(ratio)]*2
    scaled = [(p[0]*ratio[0], p[1]*ratio[1]) for p in relative]
    anchor, loop = target['anchor'], target['loop']
    fill_factor = max(.01, min(1., fill/100.))
    if target['convex']:
        rows = []
        for a, b in zip(loop, loop[1:]+loop[:1]):
            edge = og._sub(b, a)
            length = math.hypot(*edge)
            outward = (edge[1]/length, -edge[0]/length)
            support = max(og._dot(outward, p) for p in scaled)
            rows.append((*outward, og._dot(outward, a), support))
        if equal_spacing:
            factor, anchor = balanced_fit(rows, margin, anchor, fill_factor)
        else:
            factor = min((bound-og._dot((nx, ny), anchor)-margin)/support
                         for nx, ny, bound, support in rows if support > 1e-14)
            factor *= fill_factor*(1-2e-5)
    else:
        if equal_spacing:
            raise ValueError('Equal Boundary Spacing needs a convex frame (such as a circle or arch). Turn it off for this concave outline.')
        edge_index = og._SegmentIndex([loop])
        lo, hi = 0., 1.
        # The convex envelope contains its centroid: these scaled envelopes
        # are nested, making containment monotone even for concave targets.
        for _ in range(32):
            mid = (lo+hi)*.5
            current = [og._add(anchor, og._mul(p, mid)) for p in scaled]
            clear = not margin or not any(edge_index.within(a, b, margin)
                        for a, b in zip(current, current[1:]+current[:1]))
            if clear and contained(current, loop, False): lo = mid
            else: hi = mid
        factor = lo*fill_factor*(1-2e-5)
    if not math.isfinite(factor) or factor <= 1e-8:
        raise ValueError('This arrangement cannot fit at the active outline center.')
    sx, sy = (r*factor for r in ratio)
    # Fit in the target plane and center depth on that plane. Proportional
    # scaling also preserves depth proportions; free scaling keeps depth.
    depth = [og._dot3(og._sub3(p, target['origin']), target['normal']) for p in points]
    zcenter = (min(depth)+max(depth))*.5
    basis = Matrix.Identity(4)
    for col, axis in enumerate((target['u'], target['v'], target['normal'])):
        for row in range(3): basis[row][col] = axis[row]
    basis.translation = Vector(target['origin'])
    local = Matrix.Diagonal((sx, sy, sx if proportional else 1., 1.))
    local.translation = Vector(((anchor[0]-sx*center[0])*target['scale'],
                                (anchor[1]-sy*center[1])*target['scale'],
                                -local[2][2]*zcenter))
    transform = basis @ local @ basis.inverted()
    return transform, (sx, sy), envelope


def busy():
    return any(bpy.app.driver_namespace.get(key) for key in (
        'arch_tools_shape_builder', 'harhtools_array_preview', 'harhtools_outline_preview',
        'harhtools_outline', 'harhtools_arc_preview', 'harhtools_edit_arc'))


def fit_selection(context, proportional=True, boundary='OPENING', fill=100., equal_spacing=True, gap=0.):
    selected = list(context.selected_objects)
    active = context.active_object
    if context.mode != 'OBJECT' or active not in selected or len(selected) < 2:
        raise ValueError('In Object Mode, select the shapes, then select the closed target last.')
    if busy(): raise ValueError('Finish the active Harhtools tool before fitting.')
    if any(obj.type not in {'MESH', 'CURVE'} for obj in selected):
        raise ValueError('Select mesh or curve shapes and a closed planar target.')
    if any(not obj.is_editable for obj in selected):
        raise ValueError('The selected objects must be editable.')
    context.view_layer.update()
    target = target_boundary(active, boundary)
    sources = [obj for obj in selected if obj != active]
    depsgraph = context.evaluated_depsgraph_get()
    points = [p for obj in sources for p in object_points(obj, depsgraph)]
    transform, factors, envelope = solve(points, target, proportional, fill, equal_spacing, gap)
    def verify():
        actual = [target['project'](p) for obj in sources for p in
                  object_points(obj, context.evaluated_depsgraph_get())]
        envelope = hull(actual)
        index = og._SegmentIndex([target['loop']])
        clearance = max(0., gap/target['scale']-1e-6)
        if (not contained(envelope, target['loop'], target['convex'], epsilon=1e-6)
                or (clearance and any(index.within(a, b, clearance)
                    for a, b in zip(envelope, envelope[1:]+envelope[:1])))):
            raise ValueError('A modifier or constraint changed the fitted boundary; no changes were kept.')
    apply_transform(context, sources, active, transform, proportional, verify)
    return dict(count=len(sources), factors=factors, opening=target['opening'])


def apply_transform(context, sources, active, transform, proportional, verify=None):
    """Apply one arrangement transform atomically; preserve target and children."""
    # Protect the active object and unselected descendants when a parent moves.
    protected = {child for obj in sources for child in obj.children_recursive if child not in sources}
    changed = set(sources) | protected | {active}
    original_world = {obj: obj.matrix_world.copy() for obj in changed}
    original_basis = {obj: obj.matrix_basis.copy() for obj in changed}
    original_parent_inverse = {obj: obj.matrix_parent_inverse.copy() for obj in changed}
    replacements = {}
    desired = {obj: transform @ original_world[obj] if obj in sources else original_world[obj]
               for obj in changed}
    from .centering import parent_depth
    ordered = sorted(changed, key=parent_depth)
    def close(a, b):
        tolerance = [max(2e-6, math.sqrt(sum(b[r][c]**2 for r in range(3)))*2e-6) for c in range(4)]
        return all(abs(a[r][c]-b[r][c]) <= tolerance[c]
                   for r in range(4) for c in range(4))
    try:
        for obj in ordered:
            if not close(obj.matrix_world, desired[obj]):
                obj.matrix_world = desired[obj]
                context.view_layer.update()
                if (obj not in sources and obj.parent and obj.parent_type == 'OBJECT'
                        and not close(obj.matrix_world, desired[obj])
                        and abs(obj.parent.matrix_world.determinant()) > 1e-18
                        and abs(obj.matrix_basis.determinant()) > 1e-18):
                    # Parent inverse can encode the shear that location /
                    # rotation / scale channels cannot. Keep children fixed.
                    obj.matrix_parent_inverse = (obj.parent.matrix_world.inverted()
                        @ desired[obj] @ obj.matrix_basis.inverted())
                    context.view_layer.update()
        for obj in sources:
            if close(obj.matrix_world, desired[obj]): continue
            # Blender object channels cannot encode shear from nonuniform
            # scaling of a rotated shape. Preserve the exact affine result on
            # a private data copy when no modifier/driver changes that meaning.
            if (proportional or obj.constraints or obj.modifiers or obj.animation_data
                    or obj.data.shape_keys or abs(obj.matrix_world.determinant()) < 1e-18
                    or (obj.type == 'CURVE' and (obj.data.bevel_depth or obj.data.extrude))):
                continue
            original = obj.data
            copy = original.copy()
            replacements[obj] = (original, copy)
            copy.transform(obj.matrix_world.inverted() @ desired[obj])
            if obj.type == 'MESH': copy.update()
            obj.data = copy
        context.view_layer.update()
        if any(not close(obj.matrix_world, desired[obj]) for obj in ordered if obj not in replacements):
            raise ValueError('A parent, constraint or rotated scale prevented fitting. Use Proportional Scale or apply rotation first; no changes were kept.')
        if verify is not None: verify()
    except Exception:
        for obj, (original, copy) in replacements.items():
            obj.data = original
            (bpy.data.meshes if obj.type == 'MESH' else bpy.data.curves).remove(copy)
        for obj in ordered:
            obj.matrix_parent_inverse = original_parent_inverse[obj]
            obj.matrix_basis = original_basis[obj]
        context.view_layer.update()
        raise


class HarhtoolsFitSettings(bpy.types.PropertyGroup):
    mode: EnumProperty(name='Fit Mode', default='BOUNDS', items=[
        ('BOUNDS', 'Bake / Match Size', 'Match width, height and alignment to any original mesh; no closed boundary required'),
        ('FRAME', 'Inside Frame', 'Fit an arrangement within a closed planar frame')])
    bake_proportional: BoolProperty(name='Proportional Scale', default=False,
        description='Keep aspect ratio; turn off to match both target width and height exactly')
    use_alpha: BoolProperty(name='Use Visible Alpha', default=True,
        description='Match the visible texture bounds inside this plane UV crop; ignore transparent padding')
    align_rotation: BoolProperty(name='Align Rotation', default=True,
        description='Align to the original plane; match its visible silhouette when a direct alpha texture is available, otherwise use object axes')
    depth: EnumProperty(name='Depth', default='FRONT', items=[
        ('FRONT', 'Facing Surface', 'Place on the nearest front or back extent of the original'),
        ('CENTER', 'Center', 'Center on the original depth'),
        ('KEEP', 'Keep Current', 'Keep the current distance along the original plane normal')])
    offset: FloatProperty(name='Surface Offset', default=0., subtype='DISTANCE', unit='LENGTH',
        description='Move away from the original surface by this distance')
    offset_studs: display_units.distance_property('offset', 'Surface Offset')
    proportional: BoolProperty(name='Proportional Scale', default=True,
        description='Keep the proportions of all selected shapes and their arrangement')
    boundary: EnumProperty(name='Fit Inside', default='OPENING', items=[
        ('OPENING', 'Frame Opening', 'Use the largest opening in a frame, or its outline if it has no hole'),
        ('OUTER', 'Outer Boundary', 'Use the largest outer closed boundary of the active object')])
    equal_spacing: BoolProperty(name='Equal Boundary Spacing', default=True,
        description='Balance the closest gaps to a convex frame by maximizing minimum edge clearance; keep the arrangement together')
    gap: FloatProperty(name='Gap', default=0., min=0., subtype='DISTANCE', unit='LENGTH',
        description='Minimum space from the outside of the selected arrangement to the frame boundary')
    gap_studs: display_units.distance_property('gap', 'Gap')
    fill: FloatProperty(name='Fill', default=100., min=1., max=100., subtype='PERCENTAGE',
        description='Use less than 100 percent to leave extra space around the arrangement')


class OBJECT_OT_harhtools_fit_selected(bpy.types.Operator):
    bl_idname = 'object.harhtools_fit_selected'
    bl_label = 'Fit Selected into Active'
    bl_description = 'Match the selected bake to the last-selected original, or fit shapes inside a closed frame; keep the target fixed'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and context.active_object in context.selected_objects
                and len(context.selected_objects) > 1 and not busy())

    def execute(self, context):
        cfg = context.window_manager.harhtools_fit
        try:
            if cfg.mode == 'BOUNDS':
                from . import bake_fit
                result = bake_fit.fit_selection(context, cfg.bake_proportional, cfg.use_alpha,
                    cfg.align_rotation, cfg.depth, cfg.offset)
            else:
                result = fit_selection(context, cfg.proportional, cfg.boundary, cfg.fill, cfg.equal_spacing, cfg.gap)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        sx, sy = result['factors']
        scale = f'{sx:.3g}x / {sy:.3g}x'
        note = ' | '+ '; '.join(result['notes']) if result.get('notes') else ''
        self.report({'INFO'}, f'Fitted {result["count"]} object(s) to {context.active_object.name} | Scale {scale}{note}')
        return {'FINISHED'}


def draw_panel(layout, context):
    cfg = context.window_manager.harhtools_fit
    box = layout.box()
    box.prop(cfg, 'mode')
    box.label(text='Select bake, then original last.' if cfg.mode == 'BOUNDS' else 'Select shapes, then the frame last.')
    if context.active_object: box.label(text='Target: '+context.active_object.name)
    if cfg.mode == 'BOUNDS':
        box.prop(cfg, 'bake_proportional')
        box.prop(cfg, 'use_alpha')
        box.prop(cfg, 'align_rotation')
        box.prop(cfg, 'depth')
        display_units.draw(box, cfg, 'offset', context)
    else:
        box.prop(cfg, 'proportional')
        box.prop(cfg, 'equal_spacing')
        display_units.draw(box, cfg, 'gap', context)
        box.prop(cfg, 'boundary')
        box.prop(cfg, 'fill')
    row = box.row(); row.scale_y = 1.3
    row.operator('object.harhtools_fit_selected', text='Fit Bake to Active' if cfg.mode == 'BOUNDS' else 'Fit Selected into Active', icon='FULLSCREEN_ENTER')
    box.label(text='Matches size; keeps UVs and target unchanged.' if cfg.mode == 'BOUNDS' else 'Fits the outer geometry as one arrangement.')
    if context.mode != 'OBJECT': box.label(text='Switch to Object Mode to fit.', icon='INFO')


def register():
    bpy.utils.register_class(HarhtoolsFitSettings)
    bpy.types.WindowManager.harhtools_fit = PointerProperty(type=HarhtoolsFitSettings)
    bpy.utils.register_class(OBJECT_OT_harhtools_fit_selected)


def unregister():
    if OBJECT_OT_harhtools_fit_selected.is_registered: bpy.utils.unregister_class(OBJECT_OT_harhtools_fit_selected)
    if hasattr(bpy.types.WindowManager, 'harhtools_fit'): del bpy.types.WindowManager.harhtools_fit
    if HarhtoolsFitSettings.is_registered: bpy.utils.unregister_class(HarhtoolsFitSettings)
