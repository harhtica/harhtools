"""Locally narrow sharp offsets while retaining ordinary source-to-offset quads.

Each source vertex keeps its own miter intersection. Stop before a competing
boundary or neighboring miter consumes its space; never merge or remove rows.
The source is immutable, so reducing the requested width restores full detail.
"""
import math

from . import outline_geometry as g


def build(prepared, thickness, direction):
    from . import outline_mesh as m
    thickness = float(thickness)
    direction = str(direction).upper()
    if direction not in {'INWARD', 'OUTWARD'}:
        raise ValueError('Direction must be INWARD or OUTWARD.')
    if not math.isfinite(thickness) or thickness <= 0:
        raise ValueError('Outline thickness must be positive and finite.')
    tolerance, epsilon = prepared['tolerance'], prepared['epsilon']
    if thickness <= 4*tolerance:
        raise ValueError(f'Thickness is below the current sampling precision. Use more than {4*tolerance:.6g} world units or prepare with a smaller tolerance.')
    sources = prepared['loops']
    sign = 1 if direction == 'INWARD' else -1
    tree = prepared.get('_segment_index')
    if tree is None:
        tree = prepared['_segment_index'] = g._SegmentIndex(sources)

    def competitors(a, b, width):
        query = (min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]))
        def nearby(bounds):
            dx = max(0, bounds[0]-query[1], query[0]-bounds[1])
            dy = max(0, bounds[2]-query[3], query[2]-bounds[3])
            return dx*dx + dy*dy <= width*width
        stack = [tree.root]
        while stack:
            bounds, rows, left, right = stack.pop()
            if not nearby(bounds):
                continue
            if rows is None:
                stack.extend((left, right))
            else:
                for row in rows:
                    if nearby(row) and g._segment_distance_sq(a, b, row[7], row[8]) <= width*width:
                        yield row[7], row[8]

    velocities, widths = [], []
    for source in sources:
        vectors, local_widths = [], []
        for i, point in enumerate(source):
            incoming = g._sub(point, source[i-1])
            outgoing = g._sub(source[(i+1) % len(source)], point)
            incoming = g._mul(incoming, 1/math.hypot(*incoming))
            outgoing = g._mul(outgoing, 1/math.hypot(*outgoing))
            denominator = 1 + g._dot(incoming, outgoing)
            if denominator <= 1e-12:
                raise ValueError('A doubled-back corner has no stable outline. Separate its coincident edges first.')
            velocity = g._mul((-incoming[1]-outgoing[1], incoming[0]+outgoing[0]), sign/denominator)
            # Look slightly past the request so near contacts retain a gap too.
            limit = thickness/.95
            end = g._add(point, g._mul(velocity, limit))
            stop = m._first_contact(point, velocity, limit, competitors(point, end, limit), epsilon)
            vectors.append(velocity)
            local_widths.append(min(thickness, .95*stop))
        # An inward turn can make neighboring miter rays cross even before
        # reaching a remote source edge. The two inner quad corner tests have
        # an exact linear bound on the opposite vertex's thickness.
        for i, point in enumerate(source):
            j = (i+1) % len(source)
            edge = g._sub(source[j], point)
            coefficient = sign*g._cross(vectors[j], vectors[i])
            if coefficient < 0:
                cap_i = .95*sign*g._cross(vectors[j], g._mul(edge, -1))/-coefficient
                cap_j = .95*sign*g._cross(edge, vectors[i])/-coefficient
                local_widths[i] = min(local_widths[i], cap_i)
                local_widths[j] = min(local_widths[j], cap_j)
        velocities.append(vectors)
        widths.append(local_widths)

    # Reflex corner fronts can meet each other sooner than they reach a source
    # segment. Narrow just the involved rows until all strip edges are clear.
    for iteration in range(32):
        offsets = [[g._add(p, g._mul(v, w)) for p, v, w in zip(source, vectors, local)]
                   for source, vectors, local in zip(sources, velocities, widths)]
        rows = []; base = 0
        def add_edge(a, b, p, q, moving):
            rows.append((min(p[0], q[0]), max(p[0], q[0]), min(p[1], q[1]), max(p[1], q[1]), a, b, p, q, moving))
        for k, (source, offset) in enumerate(zip(sources, offsets)):
            n = len(source)
            for i, p in enumerate(source):
                j = (i+1) % n
                add_edge(base+i, base+j, p, source[j], ())
                add_edge(base+n+i, base+n+j, offset[i], offset[j], ((k, i), (k, j)))
                add_edge(base+i, base+n+i, p, offset[i], ((k, i),))
            base += n*2
        crowded = set()
        for a, b in g._candidates(rows, epsilon):
            if set(a[4:6]) & set(b[4:6]):
                continue
            if g._segment_distance_sq(a[6], a[7], b[6], b[7]) <= epsilon*epsilon:
                crowded.update(a[8]); crowded.update(b[8])
        if not crowded:
            break
        for k, i in crowded:
            widths[k][i] *= .5
    else:
        raise ValueError('Unable to keep separate outline rows here. Reduce thickness.')
    g._validate_simple(offsets, epsilon, 'Unable to retain a clear inner outline at this thickness. Reduce thickness.')
    g._validate_simple(sources+offsets, epsilon, 'Outline boundaries touch. Reduce thickness.')
    for i, (source, offset) in enumerate(zip(sources, offsets)):
        if g._area(source)*g._area(offset) <= 0 or sign*(g._area(source)-g._area(offset)) <= 0:
            raise ValueError('Unable to retain the outline orientation. Reduce thickness.')
        if g._inside(offset[0], sources) != (direction == 'INWARD'):
            raise ValueError('Outline crossed its source boundary. Reduce thickness.')
        if sum(g._contains(offset[0], other) for j, other in enumerate(offsets) if i != j) != prepared['depths'][i]:
            raise ValueError('Outline crossed another boundary. Reduce thickness.')
    flat_widths = [w for local in widths for w in local]
    clamped = sum(w < thickness*(1-1e-10) for w in flat_widths)
    border = ([list(loop) for loop in sources] + [list(reversed(loop)) for loop in offsets]
              if direction == 'INWARD' else [list(loop) for loop in offsets] + [list(reversed(loop)) for loop in sources])
    return {'source_loops': sources, 'offset_loops': offsets, 'border_loops': border,
            'matrix_world': prepared['matrix_world'].copy(), 'thickness': thickness,
            'direction': direction, 'join_style': 'MITER', 'safe_inset': True,
            'local_widths': widths, 'offset_correspondence': [list(range(len(loop))) for loop in sources],
            'offset_trimmed': [False]*len(sources),
            'diagnostics': {'source_chord_error_bound': tolerance, 'round_join_chord_error_bound': 0.0,
                            'join_style': 'MITER', 'locally_clamped_vertices': clamped,
                            'minimum_actual_thickness': min(flat_widths), 'maximum_actual_thickness': max(flat_widths),
                            'source_loop_count': len(sources), 'offset_loop_count': len(offsets),
                            'poly_points': sum(map(len, border)), 'trimmed_offset_intersections': 0,
                            'topology_preserved': True, 'editable_type': 'POLY'}}
