"""Sharp Safe Inset preserves normal quad rows, holes and recoverable detail."""
import bpy,bmesh,sys,math,json,time
from pathlib import Path
from mathutils import Matrix,Euler
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_geometry as g,outline_mesh as m,outline_preview

def prepare(loops,transform=None):
    mesh=bpy.data.meshes.new('Local clamp fixture');vertices=[];edges=[]
    for loop in loops:
        base=len(vertices);vertices.extend((*p,0) for p in loop)
        edges.extend((base+i,base+(i+1)%len(loop)) for i in range(len(loop)))
    mesh.from_pydata(vertices,edges,[])
    obj=bpy.data.objects.new('Local clamp fixture',mesh);bpy.context.collection.objects.link(obj)
    if transform is not None:obj.matrix_world=transform
    bpy.context.view_layer.update()
    return obj,g.prepare_sources([obj])

def verify(prepared,width,direction):
    result=g.build_outline(prepared,width,direction=direction,join_style='MITER',safe_inset=True)
    built=m.build_mesh(result);count=sum(map(len,prepared['loops']))
    assert len(built['vertices'])==count*2 and len(built['faces'])==count
    assert built['diagnostics']['direct_quad_rings']==len(prepared['loops'])
    assert built['diagnostics']['triangulated_rings']==0
    assert result['source_loops']==prepared['loops'] and result['diagnostics']['topology_preserved']
    assert all(0<w<=width for local in result['local_widths'] for w in local)
    data=m.make_mesh_data(result)
    assert all(p.area>0 for p in data.polygons)
    assert all(len(p.vertices)==4 for p in data.polygons)
    assert not m._crossing_edges([p[:2] for p in built['vertices']],built['faces'],prepared['epsilon'])
    bm=bmesh.new();bm.from_mesh(data)
    bmesh.ops.solidify(bm,geom=list(bm.faces),thickness=.08)
    assert all(e.is_manifold for e in bm.edges);bm.free()
    return result

square=[(-2,-2),(2,-2),(2,2),(-2,2)]
neck=[(-4,-2),(-1,-2),(-1,-.3),(1,-.3),(1,-2),(4,-2),(4,2),(1,2),(1,.3),(-1,.3),(-1,2),(-4,2)]
spike=[(-3,-2),(3,-2),(3,0),(.1,0),(0,3),(-.1,0),(-3,0)]
cases=[([square],[.1,1.99,2,2.1,5],'INWARD'),([neck],[.1,.3,.31,.5,1.6],'INWARD'),
       ([square,[(-1,-1),(1,-1),(1,1),(-1,1)]],[.1,.5,.6,2],'INWARD'),
       ([square,[(-.3,-.3),(.3,-.3),(.3,.3),(-.3,.3)]],[.1,.3,.4,1],'OUTWARD'),
       ([[(-3,-1),(-1,-1),(-1,1),(-3,1)],[(1,-1),(3,-1),(3,1),(1,1)]],[.1,1,1.1,2],'OUTWARD'),
       ([spike],[.04,.1,.25,.6,1.1],'INWARD'),([spike],[.04,.1,.25,.6,1.1],'OUTWARD')]
reports=[]
for loops,widths,direction in cases:
    obj,p=prepare(loops);snapshot=[tuple(v.co) for v in obj.data.vertices];original=repr(p['loops'])
    first=verify(p,widths[0],direction)
    for width in widths:
        print('Clamp',direction,width,flush=True)
        result=verify(p,width,direction)
        reports.append(dict(width=width,direction=direction,clamped=result['diagnostics']['locally_clamped_vertices']))
    assert verify(p,widths[0],direction)['offset_loops']==first['offset_loops']
    assert repr(p['loops'])==original and [tuple(v.co) for v in obj.data.vertices]==snapshot
    if loops==[square]:
        strict=g.build_outline(p,widths[0],direction=direction,join_style='MITER',safe_inset=False)
        assert all(math.dist(a,b)<p['epsilon'] for a,b in zip(first['offset_loops'][0],strict['offset_loops'][0])),'Normal widths must remain ordinary miter offsets'
        assert first['diagnostics']['locally_clamped_vertices']==0
transform=Matrix.Translation((321,-42,54))@Euler((.4,.8,-.7)).to_matrix().to_4x4()@Matrix.Diagonal((1.5,.75,1.,1.))
obj,p=prepare([neck],transform);result=verify(p,.4,'INWARD')
ids=(set(bpy.data.objects),set(bpy.data.meshes),set(bpy.data.scenes))
surface=outline_preview.surface([result],dict(depth=.2,width=.03,profile='ROUND',segments=4))
assert surface['pos'] and all(math.isfinite(v) for p in surface['pos'] for v in p)
assert ids==(set(bpy.data.objects),set(bpy.data.meshes),set(bpy.data.scenes))
circle=[(math.cos(i*math.tau/2048)*20,math.sin(i*math.tau/2048)*20) for i in range(2048)]
obj,p=prepare([circle]);start=time.perf_counter();result=g.build_outline(p,.4,join_style='MITER',safe_inset=True);built=m.build_mesh(result)
elapsed=time.perf_counter()-start
assert built['diagnostics']['direct_quad_rings']==1 and len(built['faces'])==sum(map(len,p['loops']))
assert len(built['faces'])>=1000
assert result['diagnostics']['locally_clamped_vertices']==0
assert elapsed<2,('Preview unexpectedly slow',elapsed)
print(json.dumps({'cases':reports,'dense_circle_seconds':elapsed}));print('LOCAL SAFE INSET CLAMP PASS')
