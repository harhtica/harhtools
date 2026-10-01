"""Cut selected intersections, then select the overlapping regions.

Run with Blender's Text Editor > Run Script.
Edit Mode: selected visible faces and edges in the meshes being edited.
Object Mode: visible faces and edges in selected, visible mesh objects.
Selected objects cut against each other and remain separate objects.
Supports coplanar faces, overlapping flat rings, and loose wire outlines.
Flat wire selections can have any world-space rotation.
When only edges are selected, cut those edges and retain the adjoining faces;
face boundaries gain the new vertices and overlapping adjoining faces are selected.
Face regions are split at all selected boundaries; overlapping coplanar regions
become a single face layer, with only the overlap patches selected afterward.
Existing holes stay open. UVs are interpolated.
Closed wire loops stay wires: select only edges around the overlap regions.
Set WIRE_OVERLAPS_AS_FACES = True below to create and select those overlap faces.
Open wires are cut but cannot define an enclosed overlap area.
Unselected geometry is preserved. If a cut would split a boundary shared with
an unselected face, include that adjacent face in the selection first.
Nothing selected means no operation. Results are shown in Edit Mode with face
or edge selection as appropriate, including when started in Object Mode.
Set DRY_RUN = True in the execution namespace to validate without changing it.
"""
import bpy
import bmesh
import json
import math
import hashlib
from mathutils.kdtree import KDTree
from mathutils import Vector, Matrix
from mathutils.geometry import delaunay_2d_cdt, tessellate_polygon

OVERLAP_FACE_ATTRIBUTE = 'intersection_overlap'
OVERLAP_EDGE_ATTRIBUTE = 'intersection_overlap_boundary'
WIRE_OVERLAPS_AS_FACES = globals().get('WIRE_OVERLAPS_AS_FACES', False)


def select_overlap_faces(bm, faces):
    """Select only the overlap patches, using stored pre-cut coverage counts."""
    layer = bm.faces.layers.int.get(OVERLAP_FACE_ATTRIBUTE)
    chosen = [f for f in faces if layer is not None and f[layer] >= 2 and not f.hide]
    for f in bm.faces: f.select_set(False)
    for e in bm.edges: e.select_set(False)
    for v in bm.verts: v.select_set(False)
    bm.select_history.clear()
    bm.select_mode = {'FACE'}
    for f in chosen: f.select_set(True)
    return len(chosen)


def wire_overlap_regions(points, edges, axes, tol, extra_faces=()):
    """Use closed input wire loops as virtual faces, without filling the mesh."""
    adjacency = {}
    for a, b in edges:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    remaining, loops = set(adjacency), []
    while remaining:
        seed = min(remaining)
        component, stack = set(), [seed]
        while stack:
            v = stack.pop()
            if v in component: continue
            component.add(v)
            stack.extend(adjacency[v])
        remaining.difference_update(component)
        if any(len(adjacency[v]) % 2 or len(adjacency[v]) > 8 for v in component):
            continue
        # At a previously welded crossing, continue along the straightest
        # pair of segments to recover the original circle/outline loops.
        pairing = {}
        for v in component:
            neighbors = list(adjacency[v])
            while neighbors:
                choices = []
                for i, a in enumerate(neighbors):
                    da = (points[a]-points[v]).normalized()
                    for b in neighbors[i+1:]:
                        db = (points[b]-points[v]).normalized()
                        choices.append((da.dot(db),a,b))
                _, a, b = min(choices)
                pairing[v,a], pairing[v,b] = b,a
                neighbors.remove(a); neighbors.remove(b)
        unused = {tuple(sorted((v,n))) for v in component for n in adjacency[v]}
        found, valid = [], True
        while unused:
            start, following = min(unused)
            ordered, traversed = [start], {tuple(sorted((start,following)))}
            previous, current = start, following
            while not (current == start and pairing[current,previous] == following):
                ordered.append(current)
                next_vertex = pairing[current,previous]
                edge = tuple(sorted((current,next_vertex)))
                if edge in traversed:
                    valid = False
                    break
                traversed.add(edge)
                previous, current = current, next_vertex
            unused.difference_update(traversed)
            if not valid: break
            if len(ordered) >= 3 and len(set(ordered)) == len(ordered): found.append(ordered)
        if valid: loops.extend(found)
    loops.extend(list(face) for face in extra_faces)
    if len(loops) < 2:
        return {'loops': len(loops), 'polygons': [], 'segments': []}
    used = sorted(adjacency)
    remap = {v: i for i, v in enumerate(used)}
    xy = [Vector((points[i][axes[0]], points[i][axes[1]])) for i in used]
    polygons = [[remap[i] for i in loop] for loop in loops]
    def signed_area(ids, coords):
        return sum(coords[ids[i]].cross(coords[ids[(i+1) % len(ids)]]) for i in range(len(ids))) * .5
    polygons = [p if signed_area(p, xy) > 0 else list(reversed(p)) for p in polygons]
    out_v, out_e, out_f, _, orig_e, orig_f = delaunay_2d_cdt(
        xy, [(remap[a], remap[b]) for a, b in edges], polygons, 4, tol, True)
    covered = [0.] * len(polygons)
    overlaps = []
    for polygon, origins in zip(out_f, orig_f):
        size = abs(signed_area(polygon, out_v))
        for i in origins: covered[i] += size
        if len(origins) >= 2 and size > tol*tol:
            overlaps.append(polygon)
    for i, polygon in enumerate(polygons):
        expected = abs(signed_area(polygon, xy))
        if abs(covered[i]-expected) > max(tol*tol*100, expected*1e-4):
            raise RuntimeError('Could not validate the closed-wire overlap regions.')
    overlap_edges = {tuple(sorted((p[i], p[(i+1) % len(p)]))) for p in overlaps for i in range(len(p))}
    segments = [(out_v[a], out_v[b]) for (a, b), ids in zip(out_e, orig_e)
                if tuple(sorted((a,b))) in overlap_edges and any(i < len(edges) for i in ids)]
    return {'loops': len(loops), 'polygons': [[out_v[i] for i in p] for p in overlaps], 'segments': segments}


def finish_wire_selection(bm, edges, regions, axes, matrix, tol):
    """Select overlap borders, optionally making only the overlap faces."""
    marker = bm.edges.layers.int[OVERLAP_EDGE_ATTRIBUTE]
    selected = []
    for edge in edges:
        points = [matrix @ v.co for v in edge.verts]
        xy = [Vector((p[axes[0]],p[axes[1]])) for p in points]
        hit = False
        for a, b in regions['segments']:
            direction = b-a
            if direction.length_squared <= tol*tol: continue
            parameters = [(p-a).dot(direction)/direction.length_squared for p in xy]
            if all(-tol <= t*direction.length <= direction.length+tol and
                   (a+direction*t-p).length <= tol*2 for t,p in zip(parameters,xy)):
                hit = True
                break
        # Preserve known overlap labels when a previous cut has already joined
        # the original loops into a graph and their source cycles are unavailable.
        if regions['loops'] < 2 and edge[marker]: hit = True
        edge[marker] = int(hit)
        if hit: selected.append(edge)
    for f in bm.faces: f.select_set(False)
    for e in bm.edges: e.select_set(False)
    for v in bm.verts: v.select_set(False)
    bm.select_history.clear()
    if not WIRE_OVERLAPS_AS_FACES or not regions['polygons']:
        bm.select_mode = {'EDGE'}
        for edge in selected: edge.select_set(True)
        return {'selection_mode': 'EDGE', 'overlap_edges_selected': len(selected),
                'overlap_faces_created': 0, 'closed_wire_loops': regions['loops']}
    candidates = list({v for e in edges for v in e.verts})
    tree = KDTree(len(candidates))
    for i, v in enumerate(candidates):
        p = matrix @ v.co
        tree.insert(Vector((p[axes[0]],p[axes[1]],0.)),i)
    tree.balance()
    layer = bm.faces.layers.int[OVERLAP_FACE_ATTRIBUTE]
    faces = []
    extra_vertices = {}
    inverse = matrix.inverted()
    normal_axis = next(k for k in range(3) if k not in axes)
    plane_depth = (matrix @ candidates[0].co)[normal_axis]
    for polygon in regions['polygons']:
        verts = []
        for p in polygon:
            _, i, distance = tree.find(Vector((p.x,p.y,0.)))
            vertex = candidates[i]
            if distance > tol*3:
                key = tuple(p)
                if key not in extra_vertices:
                    world = Vector((0.,0.,0.))
                    world[axes[0]],world[axes[1]],world[normal_axis] = p.x,p.y,plane_depth
                    extra_vertices[key] = bm.verts.new(inverse @ world)
                vertex = extra_vertices[key]
            if not verts or vertex is not verts[-1]: verts.append(vertex)
        if len(verts)>1 and verts[0] is verts[-1]: verts.pop()
        if len(set(verts)) < 3: continue
        face = bm.faces.get(verts) or bm.faces.new(verts)
        face[layer] = 2
        faces.append(face)
    bm.normal_update()
    count = select_overlap_faces(bm, faces)
    return {'selection_mode': 'FACE', 'overlap_faces_selected': count,
            'overlap_faces_created': len(faces), 'closed_wire_loops': regions['loops']}


def overlapping_attached_faces(bm, faces, matrix, axes, tol, guides=()):
    """Identify existing face interiors that overlap, ignoring edge-only contact."""
    faces = set(faces)
    triangles = []
    normal_axis = next(k for k in range(3) if k not in axes)
    inputs = [(triangle[0].face,[matrix @ loop.vert.co for loop in triangle])
              for triangle in bm.calc_loop_triangles() if triangle[0].face in faces]
    for guide in guides:
        for i, polygon in enumerate(guide['attached_faces']):
            face_tag = ('guide',guide['object'],i)
            inputs.extend((face_tag,triangle) for triangle in tessellate_polygon(
                [[Vector(guide['vertices'][j]) for j in polygon]]))
    for face, world in inputs:
        depths = [p[normal_axis] for p in world]
        if max(depths)-min(depths) > tol: continue
        poly = [(p[axes[0]],p[axes[1]]) for p in world]
        if cross2(sub2(poly[1],poly[0]),sub2(poly[2],poly[0])) < 0: poly.reverse()
        bounds = (min(p[0] for p in poly),max(p[0] for p in poly),min(p[1] for p in poly),max(p[1] for p in poly))
        triangles.append((face,poly,bounds,sum(depths)/3.))
    overlaps = set()
    for i, (face, poly, bounds, depth) in enumerate(triangles):
        for other, clip, box, other_depth in triangles[i+1:]:
            if face not in faces and other not in faces: continue
            if abs(depth-other_depth) > tol: continue
            if face is other or (face in overlaps and other in overlaps): continue
            if bounds[1] <= box[0]+tol or box[1] <= bounds[0]+tol or bounds[3] <= box[2]+tol or box[3] <= bounds[2]+tol: continue
            subject = poly[:]
            for j, a in enumerate(clip):
                b = clip[(j+1)%3]
                direction = sub2(b,a)
                output = []
                if not subject: break
                previous = subject[-1]
                previous_side = cross2(direction, sub2(previous,a))
                for current in subject:
                    side = cross2(direction,sub2(current,a))
                    if (side >= 0) != (previous_side >= 0):
                        t = previous_side/(previous_side-side)
                        output.append((previous[0]+t*(current[0]-previous[0]),previous[1]+t*(current[1]-previous[1])))
                    if side >= 0: output.append(current)
                    previous, previous_side = current, side
                subject = output
            area = abs(sum(cross2(p,subject[(j+1)%len(subject)]) for j,p in enumerate(subject)))*.5
            threshold = tol*min(max(bounds[1]-bounds[0],bounds[3]-bounds[2]),max(box[1]-box[0],box[3]-box[2]))
            if area > threshold:
                if face in faces: overlaps.add(face)
                if other in faces: overlaps.add(other)
    return overlaps


def cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def sub2(a, b):
    return (a[0] - b[0], a[1] - b[1])


def wire_plane_projection(points, guides, tol):
    """Fit an orthonormal cutting plane without moving input geometry."""
    candidates = list(points)
    for guide in guides:
        candidates.extend(Vector(p) for p in guide['vertices'])
    origin = points[0]
    delta = max((p-origin for p in candidates), key=lambda p: p.length_squared)
    if delta.length <= tol:
        raise RuntimeError('The selected wire has no usable length.')
    axis_u = delta.normalized()
    transverse = max((p-origin for p in candidates), key=lambda p: axis_u.cross(p).length_squared)
    normal = axis_u.cross(transverse)
    if normal.length <= tol:
        axis = min(range(3), key=lambda i: abs(axis_u[i]))
        reference = Vector(tuple(1. if k == axis else 0. for k in range(3)))
        normal = axis_u.cross(reference)
    normal.normalize()
    axis_v = normal.cross(axis_u).normalized()
    if any(abs((p-origin).dot(normal)) > tol*4 for p in points):
        raise RuntimeError('Selected edges must lie in one flat plane.')
    if any(abs((Vector(p)-origin).dot(normal)) > tol*4 for g in guides for p in g['vertices']):
        raise RuntimeError('Selected objects must lie in the same plane for planar intersection cuts.')
    return Matrix(((axis_u.x,axis_u.y,axis_u.z,-axis_u.dot(origin)),
                   (axis_v.x,axis_v.y,axis_v.z,-axis_v.dot(origin)),
                   (normal.x,normal.y,normal.z,-normal.dot(origin)),
                   (0.,0.,0.,1.)))


def intersections(points, edge_ids, axes, tol):
    """Return edge parameters, including endpoint contacts and collinear overlaps."""
    cuts = [set() for _ in edge_ids]
    xy = [(p[axes[0]], p[axes[1]]) for p in points]
    events = 0
    for i, (ia, ib) in enumerate(edge_ids):
        a, b = xy[ia], xy[ib]
        r = sub2(b, a)
        rr = r[0] ** 2 + r[1] ** 2
        lr = math.sqrt(rr)
        if lr <= tol:
            raise RuntimeError('A zero-length edge needs cleanup before cutting.')
        for j in range(i + 1, len(edge_ids)):
            ja, jb = edge_ids[j]
            c, d = xy[ja], xy[jb]
            if any(max(a[k], b[k]) + tol < min(c[k], d[k]) or
                   max(c[k], d[k]) + tol < min(a[k], b[k]) for k in range(2)):
                continue
            s = sub2(d, c)
            ss = s[0] ** 2 + s[1] ** 2
            ls = math.sqrt(ss)
            if ls <= tol:
                raise RuntimeError('A zero-length edge needs cleanup before cutting.')
            ca = sub2(c, a)
            denom = cross2(r, s)
            hits = []
            if abs(denom) > 1e-12 * lr * ls:
                t, u = cross2(ca, s) / denom, cross2(ca, r) / denom
                if -tol/lr <= t <= 1 + tol/lr and -tol/ls <= u <= 1 + tol/ls:
                    hits.append((min(1., max(0., t)), min(1., max(0., u))))
            elif abs(cross2(ca, r)) <= tol * lr:
                # Split a collinear overlap at its endpoints, then remove duplicates.
                for t, p in ((0., a), (1., b)):
                    q = sub2(p, c)
                    u = (q[0] * s[0] + q[1] * s[1]) / ss
                    if -tol/ls <= u <= 1 + tol/ls:
                        hits.append((t, min(1., max(0., u))))
                for u, p in ((0., c), (1., d)):
                    q = sub2(p, a)
                    t = (q[0] * r[0] + q[1] * r[1]) / rr
                    if -tol/lr <= t <= 1 + tol/lr:
                        hits.append((min(1., max(0., t)), u))
            for t, u in hits:
                pa = points[ia].lerp(points[ib], t)
                pb = points[ja].lerp(points[jb], u)
                if (pa - pb).length > tol:
                    continue  # A projected crossing is not a true 3D intersection.
                if tol/lr < t < 1 - tol/lr:
                    cuts[i].add(t)
                if tol/ls < u < 1 - tol/ls:
                    cuts[j].add(u)
                events += 1
    return cuts, events


def topology(bm, edges=None, matrix=None):
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    return ([matrix @ v.co if matrix is not None else v.co.copy() for v in bm.verts],
            [(e.verts[0].index, e.verts[1].index)
             for e in (bm.edges if edges is None else edges)])


def verify_coverage(original_points, original_edges, final_points, final_edges, tol):
    """Confirm every original line segment is fully covered by resulting edges."""
    for ia, ib in original_edges:
        start, end = original_points[ia], original_points[ib]
        delta = end - start
        length = delta.length
        unit = delta / length
        intervals = []
        for ja, jb in final_edges:
            a, b = final_points[ja] - start, final_points[jb] - start
            ta, tb = a.dot(unit), b.dot(unit)
            if (a - unit * ta).length > tol * 2 or (b - unit * tb).length > tol * 2:
                continue
            lo, hi = sorted((ta, tb))
            if hi >= -tol and lo <= length + tol:
                intervals.append((max(0., lo), min(length, hi)))
        covered_to = 0.
        for lo, hi in sorted(intervals):
            if lo > covered_to + tol * 2:
                break
            covered_to = max(covered_to, hi)
        if covered_to < length - tol * 2:
            raise RuntimeError('Validation failed: part of an original outline was lost.')


def weld_selection(bm, vertices, protected, matrix, tol, keep_protected_pairs=False):
    """Weld selected vertices, retaining any endpoint used by unselected edges."""
    vertices = [v for v in bm.verts if v in vertices]
    tree = KDTree(len(vertices))
    positions = [matrix @ v.co for v in vertices]
    for i, p in enumerate(positions):
        tree.insert(p, i)
    tree.balance()
    parents = list(range(len(vertices)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, p in enumerate(positions):
        for _, j, _ in tree.find_range(p, tol):
            a, b = root(i), root(j)
            if a != b:
                parents[max(a, b)] = min(a, b)
    groups = {}
    for i, v in enumerate(vertices):
        groups.setdefault(root(i), []).append(v)
    targets = {}
    for group in groups.values():
        anchors = [v for v in group if v in protected]
        if len(anchors) > 1 and not keep_protected_pairs:
            raise RuntimeError('Welding this selection would also merge unselected geometry. '
                               'Include the connected edges in your selection and try again.')
        keeper = anchors[0] if anchors else group[0]
        targets.update((v, keeper) for v in group if v is not keeper and v not in anchors)
    if targets:
        bmesh.ops.weld_verts(bm, targetmap=targets)
    return len(targets)


def prepare_faces(obj, bm, source_faces, source_edges, guides=()):
    """Partition selected coplanar faces with Blender's exact 2D constraints."""
    if obj.data.shape_keys:
        raise RuntimeError('Meshes with shape keys are not supported.')
    if len(source_edges) > 5000:
        raise RuntimeError('This outline tool is limited to 5000 selected edges per object.')
    bm.normal_update()
    for items in (bm.verts, bm.edges, bm.faces):
        items.index_update()
    source_copy = bm.copy()
    try:
        source_copy.verts.ensure_lookup_table()
        source_copy.edges.ensure_lookup_table()
        source_copy.faces.ensure_lookup_table()
        before = {'vertices': len(bm.verts), 'edges': len(bm.edges), 'faces': len(bm.faces)}
        face_set, edge_set = set(source_faces), set(source_edges)
        vertices = list(dict.fromkeys(v for e in source_edges for v in e.verts))
        vertex_ids = {v: i for i, v in enumerate(vertices)}
        positions = [v.co.copy() for v in vertices]
        normal = max(source_faces, key=lambda f: f.calc_area()).normal.normalized()
        dominant = max(range(3), key=lambda k: abs(normal[k]))
        if all(abs(normal[k]) < 1e-5 for k in range(3) if k != dominant):
            sign = 1. if normal[dominant] >= 0 else -1.
            normal = Vector(tuple(sign if k == dominant else 0. for k in range(3)))
        origin = normal * (sum(p.dot(normal) for p in positions) / len(positions))
        reference = Vector((1.,0.,0.) if abs(normal.x) < .9 else (0.,1.,0.))
        axis_u = (reference - normal * reference.dot(normal)).normalized()
        axis_v = normal.cross(axis_u).normalized()
        if normal.length < .5 or axis_u.length < .5:
            raise RuntimeError('The selected faces have no usable area.')
        xy = [Vector(((p-origin).dot(axis_u), (p-origin).dot(axis_v))) for p in positions]
        scale = max(max(p[k] for p in xy) - min(p[k] for p in xy) for k in range(2))
        tol = max(scale * 2e-7, 1e-8)
        if any(abs((p-origin).dot(normal)) > tol for p in positions):
            raise RuntimeError('Selected faces must be coplanar for this circle-intersection tool.')
        edge_ids = [(vertex_ids[e.verts[0]], vertex_ids[e.verts[1]]) for e in source_edges]
        face_ids = [[vertex_ids[v] for v in f.verts] for f in source_faces]

        def area(ids, coords):
            return sum(coords[ids[i]].cross(coords[ids[(i+1) % len(ids)]]) for i in range(len(ids))) * .5

        face_ids = [ids if area(ids, xy) > 0 else list(reversed(ids)) for ids in face_ids]
        all_xy, all_edges, all_faces = list(xy), list(edge_ids), list(face_ids)
        face_weights = [max(1, f[bm.faces.layers.int[OVERLAP_FACE_ATTRIBUTE]]) for f in source_faces]
        inverse = obj.matrix_world.inverted()
        for guide in guides:
            offset = len(all_xy)
            local = [inverse @ Vector(p) for p in guide['vertices']]
            if any(abs((p-origin).dot(normal)) > tol*4 for p in local):
                raise RuntimeError('Selected objects must lie in the same plane for planar intersection cuts.')
            all_xy.extend(Vector(((p-origin).dot(axis_u),(p-origin).dot(axis_v))) for p in local)
            all_edges.extend((a+offset,b+offset) for a,b in guide['edges'])
            for ids, weight in zip(guide['faces'],guide['face_weights']):
                ids = [i+offset for i in ids]
                all_faces.append(ids if area(ids,all_xy)>0 else list(reversed(ids)))
                face_weights.append(weight)
        out_v, out_e, out_f, orig_v, orig_e, orig_f = delaunay_2d_cdt(all_xy, all_edges, all_faces, 4, tol, True)
        # Faces with no source face are empty spaces, not material to fill.
        # Guide-only regions stay in the other object, preserving object identity.
        kept_faces = [(f, ids) for f, ids in zip(out_f, orig_f) if any(i<len(source_faces) for i in ids)]
        face_edges = {tuple(sorted((f[i], f[(i+1) % len(f)])))
                      for f, _ in kept_faces for i in range(len(f))}
        kept_edges = [(e, ids) for e, ids in zip(out_e, orig_e)
                      if any(i < len(source_edges) for i in ids) or tuple(sorted(e)) in face_edges]
        used_output = {i for e, _ in kept_edges for i in e}
        outside_faces = {f: tuple(f.verts) for f in bm.faces if f not in face_set}
        protected_edges = {e: frozenset(e.verts) for e in bm.edges
                           if e not in edge_set or any(f not in face_set for f in e.link_faces)}
        protected = {v for v in bm.verts if v not in vertex_ids
                     or any(e in protected_edges for e in v.link_edges)
                     or any(f not in face_set for f in v.link_faces)}
        protected_positions = {v: v.co.copy() for v in protected}
        source_edge_copies = [source_copy.edges[e.index] for e in source_edges]
        pieces = [[] for _ in source_edges]
        for e, ids in kept_edges:
            for i in ids:
                if i < len(source_edges): pieces[i].append(e)
        output_vertices = {}
        for i in used_output:
            originals = [vertices[j] for j in orig_v[i] if j<len(vertices)]
            anchors = [v for v in originals if v in protected]
            if len(anchors) > 1:
                raise RuntimeError('This cut would merge unselected geometry. Include the adjoining faces first.')
            if originals:
                output_vertices[i] = anchors[0] if anchors else originals[0]
            else:
                vertex = bm.verts.new(origin + axis_u * out_v[i].x + axis_v * out_v[i].y)
                # Every introduced constraint vertex lies on an original edge.
                for j, (a, b) in enumerate(edge_ids):
                    d = xy[b] - xy[a]
                    t = (out_v[i] - xy[a]).dot(d) / d.length_squared
                    if -1e-6 <= t <= 1.000001 and (xy[a] + d*t - out_v[i]).length <= tol*2:
                        vertex.copy_from_vert_interp((vertices[a], vertices[b]), min(1., max(0., t)))
                        bm.verts.ensure_lookup_table()
                        vertex = bm.verts[-1]
                        break
                output_vertices[i] = vertex
        for i, e in enumerate(source_edges):
            if e in protected_edges:
                if len(pieces[i]) != 1 or frozenset(output_vertices[j] for j in pieces[i][0]) != protected_edges[e]:
                    raise RuntimeError('A cut crosses a boundary shared with an unselected face. '
                                       'Select the adjoining face too, then run again.')
        # Each original face must be covered exactly once by its partition.
        covered = [0.] * len(source_faces)
        for f, ids in kept_faces:
            size = abs(area(f, out_v))
            for i in ids:
                if i<len(source_faces): covered[i] += size
        for i, ids in enumerate(face_ids):
            if abs(covered[i] - abs(area(ids, xy))) > max(tol*scale*8, abs(area(ids, xy))*1e-4):
                raise RuntimeError(f'Validation failed: selected face {i} coverage {covered[i]:.9g} differs from {abs(area(ids, xy)):.9g}.')
        # Loop interpolation requires source and destination in the same BMesh.
        # Temporary disconnected source patches are removed before validation.
        copies = bmesh.ops.duplicate(bm, geom=vertices + source_edges + source_faces)
        interpolation_vertices = [copies['vert_map'][v] for v in vertices]
        source_face_copies = [copies['face_map'][f] for f in source_faces]
        for f in source_faces:
            bm.faces.remove(f)
        for e in source_edges:
            if e not in protected_edges:
                bm.edges.remove(e)
        result_edges = []
        for (a, b), ids in kept_edges:
            pair = (output_vertices[a], output_vertices[b])
            edge = bm.edges.get(pair)
            if edge is None:
                edge = bm.edges.new(pair)
                source_ids = [i for i in ids if i < len(source_edges)]
                if source_ids:
                    edge.copy_from(source_edge_copies[min(source_ids)])
                    edge = bm.edges.get(pair)
            if edge not in protected_edges:
                edge.select_set(True)
            result_edges.append(edge)
        result_faces = []
        for ids, face_origins in kept_faces:
            face = bm.faces.new([output_vertices[i] for i in ids])
            source_face = source_face_copies[min(face_origins)]
            face.copy_from(source_face)
            face = bm.faces.get([output_vertices[i] for i in ids])
            for loop in face.loops:
                loop.copy_from_face_interp(source_face, False)
            overlap_layer = bm.faces.layers.int[OVERLAP_FACE_ATTRIBUTE]
            face[overlap_layer] = max(len(face_origins), *(face_weights[i] for i in face_origins))
            face.select_set(True)
            result_faces.append(face)
        bmesh.ops.delete(bm, geom=interpolation_vertices, context='VERTS')
        kept_vertices = set(output_vertices.values())
        for v in vertices:
            if v not in kept_vertices and v not in protected and not v.link_edges and not v.link_faces:
                bm.verts.remove(v)
        # CDT coordinates and original 3D coordinates differ by float rounding.
        # Consolidate sub-tolerance slivers using the same protected anchors.
        scope_shared_edges = {e for e in result_edges if e in protected_edges}
        cleanup_welds = weld_selection(bm, kept_vertices, protected, Matrix.Identity(4), tol)
        result_edges = [e for e in bm.edges if e not in protected_edges or e in scope_shared_edges]
        result_faces = [f for f in bm.faces if f not in outside_faces]
        bm.normal_update()
        repair_splits = 0
        for attempt in range(3):
            final_points, final_edges = topology(bm, result_edges)
            flat = [Vector(((p-origin).dot(axis_u), (p-origin).dot(axis_v), 0.)) for p in final_points]
            pending, _ = intersections(flat, final_edges, (0, 1), tol)
            if not any(pending): break
            if attempt == 2:
                raise RuntimeError(f'Validation failed: {obj.name} still has uncut intersections after junction cleanup.')
            for edge, parameters in zip(result_edges,pending):
                if not parameters: continue
                if edge in protected_edges:
                    raise RuntimeError('A cut crosses an unselected face boundary; include the adjoining face.')
                start, end = edge.verts
                base, finish = start.co.copy(), end.co.copy()
                current, previous_t = edge, 0.
                for t in sorted(parameters):
                    if (t-previous_t)*(finish-base).length <= tol: continue
                    _, vertex = bmesh.utils.edge_split(current,start,(t-previous_t)/(1.-previous_t))
                    vertex.co = base.lerp(finish,t)
                    repair_splits += 1
                    current = next(e for e in vertex.link_edges if end in e.verts)
                    start, previous_t = vertex,t
            result_edges = [e for e in bm.edges if e not in protected_edges or e in scope_shared_edges]
            cleanup_welds += weld_selection(bm,{v for e in result_edges for v in e.verts},protected,Matrix.Identity(4),tol)
            result_edges = [e for e in bm.edges if e not in protected_edges or e in scope_shared_edges]
            result_faces = [f for f in bm.faces if f not in outside_faces]
            bm.normal_update()
        if any(not v.is_valid or v.co != co for v, co in protected_positions.items()):
            raise RuntimeError('Validation failed: an unselected vertex changed.')
        if any(not e.is_valid or frozenset(e.verts) != vs for e, vs in protected_edges.items()):
            raise RuntimeError('Validation failed: an unselected edge changed.')
        if any(not f.is_valid or tuple(f.verts) != vs for f, vs in outside_faces.items()):
            raise RuntimeError('Validation failed: an unselected face changed.')
        final_points, final_edges = topology(bm, result_edges)
        verify_coverage(positions, edge_ids, final_points, final_edges, tol)
        if any(len(e.link_faces) > 2 for e in result_edges if e not in protected_edges):
            raise RuntimeError('Validation failed: overlapping face layers remain.')
        selected_overlaps = select_overlap_faces(bm, result_faces)
        report = {'object': obj.name, 'scope': 'selected_faces_and_edges' if obj.mode == 'EDIT' else 'selected_object',
                  'method': 'coplanar_face_partition', 'before': before,
                  'after': {'vertices': len(bm.verts), 'edges': len(bm.edges), 'faces': len(bm.faces)},
                  'selected_faces_before': len(source_faces), 'selected_faces_after': len(result_faces),
                  'edge_splits': sum(max(0, len(p)-1) for p in pieces)+repair_splits,
                  'vertices_welded': sum(max(0,sum(i<len(vertices) for i in ids)-1) for ids in orig_v) + cleanup_welds,
                  'overlap_regions_resolved': sum(len(ids)>1 for _,ids in kept_faces),
                  'remaining_uncut_intersections': 0, 'unselected_geometry': 'unchanged',
                  'original_outline_coverage': 'complete', 'original_face_coverage': 'complete',
                  'uvs': 'interpolated_from_source_faces', 'unchanged': False}
        report.update(overlap_faces_selected=selected_overlaps, selection_mode='FACE',
                      other_selected_objects=[g['object'] for g in guides])
        return bm, report
    finally:
        source_copy.free()


def selection_signature(bm, obj, editing, guides=()):
    """Recognize a previously validated result only while geometry and scope match."""
    bm.verts.index_update()
    data = {'version': 5, 'guides': guides, 'wire_faces': WIRE_OVERLAPS_AS_FACES, 'matrix': [list(row) for row in obj.matrix_world], 'editing': editing,
            'vertices': [(tuple(v.co), v.hide, v.select if editing else True) for v in bm.verts],
            'edges': [(tuple(sorted(v.index for v in e.verts)), e.hide, e.select if editing else True) for e in bm.edges],
            'faces': [(tuple(v.index for v in f.verts), f.hide, f.select if editing else True) for f in bm.faces]}
    return hashlib.sha256(json.dumps(data, separators=(',', ':')).encode()).hexdigest()


def prepare(obj, guides=()):
    editing = obj.mode == 'EDIT'
    bm = bmesh.from_edit_mesh(obj.data).copy() if editing else bmesh.new()
    try:
        if not editing:
            bm.from_mesh(obj.data)
        if bm.faces.layers.int.get(OVERLAP_FACE_ATTRIBUTE) is None:
            bm.faces.layers.int.new(OVERLAP_FACE_ATTRIBUTE)
        if bm.edges.layers.int.get(OVERLAP_EDGE_ATTRIBUTE) is None:
            bm.edges.layers.int.new(OVERLAP_EDGE_ATTRIBUTE)
        if obj.data.get('_intersection_validated_selection') == selection_signature(bm, obj, editing, guides):
            counts = {'vertices': len(bm.verts), 'edges': len(bm.edges), 'faces': len(bm.faces)}
            return bm, {'object': obj.name, 'before': counts, 'after': counts.copy(), 'unchanged': True,
                        'edge_splits': 0, 'vertices_welded': 0, 'remaining_uncut_intersections': 0,
                        'selection_mode': obj.data.get('_intersection_selection_mode', 'EDGE'),
                        'overlap_faces_selected': sum(f.select and f[bm.faces.layers.int[OVERLAP_FACE_ATTRIBUTE]] >= 2 for f in bm.faces),
                        'overlap_edges_selected': sum(e.select and e[bm.edges.layers.int[OVERLAP_EDGE_ATTRIBUTE]] for e in bm.edges),
                        'reason': 'This geometry and selection were already cut and validated.'}
        source_faces = [f for f in bm.faces if not f.hide and (f.select or not editing)]
        if source_faces:
            face_edges = {e for f in source_faces for e in f.edges}
            selected_edges = [e for e in bm.edges if e in face_edges or
                              (not e.hide and not any(v.hide for v in e.verts) and (e.select or not editing))]
            return prepare_faces(obj, bm, source_faces, selected_edges, guides)
        # Adding CustomData can invalidate existing BMEdge Python references.
        scope = bm.edges.layers.int.new('_intersection_selection')
        source_edges = [e for e in bm.edges
                        if not e.hide and not any(v.hide for v in e.verts)
                        and (e.select or not editing)]
        before = {'vertices': len(bm.verts), 'edges': len(bm.edges), 'faces': len(bm.faces)}
        report = {'object': obj.name, 'scope': 'selected_edges' if editing else 'selected_object',
                  'before': before, 'selected_edges_before': len(source_edges),
                  'edge_splits': 0, 'vertices_welded': 0}
        if not source_edges:
            report.update(after=before.copy(), unchanged=True, reason='No selected visible edges.')
            return bm, report
        boundary_faces = {f for e in source_edges for f in e.link_faces}
        if len(source_edges) > 5000:
            raise RuntimeError('This small-outline tool is limited to 5000 selected edges per object.')
        if obj.data.shape_keys:
            raise RuntimeError('Meshes with shape keys are not supported.')
        matrix = obj.matrix_world.copy()
        points, edge_ids = topology(bm, source_edges, matrix)
        used_indices = set(i for pair in edge_ids for i in pair)
        source_points = [points[i] for i in used_indices]
        spans = [max(p[k] for p in source_points) - min(p[k] for p in source_points) for k in range(3)]
        tol = max(max(spans) * 1e-6, 1e-7)
        normal_axis = min(range(3), key=lambda k: spans[k])
        if spans[normal_axis] > tol:
            projection = wire_plane_projection(source_points, guides, tol)
            matrix = projection @ matrix
            points = [projection @ p for p in points]
            source_points = [points[i] for i in used_indices]
            guides = [{**g, 'vertices': [list(projection @ Vector(p)) for p in g['vertices']]} for g in guides]
            normal_axis = 2
        axes = [k for k in range(3) if k != normal_axis]
        combined_points, combined_edges, guide_faces = list(points), list(edge_ids), []
        for guide in guides:
            offset = len(combined_points)
            guide_points = [Vector(p) for p in guide['vertices']]
            depth = source_points[0][normal_axis]
            if any(abs(p[normal_axis]-depth)>tol*4 for p in guide_points):
                raise RuntimeError('Selected objects must lie in the same plane for planar intersection cuts.')
            combined_points.extend(guide_points)
            combined_edges.extend((a+offset,b+offset) for a,b in guide['edges'])
            guide_faces.extend([i+offset for i in face] for face in guide['faces'])
        attached_overlaps = overlapping_attached_faces(bm, boundary_faces, matrix, axes, tol, guides) if boundary_faces else set()
        wire_regions = wire_overlap_regions(combined_points, combined_edges, axes, tol, guide_faces) if not boundary_faces else None
        selected_set = set(source_edges)
        candidate_vertices = {v for e in source_edges for v in e.verts}
        protected = {v for v in bm.verts if v not in candidate_vertices or v.link_faces
                     or any(e not in selected_set for e in v.link_edges)}
        protected_positions = {v: v.co.copy() for v in protected}
        other_edges = {e: frozenset(e.verts) for e in bm.edges if e not in selected_set}
        other_edge_shapes = {e: [matrix @ v.co for v in e.verts] for e in other_edges}
        other_faces = {f: tuple(f.verts) for f in bm.faces}
        face_shapes = {f: ([matrix @ v.co for v in f.verts], f.calc_area()) for f in bm.faces}
        for e in source_edges:
            e[scope] = 1
        length_before = sum((points[b] - points[a]).length for a, b in edge_ids)
        cuts, _ = intersections(combined_points, combined_edges, axes, tol)
        cuts = cuts[:len(source_edges)]
        inserted = 0
        for edge, params in zip(source_edges, cuts):
            if not params:
                continue
            start, end = edge.verts
            base, finish = start.co.copy(), end.co.copy()
            edge_length = (matrix @ finish - matrix @ base).length
            previous_t = 0.
            current = edge
            for t in sorted(params):
                if (t - previous_t) * edge_length <= tol:
                    continue
                new_edge, new_vert = bmesh.utils.edge_split(current, start, (t - previous_t) / (1. - previous_t))
                new_edge[scope] = current[scope] = 1
                new_vert.co = base.lerp(finish, t)
                candidate_vertices.add(new_vert)
                inserted += 1
                current = next(e for e in new_vert.link_edges if end in e.verts)
                start, previous_t = new_vert, t
        welded = weld_selection(bm, candidate_vertices, protected, matrix, tol,
                                keep_protected_pairs=bool(boundary_faces))
        # Check actual element identities as well as coordinates: no outside
        # edge, face, or shared endpoint may be rebuilt, merged, or moved.
        if any(not v.is_valid or v.co != co for v, co in protected_positions.items()):
            raise RuntimeError('Validation failed: an unselected or shared vertex changed.')
        if boundary_faces:
            # Subdividing a selected face edge necessarily adds a corner to its
            # adjoining face. Check its surface, not the original corner count.
            for e, old_points in other_edge_shapes.items():
                if not e.is_valid or any(not any((matrix @ v.co-p).length <= tol*2 for v in e.verts) for p in old_points):
                    raise RuntimeError('Validation failed: an unselected edge was cut, removed, or moved.')
            for f, (old_points, old_area) in face_shapes.items():
                if (not f.is_valid or abs(f.calc_area()-old_area) > max(1e-9, old_area*1e-5)
                        or any(not any((matrix @ v.co-p).length <= tol*2 for v in f.verts) for p in old_points)):
                    raise RuntimeError('Validation failed: cutting the selected edges changed an adjoining face surface.')
        else:
            if any(not e.is_valid or frozenset(e.verts) != vs for e, vs in other_edges.items()):
                raise RuntimeError('Validation failed: an unselected edge changed.')
            if any(not f.is_valid or tuple(f.verts) != vs for f, vs in other_faces.items()):
                raise RuntimeError('Validation failed: an unselected face changed.')
        final_scope = [e for e in bm.edges if e[scope]]
        final_points, final_edges = topology(bm, final_scope, matrix)
        remaining, _ = intersections(final_points, final_edges, axes, tol)
        if any(remaining):
            raise RuntimeError('Validation failed: selected edges still have an uncut intersection.')
        final_indices = sorted(set(i for pair in final_edges for i in pair))
        anchored_indices = {v.index for v in protected if v.is_valid} if boundary_faces else set()
        for i, idx in enumerate(final_indices):
            if any((final_points[idx] - final_points[j]).length <= tol * .95
                   and not (idx in anchored_indices and j in anchored_indices) for j in final_indices[i + 1:]):
                raise RuntimeError('Validation failed: selected vertices remain unwelded.')
        lengths = [(final_points[b] - final_points[a]).length for a, b in final_edges]
        if any(length <= tol for length in lengths):
            raise RuntimeError('Validation failed: a selected zero-length edge remains.')
        if len({tuple(sorted(pair)) for pair in final_edges}) != len(final_edges):
            raise RuntimeError('Validation failed: duplicate selected edges remain.')
        length_after = sum(lengths)
        if length_after > length_before + tol * len(final_scope):
            raise RuntimeError('Validation failed: the operation extended the outline.')
        for p in source_points:
            if not any((p - final_points[i]).length <= tol * 2 for i in final_indices):
                raise RuntimeError('Validation failed: a selected vertex moved too far.')
        verify_coverage(points, edge_ids, final_points, final_edges, tol)
        if boundary_faces:
            layer = bm.faces.layers.int[OVERLAP_FACE_ATTRIBUTE]
            for f in attached_overlaps: f[layer] = max(2, f[layer])
            selected_count = select_overlap_faces(bm, boundary_faces)
            selection_report = {'selection_mode': 'FACE', 'overlap_faces_selected': selected_count,
                                'overlap_selection': 'existing faces with overlapping interiors'}
        else:
            selection_report = finish_wire_selection(bm, final_scope, wire_regions, axes, matrix, tol)
        final_edge_count = len(final_scope)
        bm.edges.layers.int.remove(scope)
        report.update(
            after={'vertices': len(bm.verts), 'edges': len(bm.edges), 'faces': len(bm.faces)},
            edge_splits=inserted, vertices_welded=welded,
            processed_edges_after=final_edge_count, selected_edges_after=sum(e.select for e in bm.edges), unselected_geometry='unchanged',
            remaining_uncut_intersections=0, original_outline_coverage='complete',
            length_before=length_before, length_after=length_after, tolerance_world_units=tol,
            unchanged=False)
        report.update(selection_report, other_selected_objects=[g['object'] for g in guides])
        if boundary_faces:
            report.update(method='selected_face_boundary_edges', adjoining_faces_preserved=len(boundary_faces),
                          unselected_geometry='edges unchanged; adjoining faces gain boundary vertices')
        return bm, report
    except Exception:
        bm.free()
        raise


def selected_geometry(obj):
    """Freeze all participants before any object is changed."""
    editing = obj.mode == 'EDIT'
    bm = bmesh.from_edit_mesh(obj.data).copy() if editing else bmesh.new()
    try:
        if not editing: bm.from_mesh(obj.data)
        faces = [f for f in bm.faces if not f.hide and (f.select or not editing)]
        face_edges = {e for f in faces for e in f.edges}
        edges = [e for e in bm.edges if e in face_edges or
                 (not e.hide and not any(v.hide for v in e.verts) and (e.select or not editing))]
        attached = list(dict.fromkeys(f for e in edges for f in e.link_faces if not f.hide))
        vertices = list(dict.fromkeys([v for e in edges for v in e.verts] + [v for f in attached for v in f.verts]))
        ids = {v:i for i,v in enumerate(vertices)}
        marker = bm.faces.layers.int.get(OVERLAP_FACE_ATTRIBUTE)
        return {'object': obj.name, 'vertices': [list(obj.matrix_world @ v.co) for v in vertices],
                'edges': [[ids[v] for v in e.verts] for e in edges],
                'faces': [[ids[v] for v in f.verts] for f in faces],
                'face_weights': [max(1,f[marker]) if marker else 1 for f in faces],
                'attached_faces': [[ids[v] for v in f.verts] for f in attached]}
    finally:
        bm.free()


def run(*, push_undo=True):
    ctx = bpy.context
    original_active = ctx.view_layer.objects.active
    if ctx.mode not in {'OBJECT', 'EDIT_MESH'}:
        raise RuntimeError('Use Object Mode or mesh Edit Mode.')
    was_edit = ctx.mode == 'EDIT_MESH'
    objects = list(ctx.objects_in_mode_unique_data if was_edit else ctx.selected_objects)
    objects = [o for o in objects if o.type == 'MESH' and o.visible_get()]
    if not objects:
        result = {'unchanged': True, 'reason': 'No visible mesh objects selected.', 'objects': []}
        print(json.dumps(result))
        return result
    dry_run = bool(globals().get('DRY_RUN', False))
    jobs, new_meshes = [], []
    edited_objects = list(ctx.objects_in_mode) if was_edit else []
    try:
        participants = {obj.name: selected_geometry(obj) for obj in objects}
        # Validate every object on private BMeshes before committing any change.
        for obj in objects:
            guides = [participants[o.name] for o in objects if o is not obj and participants[o.name]['edges']]
            bm, report = prepare(obj, guides)
            report['dry_run'] = dry_run
            targets = [o for o in edited_objects if o.data is obj.data] if was_edit else [obj]
            jobs.append((targets, bm, report))
        if not dry_run:
            for targets, bm, report in jobs:
                if report.get('unchanged'):
                    continue
                new_mesh = targets[0].data.copy()
                new_meshes.append((targets, new_mesh))
                new_mesh.name = targets[0].data.name + '_intersection_cuts'
                bm.to_mesh(new_mesh)
                new_mesh.update()
            if new_meshes:
                if push_undo and bpy.ops.ed.undo_push.poll():
                    bpy.ops.ed.undo_push(message='Before selected intersection cuts')
                if was_edit:
                    bpy.ops.object.mode_set(mode='OBJECT')
                selection_modes = {report.get('selection_mode') for _, _, report in jobs}
                if 'FACE' in selection_modes or 'EDGE' in selection_modes:
                    ctx.tool_settings.mesh_select_mode = (False, 'EDGE' in selection_modes, 'FACE' in selection_modes)
                try:
                    for targets, mesh in new_meshes:
                        for obj in targets:
                            obj.data = mesh
                finally:
                    if was_edit or selection_modes.intersection({'FACE','EDGE'}):
                        ctx.view_layer.objects.active = original_active if original_active in objects and original_active.select_get() else next(o for o in objects if o.select_get())
                        bpy.ops.object.mode_set(mode='EDIT')
                final_participants = {o.name: selected_geometry(o) for o in objects}
                for targets, mesh in new_meshes:
                    now_edit = targets[0].mode == 'EDIT'
                    current_bm = bmesh.from_edit_mesh(mesh) if now_edit else bmesh.new()
                    if not now_edit: current_bm.from_mesh(mesh)
                    final_guides = [final_participants[o.name] for o in objects if o is not targets[0] and final_participants[o.name]['edges']]
                    mesh['_intersection_validated_selection'] = selection_signature(current_bm, targets[0], now_edit, final_guides)
                    matching_report = next(report for job_targets, _, report in jobs if job_targets == targets)
                    mesh['_intersection_selection_mode'] = matching_report.get('selection_mode', 'EDGE')
                    if not now_edit: current_bm.free()
                if push_undo and bpy.ops.ed.undo_push.poll():
                    bpy.ops.ed.undo_push(message='Cut selected intersections')
                for area in ctx.screen.areas if ctx.screen else []:
                    area.tag_redraw()
        result = {'dry_run': dry_run, 'objects': [report for _, _, report in jobs]}
        print(json.dumps(result))
        return result
    finally:
        for _, bm, _ in jobs:
            bm.free()
        for _, mesh in new_meshes:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)


if __name__ == '__main__':
    run()
