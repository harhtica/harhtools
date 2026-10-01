"""Suggest useful array axes from selected geometry and the current view."""
from mathutils import Matrix, Vector

from . import array_core


_NAMES = 'XYZ'
_BASIS = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))


def _current(cfg):
    value = getattr(cfg, 'radial_axis', 'Z') if cfg.mode == 'CIRCULAR' else getattr(cfg, 'axes', 'X')
    if isinstance(value, str) and value in _NAMES and len(value) == 1:
        return value
    return next((axis for axis in _NAMES if axis in value), 'X')


def _best(candidates, scores, current, largest=True):
    """Deterministic ties keep a valid current choice before using XYZ order."""
    optimum = (max if largest else min)(scores[name] for name in candidates)
    tolerance = max(abs(optimum), max(abs(scores[name]) for name in candidates), 1e-8) * 1e-6
    tied = [name for name in candidates if abs(scores[name] - optimum) <= tolerance]
    return current if current in tied else tied[0]


def suggest_axis(snapshot, cfg, scene, view_rotation=None):
    """Return (axis, short explanation), without modifying settings or geometry.

    ``view_rotation`` is the viewport's rotation from view coordinates to world
    coordinates (normally RegionView3D.view_rotation). Axis names always refer
    to the configured World or Active reference frame.
    """
    current = _current(cfg)
    frame = (snapshot.active_matrix.to_quaternion().to_matrix().to_4x4()
             if getattr(cfg, 'orientation', 'WORLD') == 'ACTIVE' else Matrix.Identity(4))
    inverse = frame.transposed()
    low, high = array_core._bounds(tuple(inverse @ point for point in snapshot.bounds_points))
    span = high - low
    sizes = {name: max(span[i], 0) for i, name in enumerate(_NAMES)}
    availability = array_core.axis_availability(snapshot, cfg, scene)
    candidates = [name for name in _NAMES if availability.get(name, (True, ''))[0]] or list(_NAMES)
    view_right = view_normal = None
    if view_rotation is not None:
        view_right = inverse.to_3x3() @ (view_rotation @ Vector((1, 0, 0)))
        view_normal = inverse.to_3x3() @ (view_rotation @ Vector((0, 0, 1)))
        if view_right.length:
            view_right.normalize()
        if view_normal.length:
            view_normal.normalize()
    by_size = sorted(_NAMES, key=lambda name: (sizes[name], _NAMES.index(name)))
    thin, middle, _ = (sizes[name] for name in by_size)
    tolerance = max(max(sizes.values()), 1e-8) * 1e-6
    # Two clear in-plane dimensions identify a plane; a line has many possible
    # normals and is resolved using the view/current axis instead.
    planar = middle > tolerance and thin <= middle * .08

    if cfg.mode == 'CIRCULAR':
        if planar:
            axis = _best(candidates, sizes, current, largest=False)
            if axis == by_size[0]:
                return axis, f'{axis} follows the flat selection normal'
            return axis, f'{axis} is the nearest available axis to the selection normal'
        if view_normal is not None:
            scores = {name: abs(_BASIS[i].dot(view_normal)) for i, name in enumerate(_NAMES)}
            axis = _best(candidates, scores, current)
            return axis, f'{axis} faces the current view'
        if current in candidates:
            return current, f'Keeping {current} for this selection'
        axis = _best(candidates, sizes, current, largest=False)
        return axis, f'{axis} suits the selection bounds'

    if (getattr(cfg, 'fit_length', False) and len(snapshot.sources) == 2
            and snapshot.active_source in snapshot.sources and len(snapshot.per_source_bounds) == 2):
        source_index = snapshot.sources.index(snapshot.active_source)
        centers = []
        for points in snapshot.per_source_bounds:
            a, b = array_core._bounds(tuple(inverse @ point for point in points))
            centers.append((a + b) * .5)
        separation = centers[1 - source_index] - centers[source_index]
        scores = {name: abs(separation[i]) for i, name in enumerate(_NAMES)}
        axis = _best(candidates, scores, current)
        return axis, f'{axis} runs from the active source toward the other object'

    usable = [name for name in candidates if sizes[name] > tolerance]
    if usable:
        candidates = usable
    if view_right is not None:
        if planar:
            in_plane = [name for name in candidates if name != by_size[0]]
            if in_plane:
                candidates = in_plane
        scores = {name: abs(_BASIS[i].dot(view_right)) for i, name in enumerate(_NAMES)}
        axis = _best(candidates, scores, current)
        return axis, f'{axis} runs across the current view'
    if current in candidates:
        return current, f'Keeping {current} for this selection'
    axis = _best(candidates, sizes, current)
    return axis, f'{axis} follows the widest usable direction'
