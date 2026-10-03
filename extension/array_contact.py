"""First surface contact while one rotated mesh translates along a radius.

Swept triangle SAT finds the last collision interval along that translation.
A priority BVH visits the outermost possible contact first, avoiding sampling
steps that could miss thin planes or jump across disconnected pieces.
"""
import heapq
import itertools
import numpy as np
from mathutils import Matrix, Vector
from mathutils.geometry import closest_point_on_tri


class _Node:
    def __init__(self, triangles, ids):
        self.low = triangles[ids].min(axis=(0, 1))
        self.high = triangles[ids].max(axis=(0, 1))
        self.count = len(ids)
        self.children = None
        self.ids = ids
        if len(ids) > 8:
            centers = triangles[ids].mean(axis=1)
            axis = np.ptp(centers, axis=0).argmax()
            order = ids[np.argsort(centers[:, axis], kind='stable')]
            middle = len(order)//2
            self.children = (_Node(triangles, order[:middle]), _Node(triangles, order[middle:]))
            self.ids = None


def _exits(a, b, speed):
    """Exit times for paired triangles under B + (0, 0, speed * time)."""
    ea = np.roll(a, -1, axis=1)-a
    eb = np.roll(b, -1, axis=1)-b
    na = np.cross(ea[:, 0], ea[:, 1])
    nb = np.cross(eb[:, 0], eb[:, 1])
    axes = np.concatenate((na[:, None], nb[:, None],
        np.cross(ea[:, :, None], eb[:, None, :]).reshape(-1, 9, 3),
        np.cross(na[:, None], ea), np.cross(nb[:, None], eb)), axis=1)
    lengths = np.linalg.norm(axes, axis=2)
    axes /= np.where(lengths > 1e-14, lengths, 1)[:, :, None]
    pa = np.einsum('kvc,kac->kav', a, axes)
    pb = np.einsum('kvc,kac->kav', b, axes)
    amin, amax = pa.min(axis=2), pa.max(axis=2)
    bmin, bmax = pb.min(axis=2), pb.max(axis=2)
    velocity = axes[:, :, 2]*speed
    moving = abs(velocity) > 1e-12
    denominator = np.where(moving, velocity, 1)
    first, last = (amin-bmax)/denominator, (amax-bmin)/denominator
    low = np.where(moving, np.minimum(first, last), -np.inf)
    high = np.where(moving, np.maximum(first, last), np.inf)
    separated = (~moving) & ((amin > bmax+1e-9) | (bmin > amax+1e-9))
    enter, leave = np.maximum(low.max(axis=1), 0), high.min(axis=1)
    valid = (~separated.any(axis=1)) & (leave >= enter-1e-9) & np.isfinite(leave)
    return np.where(valid, leave, -np.inf)


def _segments(p, q, r, s):
    u, v, w = q-p, s-r, p-r
    aa, bb, cc, dd, ee = u@u, u@v, v@v, u@w, v@w
    det = aa*cc-bb*bb
    t = np.clip((bb*ee-cc*dd)/det, 0, 1) if det > 1e-20 else 0.
    z = (bb*t+ee)/cc if cc > 1e-20 else 0.
    if z < 0: z, t = 0., np.clip(-dd/aa, 0, 1) if aa > 1e-20 else 0.
    elif z > 1: z, t = 1., np.clip((bb-dd)/aa, 0, 1) if aa > 1e-20 else 0.
    return p+t*u, r+z*v


def _contact_point(a, b):
    pairs = []
    for p in a: pairs.append((p, np.array(closest_point_on_tri(Vector(p), *map(Vector, b)))))
    for p in b: pairs.append((np.array(closest_point_on_tri(Vector(p), *map(Vector, a))), p))
    for i in range(3):
        for j in range(3): pairs.append(_segments(a[i], a[(i+1)%3], b[j], b[(j+1)%3]))
    p, q = min(pairs, key=lambda pair: np.linalg.norm(pair[0]-pair[1]))
    return (p+q)*.5, float(np.linalg.norm(p-q))


def _distance(a, b, first):
    """Closest disjoint triangle features, traversed by AABB distance."""
    second = _Node(b, np.arange(len(b)))
    heap, sequence = [], itertools.count()
    best, point = np.inf, None
    def push(left, right):
        delta = np.maximum(np.maximum(left.low-right.high, right.low-left.high), 0)
        lower = float(np.linalg.norm(delta))
        if lower < best: heapq.heappush(heap, (lower, next(sequence), left, right))
    push(first, second)
    while heap:
        lower, _, left, right = heapq.heappop(heap)
        if lower >= best: break
        if left.children is None and right.children is None:
            for i in left.ids:
                for j in right.ids:
                    candidate, distance = _contact_point(a[i], b[j])
                    if distance < best: best, point = distance, candidate
                    if best < 1e-9: return best, point
        elif right.children is None or (left.children is not None and left.count >= right.count):
            for child in left.children: push(child, right)
        else:
            for child in right.children: push(left, child)
    return best, point


def solve_angle(mesh, pivot, axis, sign, maximum):
    """Approach first rotational contact from a provably separated angular span.

    Distance / maximum radial speed is a conservative angular advance: it
    cannot skip over thin surfaces or an earlier disconnected contact.
    """
    vertices, indices = mesh
    if not indices: raise ValueError('Touching Geometry needs surfaces with faces.')
    points = np.asarray(vertices, dtype=float)-np.asarray(pivot)
    scale = max(float(np.linalg.norm(points, axis=1).max()), 1e-8)
    points /= scale
    triangles = points[np.asarray(indices)]
    valid = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)>1e-14
    triangles = triangles[valid]
    if not len(triangles): raise ValueError('Touching Geometry needs nondegenerate faces.')
    radial = points-(points@np.asarray(axis))[:, None]*np.asarray(axis)
    speed = float(np.linalg.norm(radial, axis=1).max())
    if speed < 1e-9: raise ValueError('Move the 3D cursor away from the source axis.')
    first = _Node(triangles, np.arange(len(triangles)))
    angle = maximum
    for _ in range(64):
        rotation = np.array(Matrix.Rotation(angle*sign, 3, axis), dtype=float)
        distance, point = _distance(triangles, triangles@rotation.T, first)
        if distance <= 2e-7:
            if angle < 1e-5: raise ValueError('These surfaces only meet at zero rotation; move the center.')
            return dict(step=angle*sign, point=Vector(point*scale+np.asarray(pivot)), error=distance*scale)
        angle -= distance/speed*.95
        if angle <= 0: break
    raise ValueError('Could not resolve contact around this center; try moving the 3D cursor.')


def solve(mesh, anchor, axis, radial, angle):
    """Return radius and contact point for source and its next rotated copy."""
    vertices, indices = mesh
    if not indices: raise ValueError('Touching Geometry needs mesh or curve surfaces with faces.')
    points = np.asarray(vertices, dtype=float)-np.asarray(anchor)
    rotation = np.array(Matrix.Rotation(angle, 3, axis), dtype=float)
    direction = rotation@np.asarray(radial)-np.asarray(radial)
    speed = float(np.linalg.norm(direction))
    if speed < 1e-8: raise ValueError('Increase Sweep to fit touching surfaces.')
    forward = direction/speed
    up = np.asarray(axis, dtype=float)
    across = np.cross(forward, up)
    across /= np.linalg.norm(across)
    basis = np.stack((up, across, forward))
    scale = max(float(np.ptp(points, axis=0).max()), 1e-8)
    a = (points@basis.T/scale)[np.asarray(indices)]
    b = (points@rotation.T@basis.T/scale)[np.asarray(indices)]
    valid = np.linalg.norm(np.cross(a[:, 1]-a[:, 0], a[:, 2]-a[:, 0]), axis=1)>1e-14
    a, b = a[valid], b[valid]
    if not len(a): raise ValueError('Touching Geometry needs nondegenerate faces.')
    first, second = _Node(a, np.arange(len(a))), _Node(b, np.arange(len(b)))
    heap, sequence = [], itertools.count()
    best, winning = -np.inf, None

    def push(left, right):
        if np.any(left.low[:2] > right.high[:2]+1e-9) or np.any(right.low[:2] > left.high[:2]+1e-9): return
        upper = (left.high[2]-right.low[2])/speed
        if upper >= max(best, 0)-1e-9: heapq.heappush(heap, (-upper, next(sequence), left, right))

    push(first, second)
    while heap:
        negative, _, left, right = heapq.heappop(heap)
        if -negative < max(best, 0)-1e-9: break
        if left.children is None and right.children is None:
            ii, jj = np.meshgrid(left.ids, right.ids, indexing='ij')
            ii, jj = ii.ravel(), jj.ravel()
            exits = _exits(a[ii], b[jj], speed)
            index = exits.argmax()
            if exits[index] > best:
                best, winning = float(exits[index]), (int(ii[index]), int(jj[index]))
        elif right.children is None or (left.children is not None and left.count >= right.count):
            for child in left.children: push(child, right)
        else:
            for child in right.children: push(left, child)
    if winning is None or best <= 1e-9:
        raise ValueError('These surfaces do not meet at a positive radius; choose another axis or fit boundary.')
    ia, ib = winning
    point, distance = _contact_point(a[ia], b[ib]+np.array((0, 0, speed*best)))
    if distance > 1e-5:
        raise ValueError('Could not verify the surface contact; choose another axis or fit boundary.')
    return dict(radius=best*scale, point=Vector(point@basis*scale+np.asarray(anchor)),
                error=distance*scale)
