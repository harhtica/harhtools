"""Match baked planes to evaluated geometry without requiring boundary loops."""
import math
import numpy as np
from mathutils import Matrix, Vector


def bounds(points):
    values = np.asarray(points, dtype=float)
    return values.min(axis=0), values.max(axis=0)


def frame(obj, points):
    """Keep object axes when useful; fit a plane when rotation was applied."""
    values = np.asarray(points, dtype=float)
    origin = (values.min(axis=0) + values.max(axis=0)) * .5
    inverse = obj.matrix_world.inverted_safe()
    local = np.asarray([tuple(inverse @ Vector(p)) for p in points])
    extent = np.ptp(local, axis=0)
    thin = int(np.argmin(extent))
    axes = [obj.matrix_world.to_3x3().col[i].normalized() for i in range(3)]
    if extent[thin] < max(extent) * .15:
        a, b = [i for i in range(3) if i != thin]
        u = axes[a]
        v = axes[b] - u * axes[b].dot(u)
        v.normalize()
        normal = u.cross(v).normalized()
    else:
        centered = values - values.mean(axis=0)
        _, vectors = np.linalg.eigh(centered.T @ centered)
        normal = Vector(vectors[:, 0])
        nearest = max(axes, key=lambda a: abs(a.dot(normal)))
        if normal.dot(nearest) < 0: normal.negate()
        projected = [a - normal * a.dot(normal) for a in axes]
        u = next(a.normalized() for a in projected if a.length > .25)
        v = normal.cross(u).normalized()
    basis = Matrix.Identity(4)
    for i, axis in enumerate((u, v, normal)):
        for j in range(3): basis[j][i] = axis[j]
    basis.translation = Vector(origin)
    return basis


def uv_mapping(obj):
    """Return an affine UV-to-world map for a rectangular baked surface."""
    if obj.type != 'MESH' or obj.modifiers or not obj.data.uv_layers.active:
        return None
    mesh = obj.data
    if not mesh.polygons or len({p.material_index for p in mesh.polygons}) != 1:
        return None
    uv = np.asarray([tuple(d.uv) for d in mesh.uv_layers.active.data], dtype=float)
    if len(uv) < 3: return None
    world = np.asarray([tuple(obj.matrix_world @ mesh.vertices[l.vertex_index].co) for l in mesh.loops])
    design = np.column_stack((uv, np.ones(len(uv))))
    mapping, _, rank, _ = np.linalg.lstsq(design, world, rcond=None)
    size = max(np.ptp(world, axis=0))
    if rank < 3 or size <= 1e-12 or np.max(np.abs(design @ mapping-world)) > size*1e-5:
        return None
    lo, hi = bounds(uv)
    area = 0.
    for poly in mesh.polygons:
        p = uv[list(poly.loop_indices)]
        area += abs(np.sum(p[:, 0]*np.roll(p[:, 1], -1)-p[:, 1]*np.roll(p[:, 0], -1)))*.5
    if abs(area-np.prod(hi-lo)) > max(area, 1e-12)*1e-5:
        return None
    return mapping, lo, hi


def alpha_region(obj, mapping):
    """Crop within this plane's UV island, never the entire texture atlas."""
    if mapping is None: return None, 'No rectangular UV mapping; using mesh bounds', None
    matrix, lo, hi = mapping
    slot = obj.data.polygons[0].material_index
    mat = obj.data.materials[slot] if slot < len(obj.data.materials) else None
    if not mat or not mat.use_nodes: return None, 'No alpha texture; using mesh bounds', None
    from .texture_connect import choose_shader
    try: shader = choose_shader(mat.node_tree)
    except ValueError: shader = None
    links = shader.inputs['Alpha'].links if shader else []
    if len(links) != 1 or links[0].from_node.type != 'TEX_IMAGE' or links[0].from_socket.name != 'Alpha':
        return None, 'No direct image alpha; using mesh bounds', None
    node = links[0].from_node
    image = node.image
    # Texture coordinate transforms need a different mapping; do not guess.
    vector_links = node.inputs['Vector'].links
    if vector_links:
        link = vector_links[0]
        uv_name = obj.data.uv_layers.active.name
        if not ((link.from_node.type == 'TEX_COORD' and link.from_socket.name == 'UV')
                or (link.from_node.type == 'UVMAP' and link.from_node.uv_map in {'', uv_name})):
            return None, 'Mapped texture coordinates; using mesh bounds', None
    if (not image or image.source not in {'FILE', 'GENERATED'} or image.channels != 4
            or image.alpha_mode in {'NONE', 'CHANNEL_PACKED'} or node.projection != 'FLAT'
            or np.any(lo < -1e-6) or np.any(hi > 1+1e-6)):
        return None, 'Alpha crop unavailable; using mesh bounds', None
    w, h = image.size
    if not w or not h or w*h > 16777216:
        return None, 'Alpha image unavailable or larger than 16 MP; using mesh bounds', None
    pixels = np.empty(w*h*4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    x0, y0 = np.maximum(0, np.floor(lo*(w,h)).astype(int))
    x1, y1 = np.minimum((w,h), np.ceil(hi*(w,h)).astype(int))
    crop = pixels.reshape(h,w,4)[y0:y1,x0:x1,3]
    ys, xs = np.nonzero(crop >= .5)
    if not len(xs): raise ValueError(f'{obj.name}: the UV crop is fully transparent; turn off Use Visible Alpha to fit its mesh.')
    lower = np.maximum(lo, ((x0+xs.min())/w, (y0+ys.min())/h))
    upper = np.minimum(hi, ((x0+xs.max()+1)/w, (y0+ys.max()+1)/h))
    points = [tuple(np.array((u,v,1.)) @ matrix)
              for u in (lower[0],upper[0]) for v in (lower[1],upper[1])]
    return points, 'Visible alpha within the plane UV crop', dict(mask=crop >= .5, size=(w,h), start=(x0,y0), mapping=matrix)


def alpha_points(obj, mapping):
    points, note, _ = alpha_region(obj, mapping)
    return points, note


def match_rotation(active, depsgraph, target_points, target_basis, source_basis,
                   source_points, region, proportional):
    """Register a planar alpha silhouette, including applied in-plane rotation.

    A small occupancy grid gives bounded cost independent of texture resolution.
    Only rotation is searched; every candidate still uses exact geometry bounds.
    """
    inv = target_basis.inverted()
    target = np.asarray([tuple(inv @ Vector(p))[:2] for p in target_points])
    low, high = bounds(target)
    size = high-low
    if min(size) < 1e-10: return target_basis, False
    resolution = 192
    step = max(size)/(resolution-4)
    center = (low+high)*.5
    start = center-step*resolution*.5
    coords = start[:,None] + (np.arange(resolution)+.5)*step
    xx, yy = np.meshgrid(coords[0], coords[1])
    grid = np.column_stack((xx.ravel(), yy.ravel()))
    mask = np.zeros((resolution,resolution),dtype=bool)
    evaluated = active.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
    finally:
        evaluated.to_mesh_clear()
    if not triangles or len(triangles) > 100000: return target_basis, False
    for indices in triangles:
        triangle = target[list(indices)]
        a,b,c = triangle
        area = np.cross(b-a,c-a)
        if abs(area) < 1e-14: continue
        p0 = np.maximum(0,np.floor((triangle.min(axis=0)-start)/step).astype(int))
        p1 = np.minimum(resolution,np.ceil((triangle.max(axis=0)-start)/step).astype(int))
        if np.any(p1 <= p0): continue
        gx = xx[p0[1]:p1[1],p0[0]:p1[0]]
        gy = yy[p0[1]:p1[1],p0[0]:p1[0]]
        inside = np.ones(gx.shape,dtype=bool)
        for one,two in ((a,b),(b,c),(c,a)):
            cross = (two[0]-one[0])*(gy-one[1])-(two[1]-one[1])*(gx-one[0])
            inside &= cross*np.sign(area) >= -1e-10
        mask[p0[1]:p1[1],p0[0]:p1[0]] |= inside
    reference = mask.ravel()
    if np.count_nonzero(reference) < 16: return target_basis, False
    si = source_basis.inverted()
    source = np.asarray([tuple(si @ Vector(p))[:2] for p in source_points])
    sl,sh = bounds(source); sc = (sl+sh)*.5; ss = sh-sl
    # Convert source-frame coordinates back to the original UV crop.
    mapping = region['mapping']
    uv_origin = np.array(si @ Vector(mapping[2]))[:2]
    uv_axes = np.column_stack([np.array(si.to_3x3() @ Vector(mapping[i]))[:2] for i in (0,1)])
    if abs(np.linalg.det(uv_axes)) < 1e-14: return target_basis, False
    uv_inverse = np.linalg.inv(uv_axes)
    alpha = region['mask']; w,h = region['size']; x0,y0 = region['start']
    def score(angle):
        c,s = math.cos(angle),math.sin(angle)
        rotation = np.array(((c,-s),(s,c)))
        rotated = target @ rotation
        lo,hi = bounds(rotated); scale = (hi-lo)/ss
        if proportional: scale[:] = min(scale)
        if min(scale) < 1e-12: return -1.
        source_grid = (grid @ rotation-(lo+hi)*.5)/scale+sc
        uv = (source_grid-uv_origin) @ uv_inverse.T
        x = np.floor(uv[:,0]*w).astype(int)-x0
        y = np.floor(uv[:,1]*h).astype(int)-y0
        valid = (x>=0)&(y>=0)&(x<alpha.shape[1])&(y<alpha.shape[0])
        occupied = np.zeros(len(grid),dtype=bool)
        occupied[valid] = alpha[y[valid],x[valid]]
        return np.count_nonzero(occupied&reference)/max(1,np.count_nonzero(occupied|reference))
    initial = score(0.)
    best, angle = initial, 0.
    for degrees in range(-180,180,5):
        trial = math.radians(degrees); value = score(trial)
        if value > best+1e-5: best,angle = value,trial
    for radius, increment in ((5.,1.),(1.,.2)):
        middle = angle
        for delta in np.arange(-radius,radius+increment*.5,increment):
            trial = middle+math.radians(float(delta)); value = score(trial)
            if value > best+1e-5: best,angle = value,trial
    # Ambiguous/noisy or unrelated silhouettes retain predictable object axes.
    if best < .35 or best < initial+.015: return target_basis, False
    return target_basis @ Matrix.Rotation(angle,4,'Z'), True


def solve(sources, active, depsgraph, proportional=False, use_alpha=True,
          align_rotation=True, depth='FRONT', offset=0.):
    from .fit_tool import object_points
    target_points = object_points(active, depsgraph)
    source_points, notes, mappings, regions = [], [], [], []
    for obj in sources:
        points = object_points(obj, depsgraph)
        mapping = uv_mapping(obj)
        mappings.append(mapping)
        region = None
        if use_alpha:
            visible, note, region = alpha_region(obj, mapping)
            if visible is not None: points = visible
            notes.append(note)
        regions.append(region)
        source_points.extend(points)
    target_basis = frame(active, target_points)
    if align_rotation:
        source_basis = frame(sources[0], object_points(sources[0], depsgraph))
        if mappings[0] is not None:
            matrix = mappings[0][0]
            u = Vector(matrix[0]).normalized()
            v = Vector(matrix[1]); v -= u*v.dot(u); v.normalize()
            for i, axis in enumerate((u,v,u.cross(v).normalized())):
                for j in range(3): source_basis[j][i] = axis[j]
    else:
        source_basis = target_basis.copy()
    if align_rotation and len(sources) == 1 and regions[0] is not None:
        target_basis, matched = match_rotation(active, depsgraph, target_points, target_basis, source_basis, source_points, regions[0], proportional)
        if matched: notes.append('Rotation matched to visible silhouette')
    source_inverse, target_inverse = source_basis.inverted(), target_basis.inverted()
    slo, shi = bounds([tuple(source_inverse @ Vector(p)) for p in source_points])
    tlo, thi = bounds([tuple(target_inverse @ Vector(p)) for p in target_points])
    ss, ts = shi-slo, thi-tlo
    if min(ss[:2]) <= 1e-10 or min(ts[:2]) <= 1e-10:
        raise ValueError('Both the bake and target need width and height to match.')
    factors = ts[:2]/ss[:2]
    if proportional: factors[:] = min(factors)
    if not all(math.isfinite(f) and 1e-8 < f < 1e8 for f in factors):
        raise ValueError('The requested scale is out of range.')
    sc, tc = (slo+shi)*.5, (tlo+thi)*.5
    # Put the plane on the side facing its previous position, not halfway
    # through a beveled mesh. Offset provides explicit control over depth.
    source_depth = (target_inverse @ Vector(np.mean(source_points, axis=0))).z
    side = 1 if source_depth >= tc[2] else -1
    destination = tc[2]
    if depth == 'FRONT': destination = thi[2] if side > 0 else tlo[2]
    elif depth == 'KEEP': destination = source_depth
    destination += side*offset
    scale = Matrix.Diagonal((float(factors[0]), float(factors[1]), 1., 1.))
    scale.translation = Vector((float(tc[0]-factors[0]*sc[0]), float(tc[1]-factors[1]*sc[1]), float(destination-sc[2])))
    transform = target_basis @ scale @ source_inverse
    return transform, tuple(factors), dict(notes=sorted(set(notes)), source_points=source_points,
        target_basis=target_basis, target_bounds=(tlo,thi))


def fit_selection(context, proportional=False, use_alpha=True, align_rotation=True, depth='FRONT', offset=0.):
    from .fit_tool import busy, apply_transform
    active = context.active_object
    selected = list(context.selected_objects)
    if context.mode != 'OBJECT' or active not in selected or len(selected) < 2:
        raise ValueError('Select the bake plane first, then the original geometry last.')
    if busy(): raise ValueError('Finish the active Harhtools tool before fitting.')
    if any(obj.type not in {'MESH','CURVE'} for obj in selected):
        raise ValueError('Select mesh or curve objects to match.')
    sources = [obj for obj in selected if obj != active]
    if any(not obj.is_editable for obj in sources): raise ValueError('The bake objects must be editable.')
    context.view_layer.update()
    transform, factors, info = solve(sources, active, context.evaluated_depsgraph_get(),
        proportional, use_alpha, align_rotation, depth, offset)
    apply_transform(context, sources, active, transform, proportional)
    return dict(count=len(sources), factors=factors, notes=info['notes'])
