"""Temporary native array surfaces, sharing evaluated UVs and real materials."""
import uuid
import bpy

TAG = '_harhtools_array_preview'


def is_preview(obj):
    try: return bool(obj.get(TAG))
    except (ReferenceError, AttributeError): return False


def purge():
    """Undo can resurrect scratch IDs; never adopt them as user geometry."""
    for obj in tuple(getattr(bpy.data, 'objects', ())):
        if is_preview(obj): bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in tuple(getattr(bpy.data, 'meshes', ())):
        if is_preview(mesh) and mesh.users == 0: bpy.data.meshes.remove(mesh)
    for collection in tuple(getattr(bpy.data, 'collections', ())):
        if is_preview(collection) and not collection.objects and not collection.children:
            bpy.data.collections.remove(collection)


class MaterialPreview:
    def __init__(self, scene, space):
        self.scene = scene
        self.space = space
        self.meshes = []
        self.matrices = []
        self.colors = []
        self.objects = []
        self.collection = None
        self.ready = False
        self.token = uuid.uuid4().hex

    def clear_objects(self):
        self.ready = False
        for obj in self.objects:
            try: bpy.data.objects.remove(obj, do_unlink=True)
            except (ReferenceError, RuntimeError): pass
        self.objects.clear()
        if self.collection is not None:
            try: bpy.data.collections.remove(self.collection)
            except (ReferenceError, RuntimeError): pass
            self.collection = None

    def clear(self):
        self.clear_objects()
        for mesh in self.meshes:
            try:
                if mesh.users == 0: bpy.data.meshes.remove(mesh)
            except (ReferenceError, RuntimeError): pass
        self.meshes.clear(); self.matrices.clear(); self.colors.clear()

    def rebuild(self, context, snapshot):
        self.clear()
        depsgraph = context.evaluated_depsgraph_get()
        try:
            for source, matrix in zip(snapshot.sources, snapshot.matrices):
                evaluated = source.evaluated_get(depsgraph)
                mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
                self.meshes.append(mesh)
                mesh.name = 'Harhtools Array Preview Surface'
                mesh[TAG] = self.token
                # Object-linked material overrides must also survive evaluation.
                for i, slot in enumerate(evaluated.material_slots):
                    material = slot.material.original if slot.material else None
                    if i < len(mesh.materials): mesh.materials[i] = material
                    else: mesh.materials.append(material)
                self.matrices.append(matrix.copy())
                self.colors.append(tuple(source.color))
        except Exception:
            self.clear()
            raise

    def sync(self, frames, origin, inverse):
        """Reuse objects/meshes during tweening; no writes when poses settle."""
        poses = [(origin @ transform @ inverse @ matrix, color)
                 for transform, alpha in frames if alpha > .001
                 for matrix, color in zip(self.matrices, self.colors)]
        if not poses:
            self.clear_objects()
            return
        try:
            if self.collection is None:
                self.collection = bpy.data.collections.new('Harhtools Array Preview (temporary)')
                self.collection[TAG] = self.token
                self.collection.hide_render = True
                self.collection.hide_select = True
                self.scene.collection.children.link(self.collection)
            while len(self.objects) > len(poses):
                bpy.data.objects.remove(self.objects.pop(), do_unlink=True)
            while len(self.objects) < len(poses):
                i = len(self.objects)
                obj = bpy.data.objects.new('Array Preview', self.meshes[i % len(self.meshes)])
                obj[TAG] = self.token
                obj.hide_render = True
                obj.hide_select = True
                obj.show_in_front = False
                self.objects.append(obj)
                self.collection.objects.link(obj)
                if self.space.local_view: obj.local_view_set(self.space, True)
            for obj, (matrix, color) in zip(self.objects, poses):
                if obj.matrix_world != matrix: obj.matrix_world = matrix
                if tuple(obj.color) != color: obj.color = color
            self.ready = True
        except Exception:
            self.clear_objects()
            raise
