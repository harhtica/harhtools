"""Safe Inset supports closed, native BMesh edge-ring subdivision at junctions."""
import bpy,bmesh,sys,math,json
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_geometry as g,outline_mesh as m

def prepare(loops):
    mesh=bpy.data.meshes.new('Loop cut fixture');vertices=[];edges=[]
    for loop in loops:
        base=len(vertices);vertices.extend((*p,0) for p in loop)
        edges.extend((base+i,base+(i+1)%len(loop)) for i in range(len(loop)))
    mesh.from_pydata(vertices,edges,[])
    obj=bpy.data.objects.new('Loop cut fixture',mesh);bpy.context.collection.objects.link(obj)
    return g.prepare_sources([obj])

def verify(result):
    built=m.build_mesh(result);faces=built['faces'];vertices=built['vertices'];diag=built['diagnostics']
    assert diag['triangle_faces']==0 and all(len(f)==4 for f in faces)
    adjacency=m._edge_faces(faces)
    assert diag['direct_quad_rings']==len(result['source_loops']) and diag['triangulated_rings']==0
    remaining=set(range(len(faces)));routes=[]
    while remaining:
        first=min(remaining);f=faces[first];edge=tuple(sorted((f[0],f[3])))
        current=first;visited=set();route=[]
        while current not in visited:
            assert current in remaining
            visited.add(current);route.append(edge);face=faces[current]
            j=next(i for i in range(4) if tuple(sorted((face[i],face[(i+1)%4])))==edge)
            edge=tuple(sorted((face[(j+2)%4],face[(j+3)%4])))
            neighbors=adjacency[edge];assert len(neighbors)==2
            current=next(i for i in neighbors if i!=current)
        assert current==first and len(route)>=3
        remaining-=visited;routes.append(route)
    assert len(routes)==len(result['source_loops'])
    assert sorted(map(len,routes))==sorted(map(len,result['source_loops']))
    assert not m._crossing_edges([p[:2] for p in vertices],faces,1e-9)
    data=m.make_mesh_data(result)
    assert all(p.area>0 for p in data.polygons),'Float32 conversion collapsed a quad'
    assert all((data.vertices[e.vertices[0]].co-data.vertices[e.vertices[1]].co).length>0 for e in data.edges)
    for route in routes:
        bm=bmesh.new();bm.from_mesh(data);bm.verts.ensure_lookup_table();bm.verts.index_update()
        lookup={tuple(sorted(v.index for v in e.verts)):e for e in bm.edges}
        ring=[lookup[e] for e in route];before=len(bm.faces)
        # This is Blender's native quad-ring subdivision, the geometry
        # operation used for loop cuts. It must cross every corner and close.
        bmesh.ops.subdivide_edgering(bm,edges=ring,interp_mode='LINEAR',cuts=1,smooth=0.)
        assert len(bm.faces)==before+len(route)
        assert all(len(f.verts)==4 for f in bm.faces)
        assert all(e.is_manifold or e.is_boundary for e in bm.edges)
        bmesh.ops.solidify(bm,geom=list(bm.faces),thickness=.05)
        assert all(e.is_manifold for e in bm.edges)
        bm.free()
    return dict(rings=len(routes),ring_lengths=list(map(len,routes)),quads=len(faces))

upper=[];lower=[]
for i in range(33):
    t=i/32;x=t*8;center=.4*math.sin(math.pi*t);half=.65*math.sin(math.pi*t)
    upper.append((x,center+half));lower.append((x,center-half))
taper=upper+list(reversed(lower[1:-1]))
neck=[(-4,-2),(-1,-2),(-1,-.3),(1,-.3),(1,-2),(4,-2),(4,2),(1,2),(1,.3),(-1,.3),(-1,2),(-4,2)]
square=[(-2,-2),(2,-2),(2,2),(-2,2)]
reports=[]
for loops,width,direction in (([taper],.4,'INWARD'),([taper],.7,'INWARD'),([neck],.5,'INWARD'),
                              ([square],2.1,'INWARD'),([square,[(-.3,-.3),(.3,-.3),(.3,.3),(-.3,.3)]],.4,'OUTWARD')):
    result=g.build_outline(prepare(loops),width,direction=direction,join_style='MITER',safe_inset=True)
    assert result['diagnostics']['locally_clamped_vertices']>0
    reports.append(verify(result))
print(json.dumps(reports));print('NATIVE SAFE INSET LOOP CUTS PASS')
