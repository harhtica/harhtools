"""Collision events, restored detail and manifold editable border regressions."""
import sys, math, json
from pathlib import Path
from collections import Counter
import bpy, bmesh
from mathutils import Matrix, Euler
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_geometry as g, outline_mesh as m, outline_preview

def prepare(loops,transform=None):
    mesh=bpy.data.meshes.new('Safe fixture');vertices=[];edges=[]
    for loop in loops:
        base=len(vertices);vertices.extend((*p,0) for p in loop)
        edges.extend((base+i,base+(i+1)%len(loop)) for i in range(len(loop)))
    mesh.from_pydata(vertices,edges,[])
    obj=bpy.data.objects.new('Safe fixture',mesh);bpy.context.collection.objects.link(obj)
    if transform is not None:obj.matrix_world=transform
    bpy.context.view_layer.update()
    return g.prepare_sources([obj])

def area(loops):return math.fsum(g._area(loop) for loop in loops)
def verify(result):
    built=m.build_mesh(result);vertices=built['vertices'];faces=built['faces']
    counts=Counter(tuple(sorted((a,b))) for f in faces for a,b in zip(f,f[1:]+f[:1]))
    assert all(n in (1,2) for n in counts.values())
    assert all(len(f) in (3,4) for f in faces)
    expected={tuple(sorted((tuple(a),tuple(b)))) for loop in result['border_loops'] for a,b in zip(loop,loop[1:]+loop[:1])}
    actual={tuple(sorted((vertices[a][:2],vertices[b][:2]))) for (a,b),n in counts.items() if n==1}
    assert expected==actual,'Boundary changed'
    assert abs(sum(g._area([vertices[i] for i in f]) for f in faces)-area(result['border_loops']))<1e-5
    data=m.make_mesh_data(result);bm=bmesh.new();bm.from_mesh(data)
    bmesh.ops.solidify(bm,geom=list(bm.faces),thickness=.1)
    assert all(e.is_manifold for e in bm.edges),'Border must extrude to a watertight solid'
    bm.free()
    return built

square=[(-2,-2),(2,-2),(2,2),(-2,2)]
neck=[(-4,-2),(-1,-2),(-1,-.3),(1,-.3),(1,-2),(4,-2),(4,2),(1,2),(1,.3),(-1,.3),(-1,2),(-4,2)]
cases=[('square collapse',[square],[.1,1.99,2,2.1,5],'INWARD',[1,1,0,0,0]),
       ('neck splits',[neck],[.1,.3,.31,.5,1.6],'INWARD',[1,2,2,2,0]),
       ('hole consumes rim',[square,[(-1,-1),(1,-1),(1,1),(-1,1)]],[.1,.5,.6,2],'INWARD',[2,0,0,0]),
       ('hole closes',[square,[(-.3,-.3),(.3,-.3),(.3,.3),(-.3,.3)]],[.1,.3,.4,1],'OUTWARD',[2,1,1,1]),
       ('islands merge',[[(-3,-1),(-1,-1),(-1,1),(-3,1)],[(1,-1),(3,-1),(3,1),(1,1)]],[.1,1,1.1,2],'OUTWARD',[2,1,1,1])]
reports=[]
for name,loops,widths,direction,counts in cases:
    p=prepare(loops);before=repr(p['loops']);areas=[]
    for width,count in zip(widths,counts):
        print(name,width,flush=True)
        r=g.build_outline(p,width,direction=direction,join_style='MITER',safe_inset=True)
        assert len(r['offset_loops'])==count,(name,width,len(r['offset_loops']),count)
        try:verify(r)
        except Exception:
            print(json.dumps(r['offset_loops']));raise
        areas.append(area(r['border_loops']))
    assert all(a<=b+1e-5 for a,b in zip(areas,areas[1:])),(name,areas)
    restored=g.build_outline(p,widths[0],direction=direction,join_style='MITER',safe_inset=True)
    assert len(restored['offset_loops'])==counts[0] and repr(p['loops'])==before
    reports.append({'case':name,'border_areas':areas})
transform=Matrix.Translation((321,-42,54))@Euler((.4,.8,-.7)).to_matrix().to_4x4()@Matrix.Diagonal((1.5,.75,1.,1.))
p=prepare([neck],transform);verify(g.build_outline(p,.4,join_style='MITER',safe_inset=True))
# Sharp cusps, both corner styles, and native bevel evaluation after merging.
spike=[(-3,-2),(3,-2),(3,0),(.1,0),(0,3),(-.1,0),(-3,0)]
for join in ('MITER','ROUND'):
    for direction in ('INWARD','OUTWARD'):
        p=prepare([spike]);first=g.build_outline(p,.04,direction=direction,join_style=join,safe_inset=True)
        for width in (.1,.25,.6,1.1):
            result=g.build_outline(p,width,direction=direction,join_style=join,safe_inset=True);verify(result)
        restored=g.build_outline(p,.04,direction=direction,join_style=join,safe_inset=True)
        assert restored['offset_loops']==first['offset_loops']
result=g.build_outline(prepare([neck]),.5,join_style='MITER',safe_inset=True)
ids=(set(bpy.data.objects),set(bpy.data.meshes),set(bpy.data.scenes))
surface=outline_preview.surface([result],dict(depth=.2,width=.03,profile='ROUND',segments=4))
assert surface['pos'] and all(math.isfinite(v) for p in surface['pos'] for v in p)
assert ids==(set(bpy.data.objects),set(bpy.data.meshes),set(bpy.data.scenes))
print(json.dumps(reports));print('SAFE INSET PASS')
