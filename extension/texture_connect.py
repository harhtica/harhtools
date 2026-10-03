"""One-click, filename-based texture connections in the material Shader Editor."""
import re
import time

import bpy


ROLES = ('Base Color', 'Metallic', 'Roughness', 'Normal')
STATE_KEY = 'harhtools_texture_connect'
_ALIASES = {
    'Base Color': {'basecolor', 'basecolour', 'basecol', 'albedo', 'alb', 'diffuse', 'diff', 'diffcolor', 'diffusecolor', 'color', 'colour', 'col', 'bc'},
    'Metallic': {'metallic', 'metalness', 'metal', 'mtl'},
    'Roughness': {'roughness', 'rough', 'rgh'},
    'Normal': {'normal', 'normals', 'normalgl', 'normaldx', 'normalmap', 'nor', 'nrm', 'norm'},
}
_PACKED = {'orm', 'arm', 'rma', 'mra', 'metallicroughness', 'roughnessmetallic', 'occlusionroughnessmetallic'}


def role_from_name(name):
    """Recognize map suffixes, not arbitrary substrings in the material name."""
    name = str(name).replace('\\', '/').rsplit('/', 1)[-1]
    name = re.sub(r'\.\d{3}$', '', name)
    name = re.sub(r'\.[a-zA-Z]{2,5}$', '', name)
    compact = re.sub(r'[^a-z]', '', name.lower())
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    name = re.sub(r'([A-Z])([A-Z][a-z])', r'\1 \2', name)
    words = re.findall(r'[a-z]+', name.lower())
    if any(word in _PACKED for word in words) or any(compact.endswith(word) for word in _PACKED if len(word) > 3):
        return None
    matches = []
    for index, word in enumerate(words):
        if word in {'color', 'colour', 'col'} and index and words[index-1] == 'base':
            matches.append((index, 'Base Color'))
        for role, aliases in _ALIASES.items():
            if word in aliases:
                matches.append((index, role))
    return max(matches)[1] if matches else None


def texture_role(node):
    # A user label is an explicit override; the file name is otherwise primary.
    role = role_from_name(node.label) if node.label else None
    if role:
        return role
    image = node.image
    return role_from_name(image.filepath or image.name) if image else None


def shader_tree(context):
    space = getattr(context, 'space_data', None)
    if (space is None or space.type != 'NODE_EDITOR' or space.tree_type != 'ShaderNodeTree'
            or space.shader_type != 'OBJECT'):
        return None
    tree = space.edit_tree or space.node_tree
    if tree:
        return tree
    # A newly switched editor may not have resolved its tree until redraw.
    material = space.id if space.pin and isinstance(space.id, bpy.types.Material) else getattr(context, 'material', None)
    if material is None and not space.pin:
        obj = getattr(context, 'active_object', None)
        material = obj.active_material if obj else None
    return material.node_tree if material else None


def choose_shader(tree):
    shaders = [node for node in tree.nodes if node.bl_idname == 'ShaderNodeBsdfPrincipled']
    if tree.nodes.active in shaders:
        return tree.nodes.active
    selected = [node for node in shaders if node.select]
    if len(selected) == 1:
        return selected[0]
    if len(selected) > 1:
        raise ValueError('Select one Principled BSDF to receive the textures.')
    outputs = [node for node in tree.nodes if node.bl_idname == 'ShaderNodeOutputMaterial' and node.is_active_output]
    attached = {link.from_node for node in outputs for link in node.inputs['Surface'].links
                if link.from_node in shaders}
    if len(attached) == 1:
        return attached.pop()
    if len(shaders) > 1:
        raise ValueError('Select the Principled BSDF to receive the textures.')
    return shaders[0] if shaders else None


def _feeds_shader(node, shader, role):
    if shader is None:
        return False
    for link in node.outputs['Color'].links:
        if link.to_node == shader and link.to_socket == shader.inputs.get(role):
            return True
        if role == 'Normal' and link.to_node.bl_idname == 'ShaderNodeNormalMap' and link.to_socket.name == 'Color':
            if any(other.to_node == shader and other.to_socket == shader.inputs['Normal']
                   for other in link.to_node.outputs['Normal'].links):
                return True
    return False


def choose_textures(tree, shader):
    images = [node for node in tree.nodes if node.bl_idname == 'ShaderNodeTexImage' and node.image]
    maps = {}; unknown = []
    classified = [(node, texture_role(node)) for node in images]
    for node, role in classified:
        if role is None and (node.select or not node.outputs['Color'].is_linked):
            unknown.append(node)
    for role in ROLES:
        candidates = [node for node, found in classified if found == role]
        selected = [node for node in candidates if node.select]
        loose = [node for node in candidates if not node.outputs['Color'].is_linked]
        current = [node for node in candidates if _feeds_shader(node, shader, role)]
        choices = selected or loose or current
        if len(choices) > 1:
            raise ValueError(f'Multiple {role} textures: select the one to use and try again.')
        if choices:
            maps[role] = choices[0]
    if not maps:
        raise ValueError('Drop in Image Texture nodes named BaseColor/Albedo, Metallic, Roughness or Normal, then click Connect Textures.')
    return maps, unknown


def transparent_alpha(image):
    """Look for real transparency; an opaque RGBA image does not enable alpha.

    Chunked reads bound temporary memory even for large maps. File reads are
    deferred until this explicit button action, never performed by UI drawing.
    """
    if image.alpha_mode in {'NONE', 'CHANNEL_PACKED'} or image.source == 'TILED':
        return False
    pixels = image.pixels  # Loads an ordinary file image if necessary.
    count = len(pixels)
    if image.channels != 4 or not count:
        return False
    chunk = 65536
    for start in range(0, count, chunk):
        values = pixels[start:min(start+chunk, count)]
        if any(alpha < .99999 for alpha in values[3::4]):
            return True
    return False


def _normal_node(tree, image_node, shader):
    for link in image_node.outputs['Color'].links:
        if link.to_node.bl_idname == 'ShaderNodeNormalMap' and link.to_socket.name == 'Color':
            return link.to_node
    for link in shader.inputs['Normal'].links:
        node = link.from_node
        if node.bl_idname == 'ShaderNodeNormalMap' and all(other.to_node == shader
                for other in node.outputs['Normal'].links):
            return node
    node = tree.nodes.new('ShaderNodeNormalMap')
    node.location = (image_node.location.x+image_node.width+50, image_node.location.y)
    node.space = 'TANGENT'
    return node


def connect_textures(tree):
    """Connect one texture set transactionally; return the choices for reporting."""
    if tree.library or not tree.is_editable:
        raise ValueError('This shader is linked/read-only. Make its material local first.')
    shader = choose_shader(tree)
    maps, unknown = choose_textures(tree, shader)
    alpha = transparent_alpha(maps['Base Color'].image) if 'Base Color' in maps else False
    before_nodes = set(tree.nodes)
    before_links = [(link.from_socket, link.to_socket) for link in tree.links]
    before_images = {node: node.image for node in maps.values()}
    before_spaces = {image: image.colorspace_settings.name for image in before_images.values()}
    copies = []
    try:
        if shader is None:
            shader = tree.nodes.new('ShaderNodeBsdfPrincipled')
            shader.location = (max(node.location.x+node.width for node in maps.values())+400,
                               max(node.location.y for node in maps.values()))
            # Only a root material tree gets a Material Output. Nested shader
            # groups retain their own output connections and interface.
            if not any(node.bl_idname == 'NodeGroupOutput' for node in tree.nodes):
                outputs = [node for node in tree.nodes if node.bl_idname == 'ShaderNodeOutputMaterial']
                output = next((node for node in outputs if node.is_active_output), outputs[0] if outputs else None)
                if output is None:
                    output = tree.nodes.new('ShaderNodeOutputMaterial')
                    output.location = (shader.location.x+350, shader.location.y)
                tree.links.new(shader.outputs['BSDF'], output.inputs['Surface'])
        for role in maps:
            if shader.inputs.get(role) is None:
                raise ValueError(f'This Principled BSDF has no {role} input.')
        color_jobs = []
        for role, node in maps.items():
            if role != 'Base Color':
                color_jobs.append((node, 'Non-Color'))
            elif node.image.colorspace_settings.is_data:
                # Restore a color interpretation if a reused base image was
                # previously marked as data. Preserve existing color spaces.
                path = (node.image.filepath or node.image.name).lower()
                color_jobs.append((node, 'Linear Rec.709' if path.endswith(('.exr', '.hdr')) else 'sRGB'))
        jobs = {}
        for node, space in color_jobs:
            jobs.setdefault((node.image, space), []).append(node)
        for (image, space), nodes in jobs.items():
            if image.colorspace_settings.name == space:
                continue
            target = image
            if image.library or not image.is_editable or image.users > len(nodes):
                # Image color space is global: isolate this setup when another
                # material/texture also uses the same image datablock.
                target = image.copy(); copies.append(target)
                for node in nodes:
                    node.image = target
            target.colorspace_settings.name = space
        for role, node in maps.items():
            if role == 'Normal':
                normal = _normal_node(tree, node, shader)
                tree.links.new(node.outputs['Color'], normal.inputs['Color'])
                tree.links.new(normal.outputs['Normal'], shader.inputs['Normal'])
            else:
                tree.links.new(node.outputs['Color'], shader.inputs[role])
        if alpha:
            tree.links.new(maps['Base Color'].outputs['Alpha'], shader.inputs['Alpha'])
    except Exception:
        # A failed color-space assignment must not leave a partial node setup.
        for link in list(tree.links):
            tree.links.remove(link)
        for node in list(tree.nodes):
            if node not in before_nodes:
                tree.nodes.remove(node)
        for node, image in before_images.items():
            node.image = image
        for image, space in before_spaces.items():
            if image.colorspace_settings.name != space:
                image.colorspace_settings.name = space
        for image in copies:
            if image.users == 0:
                bpy.data.images.remove(image)
        for source, target in before_links:
            tree.links.new(source, target)
        raise
    return {'shader': shader, 'maps': maps, 'alpha': alpha, 'unknown': unknown}


def _position(node):
    result = node.location.copy()
    parent = node.parent
    while parent:
        result += parent.location
        parent = parent.parent
    return result


def _place(node, position):
    if node.parent:
        position = position-_position(node.parent)
    node.location = position


def layout_targets(result):
    """Texture rows follow shader input order, with converters in the middle."""
    shader = result['shader']; origin = _position(shader)
    targets = {}; y = origin.y+220
    for role in ROLES:
        node = result['maps'].get(role)
        if node is None:
            continue
        targets[node] = (origin.x-650, y)
        if role == 'Normal':
            normal = shader.inputs['Normal'].links[0].from_node
            targets[normal] = (origin.x-300, y)
        y -= max(300, node.dimensions.y)+45
    for link in shader.outputs['BSDF'].links:
        if link.to_node.bl_idname == 'ShaderNodeOutputMaterial' and link.to_socket.name == 'Surface':
            targets[link.to_node] = (origin.x+350, origin.y)
    return targets


def connection_steps(result):
    shader = result['shader']; steps = []
    for role in ROLES:
        node = result['maps'].get(role)
        if node is None:
            continue
        links = []
        if role == 'Normal':
            normal = shader.inputs['Normal'].links[0].from_node
            links.extend(((node.outputs['Color'], normal.inputs['Color']),
                          (normal.outputs['Normal'], shader.inputs['Normal'])))
        else:
            links.append((node.outputs['Color'], shader.inputs[role]))
        if role == 'Base Color' and result['alpha']:
            links.append((node.outputs['Alpha'], shader.inputs['Alpha']))
        steps.append(links)
    steps.append([(link.from_socket, link.to_socket) for link in shader.outputs['BSDF'].links
                  if link.to_node.bl_idname == 'ShaderNodeOutputMaterial'])
    return steps


def _snapshot(tree):
    return dict(nodes=set(tree.nodes), links=[(link.from_socket, link.to_socket) for link in tree.links],
                positions={node: node.location.copy() for node in tree.nodes},
                images={node: node.image for node in tree.nodes if node.bl_idname == 'ShaderNodeTexImage'},
                spaces={node.image: node.image.colorspace_settings.name for node in tree.nodes
                        if node.bl_idname == 'ShaderNodeTexImage' and node.image}, active=tree.nodes.active)


def _restore_links(tree, links):
    for link in list(tree.links):
        tree.links.remove(link)
    for source, target in links:
        tree.links.new(source, target)


def _restore(tree, snapshot):
    copies = {node.image for node in snapshot['images'] if node.image and node.image != snapshot['images'][node]}
    for link in list(tree.links):
        tree.links.remove(link)
    for node in list(tree.nodes):
        if node not in snapshot['nodes']:
            tree.nodes.remove(node)
    for node, image in snapshot['images'].items():
        node.image = image
    for image, space in snapshot['spaces'].items():
        if image.colorspace_settings.name != space:
            image.colorspace_settings.name = space
    for image in copies:
        if image.users == 0:
            bpy.data.images.remove(image)
    for node, position in snapshot['positions'].items():
        node.location = position
    tree.nodes.active = snapshot['active']
    _restore_links(tree, snapshot['links'])


def frame_setup(context, result):
    """Fit the finished setup in the editor while preserving node selection."""
    if context.area is None:
        return
    space = context.space_data
    if (space.edit_tree or space.node_tree) != result['shader'].id_data:
        return
    tree = result['shader'].id_data
    nodes = set(result['maps'].values()) | {result['shader']} | set(layout_targets(result))
    selected = {node: node.select for node in tree.nodes}
    try:
        for node in tree.nodes:
            node.select = node in nodes
        region = next((region for region in context.area.regions if region.type == 'WINDOW'), None)
        if region:
            with context.temp_override(region=region):
                if bpy.ops.node.view_selected.poll():
                    bpy.ops.node.view_selected()
    finally:
        for node, value in selected.items():
            node.select = value


class NODE_OT_harhtools_connect_textures(bpy.types.Operator):
    bl_idname = 'node.harhtools_connect_textures'
    bl_label = 'Connect Textures'
    bl_description = ('Arrange and connect named BaseColor/Albedo, Metallic, Roughness and Normal textures to Principled BSDF; '
                      'set data maps to Non-Color and connect transparent base-color alpha. Select maps to resolve duplicates')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        tree = shader_tree(context)
        return bool(tree and tree.is_editable and not tree.library and not bpy.app.driver_namespace.get(STATE_KEY))

    def execute(self, context):
        tree = shader_tree(context)
        before = _snapshot(tree)
        try:
            result = connect_textures(tree)
            from mathutils import Vector
            for node, position in layout_targets(result).items():
                _place(node, Vector(position))
        except Exception as exc:
            _restore(tree, before)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        frame_setup(context, result)
        self._report(result)
        return {'FINISHED'}

    def _report(self, result):
        labels = list(result['maps']) + (['Alpha'] if result['alpha'] else [])
        message = 'Connected '+', '.join(labels)+' to '+result['shader'].name
        if result['unknown']:
            message += f' | Skipped {len(result["unknown"])} unrecognized/packed map(s)'
        self.report({'INFO'}, message)

    def invoke(self, context, event):
        from mathutils import Vector
        self._tree = shader_tree(context)
        self._before = _snapshot(self._tree)
        self._timer = None
        try:
            self._result = connect_textures(self._tree)
            self._targets = {node: Vector(position) for node, position in layout_targets(self._result).items()}
            self._starts = {node: _position(node) for node in self._targets}
            self._steps = connection_steps(self._result)
            _restore_links(self._tree, self._before['links'])
            self._connected = 0
            self._start = time.perf_counter()
            self._area = context.area
            self._timer = context.window_manager.event_timer_add(1/60, window=context.window)
            bpy.app.driver_namespace[STATE_KEY] = self
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception as exc:
            _restore(self._tree, self._before)
            self._cleanup(context)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def _tick(self, progress):
        for index, (node, target) in enumerate(self._targets.items()):
            amount = max(0., min(1., progress*1.35-index*.045))
            eased = amount*amount*(3-2*amount)
            _place(node, self._starts[node].lerp(target, eased))
        desired = min(len(self._steps), max(0, int((progress-.16)/.13)+1)) if progress >= .16 else 0
        if progress >= 1:
            desired = len(self._steps)
            for node, target in self._targets.items():
                _place(node, target)
        while self._connected < desired:
            for source, target in self._steps[self._connected]:
                self._tree.links.new(source, target)
            self._connected += 1
        if self._area:
            self._area.tag_redraw()

    def _cleanup(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if bpy.app.driver_namespace.get(STATE_KEY) == self:
            bpy.app.driver_namespace.pop(STATE_KEY, None)

    def modal(self, context, event):
        try:
            if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
                _restore(self._tree, self._before)
                self._cleanup(context)
                return {'CANCELLED'}
            progress = (time.perf_counter()-self._start)/.65
            # Blender's Event exposes the event type, not its Timer handle.
            # Extra timer events are harmless: progress uses elapsed wall time
            # and each connection step is applied at most once.
            if event.type == 'TIMER':
                self._tick(min(1., progress))
                if progress < 1:
                    return {'RUNNING_MODAL'}
            elif event.value == 'PRESS':
                self._tick(1.)
            else:
                return {'PASS_THROUGH'}
            self._cleanup(context)
            frame_setup(context, self._result)
            self._report(self._result)
            return {'FINISHED'}
        except Exception as exc:
            _restore(self._tree, self._before)
            self._cleanup(context)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def cancel(self, context):
        _restore(self._tree, self._before)
        self._cleanup(context)


def draw_header(self, context):
    space = getattr(context, 'space_data', None)
    if (space is not None and space.type == 'NODE_EDITOR' and space.tree_type == 'ShaderNodeTree'
            and space.shader_type == 'OBJECT'):
        self.layout.separator()
        self.layout.operator(NODE_OT_harhtools_connect_textures.bl_idname, text='Connect Textures', icon='NODE_MATERIAL')


def register():
    bpy.utils.register_class(NODE_OT_harhtools_connect_textures)
    bpy.types.NODE_HT_header.append(draw_header)


def unregister():
    state = bpy.app.driver_namespace.get(STATE_KEY)
    if state:
        state.cancel(bpy.context)
    bpy.types.NODE_HT_header.remove(draw_header)
    if NODE_OT_harhtools_connect_textures.is_registered:
        bpy.utils.unregister_class(NODE_OT_harhtools_connect_textures)
