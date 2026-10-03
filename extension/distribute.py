"""Equal edge-to-edge gaps for objects and disconnected mesh pieces."""
from dataclasses import dataclass

import bpy
import bmesh
from bpy.props import EnumProperty, PointerProperty
from mathutils import Vector

from . import display_units


AXES = [('AUTO', 'Auto', 'Use the axis with the largest spread between pieces'),
        ('X', 'X', ''), ('Y', 'Y', ''), ('Z', 'Z', '')]
SPACES = [('WORLD', 'Global', 'Use world axes'),
          ('ACTIVE', 'Active', 'Use the active object axes')]
PARTS = [('ISLANDS', 'Disconnected Pieces', 'Treat each disconnected mesh island as a separate piece'),
         ('OBJECTS', 'Whole Objects', 'Keep all geometry inside each object together')]
ALIGNMENTS = [('CENTER', 'Center', 'Align piece centers to the selection bounds center'),
              ('MIN', 'Min Edge', 'Align the lowest edges'),
              ('MAX', 'Max Edge', 'Align the highest edges')]


@dataclass
class Piece:
    obj: object
    indices: tuple | None
    points: list
    bm: object = None

    @property
    def center(self):
        return Vector(tuple((min(p[i] for p in self.points) + max(p[i] for p in self.points)) / 2
                            for i in range(3)))


def components(count, edges):
    neighbors = [[] for _ in range(count)]
    for a, b in edges:
        neighbors[a].append(b)
        neighbors[b].append(a)
    seen = set()
    for start in range(count):
        if start in seen:
            continue
        seen.add(start)
        stack, found = [start], []
        while stack:
            index = stack.pop()
            found.append(index)
            for other in neighbors[index]:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        yield tuple(sorted(found))


def collect(context, parts='ISLANDS', minimum=3):
    edit = context.mode == 'EDIT_MESH'
    if context.mode not in {'OBJECT', 'EDIT_MESH'}:
        raise ValueError('Use Object Mode or Mesh Edit Mode.')
    objects = list(context.objects_in_mode_unique_data if edit else context.selected_objects)
    result = []
    dg = context.evaluated_depsgraph_get()
    for obj in objects:
        if not obj.is_editable:
            raise ValueError(f'{obj.name}: use a local, editable object.')
        matrix = obj.matrix_world.copy()
        if obj.type == 'MESH' and (edit or parts == 'ISLANDS'):
            bm = bmesh.from_edit_mesh(obj.data) if edit else None
            if bm:
                bm.verts.ensure_lookup_table()
                bm.verts.index_update()
                vertices = bm.verts
                edges = [tuple(v.index for v in e.verts) for e in bm.edges]
            else:
                vertices = obj.data.vertices
                edges = [tuple(e.vertices) for e in obj.data.edges]
            islands = list(components(len(vertices), edges))
            if edit or len(islands) > 1:
                for indices in islands:
                    if edit and not any(vertices[i].select and not vertices[i].hide for i in indices):
                        continue
                    result.append(Piece(obj, indices, [matrix @ vertices[i].co for i in indices], bm))
                continue
        evaluated = obj.evaluated_get(dg)
        points = []
        if obj.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
            mesh = evaluated.to_mesh()
            try:
                if mesh is not None:
                    points = [evaluated.matrix_world @ v.co for v in mesh.vertices]
            finally:
                evaluated.to_mesh_clear()
        if not points:
            points = [matrix.translation.copy()]
        result.append(Piece(obj, None, points))
    if len(result) < minimum:
        raise ValueError('Select at least three objects or disconnected pieces; the two end pieces stay fixed.'
                         if minimum == 3 else 'Select at least two objects or disconnected pieces to align.')
    if edit:
        # One shared edit mesh cannot receive different world-space movements.
        for piece in result:
            if sum(o.data == piece.obj.data for o in context.objects_in_mode) > 1:
                raise ValueError('Make linked edit objects single user before spacing their pieces.')
    return result


def axes(space, active):
    basis = [Vector(tuple(int(i == j) for i in range(3))) for j in range(3)]
    if space == 'ACTIVE' and active:
        basis = [(active.matrix_world.to_3x3() @ v).normalized() for v in basis]
    if any(v.length < .5 for v in basis):
        raise ValueError('The active object has zero scale; choose Global axes.')
    return basis


def plan(pieces, axis='AUTO', space='WORLD', active=None):
    basis = axes(space, active)
    centers = [p.center for p in pieces]
    spans = [max(c.dot(v) for c in centers) - min(c.dot(v) for c in centers) for v in basis]
    index = max(range(3), key=lambda i: spans[i]) if axis == 'AUTO' else 'XYZ'.index(axis)
    direction = basis[index]
    rows = sorted([(min(p.dot(direction) for p in piece.points),
                    max(p.dot(direction) for p in piece.points), order, piece)
                   for order, piece in enumerate(pieces)], key=lambda r: ((r[0] + r[1]) / 2, r[2]))
    if spans[index] < 1e-8:
        raise ValueError('The piece centers coincide on this axis; choose another axis.')
    gap = (rows[-1][1] - rows[0][0] - sum(hi - lo for lo, hi, _, _ in rows)) / (len(rows) - 1)
    cursor = rows[0][0]
    moves = []
    for i, (lo, hi, _, piece) in enumerate(rows):
        delta = 0.0 if i in {0, len(rows) - 1} else cursor - lo
        moves.append((piece, direction * delta))
        cursor += hi - lo + gap
    return moves, gap, 'XYZ'[index]


def _depth(obj):
    count = 0
    while obj.parent:
        count += 1
        obj = obj.parent
    return count


def apply(context, moves):
    """Translate only; preserve topology, UVs, keys, and unrelated linked users."""
    edit = context.mode == 'EDIT_MESH'
    objects = {piece.obj for piece, _ in moves}
    original_world = {obj: obj.matrix_world.copy() for obj in objects}
    original_basis = {obj: obj.matrix_basis.copy() for obj in objects}
    original_data = {obj: obj.data for obj in objects}
    # Preserve unselected children too when a whole parent object moves.
    descendants = set()
    for obj in objects:
        descendants.update(obj.children_recursive)
    untouched = descendants - objects
    child_world = {obj: obj.matrix_world.copy() for obj in untouched}
    child_basis = {obj: obj.matrix_basis.copy() for obj in untouched}
    inverses = {}
    for piece, _ in moves:
        if piece.indices is not None:
            try:
                inverses[piece.obj] = original_world[piece.obj].to_3x3().inverted()
            except ValueError:
                raise ValueError(f'{piece.obj.name}: cannot space pieces with zero object scale.')
            if not edit and not piece.obj.data.is_editable:
                raise ValueError(f'{piece.obj.name}: make the mesh data local first.')
    coord_backup, copies = {}, []
    changed = {piece.obj for piece, delta in moves if piece.indices is not None and delta.length > 1e-10}
    try:
        if not edit:
            for obj in changed:
                if obj.data.users > 1:
                    obj.data = obj.data.copy()
                    copies.append(obj.data)
        desired = {obj: matrix.copy() for obj, matrix in original_world.items()}
        for piece, delta in moves:
            obj = piece.obj
            if piece.indices is None:
                desired[obj].translation += delta
                continue
            if delta.length <= 1e-10:
                continue
            local_delta = inverses[obj] @ delta
            blocks = ([piece.bm.verts] if edit else [obj.data.vertices] +
                      ([block.data for block in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else []))
            for block_index, block in enumerate(blocks):
                for i in piece.indices:
                    vertex = block[i]
                    coord_backup[(obj, block_index, i)] = (vertex, vertex.co.copy())
                    vertex.co += local_delta
        if edit:
            for obj in changed:
                bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
        else:
            for obj in changed:
                obj.data.update()
            for obj in sorted(objects | untouched, key=_depth):
                matrix = desired[obj] if obj in desired else child_world[obj]
                if any(abs(obj.matrix_world[r][c] - matrix[r][c]) > 1e-8 for r in range(4) for c in range(4)):
                    obj.matrix_world = matrix
                    context.view_layer.update()
            # Transform constraints/drivers must not silently corrupt equal gaps.
            dg = context.evaluated_depsgraph_get()
            for obj, expected in {**desired, **child_world}.items():
                actual = obj.evaluated_get(dg).matrix_world
                if any(abs(actual[r][c] - expected[r][c]) > 2e-5 for r in range(4) for c in range(4)):
                    raise ValueError('A constraint or driver prevented spacing; no changes were kept.')
    except Exception:
        for vertex, co in coord_backup.values():
            vertex.co = co
        if not edit:
            for obj in objects:
                if obj.data != original_data[obj]:
                    obj.data = original_data[obj]
                obj.matrix_basis = original_basis[obj]
                if obj.type == 'MESH': obj.data.update()
            for obj, basis in child_basis.items(): obj.matrix_basis = basis
            for mesh in copies:
                if not mesh.users: bpy.data.meshes.remove(mesh)
            context.view_layer.update()
        else:
            for obj in changed: bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
        raise


def distribute(context, axis='AUTO', space='WORLD', parts='ISLANDS'):
    pieces = collect(context, parts)
    moves, gap, resolved = plan(pieces, axis, space, context.active_object)
    apply(context, moves)
    return len(pieces), gap, resolved


def align(context, axis='AUTO', space='WORLD', parts='ISLANDS', method='CENTER'):
    pieces = collect(context, parts, minimum=2)
    basis = axes(space, context.active_object)
    centers = [p.center for p in pieces]
    spans = [max(c.dot(v) for c in centers) - min(c.dot(v) for c in centers) for v in basis]
    main = max(range(3), key=lambda i: spans[i])
    indices = [i for i in range(3) if i != main] if axis == 'AUTO' else ['XYZ'.index(axis)]
    # A rotated/scaled parent may shear local axes. Solve for exact changes in
    # projected coordinates instead of summing non-orthogonal axis vectors.
    from mathutils import Matrix
    frame = Matrix(basis)
    try:
        inverse = frame.inverted()
    except ValueError:
        raise ValueError('The active object axes are degenerate; choose Global axes.')
    offsets = [Vector((0, 0, 0)) for _ in pieces]
    for index in indices:
        rows = [(min(v.dot(basis[index]) for v in p.points),
                 max(v.dot(basis[index]) for v in p.points)) for p in pieces]
        low, high = min(r[0] for r in rows), max(r[1] for r in rows)
        target = low if method == 'MIN' else high if method == 'MAX' else (low + high) / 2
        for offset, (lo, hi) in zip(offsets, rows):
            current = lo if method == 'MIN' else hi if method == 'MAX' else (lo + hi) / 2
            offset[index] = target - current
    apply(context, [(p, inverse @ delta) for p, delta in zip(pieces, offsets)])
    return len(pieces), '/'.join('XYZ'[i] for i in indices)


class HarhtoolsSpacingSettings(bpy.types.PropertyGroup):
    axis: EnumProperty(name='Axis', items=AXES, default='AUTO')
    space: EnumProperty(name='Axes', items=SPACES, default='WORLD')
    parts: EnumProperty(name='Space', items=PARTS, default='ISLANDS')
    alignment: EnumProperty(name='Align', items=ALIGNMENTS, default='CENTER')


class OBJECT_OT_harhtools_even_spacing(bpy.types.Operator):
    bl_idname = 'object.harhtools_even_spacing'
    bl_label = 'Distribute Even Gaps'
    bl_description = ('Equalize edge-to-edge gaps without resizing. Keep the first and last pieces fixed. '
                      'In Edit Mode, selecting any vertex moves its whole disconnected piece')
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(name='Axis', items=AXES, default='AUTO')
    space: EnumProperty(name='Axes', items=SPACES, default='WORLD')
    parts: EnumProperty(name='Space', items=PARTS, default='ISLANDS')

    @classmethod
    def poll(cls, context):
        return (context.mode in {'OBJECT', 'EDIT_MESH'} and context.active_object is not None
                and not any(bpy.app.driver_namespace.get(key) for key in
                            ('harhtools_array_preview', 'arch_tools_shape_builder',
                             'harhtools_outline_preview', 'harhtools_arc_preview')))

    def execute(self, context):
        try:
            count, gap, axis = distribute(context, self.axis, self.space, self.parts)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        amount = display_units.format_length(context, abs(gap))
        self.report({'INFO'}, f'{count} pieces spaced on {axis} | ' +
                    (f'Overlap {amount}' if gap < -1e-6 else f'Gap {amount}'))
        return {'FINISHED'}


class OBJECT_OT_harhtools_align_pieces(bpy.types.Operator):
    bl_idname = 'object.harhtools_align_pieces'
    bl_label = 'Align Pieces'
    bl_description = ('Align centers or edges without resizing. Auto straightens the row across its long axis. '
                      'Select X, Y or Z to align on a specific axis. Edit Mode moves whole disconnected pieces')
    bl_options = {'REGISTER', 'UNDO'}
    axis: EnumProperty(name='Axis', items=AXES, default='AUTO')
    space: EnumProperty(name='Axes', items=SPACES, default='WORLD')
    parts: EnumProperty(name='Space', items=PARTS, default='ISLANDS')
    alignment: EnumProperty(name='Align', items=ALIGNMENTS, default='CENTER')

    @classmethod
    def poll(cls, context):
        return OBJECT_OT_harhtools_even_spacing.poll(context)

    def execute(self, context):
        try:
            count, axis = align(context, self.axis, self.space, self.parts, self.alignment)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f'Aligned {count} pieces on {axis}')
        return {'FINISHED'}


def draw_panel(layout, context):
    cfg = context.window_manager.harhtools_spacing
    box = layout.box()
    box.label(text='Space / Align Pieces')
    if context.mode != 'EDIT_MESH': box.prop(cfg, 'parts')
    box.row(align=True).prop(cfg, 'axis', expand=True)
    box.row(align=True).prop(cfg, 'space', expand=True)
    row = box.row(); row.scale_y = 1.25
    op = row.operator('object.harhtools_even_spacing', icon='ALIGN_JUSTIFY')
    op.axis, op.space, op.parts = cfg.axis, cfg.space, cfg.parts
    box.label(text='Equal edge gaps; end pieces stay fixed.')
    box.prop(cfg, 'alignment')
    row = box.row(); row.scale_y = 1.25
    op = row.operator('object.harhtools_align_pieces', icon='ALIGN_CENTER')
    op.axis, op.space, op.parts, op.alignment = cfg.axis, cfg.space, cfg.parts, cfg.alignment
    if cfg.axis == 'AUTO': box.label(text='Auto Align straightens the row.')
    if context.mode == 'EDIT_MESH': box.label(text='Select any part of each disconnected piece.')


def register():
    bpy.utils.register_class(HarhtoolsSpacingSettings)
    bpy.types.WindowManager.harhtools_spacing = PointerProperty(type=HarhtoolsSpacingSettings)
    bpy.utils.register_class(OBJECT_OT_harhtools_even_spacing)
    bpy.utils.register_class(OBJECT_OT_harhtools_align_pieces)


def unregister():
    if OBJECT_OT_harhtools_align_pieces.is_registered: bpy.utils.unregister_class(OBJECT_OT_harhtools_align_pieces)
    if OBJECT_OT_harhtools_even_spacing.is_registered: bpy.utils.unregister_class(OBJECT_OT_harhtools_even_spacing)
    if hasattr(bpy.types.WindowManager, 'harhtools_spacing'): del bpy.types.WindowManager.harhtools_spacing
    if HarhtoolsSpacingSettings.is_registered: bpy.utils.unregister_class(HarhtoolsSpacingSettings)
