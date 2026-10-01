"""Local, reusable shape presets. Assets live outside the extension installation."""

import hashlib
import json
import math
from pathlib import Path
import re
import struct
import tempfile
import time
from types import SimpleNamespace
import uuid
import zlib

import bpy
import bpy.utils.previews
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from mathutils import Matrix, Vector


_SCHEMA = 2
_PREVIEW_VERSION = 4
_SIZE = 128
_catalog = {}
_previews = None
_storage_override = None  # Isolated tests can supply their own directory.
last_error = ''
_DRAG_KEY = 'harhtools_shape_library_drag'
_last_row_click = None
_DRAG_CHOICES = [('IDLE', 'Idle', '', 0), ('DRAG', 'Drag Shape', 'Drag into the viewport to place a copy', 1)]
_drag_enum_items = {}
_pending_drag = None


def storage_directory():
    """Use Blender's shared user root, surviving both add-on and Blender updates."""
    if _storage_override is not None:
        return Path(_storage_override)
    # CONFIG is .../Blender/<version>/config on all supported desktop platforms.
    config = Path(bpy.utils.user_resource('CONFIG'))
    return config.parent.parent / 'harhtools' / 'shapes'


def _path(identifier, suffix='.json'):
    if not re.fullmatch(r'[0-9a-f]{32}', identifier):
        raise ValueError('Invalid shape preset identifier.')
    return storage_directory() / (identifier + suffix)


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.', suffix='.tmp', delete=False) as handle:
            temp = Path(handle.name)
            handle.write(data)
        temp.replace(path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def _write_asset(asset):
    _atomic_write(_path(asset['id']), json.dumps(asset, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def _validate(asset):
    if not isinstance(asset, dict) or asset.get('schema') not in {1, _SCHEMA}:
        raise ValueError('Unsupported shape preset format.')
    _path(asset.get('id', ''))
    if not isinstance(asset.get('name'), str) or not asset['name'].strip():
        raise ValueError('A shape preset needs a name.')
    if not isinstance(asset.get('created'), (int, float)) or not math.isfinite(asset['created']):
        raise ValueError('Invalid shape creation time.')
    vertices = asset.get('vertices', [])
    if not isinstance(vertices, list) or not vertices or len(vertices) > 2_000_000:
        raise ValueError('The shape preset has no usable geometry.')
    for vertex in vertices:
        if len(vertex) != 3 or any(not isinstance(x, (float, int)) or not math.isfinite(x) for x in vertex):
            raise ValueError('Invalid shape vertex.')
    for key, minimum in (('edges', 2), ('faces', 3)):
        elements = asset.get(key)
        if not isinstance(elements, list) or len(elements) > 4_000_000:
            raise ValueError('Invalid shape topology.')
        for face in elements:
            if len(face) < minimum or key == 'edges' and len(face) != 2:
                raise ValueError('Invalid shape topology.')
            if len(set(face)) != len(face) or any(type(i) is not int or i < 0 or i >= len(vertices) for i in face):
                raise ValueError('Invalid shape vertex index.')
    basis = asset.get('basis', [])
    if len(basis) != 3 or any(len(row) != 3 or any(not isinstance(x, (float, int)) or not math.isfinite(x) for x in row) for row in basis):
        raise ValueError('Invalid shape orientation.')
    kind = asset.get('object_type', 'MESH')
    if kind not in {'MESH', 'CURVE'}:
        raise ValueError('Unsupported shape object type.')
    if kind == 'CURVE':
        if asset['schema'] < 2:
            raise ValueError('Curve presets require the editable-curve format.')
        _validate_curve(asset.get('curve_data'))
    return asset


def _geometry_hash(asset):
    if asset.get('object_type') == 'CURVE':
        # The evaluated mesh is just a preview cache. Handles and spline settings
        # are the authoritative geometry, even if two curves look identical.
        geometry = {key: asset[key] for key in ('object_type', 'curve_data', 'basis')}
    else:
        # Keep schema-1 mesh hashes stable, including duplicate detection.
        geometry = {key: asset[key] for key in ('vertices', 'edges', 'faces', 'basis')}
    return hashlib.sha256(json.dumps(geometry, separators=(',', ':')).encode()).hexdigest()


_CURVE_SETTINGS = ('dimensions', 'resolution_u', 'render_resolution_u', 'fill_mode',
                   'twist_mode', 'twist_smooth', 'bevel_depth', 'bevel_resolution',
                   'extrude', 'offset', 'use_fill_caps', 'use_radius', 'use_stretch',
                   'use_deform_bounds', 'path_duration', 'use_path')
_SPLINE_SETTINGS = ('use_cyclic_u', 'resolution_u', 'order_u', 'use_endpoint_u',
                    'use_bezier_u', 'use_smooth', 'radius_interpolation',
                    'tilt_interpolation', 'material_index')
_HANDLE_TYPES = {'FREE', 'VECTOR', 'ALIGNED', 'AUTO', 'AUTO_CLAMPED'}


def _curve_payload(curve):
    """Store original editable splines; never infer handles from tessellation."""
    result = {'settings': {key: getattr(curve, key) for key in _CURVE_SETTINGS
                           if hasattr(curve, key)}, 'splines': []}
    for spline in curve.splines:
        item = {'type': spline.type,
                'settings': {key: getattr(spline, key) for key in _SPLINE_SETTINGS
                             if hasattr(spline, key) and (spline.type == 'NURBS'
                             or key not in {'order_u', 'use_endpoint_u', 'use_bezier_u'})}, 'points': []}
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        for point in points:
            record = {'co': list(point.co), 'tilt': point.tilt, 'radius': point.radius,
                      'weight_softbody': point.weight_softbody}
            if spline.type == 'BEZIER':
                record.update(handle_left=list(point.handle_left),
                              handle_right=list(point.handle_right),
                              handle_left_type=point.handle_left_type,
                              handle_right_type=point.handle_right_type)
            item['points'].append(record)
        result['splines'].append(item)
    return result


def _validate_curve(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('settings'), dict):
        raise ValueError('Invalid editable curve settings.')
    splines = payload.get('splines')
    if not isinstance(splines, list) or not splines or len(splines) > 100_000:
        raise ValueError('The curve preset has no usable splines.')
    def vector(value, size):
        return (isinstance(value, list) and len(value) == size
                and all(type(x) in {int, float} and math.isfinite(x) for x in value))
    def settings(values, allowed):
        if not isinstance(values, dict) or any(key not in allowed for key in values):
            raise ValueError('Invalid editable curve setting.')
        for value in values.values():
            if type(value) not in {bool, int, float, str} or isinstance(value, float) and not math.isfinite(value):
                raise ValueError('Invalid editable curve setting value.')
    settings(payload['settings'], _CURVE_SETTINGS)
    count = 0
    for spline in splines:
        if not isinstance(spline, dict) or spline.get('type') not in {'BEZIER', 'POLY', 'NURBS'}:
            raise ValueError('Unsupported editable spline type.')
        settings(spline.get('settings'), _SPLINE_SETTINGS)
        points = spline.get('points')
        if not isinstance(points, list) or not points:
            raise ValueError('The editable spline has no points.')
        count += len(points)
        if count > 2_000_000:
            raise ValueError('The editable curve has too many points.')
        for point in points:
            if not isinstance(point, dict) or not vector(point.get('co'), 3 if spline['type'] == 'BEZIER' else 4):
                raise ValueError('Invalid editable curve point.')
            for key in ('tilt', 'radius', 'weight_softbody'):
                value = point.get(key)
                if type(value) not in {int, float} or not math.isfinite(value):
                    raise ValueError('Invalid editable curve point property.')
            if spline['type'] == 'BEZIER':
                if (not vector(point.get('handle_left'), 3) or not vector(point.get('handle_right'), 3)
                        or point.get('handle_left_type') not in _HANDLE_TYPES
                        or point.get('handle_right_type') not in _HANDLE_TYPES):
                    raise ValueError('Invalid editable Bezier handle.')


def _restore_curve(name, payload):
    """Create an unlinked curve data block, cleaning up if a preset is invalid."""
    _validate_curve(payload)
    curve = bpy.data.curves.new(name, 'CURVE')
    try:
        for key, value in payload['settings'].items():
            if getattr(curve, key) != value:
                setattr(curve, key, value)
        for item in payload['splines']:
            spline = curve.splines.new(item['type'])
            points = spline.bezier_points if item['type'] == 'BEZIER' else spline.points
            points.add(len(item['points']) - 1)
            # Set all anchor positions before restoring any automatic handles.
            for point, record in zip(points, item['points']):
                if item['type'] == 'BEZIER':
                    point.handle_left_type = point.handle_right_type = 'FREE'
                point.co = record['co']
                for key in ('tilt', 'radius', 'weight_softbody'):
                    # Blender's soft-body default is 0 although its assignment
                    # range starts at .01. Leave exact defaults untouched.
                    if getattr(point, key) != record[key]:
                        setattr(point, key, record[key])
            for key, value in item['settings'].items():
                if getattr(spline, key) != value:
                    setattr(spline, key, value)
            if item['type'] == 'BEZIER':
                for point, record in zip(points, item['points']):
                    point.handle_left = record['handle_left']
                    point.handle_right = record['handle_right']
                for point, record in zip(points, item['points']):
                    point.handle_left_type = record['handle_left_type']
                    point.handle_right_type = record['handle_right_type']
        return curve
    except Exception:
        bpy.data.curves.remove(curve)
        raise


def _asset_from_object(obj, depsgraph=None):
    if obj is None or obj.type not in {'MESH', 'CURVE'}:
        raise ValueError('Select a mesh or curve to save.')
    if obj.mode == 'EDIT':
        obj.update_from_editmode()
    evaluated = obj.evaluated_get(depsgraph or bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        if mesh is None or not mesh.vertices:
            raise ValueError('The selected shape is empty.')
        asset = {
            'schema': _SCHEMA, 'id': uuid.uuid4().hex, 'name': obj.name[:80],
            'object_type': obj.type,
            'created': time.time(),
            'vertices': [list(v.co) for v in mesh.vertices],
            'edges': [list(e.vertices) for e in mesh.edges],
            'faces': [list(p.vertices) for p in mesh.polygons],
            'basis': [list(row) for row in obj.matrix_world.to_3x3()],
        }
        if obj.type == 'CURVE':
            asset['curve_data'] = _curve_payload(obj.data)
        asset['geometry_hash'] = _geometry_hash(asset)
        return asset
    finally:
        evaluated.to_mesh_clear()


def _preview_png(asset):
    """Rasterize an orthographic shape thumbnail with holes; no render scene needed."""
    basis = Matrix(asset['basis'])
    points = [basis @ Vector(co) for co in asset['vertices']]
    center = sum(points, Vector()) / len(points)
    relative = [p - center for p in points]
    longest = max(relative, key=lambda p: p.length_squared)
    u = longest.normalized() if longest.length_squared else Vector((1, 0, 0))
    cross = max((u.cross(p) for p in relative), key=lambda p: p.length_squared)
    normal = cross.normalized() if cross.length_squared > 1e-16 else Vector((0, 0, 1))
    # Planar presets face the camera. Their projected world-up keeps thumbnails
    # recognizable even when Shape Builder chose a diagonal local basis.
    if max(abs(p.dot(normal)) for p in relative) <= max(longest.length * 1e-5, 1e-6):
        if normal[max(range(3), key=lambda i: abs(normal[i]))] < 0:
            normal.negate()
        up = Vector((0, 0, 1)) if abs(normal.z) < .9 else Vector((0, 1, 0))
        v = (up - normal * up.dot(normal)).normalized()
        u = v.cross(normal).normalized()
    else:
        # An isometric view also makes saved non-planar meshes identifiable.
        u = Vector((.707107, -.707107, 0))
        v = Vector((.408248, .408248, .816497))
    xy = [(p.dot(u), p.dot(v)) for p in relative]
    min_x, max_x = min(p[0] for p in xy), max(p[0] for p in xy)
    min_y, max_y = min(p[1] for p in xy), max(p[1] for p in xy)
    scale = (_SIZE - 22) / max(max_x - min_x, max_y - min_y, 1e-9)
    xy = [((_SIZE - 1) / 2 + (x - (min_x + max_x) / 2) * scale,
           (_SIZE - 1) / 2 - (y - (min_y + max_y) / 2) * scale) for x, y in xy]
    # Supersampling the triangle fill/outline gives small previews clean edges.
    size = _SIZE * 2
    xy = [(x * 2, y * 2) for x, y in xy]
    # Genuine alpha lets the sidebar theme show through without imposing a
    # fixed-width checker tile when the user resizes Blender's sidebar.
    pixels = bytearray((0, 0, 0, 0) * (size * size))

    def pixel(x, y, color):
        if 0 <= x < size and 0 <= y < size:
            index = (y * size + x) * 4
            pixels[index:index + 4] = bytes((*color, 255))

    mesh = bpy.data.meshes.new('.harhtools_shape_thumbnail')
    try:
        mesh.from_pydata(asset['vertices'], asset['edges'], asset['faces'])
        mesh.calc_loop_triangles()
        for triangle in mesh.loop_triangles:
            coords = [xy[i] for i in triangle.vertices]
            y0 = max(0, math.ceil(min(y for x, y in coords)))
            y1 = min(size - 1, math.floor(max(y for x, y in coords)))
            for y in range(y0, y1 + 1):
                intersections = []
                for (ax, ay), (bx, by) in zip(coords, coords[1:] + coords[:1]):
                    if (ay <= y + .5 < by) or (by <= y + .5 < ay):
                        intersections.append(ax + (bx - ax) * (y + .5 - ay) / (by - ay))
                if len(intersections) >= 2:
                    for x in range(max(0, math.ceil(min(intersections) - .5)), min(size, math.ceil(max(intersections) - .5))):
                        pixel(x, y, (242, 184, 214))
        edge_users = {}
        for face in asset['faces']:
            for a, b in zip(face, face[1:] + face[:1]):
                edge = tuple(sorted((a, b)))
                edge_users[edge] = edge_users.get(edge, 0) + 1
        for a, b in asset['edges']:
            if edge_users.get(tuple(sorted((a, b))), 0) == 2:
                continue
            ax, ay = xy[a]; bx, by = xy[b]
            steps = max(1, math.ceil(math.hypot(bx - ax, by - ay)))
            for i in range(steps + 1):
                x, y = round(ax + (bx - ax) * i / steps), round(ay + (by - ay) * i / steps)
                for dx, dy in ((0, 0), (0, 1), (1, 0), (-1, 0), (0, -1)):
                    pixel(x + dx, y + dy, (255, 238, 247))
    finally:
        bpy.data.meshes.remove(mesh)

    raw = bytearray()
    for y in range(_SIZE):
        raw.append(0)
        for x in range(_SIZE):
            indices = [((y * 2 + dy) * size + x * 2 + dx) * 4 for dy in (0, 1) for dx in (0, 1)]
            alpha = sum(pixels[i + 3] for i in indices)
            # Average premultiplied samples, then return straight-alpha RGB.
            # This keeps the pale antialiased silhouette free of dark fringes.
            if alpha:
                raw.extend(sum(pixels[i + c] * pixels[i + 3] for i in indices) // alpha for c in range(3))
                raw.append(alpha // 4)
            else:
                raw.extend((0, 0, 0, 0))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', _SIZE, _SIZE, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))


def _load_preview(identifier):
    if _previews is None:
        return 0
    if identifier in _previews:
        return _previews[identifier].icon_id
    path = _path(identifier, '.png')
    if not path.exists():
        if not hasattr(bpy.data, 'meshes'):
            _schedule_preview_refresh()
            return 0
        _atomic_write(path, _preview_png(_catalog[identifier]))
    return _previews.load(identifier, str(path), 'IMAGE').icon_id


def _sync_items(context=None, selected=None):
    context = context or bpy.context
    wm = context.window_manager
    if not hasattr(wm, 'harhtools_shape_assets'):
        return
    old = selected or selected_identifier(context)
    wm.harhtools_shape_assets.clear()
    ordered = sorted(_catalog.values(), key=lambda a: (-float(a.get('created', 0)), a['name'].casefold()))
    for asset in ordered:
        item = wm.harhtools_shape_assets.add()
        item.identifier = asset['id']; item.name = asset['name']
    wm.harhtools_shape_asset_index = next((i for i, item in enumerate(wm.harhtools_shape_assets) if item.identifier == old), 0)
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def refresh_library(context=None):
    global last_error
    _catalog.clear()
    if _previews is not None:
        _previews.clear()
    last_error = ''
    directory = storage_directory()
    if directory.exists():
        failed = 0
        for path in directory.glob('*.json'):
            try:
                if path.stat().st_size > 128 * 1024 * 1024:
                    raise ValueError('Shape file exceeds the size limit.')
                asset = _validate(json.loads(path.read_text(encoding='utf-8')))
                if path.stem != asset['id']:
                    raise ValueError('Shape identifier does not match its file.')
                _catalog[asset['id']] = asset
            except (OSError, ValueError, TypeError, KeyError) as exc:
                failed += 1
                print(f'harhtools: skipped shape preset {path.name}: {exc}')
        if failed:
            last_error = f'{failed} unreadable preset(s) skipped.'
    rebuild_previews(context, force=False)
    _sync_items(context)
    return len(_catalog)


def _preview_refresh_timer():
    # Blender restricts bpy.data during the standard add-on enable/import path.
    # Mesh tessellation is safe after registration has returned to the event loop.
    if not hasattr(bpy.data, 'meshes'):
        return .1
    if _previews is not None:
        rebuild_previews(force=False)
    return None


def _schedule_preview_refresh():
    if not bpy.app.timers.is_registered(_preview_refresh_timer):
        bpy.app.timers.register(_preview_refresh_timer, first_interval=.01)


def rebuild_previews(context=None, force=True):
    """Refresh legacy thumbnails once; also callable immediately after a live update."""
    global last_error
    if not hasattr(bpy.data, 'meshes'):
        _schedule_preview_refresh()
        return 0
    rebuilt = 0
    for identifier, asset in _catalog.items():
        if not force and asset.get('preview_version') == _PREVIEW_VERSION and _path(identifier, '.png').exists():
            continue
        try:
            _atomic_write(_path(identifier, '.png'), _preview_png(asset))
            updated = dict(asset, preview_version=_PREVIEW_VERSION)
            _write_asset(updated)
            asset['preview_version'] = _PREVIEW_VERSION
            rebuilt += 1
        except Exception as exc:
            last_error = f'Could not refresh a shape thumbnail: {exc}'
            print('harhtools: ' + last_error)
    if rebuilt and _previews is not None:
        _previews.clear()
    _sync_items(context)
    return rebuilt


def capture_shape(obj, context=None):
    """Snapshot editable curves or meshes; repeated snapshots reuse the preset."""
    global last_error
    context = context or bpy.context
    asset = _asset_from_object(obj, context.evaluated_depsgraph_get())
    for previous in _catalog.values():
        if previous.get('geometry_hash') == asset['geometry_hash']:
            last_error = ''
            _sync_items(context, previous['id'])
            return previous['id']
    _atomic_write(_path(asset['id'], '.png'), _preview_png(asset))
    asset['preview_version'] = _PREVIEW_VERSION
    try:
        _write_asset(asset)
    except Exception:
        _path(asset['id'], '.png').unlink(missing_ok=True)
        raise
    _catalog[asset['id']] = asset
    last_error = ''
    _sync_items(context, asset['id'])
    return asset['id']


def capture_created_shape(obj, context=None):
    """A disk error must never discard a successfully built shape."""
    global last_error
    try:
        return capture_shape(obj, context)
    except Exception as exc:
        last_error = f'Shape created; preset could not be saved: {exc}'
        print('harhtools: ' + last_error)
        return None


def selected_identifier(context=None):
    wm = (context or bpy.context).window_manager
    items = getattr(wm, 'harhtools_shape_assets', [])
    index = getattr(wm, 'harhtools_shape_asset_index', 0)
    return items[index].identifier if 0 <= index < len(items) else ''


def insert_shape(identifier, context=None, location=None, rotation=None):
    context = context or bpy.context
    if context.mode != 'OBJECT':
        raise ValueError('Use Object Mode to insert a shape.')
    asset = _validate(_catalog[identifier])
    is_curve = asset.get('object_type') == 'CURVE'
    data = _restore_curve(asset['name'], asset['curve_data']) if is_curve else bpy.data.meshes.new(asset['name'])
    obj = None
    try:
        if not is_curve:
            data.from_pydata(asset['vertices'], asset['edges'], asset['faces'])
            data.update()
        obj = bpy.data.objects.new(asset['name'], data)
        basis = Matrix(asset['basis'])
        obj.matrix_world = ((rotation @ basis) if rotation is not None else basis).to_4x4()
        obj.matrix_world.translation = context.scene.cursor.location if location is None else Vector(location)
        collection = context.collection or context.scene.collection
        collection.objects.link(obj)
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        context.view_layer.update()
        return obj
    except Exception:
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            (bpy.data.curves if is_curve else bpy.data.meshes).remove(data)
        raise


def rename_shape(identifier, name, context=None):
    name = name.strip()[:80]
    if not name:
        raise ValueError('Give the shape a name.')
    asset = dict(_catalog[identifier], name=name)
    _write_asset(asset)
    _catalog[identifier] = asset
    _sync_items(context, identifier)


def remove_shape(identifier, context=None):
    # Presets are independent snapshots. Deleting one never touches scene objects.
    _path(identifier).unlink(missing_ok=True)
    _path(identifier, '.png').unlink(missing_ok=True)
    _catalog.pop(identifier, None)
    if _previews is not None and identifier in _previews:
        del _previews[identifier]
    _sync_items(context)


def _drag_allowed(context):
    return (context.mode == 'OBJECT' and context.window is not None
            and not bpy.app.driver_namespace.get('harhtools_array_preview')
            and not bpy.app.driver_namespace.get('arch_tools_shape_builder')
            and not bpy.app.driver_namespace.get(_DRAG_KEY) and _pending_drag is None)


def _start_drag(identifier, from_row=False):
    global _pending_drag
    context = bpy.context
    wm = context.window_manager
    for index, item in enumerate(wm.harhtools_shape_assets):
        if item.identifier == identifier:
            wm.harhtools_shape_asset_index = index
            break
    if identifier in _catalog and _drag_allowed(context):
        window, area, region = context.window, context.area, context.region
        def begin():
            global _pending_drag
            if _pending_drag is not begin:
                return None
            _pending_drag = None
            try:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.harhtools.shape_drag('INVOKE_DEFAULT', identifier=identifier, from_row=from_row)
            except (ReferenceError, RuntimeError):
                pass
            return None
        # Let the native property handler exit before installing a modal
        # handler. Starting inside its setter leaves that button latched.
        _pending_drag = begin
        bpy.app.timers.register(begin, first_interval=0.0)


def _item_drag_get(item):
    return 0


def _item_drag_choices(item, _context):
    try:
        icon_id = _load_preview(item.identifier)
    except Exception:
        icon_id = 0
    key = (item.identifier, icon_id)
    # Blender retains enum string pointers; hold these tuples for the session.
    if key not in _drag_enum_items:
        _drag_enum_items[key] = [('IDLE', 'Idle', '', 0, 0),
                                 ('DRAG', 'Drag Shape', 'Drag to place; double-click to rename', icon_id, 1)]
    return _drag_enum_items[key]


def _item_drag_set(item, value):
    # Native enum rows execute on PRESS; the placement modal handles release.
    if value:
        _start_drag(item.identifier, from_row=True)


def _selection_drag_get(_wm):
    return 0


def _selection_drag_set(_wm, value):
    if value:
        _start_drag(selected_identifier())


def _drag_geometry(asset):
    """Only CPU arrays for the ghost; no temporary scene object or selection."""
    basis = Matrix(asset['basis'])
    points = [basis @ Vector(vertex) for vertex in asset['vertices']]
    low = Vector(tuple(min(point[i] for point in points) for i in range(3)))
    high = Vector(tuple(max(point[i] for point in points) for i in range(3)))
    center = (low + high) * .5
    temporary = bpy.data.meshes.new('.harhtools_drag_tessellation')
    try:
        temporary.from_pydata(asset['vertices'], asset['edges'], asset['faces'])
        temporary.calc_loop_triangles()
        triangles = [tuple(triangle.vertices) for triangle in temporary.loop_triangles]
    finally:
        bpy.data.meshes.remove(temporary)
    # Preserve the full mesh on drop; bound only the number of preview primitives.
    if len(triangles) > 30000:
        triangles = triangles[::math.ceil(len(triangles) / 30000)]
    edges = asset['edges']
    if len(edges) > 24000:
        edges = edges[::math.ceil(len(edges) / 24000)]
    return points, center, triangles, edges


def _view_at_event(context, event):
    """Find the event window's viewport, rejecting overlapping sidebar/header UI."""
    window = context.window
    if not window:
        return None
    x, y = event.mouse_x, event.mouse_y
    for area in window.screen.areas:
        if area.type != 'VIEW_3D' or not (area.x <= x < area.x + area.width and area.y <= y < area.y + area.height):
            continue
        for region in area.regions:
            if region.type in {'UI', 'TOOLS', 'HEADER', 'TOOL_HEADER', 'HUD'} and region.width > 2 and region.height > 2:
                if region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                    return None
        region = next((region for region in area.regions if region.type == 'WINDOW'
                       and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height), None)
        if region:
            return window, area, region
    return None


def _placement_at_event(target, event, center):
    """Keep the visible center under the pointer on the 3D cursor's view plane."""
    from bpy_extras.view3d_utils import region_2d_to_location_3d
    window, area, region = target
    with bpy.context.temp_override(window=window, area=area, region=region):
        view = bpy.context.region_data or area.spaces.active.region_3d
        point = region_2d_to_location_3d(region, view,
                                       (event.mouse_x - region.x, event.mouse_y - region.y),
                                       window.scene.cursor.location)
    return point - center


def _frame_from_normal(normal, up=None):
    normal = Vector(normal).normalized()
    up = Vector(up) if up is not None else Vector((0, 0, 1))
    up -= normal * up.dot(normal)
    if up.length_squared < 1e-10:
        up = Vector((0, 1, 0)) if abs(normal.y) < .9 else Vector((1, 0, 0))
        up -= normal * up.dot(normal)
    up.normalize()
    right = up.cross(normal).normalized()
    return Matrix((right, normal.cross(right), normal)).transposed()


def _shape_frame(points, basis):
    """Use a flat shape's geometric plane, not Shape Builder's arbitrary axes."""
    center = sum(points, Vector()) / len(points)
    relative = [p - center for p in points]
    longest = max(relative, key=lambda p: p.length_squared)
    if longest.length_squared > 1e-16:
        cross = max((longest.cross(p) for p in relative), key=lambda p: p.length_squared)
        if cross.length_squared > 1e-16:
            normal = cross.normalized()
            if max(abs(p.dot(normal)) for p in relative) <= max(longest.length * 1e-4, 1e-6):
                # Stable facing for a planar shape even if its edge order flips.
                if normal[max(range(3), key=lambda i: abs(normal[i]))] < 0:
                    normal.negate()
                return _frame_from_normal(normal)
    # Solid assets retain their authored local up / forward orientation.
    return Matrix(basis).to_quaternion().to_matrix()


def _target_frame(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    matrix = evaluated.matrix_world
    if evaluated.type == 'MESH' and evaluated.data.vertices:
        vertices = evaluated.data.vertices
        stride = max(1, len(vertices) // 1024)
        points = [matrix.to_3x3() @ vertices[i].co for i in range(0, len(vertices), stride)]
        plane = _shape_frame(points, matrix.to_3x3())
        # The geometric normal handles wire guides in arbitrary local planes;
        # the reference object's authored Y axis retains its in-plane turn.
        return _frame_from_normal(plane.col[2], matrix.to_3x3() @ Vector((0, 1, 0)))
    return matrix.to_quaternion().to_matrix()


def _ray_plane(origin, direction, point, normal):
    denominator = direction.dot(normal)
    if abs(denominator) < 1e-7:
        return None
    distance = (point - origin).dot(normal) / denominator
    return origin + direction * distance


def _object_surface_hit(obj, depsgraph, origin, direction):
    evaluated = obj.evaluated_get(depsgraph)
    if evaluated.type != 'MESH' or not evaluated.data.polygons:
        return None
    matrix = evaluated.matrix_world
    inverse = matrix.inverted_safe()
    local_direction = inverse.to_3x3() @ direction
    if local_direction.length_squared < 1e-16:
        return None
    hit, point, normal, _index = evaluated.ray_cast(inverse @ origin, local_direction.normalized())
    if not hit:
        return None
    return matrix @ point, (inverse.transposed().to_3x3() @ normal).normalized(), obj


def _placement_sample(context, target, event, source_frame):
    """Pick a cursor, target plane, or visible surface without changing the scene."""
    from bpy_extras.view3d_utils import (region_2d_to_location_3d, region_2d_to_origin_3d,
                                        region_2d_to_vector_3d, location_3d_to_region_2d)
    window, area, region = target
    cfg = context.scene.harhtools_shape_placement
    with context.temp_override(window=window, area=area, region=region):
        view = context.region_data or area.spaces.active.region_3d
        mouse = Vector((event.mouse_x - region.x, event.mouse_y - region.y))
        identity = Matrix.Identity(3)
        if cfg.at_cursor:
            rotation = (context.scene.cursor.matrix.to_3x3().normalized() @ source_frame.transposed()
                        if cfg.align_rotation else identity)
            return context.scene.cursor.location.copy(), rotation, None, '3D cursor'
        origin = region_2d_to_origin_3d(region, view, mouse)
        direction = region_2d_to_vector_3d(region, view, mouse).normalized()
        depsgraph = context.evaluated_depsgraph_get()
        obj = cfg.target_object
        hit = None
        if obj is not None and obj.name in context.view_layer.objects:
            hit = _object_surface_hit(obj, depsgraph, origin, direction)
            frame = _target_frame(obj, depsgraph)
            # A wire object has no ray-castable faces. Its plane and origin still
            # make it useful as an explicit placement/alignment reference.
            if hit is None:
                point = _ray_plane(origin, direction, obj.matrix_world.translation, frame.col[2])
                if point is None:
                    point = region_2d_to_location_3d(region, view, mouse, obj.matrix_world.translation)
                hit = (point, frame.col[2], obj)
            projected = location_3d_to_region_2d(region, view, obj.matrix_world.translation)
            if projected is not None and (projected - mouse).length <= 16 * context.preferences.system.ui_scale:
                hit = (obj.matrix_world.translation.copy(), hit[1], obj)
        elif cfg.surface_snap:
            hit_result = context.scene.ray_cast(depsgraph, origin, direction)
            if hit_result[0]:
                _hit, point, normal, _face, hit_obj, _matrix = hit_result
                if hit_obj.visible_get(view_layer=context.view_layer):
                    hit = (point, normal, hit_obj)
        if hit is not None:
            point, normal, hit_obj = hit
            # Keep a consistent normal on a two-sided flat guide.
            if normal.dot(direction) > 0:
                normal = -normal
            reference = _target_frame(hit_obj, depsgraph)
            frame = _frame_from_normal(normal, reference.col[1])
            rotation = frame @ source_frame.transposed() if cfg.align_rotation else identity
            return point, rotation, normal, hit_obj.name
        point = region_2d_to_location_3d(region, view, mouse, context.scene.cursor.location)
        return point, identity, None, 'View plane'


def _rotation_from_drag(axis, start_x, current_x, initial, fine=False):
    angle = math.radians((current_x - start_x) * (.06 if fine else .6))
    if not fine:
        step = math.radians(15)
        snapped = round(angle / step) * step
        if abs(snapped - angle) < math.radians(3):
            angle = snapped
    return Matrix.Rotation(angle, 3, axis) @ initial, angle


def _placement_location(point, rotation, center, points, normal=None):
    """Center on the pointer, resting solid presets on a hovered surface."""
    point = Vector(point)
    if normal is not None:
        # Exact support, including mirrored/nonuniform saved scales.
        minimum = min((rotation @ (p - center)).dot(normal) for p in points)
        point -= normal * minimum
    return point - rotation @ center


def _double_click(identifier, context, event, now=None):
    if event.value == 'DOUBLE_CLICK':
        return True
    if _last_row_click is None:
        return False
    previous_id, previous_window, previous_time, x, y = _last_row_click
    delay = getattr(context.preferences.inputs, 'mouse_double_click_time', 350) / 1000.0
    current_time = time.monotonic() if now is None else now
    distance = math.hypot(event.mouse_x - x, event.mouse_y - y)
    return (previous_id == identifier and previous_window == context.window.as_pointer()
            and 0 <= current_time - previous_time <= delay
            and distance <= 8 * context.preferences.system.ui_scale)


@persistent
def cancel_drag(*_args):
    global _pending_drag
    if _pending_drag is not None:
        if bpy.app.timers.is_registered(_pending_drag):
            bpy.app.timers.unregister(_pending_drag)
        _pending_drag = None
    state = bpy.app.driver_namespace.get(_DRAG_KEY)
    if state:
        state.finish()


class HARHTOOLS_OT_shape_drag(bpy.types.Operator):
    bl_idname = 'harhtools.shape_drag'
    bl_label = 'Drag Shape into Viewport'
    bl_description = 'Drag into the viewport; release to place. X/Y/Z rotates with the mouse; Esc cancels'
    bl_options = {'UNDO', 'INTERNAL'}
    identifier: StringProperty(options={'HIDDEN'})
    from_row: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _drag_allowed(context)

    def invoke(self, context, event):
        global _last_row_click
        self._done = False
        self._handler = None
        self._hint_handler = None
        self._target = None
        self._location = None
        self._rotation = Matrix.Identity(3)
        self._auto_rotation = Matrix.Identity(3)
        self._user_rotation = Matrix.Identity(3)
        self._turn_axis = None
        self._turn_origin_x = event.mouse_x
        self._turn_initial = Matrix.Identity(3)
        self._point = None
        self._normal = None
        self._placement_label = 'View plane'
        self._hint = ''
        self._pointer = Vector((event.mouse_x, event.mouse_y))
        self._fill = None
        self._lines = None
        self._shader = None
        self._line_shader = None
        self._dragging = False
        self._release_pending = None
        self._release_timer = None
        self._origin_window = context.window
        self._workspace = context.workspace
        self._cursor_windows = {}
        self._start = Vector((event.mouse_x, event.mouse_y))
        self._rename_pending = self.from_row and _double_click(self.identifier, context, event)
        if self._rename_pending:
            _last_row_click = None
        try:
            asset = _validate(_catalog[self.identifier])
            self._points, self._center, self._triangles, self._edges = _drag_geometry(asset)
            self._source_frame = _shape_frame(self._points, asset['basis'])
            self._ghost_offset = max(1e-5, max((p-self._center).length for p in self._points) * 1e-5)
            bpy.app.driver_namespace[_DRAG_KEY] = self
            if not bpy.app.background:
                self._handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_preview, (), 'WINDOW', 'POST_VIEW')
                self._hint_handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_hint, (), 'WINDOW', 'POST_PIXEL')
            context.window.cursor_modal_set('HAND')
            self._cursor_windows[context.window.as_pointer()] = context.window
            self._status()
            context.window_manager.modal_handler_add(self)
            self._redraw()
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.finish()
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def _redraw(self):
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    def _status(self, angle=None):
        if self._turn_axis:
            degrees = math.degrees(angle or 0)
            self._hint = f'{self._turn_axis}  {degrees:.0f}°  ·  Shift: fine'
            text = f'Rotate {self._turn_axis}: {degrees:.0f}° | Move mouse | Shift: fine | {self._turn_axis}: move again'
        else:
            self._hint = f'{self._placement_label}  ·  X / Y / Z: rotate'
            text = f'{self._placement_label} | X / Y / Z: rotate | Release / Ctrl+A: place'
        self._workspace.status_text_set(text + ' | Esc / right-click: cancel')

    def update_pointer(self, context, event):
        global _last_row_click
        self._pointer = Vector((event.mouse_x, event.mouse_y))
        if not self._dragging:
            self._dragging = ((Vector((event.mouse_x, event.mouse_y)) - self._start).length
                              >= 5 * context.preferences.system.ui_scale)
        self._target = _view_at_event(context, event) if self._dragging else None
        if self._dragging:
            _last_row_click = None
            self._rename_pending = False
        self._location = None
        angle = None
        if self._target:
            if self._turn_axis and self._point is not None:
                self._user_rotation, angle = _rotation_from_drag(
                    self._turn_axis, self._turn_origin_x, event.mouse_x, self._turn_initial,
                    fine=getattr(event, 'shift', False))
            else:
                self._point, self._auto_rotation, self._normal, self._placement_label = _placement_sample(
                    context, self._target, event, self._source_frame)
            self._rotation = self._user_rotation @ self._auto_rotation
            self._location = _placement_location(self._point, self._rotation, self._center,
                                                  self._points, self._normal)
        self._status(angle)
        if context.window:
            self._cursor_windows[context.window.as_pointer()] = context.window
            context.window.cursor_modal_set('CROSSHAIR' if self._target else 'HAND')
        self._redraw()

    def modal(self, context, event):
        global _last_row_click
        from . import shortcuts
        if self._done:
            return {'CANCELLED'}
        if event.type in {'ESC', 'RIGHTMOUSE', 'WINDOW_DEACTIVATE'} and event.value in {'PRESS', 'NOTHING'}:
            self.finish()
            return {'CANCELLED'}
        if event.type == 'Z' and (event.ctrl or event.oskey) and event.value == 'PRESS':
            self.finish()
            return {'CANCELLED', 'PASS_THROUGH'}
        if event.type in {'X', 'Y', 'Z'} and event.value == 'PRESS' and self._target:
            if self._turn_axis == event.type:
                self._turn_axis = None
            else:
                self._turn_axis = event.type
                self._turn_initial = self._user_rotation.copy()
                self._turn_origin_x = event.mouse_x
            self.update_pointer(context, event)
            return {'RUNNING_MODAL'}
        finishing_release = False
        if self._release_pending is not None:
            if event.type != 'TIMER':
                return {'PASS_THROUGH'}
            event = self._release_pending
            self._release_pending = None
            context.window_manager.event_timer_remove(self._release_timer)
            self._release_timer = None
            finishing_release = True
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.update_pointer(context, event)
            return {'RUNNING_MODAL'}
        applying=shortcuts.confirm_event(event) and self._target is not None
        if (event.type == 'LEFTMOUSE' and event.value == 'RELEASE') or applying:
            if not applying and not finishing_release and not bpy.app.background:
                self._release_pending = SimpleNamespace(type=event.type, value=event.value,
                                                       mouse_x=event.mouse_x, mouse_y=event.mouse_y,
                                                       ctrl=event.ctrl, oskey=event.oskey, shift=event.shift)
                self._release_timer = context.window_manager.event_timer_add(.01, window=context.window)
                # Keep the drag guard until Blender releases the native button.
                # FINISHED|PASS_THROUGH is still handled by Blender; only plain
                # PASS_THROUGH lets the original release reach that button.
                return {'PASS_THROUGH'}
            self.update_pointer(context, event)
            if self._rename_pending and not self._dragging and not applying:
                self.finish()
                bpy.ops.harhtools.shape_rename('INVOKE_DEFAULT')
                return {'CANCELLED'}
            if not self._target or self._location is None or self.identifier not in _catalog:
                if self.from_row and not self._dragging:
                    _last_row_click = (self.identifier, context.window.as_pointer(), time.monotonic(),
                                       event.mouse_x, event.mouse_y)
                self.finish()
                return {'CANCELLED'}
            window, area, region = self._target
            try:
                with context.temp_override(window=window, area=area, region=region):
                    insert_shape(self.identifier, context, location=self._location, rotation=self._rotation)
            except Exception as exc:
                self.finish()
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            self.finish()
            return {'FINISHED'}
        # Navigation remains available while held; calculate placement again at
        # release so a view change cannot leave the committed object behind.
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}

    def draw_preview(self):
        if self._done or not self._target or self._location is None:
            return
        window, area, region = self._target
        context = bpy.context
        if (context.window != window or context.area != area or context.region != region):
            return
        import gpu
        from gpu_extras.batch import batch_for_shader
        from . import shortcuts
        if self._shader is None:
            self._shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            self._line_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
            if self._triangles:
                self._fill = batch_for_shader(self._shader, 'TRIS', {'pos': self._points}, indices=self._triangles)
            if self._edges:
                self._lines = batch_for_shader(self._line_shader, 'LINES', {'pos': self._points}, indices=self._edges)
        old_blend = gpu.state.blend_get()
        old_depth = gpu.state.depth_test_get()
        old_mask = gpu.state.depth_mask_get()
        try:
            gpu.state.blend_set('ALPHA')
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.depth_mask_set(False)
            cfg = shortcuts.settings(context)
            with gpu.matrix.push_pop():
                matrix = self._rotation.to_4x4()
                # Only the ghost gets a tiny surface offset, preventing flicker
                # against a coplanar target without moving the committed mesh.
                offset = (self._normal * self._ghost_offset
                          if self._normal is not None else Vector())
                matrix.translation = self._location + offset
                gpu.matrix.multiply_matrix(matrix)
                if self._fill:
                    self._shader.bind()
                    self._shader.uniform_float('color', (*cfg.accent_color, .16))
                    self._fill.draw(self._shader)
                if self._lines:
                    self._line_shader.bind()
                    self._line_shader.uniform_float('viewportSize', gpu.state.viewport_get()[2:])
                    self._line_shader.uniform_float('lineWidth', 1.4 * context.preferences.system.ui_scale)
                    self._line_shader.uniform_float('color', (*cfg.light_color, .85))
                    self._lines.draw(self._line_shader)
        finally:
            gpu.state.blend_set(old_blend)
            gpu.state.depth_test_set(old_depth)
            gpu.state.depth_mask_set(old_mask)

    def draw_hint(self):
        if self._done or not self._target or self._location is None:
            return
        window, area, region = self._target
        context = bpy.context
        if (context.window, context.area, context.region) != (window, area, region):
            return
        import blf
        from . import shortcuts
        scale = context.preferences.system.ui_scale
        blf.size(0, 12 * scale)
        width, _height = blf.dimensions(0, self._hint)
        x = max(8, min(region.width - width - 8, self._pointer.x - region.x + 16 * scale))
        y = max(12, min(region.height - 22, self._pointer.y - region.y - 26 * scale))
        blf.position(0, x, y, 0)
        blf.color(0, *shortcuts.settings(context).light_color, .95)
        blf.enable(0, blf.SHADOW)
        blf.shadow(0, 3, 0, 0, 0, .8)
        blf.draw(0, self._hint)
        blf.disable(0, blf.SHADOW)

    def finish(self):
        if getattr(self, '_done', False):
            return
        self._done = True
        if self._release_timer is not None:
            bpy.context.window_manager.event_timer_remove(self._release_timer)
            self._release_timer = None
        self._release_pending = None
        if self._handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handler, 'WINDOW')
            self._handler = None
        if self._hint_handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._hint_handler, 'WINDOW')
            self._hint_handler = None
        if bpy.app.driver_namespace.get(_DRAG_KEY) is self:
            bpy.app.driver_namespace.pop(_DRAG_KEY, None)
        for window in self._cursor_windows.values():
            try:
                window.cursor_modal_restore()
            except ReferenceError:
                pass
        try:
            self._workspace.status_text_set(None)
        except ReferenceError:
            pass
        self._target = None
        self._location = None
        self._fill = None
        self._lines = None
        self._redraw()

    def cancel(self, context):
        self.finish()


class HARHTOOLS_PG_shape_asset(bpy.types.PropertyGroup):
    identifier: StringProperty()
    drag: EnumProperty(name='Drag Shape', items=_item_drag_choices, description='Drag into the viewport to place; click to select; double-click to rename',
                       get=_item_drag_get, set=_item_drag_set, options={'SKIP_SAVE'})


class HARHTOOLS_PG_shape_placement(bpy.types.PropertyGroup):
    at_cursor: BoolProperty(name='Place at 3D Cursor', default=False,
        description='Keep the dragged shape centered at the 3D cursor; release in the viewport to place')
    target_object: PointerProperty(name='Lock to Object', type=bpy.types.Object,
        description='Use this object as the placement surface or wire plane; its origin attracts the pointer')
    align_rotation: BoolProperty(name='Align Rotation', default=True,
        description='Align the saved shape to the hovered surface, reference object, or 3D cursor orientation')
    surface_snap: BoolProperty(name='Surface Magnet', default=True,
        description='Follow visible surfaces automatically while dragging; empty space uses the view plane')


def _preview_selected(wm, context):
    # This independent list is a drag hitbox, not the catalog selection. Clear
    # its pressed selection immediately so no grey tile remains behind alpha.
    # The negative-index branch also guards the reset's recursive update.
    if wm.harhtools_shape_preview_index < 0:
        return
    wm.harhtools_shape_preview_index = -1
    identifier = selected_identifier(context)
    if identifier:
        _start_drag(identifier)


class HARHTOOLS_UL_shape_preview(bpy.types.UIList):
    """A native tall selection row makes the entire thumbnail a drag target."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        from . import icons
        column = layout.column(align=True)
        column.scale_y = 1 / 6
        column.label(text='', icon_value=icons.icon('grab'))
        row = column.row()
        row.alignment = 'CENTER'
        row.template_icon(icon_value=_load_preview(item.identifier), scale=5)

    def filter_items(self, context, data, propname):
        identifier = selected_identifier(context)
        return [self.bitflag_filter_item if item.identifier == identifier else 0
                for item in getattr(data, propname)], []

    def draw_filter(self, context, layout):
        pass


class HARHTOOLS_UL_shape_assets(bpy.types.UIList):
    def draw_filter(self, context, layout):
        pass  # Search is always visible above the list.

    def filter_items(self, context, data, propname):
        query = context.window_manager.harhtools_shape_search.strip().casefold()
        return [self.bitflag_filter_item if query in item.name.casefold() else 0
                for item in getattr(data, propname)], []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        try:
            icon_id = _load_preview(item.identifier)
        except Exception:
            icon_id = 0
        state = bpy.app.driver_namespace.get(_DRAG_KEY)
        if state and state._dragging and state.identifier == item.identifier:
            # Drop the native drag-toggle button only after real movement.
            # Its static stand-in preserves the row while Blender clears it.
            layout.label(text=item.name if self.layout_type != 'GRID' else '', icon_value=icon_id)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.prop_enum(item, 'drag', 'DRAG', text='')
        else:
            layout.prop_enum(item, 'drag', 'DRAG', text=item.name)


class HARHTOOLS_OT_shape_save(bpy.types.Operator):
    bl_idname = 'harhtools.shape_save'
    bl_label = 'Save Selected Shape'
    bl_description = 'Save the last selected mesh or curve in your reusable Shape Library'

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type in {'MESH', 'CURVE'}

    def execute(self, context):
        try:
            capture_shape(context.active_object, context)
        except Exception as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        return {'FINISHED'}


class HARHTOOLS_OT_shape_insert(bpy.types.Operator):
    bl_idname = 'harhtools.shape_insert'
    bl_label = 'Insert at Cursor'
    bl_description = 'Place an independent copy of this preset at the 3D cursor'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and bool(selected_identifier(context))
                and not bpy.app.driver_namespace.get('harhtools_array_preview')
                and not bpy.app.driver_namespace.get('arch_tools_shape_builder'))

    def execute(self, context):
        try:
            insert_shape(selected_identifier(context), context)
        except Exception as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        return {'FINISHED'}


class HARHTOOLS_OT_shape_rename(bpy.types.Operator):
    bl_idname = 'harhtools.shape_rename'
    bl_label = 'Rename Shape'
    shape_name: StringProperty(name='Name', maxlen=80)
    identifier: StringProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        self.identifier = selected_identifier(context)
        if self.identifier not in _catalog:
            return {'CANCELLED'}
        self.shape_name = _catalog[self.identifier]['name']
        return context.window_manager.invoke_props_dialog(self, width=280)

    def draw(self, context):
        self.layout.prop(self, 'shape_name', text='')

    def execute(self, context):
        try:
            rename_shape(self.identifier or selected_identifier(context), self.shape_name, context)
        except Exception as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        return {'FINISHED'}


class HARHTOOLS_OT_shape_remove(bpy.types.Operator):
    bl_idname = 'harhtools.shape_remove'
    bl_label = 'Delete Shape Preset'
    bl_description = 'Delete the selected library preset; existing scene objects stay unchanged'
    identifier: StringProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        self.identifier = selected_identifier(context)
        if not self.identifier:
            return {'CANCELLED'}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        try:
            remove_shape(self.identifier or selected_identifier(context), context)
        except Exception as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        return {'FINISHED'}


class HARHTOOLS_OT_shape_refresh(bpy.types.Operator):
    bl_idname = 'harhtools.shape_refresh'
    bl_label = 'Refresh Shape Library'
    bl_description = 'Reload your saved shapes from disk'

    def execute(self, context):
        refresh_library(context)
        return {'FINISHED'}


def draw_panel(layout, context):
    from . import icons, shortcuts
    wm = context.window_manager
    cfg = context.scene.harhtools_shape_placement
    box = shortcuts.section_box(layout, context, 'Shape Library', 'LIBRARY', group='TOOLS',
                                icon_value=icons.icon('library'))
    if box is None:
        return
    search = box.row()
    search.scale_y = shortcuts.CONTROL_HEIGHT
    search.prop(wm, 'harhtools_shape_search', text='', icon='VIEWZOOM')
    body = box.row(align=False)
    content = body.column(align=False)
    actions = body.column(align=False)
    actions.ui_units_x = 1.45
    actions.scale_y = shortcuts.CONTROL_HEIGHT
    actions.operator('harhtools.shape_save', text='', icon='ADD')
    actions.operator('harhtools.shape_rename', text='', icon='GREASEPENCIL')
    actions.operator('harhtools.shape_remove', text='', icon='TRASH')
    actions.separator(factor=.2)
    actions.operator('harhtools.shape_refresh', text='', icon='FILE_REFRESH')
    if not wm.harhtools_shape_assets:
        content.label(text='No saved shapes', icon='MESH_DATA')
    else:
        content.template_list('HARHTOOLS_UL_shape_assets', 'Library', wm, 'harhtools_shape_assets', wm,
                              'harhtools_shape_asset_index', rows=4, maxrows=4, sort_lock=True)
        identifier = selected_identifier(context)
        try:
            icon_id = _load_preview(identifier) if identifier else 0
        except Exception:
            icon_id = 0
        if icon_id:
            row = content.row()
            row.scale_y = 6
            row.ui_units_y = 9.5
            row.template_list('HARHTOOLS_UL_shape_preview', 'Preview', wm, 'harhtools_shape_assets', wm,
                              'harhtools_shape_preview_index', rows=1, maxrows=1, sort_lock=True)
            cursor = content.row()
            cursor.scale_y = shortcuts.CONTROL_HEIGHT
            cursor.prop(cfg, 'at_cursor', text='Place at 3D Cursor', icon='PIVOT_CURSOR', toggle=True)
    placement = shortcuts.section_box(box, context, 'Placement', 'LIBRARY_PLACEMENT')
    if placement is not None:
        target = placement.row()
        target.scale_y = shortcuts.CONTROL_HEIGHT
        target.enabled = not cfg.at_cursor
        target.label(text='Lock to Object')
        target.prop(cfg, 'target_object', text='')
        for name in ('align_rotation', 'surface_snap'):
            row = placement.row(align=False)
            if name == 'surface_snap':
                row.enabled = not cfg.at_cursor and cfg.target_object is None
            row.prop(cfg, name)
    if last_error:
        box.label(text='Some presets could not be saved or read.', icon='ERROR')


@persistent
def _load_post(_dummy):
    refresh_library()


_CLASSES = (HARHTOOLS_PG_shape_asset, HARHTOOLS_PG_shape_placement, HARHTOOLS_UL_shape_assets, HARHTOOLS_UL_shape_preview, HARHTOOLS_OT_shape_save, HARHTOOLS_OT_shape_drag,
            HARHTOOLS_OT_shape_insert, HARHTOOLS_OT_shape_rename, HARHTOOLS_OT_shape_remove,
            HARHTOOLS_OT_shape_refresh)


def register():
    global _previews
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.harhtools_shape_placement = PointerProperty(type=HARHTOOLS_PG_shape_placement)
    bpy.types.WindowManager.harhtools_shape_assets = CollectionProperty(type=HARHTOOLS_PG_shape_asset, options={'SKIP_SAVE'})
    bpy.types.WindowManager.harhtools_shape_asset_index = IntProperty(default=0, min=0, options={'SKIP_SAVE'})
    bpy.types.WindowManager.harhtools_shape_search = StringProperty(name='Search shapes', options={'SKIP_SAVE'})
    bpy.types.WindowManager.harhtools_shape_preview_index = IntProperty(default=-1, min=-1, update=_preview_selected, options={'SKIP_SAVE'})
    bpy.types.WindowManager.harhtools_shape_drag = EnumProperty(items=_DRAG_CHOICES,
        name='Drag to Place', description='Hold and drag into the viewport, then release to place a copy',
        get=_selection_drag_get, set=_selection_drag_set, options={'SKIP_SAVE'})
    _previews = bpy.utils.previews.new()
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if cancel_drag not in handlers:
            handlers.append(cancel_drag)
    refresh_library()


def unregister():
    global _previews, _last_row_click
    _last_row_click = None
    if bpy.app.timers.is_registered(_preview_refresh_timer):
        bpy.app.timers.unregister(_preview_refresh_timer)
    cancel_drag()
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if cancel_drag in handlers:
            handlers.remove(cancel_drag)
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    if hasattr(bpy.types.Scene, 'harhtools_shape_placement'):
        del bpy.types.Scene.harhtools_shape_placement
    for prop in ('harhtools_shape_assets', 'harhtools_shape_asset_index', 'harhtools_shape_drag', 'harhtools_shape_search', 'harhtools_shape_preview_index'):
        if hasattr(bpy.types.WindowManager, prop):
            delattr(bpy.types.WindowManager, prop)
    for cls in reversed(_CLASSES):
        if getattr(cls, 'is_registered', False):
            bpy.utils.unregister_class(cls)
    _catalog.clear()
    _drag_enum_items.clear()
