"""Portable mesh-border topology, boundary, sharp-corner and UV regressions."""
import json
import math
from collections import Counter
from pathlib import Path
import sys

import bpy
import bmesh
from mathutils import Euler, Matrix, Vector

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from extension import outline_geometry as og, outline_mesh as om

CHECKS=[]
ARTIFACTS=ROOT/'tests'/'_artifacts';ARTIFACTS.mkdir(exist_ok=True)


def poly(name,loops,transform=None):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D'
    for loop in loops:
        spline=data.splines.new('POLY');spline.points.add(len(loop)-1);spline.use_cyclic_u=True
        for point,co in zip(spline.points,loop):point.co=(*co,0,1)
    obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj)
    if transform is not None:obj.matrix_world=transform
    bpy.context.view_layer.update()
    return obj


def snapshot(obj):
    return tuple(tuple(row) for row in obj.matrix_world),tuple(tuple(p.co) for s in obj.data.splines for p in s.points)


def face_contains(point,coords):
    inside=False;x,y=point
    for a,b in zip(coords,coords[1:]+coords[:1]):
        if (a[1]>y)!=(b[1]>y) and a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])>x:inside=not inside
    return inside


def verify(result,built,data,*,grid=True):
    vertices=built['vertices'];faces=built['faces']
    assert all(len(face) in (3,4) for face in faces)
    assert {i for f in faces for i in f}==set(range(len(vertices)))
    edges=Counter(tuple(sorted((a,b))) for f in faces for a,b in zip(f,f[1:]+f[:1]))
    assert max(edges.values())==2 and min(edges.values())==1
    assert len(vertices)-len(edges)+len(faces)==0
    expected_boundaries=[loop for pair in zip(result['source_loops'],result['offset_loops']) for loop in pair]
    expected_edges={tuple(sorted((tuple(a),tuple(b)))) for loop in expected_boundaries for a,b in zip(loop,loop[1:]+loop[:1])}
    actual_edges={tuple(sorted((vertices[a][:2],vertices[b][:2]))) for (a,b),count in edges.items() if count==1}
    assert actual_edges==expected_edges,'Source or offset boundary changed'
    assert len(data.polygons)==len(faces) and all(p.normal.z>.99999 for p in data.polygons)
    bm=bmesh.new();bm.from_mesh(data)
    assert all(v.link_faces for v in bm.verts)
    assert all(e.is_manifold or e.is_boundary for e in bm.edges)
    assert all(not e.is_wire for e in bm.edges)
    bm.free()
    data.calc_loop_triangles()
    expected=math.fsum(abs(abs(og._area(a))-abs(og._area(b))) for a,b in zip(result['source_loops'],result['offset_loops']))
    measured=math.fsum(t.area for t in data.loop_triangles)
    assert abs(measured-expected)<max(expected*3e-6,1e-8),(measured,expected)
    assert data.uv_layers.active and len(data.uv_layers.active.data)==len(data.loops)
    assert all(math.isfinite(v) for uv in data.uv_layers.active.data for v in uv.uv)
    # Independent interior probes catch filled centers, missing strips and
    # overlapping faces. Offset fractional grid avoids coincident grid seams.
    if grid:
        xmin=min(p[0] for p in vertices);xmax=max(p[0] for p in vertices)
        ymin=min(p[1] for p in vertices);ymax=max(p[1] for p in vertices)
        polygon_coords=[[vertices[i] for i in face] for face in faces]
        hits=0;empty=0
        for x in range(33):
            for y in range(31):
                point=(xmin+(x+.371)*(xmax-xmin)/33,ymin+(y+.219)*(ymax-ymin)/31)
                wanted=sum(face_contains(point,loop) for loop in expected_boundaries)%2
                actual=sum(face_contains(point,polygon) for polygon in polygon_coords)
                assert actual==wanted,(point,actual,wanted)
                hits+=actual;empty+=not actual
        assert hits and empty


def run(name,loops,width=.15,*,direction='INWARD',join='MITER',transform=None,direct=None):
    source=poly(name,loops,transform);before=snapshot(source)
    prepared=og.prepare_sources([source]);result=og.build_outline(prepared,width,direction=direction,join_style=join)
    built=om.build_mesh(result);data=om.make_mesh_data(result,name)
    verify(result,built,data)
    assert snapshot(source)==before
    if direct is not None:assert built['diagnostics']['direct_quad_rings']==direct,built['diagnostics']
    CHECKS.append(dict(case=name,**built['diagnostics']))
    return result,built,data


square=[(-2,-2),(2,-2),(2,2),(-2,2)]
_,built,square_data=run('Square inset is four editable quads',[square],direct=1)
assert len(built['faces'])==4 and all(len(f)==4 for f in built['faces'])
bm=bmesh.new();bm.from_mesh(square_data)
bmesh.ops.solidify(bm,geom=list(bm.faces),thickness=.2)
assert all(edge.is_manifold for edge in bm.edges)
assert abs(abs(bm.calc_volume(signed=True))-(16-3.7**2)*.2)<1e-6
bm.free()
CHECKS.append(dict(case='Quad border thickens into a watertight hollow frame'))
_,built,_=run('Square outside keeps sharp corners',[square],direction='OUTWARD',direct=1)
assert len(built['faces'])==4
run('Hollow outer and hole borders',[square,[(-.8,-.8),(.8,-.8),(.8,.8),(-.8,.8)]],direct=2)
run('Separate islands remain separate',[[(-4,-1),(-2,-1),(-2,1),(-4,1)],[(2,-1),(4,-1),(4,1),(2,1)]],direct=2)
run('Concave inset has connected miter quads',[[(0,0),(3,0),(3,1),(1,1),(1,3),(0,3)]],width=.1,direct=1)
run('Legacy rounded corners mesh cleanly',[square],direction='OUTWARD',join='ROUND',direct=0)
transform=(Matrix.Translation((1234.5,-876.25,987.75)) @ Euler((.71,-.48,.93)).to_matrix().to_4x4()
           @ Matrix.Diagonal((-1.6,.72,1.3,1.0)))
result,_,data=run('Tilted mirrored nonuniform source preserved',[square],transform=transform,direct=1)
assert result['matrix_world'].to_3x3().determinant()>.99999

arch=[(-1,-1),(1,-1),(1,0)]
arch += [(-1+2*math.cos(t),2*math.sin(t)) for t in (math.pi/3*i/80 for i in range(1,81))]
arch += [(1+2*math.cos(t),2*math.sin(t)) for t in (2*math.pi/3+math.pi/3*i/80 for i in range(1,81))]
run('Pointed Gothic arch outside',[arch],width=.08,direction='OUTWARD')
run('Pointed Gothic arch inside',[arch],width=.08,direction='INWARD')
theta=math.acos(.6)
lobes=[(cx+math.cos(a+(b-a)*i/120),math.sin(a+(b-a)*i/120))
       for cx,a,b in ((-.6,theta,math.tau-theta),(.6,math.pi+theta,3*math.pi-theta)) for i in range(120)]
run('Concave Gothic cusp outside',[lobes],width=.04,direction='OUTWARD')
run('Concave Gothic cusp inside',[lobes],width=.04,direction='INWARD')

# Dense cusps lose offset samples during collision cleanup. Each surviving
# sharp source corner must connect directly to its matching offset corner.
# These constraints must survive CDT and subsequent triangle-to-quad merging.
for direction in ('INWARD','OUTWARD'):
    result,built,data=run('Cusp seam survives cleanup '+direction,[lobes],width=.04,direction=direction)
    source,offset=result['source_loops'][0],result['offset_loops'][0]
    result['offset_correspondence']=[None]
    built=om.build_mesh(result);data=om.make_mesh_data(result);verify(result,built,data)
    edges=om._edge_faces(built['faces']);vertices=[p[:2] for p in built['vertices']]
    for i,turn in om._corners(source):
        if turn>=0:continue
        j=min((j for j,t in om._corners(offset) if t<0),key=lambda j:math.dist(source[i],offset[j]))
        edge=tuple(sorted((vertices.index(tuple(source[i])),vertices.index(tuple(offset[j])))))
        assert edge in edges and len(edges[edge])==2,'Concave miter needs a direct two-face seam'
    assert built['diagnostics']['protected_miter_seams']>=2

compound=[]
radius=math.hypot(1,.1);start=math.atan2(.1,1);end=math.acos(.5/radius)
for cx,cy,r,a,b in ((1,0,2,math.pi,2*math.pi/3),(-1,0,2,math.pi/3,0),
                 (0,-.1,radius,start,end),(1,-.1,radius,math.pi-end,math.pi-start),
                 (-1,-.1,radius,start,end),(0,-.1,radius,math.pi-end,math.pi-start)):
    compound.extend((cx+r*math.cos(a+(b-a)*i/82),cy+r*math.sin(a+(b-a)*i/82)) for i in range(82))
result,built,data=run('Six-arc Gothic border preserves all corner seams',[compound],width=.02,direction='OUTWARD')
source,offset=result['source_loops'][0],result['offset_loops'][0]
assert len(source)!=len(offset),'Fixture must exercise removed offset points'
vertices=[p[:2] for p in built['vertices']];edges=om._edge_faces(built['faces'])
assert len(om._corners(source))==len(om._corners(offset))==6
for i,turn in om._corners(source):
    j=min((j for j,t in om._corners(offset) if turn*t>0),key=lambda j:math.dist(source[i],offset[j]))
    edge=tuple(sorted((vertices.index(tuple(source[i])),vertices.index(tuple(offset[j])))))
    assert len(edges.get(edge,[]))==2,'All six corners need an explicit shared edge'
assert built['diagnostics']['protected_miter_seams']==6

# Explicit loss of correspondence exercises the same constrained fallback
# used when a dense apex needed intersection trimming, with all boundaries
# still exactly preserved and the hollow center remaining open.
source=poly('No correspondence',[square]);prepared=og.prepare_sources([source])
result=og.build_outline(prepared,.2,join_style='MITER');result['offset_correspondence']=[None]
built=om.build_mesh(result);data=om.make_mesh_data(result);verify(result,built,data)
assert built['diagnostics']['triangulated_rings']==1 and built['diagnostics']['quad_faces']==4
CHECKS.append(dict(case='Constrained fallback keeps four-sided border topology',**built['diagnostics']))

before=set(bpy.data.meshes)
broken=dict(result,offset_loops=[result['source_loops'][0]],offset_correspondence=[None])
try:om.make_mesh_data(broken)
except ValueError:pass
else:raise AssertionError('Collapsed border should not create mesh data')
assert set(bpy.data.meshes)==before
CHECKS.append(dict(case='Invalid border cannot leave partial mesh data'))

(ARTIFACTS/'outline_mesh_results.json').write_text(json.dumps(CHECKS,indent=2),encoding='utf8')
print('OUTLINE_MESH_PASS',json.dumps(CHECKS))
