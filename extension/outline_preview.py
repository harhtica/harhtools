"""Temporary native bevel evaluation and cached profile thumbnails."""
import math
import json
import bpy
import bmesh
import bpy.utils.previews
from mathutils import Vector
from . import outline_mesh,outline_bevel,outline_profiles

_icons=None
_icon_key=None
_requested_key=None
_error_key=None
_error_message=''


def surface(results,options):
    """Evaluate in an isolated scene, return draw arrays, remove all scratch IDs."""
    scene=bpy.data.scenes.new('Harhtools temporary bevel evaluation')
    objects=[];meshes=[];positions=[];colors=[]
    try:
        for result in results:
            mesh=outline_mesh.make_mesh_data(result);meshes.append(mesh)
            obj=bpy.data.objects.new('Harhtools temporary border',mesh);objects.append(obj)
            scene.collection.objects.link(obj);obj.matrix_world=result['matrix_world']
        outline_bevel.apply(objects,**options)
        with bpy.context.temp_override(scene=scene,view_layer=scene.view_layers[0]):
            graph=bpy.context.evaluated_depsgraph_get();graph.update()
            for obj in objects:
                evaluated=obj.evaluated_get(graph);mesh=evaluated.to_mesh()
                try:
                    mesh.calc_loop_triangles();normal_matrix=obj.matrix_world.to_3x3().inverted().transposed()
                    # Display bias prevents coplanar source faces from flickering;
                    # only draw coordinates are biased, never output geometry.
                    span=max((v.co.length for v in obj.data.vertices),default=1)
                    bias=obj.matrix_world.to_3x3()@Vector((0,0,max(span*1e-5,1e-8)))
                    for triangle in mesh.loop_triangles:
                        normal=(normal_matrix@triangle.normal).normalized()
                        light=.38+.57*abs(normal.dot(Vector((.35,-.45,.82)).normalized()))
                        color=(light*.96,light*.98,light,1.)
                        positions.extend(tuple(obj.matrix_world@mesh.vertices[i].co+bias) for i in triangle.vertices)
                        colors.extend((color,)*3)
                finally:evaluated.to_mesh_clear()
        return {'pos':positions,'color':colors}
    finally:
        for obj in objects:bpy.data.objects.remove(obj,do_unlink=True)
        for mesh in meshes:
            if mesh.users==0:bpy.data.meshes.remove(mesh)
        bpy.data.scenes.remove(scene)


def profile_points(profile,segments,shape,profile_data=''):
    """Read the actual native bevel cross-section from a detached BMesh."""
    shape=shape if profile=='CUSTOM' else outline_bevel.PROFILES.get(profile,.5)
    segments=1 if profile=='CHAMFER' else segments
    bm=bmesh.new();holder=None;holder_mesh=None
    try:
        verts=[bm.verts.new(p) for p in [(-2,-1,0),(2,-1,0),(2,1,0),(-2,1,0),
               (-2,-1,-.5),(2,-1,-.5),(2,1,-.5),(-2,1,-.5)]]
        for f in [(0,1,2,3),(7,6,5,4),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]:bm.faces.new([verts[i] for i in f])
        bm.normal_update()
        edge=next(e for e in bm.edges if all(abs(v.co.y-1)<1e-7 and abs(v.co.z)<1e-7 for v in e.verts))
        if profile in outline_profiles.NAMES or profile=='EDITED':
            holder_mesh=bpy.data.meshes.new('Harhtools profile scratch')
            holder=bpy.data.objects.new('Harhtools profile scratch',holder_mesh)
            mod=holder.modifiers.new('Profile','BEVEL')
            if profile=='EDITED':
                if not profile_data:raise ValueError('Choose or edit a custom profile first.')
                outline_profiles.restore(mod.custom_profile,json.loads(profile_data),segments)
            else:outline_profiles.configure(mod.custom_profile,profile,segments)
            # BMesh exposes custom_profile but Blender's Python binding does
            # not implement that argument. Read the native modifier's own
            # initialized CurveProfile samples instead (same bevel sampler).
            return list(reversed([tuple(p.location) for p in mod.custom_profile.segments]+[(0.,1.)]))
        bmesh.ops.bevel(bm,geom=[edge],offset=.2,segments=segments,profile=shape,affect='EDGES')
        points={v:(max(0,min(1,(v.co.y-.8)/.2)),max(0,min(1,(v.co.z+.2)/.2))) for v in bm.verts
                if abs(v.co.x-2)<1e-7 and v.co.y>=.79999 and v.co.z>=-.200001}
        current=min(points,key=lambda v:math.dist(points[v],(0,1)));ordered=[];seen=set()
        while current is not None:
            ordered.append(points[current]);seen.add(current)
            current=next((e.other_vert(current) for e in current.link_edges if e.other_vert(current) in points and e.other_vert(current) not in seen),None)
        return ordered
    finally:
        bm.free()
        if holder is not None:bpy.data.objects.remove(holder,do_unlink=True)
        if holder_mesh is not None:bpy.data.meshes.remove(holder_mesh)


def _build_icon(key):
    """Generate outside panel draw; native custom profiles allocate scratch IDs."""
    global _icons,_icon_key
    if _icons is None:_icons=bpy.utils.previews.new()
    if key!=_icon_key:
        points=profile_points(*key);size=160;pixels=[.105,.11,.12,1.]*(size*size)
        # Plot native segment endpoints, not an artist approximation. The
        # normalized section isolates profile shape from model dimensions.
        segments=list(zip(points,points[1:]));pink=(1.,.55,.72,1.);white=(.73,.76,.8,1.)
        polygon=[(0,0)]+points+[(0,0)]
        def distance(px,py,a,b):
            dx,dy=b[0]-a[0],b[1]-a[1];den=dx*dx+dy*dy
            t=max(0,min(1,((px-a[0])*dx+(py-a[1])*dy)/den)) if den>1e-20 else 0
            return math.hypot(px-a[0]-t*dx,py-a[1]-t*dy)
        for y in range(size):
            py=(y-22)/116
            intersections=sorted((b[0]-a[0])*(py-a[1])/(b[1]-a[1])+a[0] for a,b in zip(polygon,polygon[1:]) if (a[1]>py)!=(b[1]>py))
            for a,b in zip(intersections[::2],intersections[1::2]):
                for x in range(max(0,math.ceil(a*116+22)),min(size,math.ceil(b*116+22))):
                    offset=(y*size+x)*4;pixels[offset:offset+4]=white
        # Stroke only each segment's pixel bounds; profile changes must not
        # scan every pixel against every segment in the panel draw callback.
        for a,b in segments:
            for y in range(max(0,math.floor(min(a[1],b[1])*116+20)),min(size,math.ceil(max(a[1],b[1])*116+24))):
                for x in range(max(0,math.floor(min(a[0],b[0])*116+20)),min(size,math.ceil(max(a[0],b[0])*116+24))):
                    if distance((x-22)/116,(y-22)/116,a,b)<.012:
                        offset=(y*size+x)*4;pixels[offset:offset+4]=pink
        preview=_icons.get('profile') or _icons.new('profile')
        preview.image_size=(size,size);preview.image_pixels_float=pixels
        _icon_key=key
    return _icons['profile'].icon_id


def _key(cfg):
    key=(cfg.bevel_profile,cfg.bevel_segments,float(cfg.bevel_shape))
    if cfg.bevel_profile=='EDITED':
        from . import profile_editor
        key+=(profile_editor.serialize(cfg.edited_profile),)
    return key


def _redraw_panels():
    for manager in getattr(bpy.data,'window_managers',()):
        for window in manager.windows:
            for area in window.screen.areas:
                if area.type=='VIEW_3D':area.tag_redraw()


def _refresh_icon():
    """One coalesced main-thread timer, never run from a panel draw callback."""
    global _requested_key,_error_key,_error_message
    key=_requested_key;_requested_key=None
    if key is None:return None
    try:
        _build_icon(key);_error_key=None;_error_message=''
    except Exception as exc:
        _error_key=key;_error_message=str(exc)
        print('Harhtools profile preview:',_error_message)
    _redraw_panels()
    return None


def profile_icon(cfg):
    """Read cached pixels or queue them; drawing must never write Blender IDs."""
    global _requested_key
    key=_key(cfg)
    if _icons is not None and key==_icon_key:
        return _icons['profile'].icon_id
    if key!=_error_key:
        _requested_key=key
        if not bpy.app.timers.is_registered(_refresh_icon):
            bpy.app.timers.register(_refresh_icon,first_interval=.01)
    return 0


def profile_status(cfg):
    return ('Profile preview unavailable','ERROR') if _key(cfg)==_error_key else ('Loading profile preview...','TIME')


def clear():
    global _icons,_icon_key,_requested_key,_error_key,_error_message
    if bpy.app.timers.is_registered(_refresh_icon):bpy.app.timers.unregister(_refresh_icon)
    if _icons is not None:bpy.utils.previews.remove(_icons)
    _icons=None;_icon_key=None
    _requested_key=None;_error_key=None;_error_message=''
