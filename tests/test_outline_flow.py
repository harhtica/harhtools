"""Collapsed borders retain local cross-strip edges, not remote triangle fans."""
import bpy,bmesh,sys,math,time,json
from pathlib import Path
from collections import Counter
from mathutils import Matrix,Euler
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import outline_geometry as g,outline_mesh as m,outline_preview

def source(loop,transform=None):
    data=bpy.data.meshes.new('Tapered flow fixture')
    data.from_pydata([(*p,0) for p in loop],[(i,(i+1)%len(loop)) for i in range(len(loop))],[])
    obj=bpy.data.objects.new('Tapered flow fixture',data);bpy.context.collection.objects.link(obj)
    if transform is not None:obj.matrix_world=transform
    bpy.context.view_layer.update();return obj

def verify(result):
    built=m.build_mesh(result);vertices=[p[:2] for p in built['vertices']];faces=built['faces']
    counts=Counter(tuple(sorted((a,b))) for f in faces for a,b in zip(f,f[1:]+f[:1]))
    boundary={edge for edge,n in counts.items() if n==1}
    expected={tuple(sorted((tuple(a),tuple(b)))) for loop in result['border_loops'] for a,b in zip(loop,loop[1:]+loop[:1])}
    assert {tuple(sorted((vertices[a],vertices[b]))) for a,b in boundary}==expected
    checked=0
    for loop in result['source_loops']:
        for i,p in enumerate(loop):
            incoming=g._sub(p,loop[i-1]);outgoing=g._sub(loop[(i+1)%len(loop)],p)
            incoming=g._mul(incoming,1/math.hypot(*incoming));outgoing=g._mul(outgoing,1/math.hypot(*outgoing))
            if g._dot(incoming,outgoing)<.85:continue # Sharp apex itself needs a miter.
            tangent=g._add(incoming,outgoing);index=vertices.index(tuple(p))
            cross_edges=[g._sub(vertices[b if a==index else a],p) for a,b in counts if index in (a,b) and (a,b) not in boundary]
            assert any(math.hypot(*edge)<=result['thickness']*1.1 and abs(g._dot(edge,tangent))<math.hypot(*edge)*math.hypot(*tangent)*.01 for edge in cross_edges),('Missing local normal edge',p)
            checked+=1
    assert checked>20
    data=m.make_mesh_data(result);bm=bmesh.new();bm.from_mesh(data)
    assert all(e.is_manifold or e.is_boundary for e in bm.edges)
    bmesh.ops.solidify(bm,geom=list(bm.faces),thickness=.08)
    assert all(e.is_manifold for e in bm.edges);bm.free()
    assert not m._crossing_edges(vertices,faces,max(1e-9,result['thickness']*1e-8))
    return built,checked

reports=[]
for segments in (32,128):
    upper=[];lower=[]
    for i in range(segments+1):
        t=i/segments;x=8*t;center=.4*math.sin(math.pi*t);half=.65*math.sin(math.pi*t)
        upper.append((x,center+half));lower.append((x,center-half))
    loop=upper+list(reversed(lower[1:-1]))
    obj=source(loop);p=g.prepare_sources([obj]);snapshot=[tuple(v.co) for v in obj.data.vertices]
    for width in (.25,.4,.7):
        result=g.build_outline(p,width,join_style='MITER',safe_inset=True)
        assert result.get('adaptive_topology') or any(result.get('offset_trimmed',()))
        start=time.perf_counter();built,checked=verify(result);elapsed=time.perf_counter()-start
        reports.append(dict(segments=segments,width=width,normal_connections=checked,seconds=round(elapsed,4),**built['diagnostics']))
    assert snapshot==[tuple(v.co) for v in obj.data.vertices]
    reduced=g.build_outline(p,.25,join_style='MITER',safe_inset=True);verify(reduced)
    if segments==32:
        surface=outline_preview.surface([reduced],dict(depth=.08,width=.015,segments=4,profile='ROUND'))
        assert surface['pos'] and all(math.isfinite(x) for p in surface['pos'] for x in p)
print(json.dumps(reports));print('COLLISION EDGE FLOW PASS')
