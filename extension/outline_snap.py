"""Cached, plane-aware geometry snapping for a uniform outline thickness.

The scene is inspected only by ``rebuild_targets`` (called at construction by
default, or on the first query with ``lazy_targets=True``).
``query`` searches a cached screen-space index and returns one positive distance
to the ORIGINAL source boundary. It never scales or edits any scene geometry.
Source and target Beziers use their actual control polygons, not evaluated fills.
"""
import math
from collections import defaultdict
from mathutils import Vector


def _dot(a, b):
    return math.fsum(x*y for x, y in zip(a, b))


def _distance2(a, b):
    return math.fsum((x-y)**2 for x, y in zip(a, b))


def _bounds_distance2(point, bounds):
    x, y = point
    (xmin, xmax), (ymin, ymax) = bounds
    dx = xmin-x if x < xmin else x-xmax if x > xmax else 0.0
    dy = ymin-y if y < ymin else y-ymax if y > ymax else 0.0
    return dx*dx+dy*dy


def _point(cp, t):
    if len(cp) == 2:
        return tuple(a+(b-a)*t for a, b in zip(*cp))
    s = 1-t
    return tuple(s*s*s*a+3*s*s*t*b+3*s*t*t*c+t*t*t*d for a, b, c, d in zip(*cp))


def _power(values):
    if len(values) == 2:
        return [values[0], values[1]-values[0]]
    a, b, c, d = values
    return [a, 3*(b-a), 3*(a-2*b+c), -a+3*b-3*c+d]


def _poly_eval(p, t):
    result = 0.0
    for value in reversed(p):
        result = result*t+value
    return result


def _poly_add(a, b, factor=1.0):
    result = list(a)+[0.0]*max(0, len(b)-len(a))
    for i, value in enumerate(b):
        result[i] += factor*value
    return result


def _poly_mul(a, b):
    result = [0.0]*(len(a)+len(b)-1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            result[i+j] += x*y
    return result


def _derivative(p):
    return [i*p[i] for i in range(1, len(p))] or [0.0]


def _unit_roots(coefficients):
    """All real roots in [0,1], isolating intervals by derivative roots.

    Cubic closest-point equations have degree five; projected rational cubics
    have degree at most eight. Critical points also recover repeated roots.
    """
    norm = max((abs(v) for v in coefficients), default=0.0)
    if norm <= 1e-30:
        return []
    p = [v/norm for v in coefficients]
    while len(p) > 1 and abs(p[-1]) < 1e-14:
        p.pop()
    if len(p) == 1:
        return []
    if len(p) == 2:
        root = -p[0]/p[1]
        return [min(1.0, max(0.0, root))] if -1e-12 <= root <= 1+1e-12 else []
    critical = _unit_roots(_derivative(p))
    stops = sorted({0.0, 1.0, *critical})
    roots = [t for t in stops if abs(_poly_eval(p, t)) <= 1e-11]
    for a, b in zip(stops, stops[1:]):
        fa, fb = _poly_eval(p, a), _poly_eval(p, b)
        if fa*fb >= 0:
            continue
        for _ in range(55):
            mid = (a+b)*.5
            fm = _poly_eval(p, mid)
            if fa*fm <= 0:
                b, fb = mid, fm
            else:
                a, fa = mid, fm
        roots.append((a+b)*.5)
    out = []
    for value in sorted(roots):
        if not out or value-out[-1] > 1e-8:
            out.append(value)
    return out


def nearest_on_segment(point, a, b):
    delta = tuple(y-x for x, y in zip(a, b))
    denominator = _dot(delta, delta)
    t = min(1.0, max(0.0, _dot(tuple(x-y for x, y in zip(point, a)), delta)/denominator)) if denominator else 0.0
    result = _point((a, b), t)
    return result, t, _distance2(point, result)


def nearest_on_cubic(point, cp):
    """Global closest point on a cubic in the source plane (double arithmetic)."""
    equation = [0.0]
    for axis in range(len(point)):
        polynomial = _power([p[axis] for p in cp])
        derivative = _derivative(polynomial)
        polynomial[0] -= point[axis]
        equation = _poly_add(equation, _poly_mul(polynomial, derivative))
    candidates = [0.0, 1.0, *_unit_roots(equation)]
    t = min(candidates, key=lambda value: _distance2(point, _point(cp, value)))
    result = _point(cp, t)
    return result, t, _distance2(point, result)


def _selectable_paths(context):
    """Collection selection restrictions apply even when object.hide_select is off."""
    allowed = defaultdict(list)
    def visit(layer, blocked=False, parents=()):
        collection = layer.collection
        path = (*parents, layer)
        blocked = blocked or layer.exclude or layer.hide_viewport or collection.hide_viewport or collection.hide_select
        if not blocked:
            for obj in collection.objects:
                allowed[obj.as_pointer()].append(path)
        for child in layer.children:
            visit(child, blocked, path)
    visit(context.view_layer.layer_collection)
    return allowed


class OutlineSnapCache:
    """Construct once at invoke; explicitly rebuild after target geometry changes.

    ``source_boundary`` is a sequence of closed world-space loops (the repeated
    closing vertex is optional). ``source_segments`` may supply the COMPLETE
    exact boundary as {kind: 'LINE'|'BEZIER', cp: world points}; it supersedes the
    sampled loops for distance measurement. LINE accepts two or four points.
    Optional ``owner`` metadata lets query's source_filter limit eligible sources.
    ``exact_source_cubics`` is an alternative complete boundary of cubic controls.
    The caller decides INSET/OUTSET; returned thickness is always unsigned.
    ``lazy_targets`` permits source measurement without scanning the scene until
    geometry snapping is actually queried.
    """
    def __init__(self, context, source_origin, source_normal, source_scale,
                 source_boundary, excluded_objects=(), pixel_tolerance=12.0,
                 exact_source_cubics=None, source_segments=None, plane_epsilon=None,
                 lazy_targets=False):
        self.context = context
        self.origin = tuple(float(v) for v in source_origin)
        normal = Vector(source_normal)
        if normal.length <= 1e-12:
            raise ValueError('Outline snapping needs a nonzero source-plane normal.')
        normal.normalize()
        seed = Vector((0, 1, 0)) if abs(normal.x) > .9 else Vector((1, 0, 0))
        u = (seed-normal*seed.dot(normal)).normalized()
        self.u, self.v, self.normal = tuple(u), tuple(normal.cross(u)), tuple(normal)
        self.scale = max(abs(float(source_scale)), 1e-9)
        self.plane_epsilon = float(plane_epsilon) if plane_epsilon is not None else max(self.scale*1e-5, 1e-7)
        self.pixel_tolerance = max(.1, float(pixel_tolerance))
        self._excluded_names = {o if isinstance(o, str) else o.name for o in excluded_objects}
        self._excluded_names.update(o.name for o in context.selected_objects)
        self._source = []
        self._source_bounds = []
        self._source_owners = []
        if source_segments is not None:
            for segment in source_segments:
                cp = list(segment['cp'])
                if segment.get('kind', 'BEZIER') == 'LINE':
                    cp = [cp[0], cp[-1]]
                self._add_source(cp, segment.get('owner'))
        elif exact_source_cubics is not None:
            for cp in exact_source_cubics:
                self._add_source(cp)
        else:
            for loop in source_boundary:
                points = list(loop)
                if len(points) < 2:
                    continue
                if _distance2(points[0], points[-1]) > 1e-24:
                    points.append(points[0])
                for a, b in zip(points, points[1:]):
                    self._add_source((a, b))
        if not self._source:
            raise ValueError('Outline snapping needs an original source boundary.')
        self._source_tree = self._build_source_tree(list(range(len(self._source))))
        self.stats = {'target_rebuilds': 0, 'projection_rebuilds': 0, 'queries': 0,
                      'source_searches': 0, 'source_nodes_tested': 0, 'source_segments_tested': 0}
        self._targets = []
        self._screen_key = None
        self._grid = {}
        self._projected_samples = []
        self._screen_lines = []
        self._targets_ready = False
        if not lazy_targets:
            self.rebuild_targets(context)

    def _to_plane(self, point):
        delta = tuple(float(p)-o for p, o in zip(point, self.origin))
        return _dot(delta, self.u), _dot(delta, self.v)

    def _plane_error(self, point):
        return abs(_dot(tuple(float(p)-o for p, o in zip(point, self.origin)), self.normal))

    def _world(self, point):
        return tuple(o+self.u[i]*point[0]+self.v[i]*point[1] for i, o in enumerate(self.origin))

    def _add_source(self, cp, owner=None):
        if len(cp) not in {2, 4}:
            raise ValueError('Source segments need two line points or four cubic controls.')
        if any(self._plane_error(p) > self.plane_epsilon for p in cp):
            raise ValueError('Source boundary is not in the outline plane.')
        planar = tuple(self._to_plane(p) for p in cp)
        if len(cp) == 2 and _distance2(*planar) <= 1e-24:
            return
        self._source.append(planar)
        self._source_bounds.append(tuple((min(p[i] for p in planar), max(p[i] for p in planar)) for i in range(2)))
        self._source_owners.append(owner)

    def _build_source_tree(self, indices):
        """Control-hull bounds are conservative for both lines and true cubics."""
        bounds = tuple((min(self._source_bounds[i][axis][0] for i in indices),
                        max(self._source_bounds[i][axis][1] for i in indices))
                       for axis in range(2))
        owners = frozenset(self._source_owners[i] for i in indices)
        if len(indices) <= 8:
            return bounds, owners, tuple(indices), None, None
        axis = max(range(2), key=lambda a: bounds[a][1]-bounds[a][0])
        indices.sort(key=lambda i: sum(self._source_bounds[i][axis]))
        middle = len(indices)//2
        return (bounds, owners, (), self._build_source_tree(indices[:middle]),
                self._build_source_tree(indices[middle:]))

    def _add_target(self, name, cp):
        if any(not math.isfinite(float(value)) for p in cp for value in p):
            return
        if any(self._plane_error(p) > self.plane_epsilon for p in cp):
            self.stats['off_plane_segments'] += 1
            return
        planar = tuple(self._to_plane(p) for p in cp)
        self._add_planar_target(name, planar)

    def _add_planar_target(self, name, planar):
        if len(planar) == 2 and _distance2(*planar) <= 1e-24:
            return
        self._targets.append({'object_name': name, 'cp': planar})

    @staticmethod
    def _object_signature(obj):
        data = obj.data
        topology = ((len(data.vertices), len(data.edges), len(data.polygons)) if obj.type == 'MESH'
                    else tuple((s.type, s.use_cyclic_u,
                                tuple((tuple(p.co), tuple(p.handle_left), tuple(p.handle_right)) for p in s.bezier_points)
                                if s.type == 'BEZIER' else tuple(tuple(p.co) for p in s.points))
                               for s in data.splines))
        return (data.as_pointer(), tuple(value for row in obj.matrix_world for value in row),
                tuple(value for corner in obj.bound_box for value in corner), topology)

    def _target_is_live(self, name):
        """Check only queried objects; no scene traversal on mouse movement."""
        try:
            obj, signature, paths = self._object_states[name]
            if (obj.name != name or not obj.as_pointer() or obj.hide_select
                    or obj.select_get(view_layer=self._view_layer)
                    or not obj.visible_get(view_layer=self._view_layer)
                    or self._object_signature(obj) != signature):
                return False
            return any(obj.name in path[-1].collection.objects and all(
                not (layer.exclude or layer.hide_viewport or layer.collection.hide_viewport or layer.collection.hide_select)
                for layer in path) for path in paths)
        except (ReferenceError, KeyError, RuntimeError):
            return False

    def rebuild_targets(self, context=None):
        """Explicit scene scan. query() never enumerates scene objects."""
        context = context or self.context
        self.context = context
        self._targets = []
        self._object_states = {}
        self._view_layer = context.view_layer
        self._screen_key = None
        self._targets_ready = False
        self.stats['target_rebuilds'] += 1
        self.stats.update(objects_scanned=0, objects_used=0, off_plane_segments=0, unsupported_splines=0)
        allowed = _selectable_paths(context)
        depsgraph = context.evaluated_depsgraph_get()
        for obj in context.view_layer.objects:
            self.stats['objects_scanned'] += 1
            if (obj.name in self._excluded_names or obj.type not in {'MESH', 'CURVE'}
                    or obj.hide_select or obj.as_pointer() not in allowed
                    or obj.select_get() or not obj.visible_get(view_layer=context.view_layer)):
                continue
            before = len(self._targets)
            evaluated = obj.evaluated_get(depsgraph)
            matrix = evaluated.matrix_world
            if obj.type == 'MESH':
                mesh = evaluated.to_mesh()
                try:
                    projected_vertices = {}
                    for edge in mesh.edges:
                        if getattr(edge, 'hide', False):
                            continue
                        a, b = (mesh.vertices[i] for i in edge.vertices)
                        if getattr(a, 'hide', False) or getattr(b, 'hide', False):
                            continue
                        for vertex in (a, b):
                            if vertex.index not in projected_vertices:
                                world = tuple(matrix @ vertex.co)
                                if not all(math.isfinite(value) for value in world):
                                    projected_vertices[vertex.index] = (None, 2)
                                elif self._plane_error(world) > self.plane_epsilon:
                                    projected_vertices[vertex.index] = (None, 1)
                                else:
                                    projected_vertices[vertex.index] = (self._to_plane(world), 0)
                        pa, sa = projected_vertices[a.index]
                        pb, sb = projected_vertices[b.index]
                        if sa == 2 or sb == 2:
                            continue
                        if sa == 1 or sb == 1:
                            self.stats['off_plane_segments'] += 1
                            continue
                        previous = len(self._targets)
                        self._add_planar_target(obj.name, (pa, pb))
                        if len(self._targets) > previous and not obj.modifiers:
                            self._targets[-1]['mesh_sample'] = (edge.index,
                                tuple((int(i), tuple(obj.data.vertices[i].co)) for i in edge.vertices))
                finally:
                    evaluated.to_mesh_clear()
            else:
                # Keep true source spline controls: evaluated curve meshes have
                # fill tessellation and bevel edges which are not outline targets.
                curve = evaluated.data
                if not hasattr(curve, 'splines'):
                    continue
                for spline in curve.splines:
                    if spline.type == 'BEZIER':
                        points = spline.bezier_points
                        count = len(points) if spline.use_cyclic_u else len(points)-1
                        for i in range(max(0, count)):
                            a, b = points[i], points[(i+1) % len(points)]
                            if getattr(a, 'hide', False) or getattr(b, 'hide', False):
                                continue
                            self._add_target(obj.name, tuple(matrix @ p for p in (a.co, a.handle_right, b.handle_left, b.co)))
                    elif spline.type == 'POLY':
                        points = spline.points
                        count = len(points) if spline.use_cyclic_u else len(points)-1
                        for i in range(max(0, count)):
                            a, b = points[i], points[(i+1) % len(points)]
                            if getattr(a, 'hide', False) or getattr(b, 'hide', False):
                                continue
                            self._add_target(obj.name, (matrix @ a.co.xyz, matrix @ b.co.xyz))
                    else:
                        self.stats['unsupported_splines'] += 1
            self.stats['objects_used'] += len(self._targets) > before
            if len(self._targets) > before:
                self._object_states[obj.name] = obj, self._object_signature(obj), allowed[obj.as_pointer()]
        self.stats['target_segments'] = len(self._targets)
        self._targets_ready = True
        return self

    def _clip(self, point):
        x, y = point
        return tuple(a*x+b*y+c for a, b, c in self._plane_clip)

    def _project(self, point):
        x, y, _, w = self._clip(point)
        if w <= 1e-10:
            return None
        return self._width*.5*(1+x/w), self._height*.5*(1+y/w)

    def _samples(self, cp):
        if len(cp) == 2:
            return [(0.0, self._project(cp[0])), (1.0, self._project(cp[1]))]
        result = [(0.0, self._project(cp[0]))]
        def divide(a, b, pa, pb, depth):
            mid = (a+b)*.5
            pm = self._project(_point(cp, mid))
            quarters = [self._project(_point(cp, a+(b-a)*fraction)) for fraction in (.25, .75)]
            visible = pa is not None and pb is not None and pm is not None and all(p is not None for p in quarters)
            flat = visible and max(nearest_on_segment(p, pa, pb)[2] for p in [pm, *quarters]) <= .25**2
            if depth >= 12 or flat:
                result.append((b, pb))
                return
            divide(a, mid, pa, pm, depth+1)
            divide(mid, b, pm, pb, depth+1)
        divide(0.0, 1.0, result[0][1], self._project(cp[-1]), 0)
        return result

    def _prepare_screen(self, region, rv3d):
        ui_scale = float(self.context.preferences.system.ui_scale)
        if not math.isfinite(ui_scale) or ui_scale <= 0:
            ui_scale = 1.0  # Blender initializes this to zero in background mode.
        matrix = tuple(tuple(float(x) for x in row) for row in rv3d.perspective_matrix)
        key = (region.width, region.height, matrix, ui_scale, self.pixel_tolerance)
        if key == self._screen_key:
            return
        self._screen_key = key
        self._matrix = matrix
        # All targets lie in the fixed source plane. Compose its world basis
        # with the view matrix once, instead of expanding every point to XYZ.
        self._plane_clip = tuple((_dot(row[:3], self.u), _dot(row[:3], self.v),
                                  _dot(row[:3], self.origin)+row[3]) for row in matrix)
        self._width, self._height = float(region.width), float(region.height)
        self._radius = self.pixel_tolerance*ui_scale
        self._tile = max(16.0, self._radius*2)
        self._grid = defaultdict(set)
        self._projected_samples = []
        self._screen_lines = []
        self.stats['projection_rebuilds'] += 1
        padding = self._radius+.5
        for index, target in enumerate(self._targets):
            clips = [self._clip(p) for p in target['cp']]
            if all(p[3] <= 1e-10 for p in clips):
                self._projected_samples.append([])
                self._screen_lines.append(None)
                continue
            if len(clips) == 2 and all(p[3] > 1e-10 for p in clips):
                a, b = [(self._width*.5*(1+p[0]/p[3]), self._height*.5*(1+p[1]/p[3]))
                        for p in clips]
                dx, dy = b[0]-a[0], b[1]-a[1]
                self._screen_lines.append((*a, dx, dy, dx*dx+dy*dy, clips[0][3], clips[1][3]))
                samples = [(0.0, a), (1.0, b)]
            else:
                self._screen_lines.append(None)
                samples = self._samples(target['cp'])
            self._projected_samples.append(samples)
            for (_, a), (_, b) in zip(samples, samples[1:]):
                if a is None or b is None:
                    continue
                left, right = max(-padding, min(a[0], b[0])-padding), min(self._width+padding, max(a[0], b[0])+padding)
                bottom, top = max(-padding, min(a[1], b[1])-padding), min(self._height+padding, max(a[1], b[1])+padding)
                if left > right or bottom > top:
                    continue
                for x in range(math.floor(left/self._tile), math.floor(right/self._tile)+1):
                    for y in range(math.floor(bottom/self._tile), math.floor(top/self._tile)+1):
                        self._grid[x, y].add(index)

    def _nearest_screen(self, mouse, cp):
        # In perspective view each projected cubic is rational. Solve the full
        # rational distance derivative rather than snapping to sampled chords.
        clips = [self._clip(p) for p in cp]
        if len(cp) == 2 and all(p[3] > 1e-10 for p in clips):
            # Perspective maps a straight segment to a straight screen segment.
            # Convert the closest screen fraction back through homogeneous w.
            projected = [(self._width*.5*(1+p[0]/p[3]),
                          self._height*.5*(1+p[1]/p[3])) for p in clips]
            screen, fraction, distance = nearest_on_segment(mouse, *projected)
            w0, w1 = clips[0][3], clips[1][3]
            t = fraction*w0/(w1*(1-fraction)+fraction*w0)
            return distance, _point(cp, t), screen, t
        x, y, w = [_power([p[i] for p in clips]) for i in (0, 1, 3)]
        a = _poly_add([value*self._width*.5 for value in x], w, self._width*.5-mouse[0])
        b = _poly_add([value*self._height*.5 for value in y], w, self._height*.5-mouse[1])
        aa_bb = _poly_add(_poly_mul(a, a), _poly_mul(b, b))
        derivative_part = _poly_add(_poly_mul(a, _derivative(a)), _poly_mul(b, _derivative(b)))
        equation = _poly_add(_poly_mul(derivative_part, w), _poly_mul(aa_bb, _derivative(w)), -1)
        best = None
        for t in [0.0, 1.0, *_unit_roots(equation)]:
            point = _point(cp, t)
            screen = self._project(point)
            if screen is None:
                continue
            distance = _distance2(screen, mouse)
            if best is None or distance < best[0]:
                best = distance, point, screen, t
        return best

    def nearest_source(self, world_point, allowed_owners=None):
        """Return (distance, boundary point), or None if no owner is eligible.

        Owners are optional ``source_segments`` metadata supplied by the caller.
        They let overlapping selected shapes apply their own inset/outset side
        rules without choosing the closer boundary of an ineligible source.
        """
        point = self._to_plane(world_point)
        best = None
        self.stats['source_searches'] += 1
        if allowed_owners is not None and not allowed_owners:
            return None
        stack = [(0.0, self._source_tree)]
        while stack:
            lower, node = stack.pop()
            if best is not None and lower > best[2]:
                continue
            bounds, owners, indices, left, right = node
            self.stats['source_nodes_tested'] += 1
            if allowed_owners is not None and owners.isdisjoint(allowed_owners):
                continue
            if indices:
                for index in indices:
                    if allowed_owners is not None and self._source_owners[index] not in allowed_owners:
                        continue
                    lower = _bounds_distance2(point, self._source_bounds[index])
                    if best is not None and lower > best[2]:
                        continue
                    cp = self._source[index]
                    self.stats['source_segments_tested'] += 1
                    result = nearest_on_segment(point, *cp) if len(cp) == 2 else nearest_on_cubic(point, cp)
                    if best is None or result[2] < best[2]:
                        best = result
            else:
                a, b = _bounds_distance2(point, left[0]), _bounds_distance2(point, right[0])
                # Visit the nearer subtree first so it bounds the farther one.
                if a < b:stack.extend(((b, right), (a, left)))
                else:stack.extend(((a, left), (b, right)))
        return (math.sqrt(max(0.0, best[2])), Vector(self._world(best[0]))) if best is not None else None

    def query(self, mouse_xy, region, rv3d, source_filter=None):
        """Return a nearby coplanar target and a positive uniform thickness, else None.

        mouse_xy is relative to the WINDOW region, in pixels. Source plane and
        target geometry stay fixed during a gesture; only view projection may
        invalidate automatically. Call rebuild_targets after scene geometry edits.
        source_filter(world_point) may return eligible source-owner IDs. Targets
        with no eligible source are skipped before choosing the nearest target.
        """
        self.stats['queries'] += 1
        mouse = tuple(float(v) for v in mouse_xy[:2])
        if not (0 <= mouse[0] <= region.width and 0 <= mouse[1] <= region.height):
            return None
        if not self._targets_ready:
            self.rebuild_targets()
        self._prepare_screen(region, rv3d)
        p, u, v = [self._project(point) for point in ((0, 0), (self.scale, 0), (0, self.scale))]
        if p is None or u is None or v is None:
            return None
        du, dv = (u[0]-p[0], u[1]-p[1]), (v[0]-p[0], v[1]-p[1])
        if abs(du[0]*dv[1]-du[1]*dv[0]) <= 1e-6*max(1.0, math.sqrt(_dot(du, du)*_dot(dv, dv))):
            return None  # An edge-on source plane cannot define a stable snap.
        tile = math.floor(mouse[0]/self._tile), math.floor(mouse[1]/self._tile)
        best = None
        live = {}
        for index in sorted(self._grid.get(tile, ())):
            target = self._targets[index]
            screen_line = self._screen_lines[index]
            if screen_line is not None:
                ax, ay, dx, dy, denominator, w0, w1 = screen_line
                fraction = min(1.0, max(0.0, ((mouse[0]-ax)*dx+(mouse[1]-ay)*dy)/denominator)) if denominator else 0.0
                screen = ax+fraction*dx, ay+fraction*dy
                distance = (mouse[0]-screen[0])**2+(mouse[1]-screen[1])**2
                if distance > self._radius**2 or (best is not None and distance >= best['pixel_distance']**2-1e-10):
                    continue
                t = fraction*w0/(w1*(1-fraction)+fraction*w0)
                hit = distance, _point(target['cp'], t), screen, t
            else:
                # Coarse sampled search gates exact rational-cubic refinement.
                samples = self._projected_samples[index]
                coarse = min((nearest_on_segment(mouse, a, b)[2]
                              for (_, a), (_, b) in zip(samples, samples[1:])
                              if a is not None and b is not None), default=math.inf)
                if coarse > (self._radius+.5)**2:
                    continue
                hit = self._nearest_screen(mouse, target['cp'])
                if hit is None or hit[0] > self._radius**2:
                    continue
                if best is not None and hit[0] >= best['pixel_distance']**2-1e-10:
                    continue
            name = target['object_name']
            if name not in live:
                live[name] = self._target_is_live(name)
            if not live[name]:
                continue
            sample = target.get('mesh_sample')
            if sample is not None:
                obj = self._object_states[name][0]
                edge_index, vertices = sample
                if (getattr(obj.data.edges[edge_index], 'hide', False)
                        or any(getattr(obj.data.vertices[i], 'hide', False)
                               or tuple(obj.data.vertices[i].co) != cp for i, cp in vertices)):
                    continue
            world = self._world(hit[1])
            allowed = source_filter(Vector(world)) if source_filter is not None else None
            source_hit = self.nearest_source(world, allowed)
            if source_hit is None:
                continue
            thickness, nearest = source_hit
            if thickness <= max(self.scale*1e-9, 1e-10):
                continue
            if best is None or hit[0] < best['pixel_distance']**2-1e-10:
                best = dict(thickness=thickness, world_point=Vector(world),
                            screen_point=Vector(hit[2]), object_name=target['object_name'],
                            pixel_distance=math.sqrt(hit[0]), nearest_source_point=nearest,
                            target_parameter=hit[3])
        return best
