"""Temporary native bevel evaluation and cached profile thumbnails."""
import math
import bpy
import bmesh
import bpy.utils.previews
from mathutils import Vector
from . import outline_mesh,outline_bevel

_icons=None
_icon_key=None


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


def profile_points(profile,segments,shape):
    """Read the actual native bevel cross-section from a detached BMesh."""
    shape=shape if profile=='CUSTOM' else outline_bevel.PROFILES[profile]
    segments=1 if profile=='CHAMFER' else segments
    bm=bmesh.new()
    try:
        verts=[bm.verts.new(p) for p in [(-2,-1,0),(2,-1,0),(2,1,0),(-2,1,0),
               (-2,-1,-.5),(2,-1,-.5),(2,1,-.5),(-2,1,-.5)]]
        for f in [(0,1,2,3),(7,6,5,4),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]:bm.faces.new([verts[i] for i in f])
        bm.normal_update()
        edge=next(e for e in bm.edges if all(abs(v.co.y-1)<1e-7 and abs(v.co.z)<1e-7 for v in e.verts))
        bmesh.ops.bevel(bm,geom=[edge],offset=.2,segments=segments,profile=shape,affect='EDGES')
        return sorted({(max(0,min(1,(v.co.y-.8)/.2)),max(0,min(1,(v.co.z+.2)/.2))) for v in bm.verts
                       if abs(v.co.x-2)<1e-7 and v.co.y>=.79999 and v.co.z>=-.200001})
    finally:bm.free()


def profile_icon(cfg):
    global _icons,_icon_key
    key=(cfg.bevel_profile,cfg.bevel_segments,float(cfg.bevel_shape))
    if _icons is None:_icons=bpy.utils.previews.new()
    if key!=_icon_key:
        points=profile_points(*key);size=160;pixels=[]
        # Plot native segment endpoints, not an artist approximation. The
        # normalized section isolates profile shape from model dimensions.
        segments=list(zip(points,points[1:]));pink=(1.,.55,.72,1.);white=(.73,.76,.8,1.)
        for y in range(size):
            py=(y-22)/116
            for x in range(size):
                px=(x-22)/116;color=(.105,.11,.12,1.)
                if 0<=px<=1:
                    height=next((a[1]+(b[1]-a[1])*(px-a[0])/max(b[0]-a[0],1e-12)
                                 for a,b in segments if a[0]<=px<=b[0]),0)
                    if -.08<=py<=height:color=white
                    if abs(py-height)<.016:color=pink
                pixels.extend(color)
        preview=_icons.get('profile') or _icons.new('profile')
        preview.image_size=(size,size);preview.image_pixels_float=pixels
        _icon_key=key
    return _icons['profile'].icon_id


def clear():
    global _icons,_icon_key
    if _icons is not None:bpy.utils.previews.remove(_icons)
    _icons=None;_icon_key=None
