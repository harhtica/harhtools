"""Headless width/topology/source-preservation tests for Make Outline."""
import sys,math,time,json
from pathlib import Path
import bpy
from mathutils import Vector,Matrix,Euler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from extension import outline_geometry as og
from extension import curve_geometry as cg
from extension import shape_builder as sb

REPORTS=[]

def poly(name,loops,matrix=None,mesh=False):
    if mesh:
        data=bpy.data.meshes.new(name);verts=[];edges=[]
        for loop in loops:
            base=len(verts);verts.extend((x,y,0) for x,y in loop)
            edges.extend((base+i,base+(i+1)%len(loop)) for i in range(len(loop)))
        data.from_pydata(verts,edges,[])
    else:
        data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D'
        for loop in loops:
            s=data.splines.new('POLY');s.points.add(len(loop)-1);s.use_cyclic_u=True
            for p,(x,y) in zip(s.points,loop):p.co=(x,y,0,1)
    obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj)
    if matrix is not None:obj.matrix_world=matrix
    return obj

def circle(name,r=1,matrix=None):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='2D'
    spline=data.splines.new('BEZIER');spline.bezier_points.add(3);spline.use_cyclic_u=True
    k=4/3*math.tan(math.pi/8)
    for i,p in enumerate(spline.bezier_points):
        a=i*math.pi/2;v=Vector((math.cos(a),math.sin(a),0));t=Vector((-math.sin(a),math.cos(a),0))
        p.co=r*v;p.handle_left_type='FREE';p.handle_right_type='FREE'
        p.handle_left=p.co-r*k*t;p.handle_right=p.co+r*k*t
    obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj)
    if matrix is not None:obj.matrix_world=matrix
    return obj

def evaluated_area(result):
    obj=bpy.data.objects.new('Test outline',og.make_curve_data(result));bpy.context.collection.objects.link(obj)
    obj.matrix_world=result['matrix_world'];bpy.context.view_layer.update()
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
    area=sum(p.area for p in mesh.polygons);evaluated.to_mesh_clear()
    return area

def rejects(callback,fragment=None):
    try:callback()
    except ValueError as exc:
        if fragment:assert fragment.lower() in str(exc).lower(),str(exc)
        return str(exc)
    raise AssertionError('Expected safe rejection')

def check_width(prepared,result,width,limit=1e-6,max_samples=None):
    # For regular shape offsets, each output sample is width away from the
    # nearest original edge. Convex closing-corner miters are excluded here.
    source_edges=[(a,b) for loop in prepared['loops'] for a,b in zip(loop,loop[1:]+loop[:1])]
    deviations=[]
    for loop in result['offset_loops']:
        pairs=list(zip(loop,loop[1:]+loop[:1]))
        if max_samples:pairs=pairs[::max(1,len(pairs)//max_samples)]
        for a,b in pairs:
            p=((a[0]+b[0])*.5,(a[1]+b[1])*.5)
            dist=math.sqrt(min(og._point_segment_sq(p,c,d) for c,d in source_edges))
            deviations.append(abs(dist-width))
    assert max(deviations)<limit,(max(deviations),limit)
    return max(deviations)

square=[(-2,-2),(2,-2),(2,2),(-2,2)]
obj=poly('Square',[square]);prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.25)
assert len(result['border_loops'])==2
assert abs(abs(og._area(result['offset_loops'][0]))-3.5**2)<1e-5
assert abs(evaluated_area(result)-(16-3.5**2))<1e-5
check_width(prepared,result,.25)
REPORTS.append({'case':'square exact inward width and evaluated ring area','points':result['diagnostics']['poly_points']})

result=og.build_outline(prepared,.25,direction='OUTWARD')
assert abs(evaluated_area(result)-(16*.25+math.pi*.25**2))<3e-5
check_width(prepared,result,.25,prepared['tolerance']*1.1)
REPORTS.append({'case':'square outward rounded joins','points':result['diagnostics']['poly_points']})

obj=circle('Circle');snapshot=[tuple(v) for p in obj.data.splines[0].bezier_points for v in (p.co,p.handle_left,p.handle_right)]
t0=time.perf_counter();prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.1);duration=time.perf_counter()-t0
err=check_width(prepared,result,.1,prepared['tolerance']*1.1)
assert len(prepared['world_segments'])==4 and all(s['kind']=='BEZIER' for s in prepared['world_segments'])
assert snapshot==[tuple(v) for p in obj.data.splines[0].bezier_points for v in (p.co,p.handle_left,p.handle_right)]
assert abs(evaluated_area(result)-math.pi*(1-.9**2))<.001
REPORTS.append({'case':'Bezier circle sampled offset','max_chord_width_error':err,'seconds':duration,'points':result['diagnostics']['poly_points']})

obj=poly('Concave L',[[(0,0),(3,0),(3,1),(1,1),(1,3),(0,3)]])
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.15)
err=check_width(prepared,result,.15,prepared['tolerance']*1.1)
assert evaluated_area(result)>0
REPORTS.append({'case':'concave L rounded interior corner','max_width_error':err})

obj=poly('Hole',[square,[(-1,-1),(1,-1),(1,1),(-1,1)]])
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.2)
assert prepared['depths']==[0,1]
assert len(result['border_loops'])==4
expected=(16-3.6**2)+(8*.2+math.pi*.2**2)
assert abs(evaluated_area(result)-expected)<5e-5,(evaluated_area(result),expected)
REPORTS.append({'case':'hole border and evaluated fill remains empty','area':evaluated_area(result)})

transform=Matrix.Translation((2,5,9))@Euler((.53,.25,.74)).to_matrix().to_4x4()@Matrix.Diagonal((2.0,.75,1,1))
obj=poly('Transformed mesh',[square],transform,mesh=True)
bpy.context.view_layer.update()
matrix_before=obj.matrix_world.copy();coords_before=[tuple(v.co) for v in obj.data.vertices]
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.25)
assert abs(evaluated_area(result)-(8*3-7.5*2.5))<2e-5
check_width(prepared,result,.25,1e-6)
assert obj.matrix_world==matrix_before and coords_before==[tuple(v.co) for v in obj.data.vertices]
assert abs(result['matrix_world'].to_3x3().determinant()-1)<1e-6
REPORTS.append({'case':'rotated nonuniform mesh scale uses uniform world-unit width'})

for name,loops,width in [('square collapse',[square],2.1),('narrow concave feature',[[(0,0),(3,0),(3,.2),(1,.2),(1,3),(0,3)]],.15),('hole collision',[square,[(-1.8,-1.8),(1.8,-1.8),(1.8,1.8),(-1.8,1.8)]],.15)]:
    prepared=og.prepare_sources([poly(name,loops)])
    message=rejects(lambda:og.build_outline(prepared,width))
    REPORTS.append({'case':name,'rejected':message})

rejects(lambda:og.prepare_sources([poly('Bow tie',[[(0,0),(2,2),(0,2),(2,0)]])]))
open_obj=poly('Open',[square]);open_obj.data.splines[0].use_cyclic_u=False
rejects(lambda:og.prepare_sources([open_obj]),'close')
nonplanar=poly('Nonplanar',[square],mesh=True);nonplanar.data.vertices[0].co.z=.1
rejects(lambda:og.prepare_sources([nonplanar]),'plane')
REPORTS.append({'case':'open, self-intersecting, and nonplanar sources rejected'})

# Subdivision bound is tested against the actual input cubic, not a true circle:
# Blender's four-cubic circle is itself only an approximation to a circle.
obj=circle('Bound check');prepared=og.prepare_sources([obj]);edges=[(a,b) for loop in prepared['loops'] for a,b in zip(loop,loop[1:]+loop[:1])]
worst=0
for segment in prepared['world_segments']:
    for i in range(301):
        point=Vector(cg.evaluate(segment['cp'],i/300))-prepared['origin'];p=(point.dot(prepared['u']),point.dot(prepared['v']))
        worst=max(worst,math.sqrt(min(og._point_segment_sq(p,a,b) for a,b in edges)))
assert worst<prepared['tolerance']*1.02,(worst,prepared['tolerance'])
REPORTS.append({'case':'input cubic sampling bound','measured_error':worst,'bound':prepared['tolerance']})

# Two round lobes meeting at genuine concave cusps, built from circular cubic
# spans. Output must stay a valid single inner boundary at the cusp joins.
data=bpy.data.curves.new('Cusped lobes','CURVE');data.dimensions='2D'
arcs=[];theta=math.acos(.6)
for cx,start,end in [(-.6,theta,math.tau-theta),(.6,math.pi+theta,3*math.pi-theta)]:
    count=math.ceil((end-start)/(math.pi/2))
    for i in range(count):
        a=start+(end-start)*i/count;b=start+(end-start)*(i+1)/count;k=4/3*math.tan((b-a)/4)
        p=Vector((cx+math.cos(a),math.sin(a),0));q=Vector((cx+math.cos(b),math.sin(b),0))
        ta=Vector((-math.sin(a),math.cos(a),0));tb=Vector((-math.sin(b),math.cos(b),0))
        arcs.append((p,p+k*ta,q-k*tb,q))
spline=data.splines.new('BEZIER');spline.bezier_points.add(len(arcs)-1);spline.use_cyclic_u=True
for i,p in enumerate(spline.bezier_points):
    p.handle_left_type='FREE';p.handle_right_type='FREE';p.co=arcs[i][0]
    p.handle_right=arcs[i][1];p.handle_left=arcs[i-1][2]
obj=bpy.data.objects.new('Cusped lobes',data);bpy.context.collection.objects.link(obj)
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.08)
assert len(result['offset_loops'])==1 and evaluated_area(result)>0
check_width(prepared,result,.08,prepared['tolerance']*1.1)
REPORTS.append({'case':'circular cubic lobes with concave cusps','points':result['diagnostics']['poly_points']})

obj=poly('Islands',[[(-3,-1),(-1,-1),(-1,1),(-3,1)],[(1,-1),(3,-1),(3,1),(1,1)]])
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.15)
assert len(result['border_loops'])==4 and abs(evaluated_area(result)-2*(4-1.7**2))<1e-5
REPORTS.append({'case':'separate islands remain separate'})

obj=poly('Outward hole',[square,[(-1,-1),(1,-1),(1,1),(-1,1)]])
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.2,direction='OUTWARD')
assert len(result['border_loops'])==4
assert abs(evaluated_area(result)-(16*.2+math.pi*.2**2+4-1.6**2))<5e-5
REPORTS.append({'case':'outward outline respects hole clearance and evaluated fill'})

obj=circle('Transformed Bezier ellipse',matrix=transform);bpy.context.view_layer.update()
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.12)
check_width(prepared,result,.12,prepared['tolerance']*1.1)
assert abs(prepared['normal'].dot(Vector((transform.to_3x3().inverted().transposed()@Vector((0,0,1))).normalized())))>1-1e-6
REPORTS.append({'case':'rotated nonuniform Bezier scale uses uniform world-unit width'})

# Regression: dense flat sources at workshop translations used to fail the
# plane check because thousands of float32 Vector additions drifted the mean.
# These portable fixtures cover every source path, baked float32 coordinates,
# and a large translation without raising the geometric tolerance.
def source_snapshot(obj):
    if obj.type=='MESH':
        coordinates=tuple(tuple(p.co) for p in obj.data.vertices)
    else:
        coordinates=tuple(tuple(v) for spline in obj.data.splines for p in
                          (spline.bezier_points if spline.type=='BEZIER' else spline.points)
                          for v in ((p.co,p.handle_left,p.handle_right) if spline.type=='BEZIER' else (p.co,)))
    return tuple(tuple(row) for row in obj.matrix_world),coordinates

def plane_error(prepared):
    origin=prepared['_origin64'];normal=prepared['_normal64']
    return max(abs(math.fsum((point[i]-origin[i])*normal[i] for i in range(3)))
               for segment in prepared['world_segments'] for point in segment['cp'])

dense_loop=[(2*math.cos(i*math.tau/1128),2*math.sin(i*math.tau/1128)) for i in range(1128)]
workshop_matrix=Matrix.Translation((.18,17.999989,-23.000017))@Euler((.6,.7,.8)).to_matrix().to_4x4()@Matrix.Diagonal((1.7,.4,1,1))
dense_mesh=poly('Dense rotated translated mesh',[dense_loop],workshop_matrix,mesh=True)
dense_poly=poly('Dense rotated translated POLY',[dense_loop],workshop_matrix)
saved_style=poly('Dense unit-transform tilted workshop mesh',[dense_loop],mesh=True)
local_rotation=Euler((.002,math.pi/2-.0001,.0003)).to_matrix()
for vertex in saved_style.data.vertices:vertex.co=local_rotation@vertex.co
saved_style.location=(.18,17.999989,-23.000017)
baked=poly('Dense baked float32 mesh',[dense_loop],mesh=True)
for vertex in baked.data.vertices:vertex.co=workshop_matrix@vertex.co
far=poly('Dense mesh large translation',[dense_loop],Matrix.Translation((1000,-2000,3000))@workshop_matrix.to_3x3().to_4x4(),mesh=True)
data=bpy.data.curves.new('Dense translated Bezier','CURVE');data.dimensions='2D'
spline=data.splines.new('BEZIER');spline.bezier_points.add(63);spline.use_cyclic_u=True
for i,p in enumerate(spline.bezier_points):
    angle=i*math.tau/64;k=4/3*math.tan(math.pi/128)
    co=Vector((2*math.cos(angle),2*math.sin(angle),0));tangent=Vector((-2*math.sin(angle),2*math.cos(angle),0))
    p.handle_left_type=p.handle_right_type='FREE';p.co=co;p.handle_left=co-k*tangent;p.handle_right=co+k*tangent
dense_bezier=bpy.data.objects.new('Dense rotated translated Bezier',data);bpy.context.collection.objects.link(dense_bezier)
dense_bezier.matrix_world=workshop_matrix;bpy.context.view_layer.update()
for source in [saved_style,dense_mesh,dense_poly,dense_bezier,baked,far]:
    before=source_snapshot(source);prepared=og.prepare_sources([source])
    residual=plane_error(prepared);limit=max(prepared['scale']*2e-6,1e-7)
    assert residual<limit,(source.name,residual,limit)
    assert all(isinstance(prepared[key],Vector) for key in ('origin','u','v','normal'))
    # Projected world loops must remain in the precise source plane even when
    # the Blender output matrix cannot represent a large origin exactly.
    assert max(abs(math.fsum((p[i]-prepared['_origin64'][i])*prepared['_normal64'][i] for i in range(3)))
               for loop in prepared['world_loops'] for p in loop)<limit
    result=og.build_outline(prepared,.05,direction='OUTWARD')
    expected=abs(sum(og._area(loop) for loop in result['border_loops']));filled=evaluated_area(result)
    assert abs(filled-expected)/expected<1e-4,(source.name,filled,expected)
    assert source_snapshot(source)==before
    REPORTS.append({'case':source.name+' remains planar and unchanged','plane_residual':residual,'unchanged_limit':limit,'evaluated_area':filled})

# Truly warped source geometry must still be rejected, including handles that
# leave a plane while the Bezier anchors themselves remain planar.
dense_mesh.data.vertices[0].co.z=.02
before=source_snapshot(dense_mesh);rejects(lambda:og.prepare_sources([dense_mesh]),'one plane')
assert source_snapshot(dense_mesh)==before
dense_bezier.data.splines[0].bezier_points[0].handle_right.z=.02
before=source_snapshot(dense_bezier);rejects(lambda:og.prepare_sources([dense_bezier]),'one plane')
assert source_snapshot(dense_bezier)==before
REPORTS.append({'case':'dense transformed warped vertex and off-plane Bezier handle remain rejected without source edits'})

arch_spans=[cg.line((-1,0,0),(1,0,0)),cg.line((1,0,0),(1,1,0))]
for cx,a,b in [(-1,0,math.pi/3),(1,2*math.pi/3,math.pi)]:
    k=4/3*math.tan((b-a)/4)
    p=(cx+2*math.cos(a),1+2*math.sin(a),0);q=(cx+2*math.cos(b),1+2*math.sin(b),0)
    arch_spans.append((p,(p[0]-2*k*math.sin(a),p[1]+2*k*math.cos(a),0),
                       (q[0]+2*k*math.sin(b),q[1]-2*k*math.cos(b),0),q))
arch_spans.append(cg.line((-1,1,0),(-1,0,0)))
data=bpy.data.curves.new('Pointed arch','CURVE');data.dimensions='2D'
spline=data.splines.new('BEZIER');spline.bezier_points.add(len(arch_spans)-1);spline.use_cyclic_u=True
for i,p in enumerate(spline.bezier_points):
    p.handle_left_type='FREE';p.handle_right_type='FREE';p.co=arch_spans[i][0]
    p.handle_right=arch_spans[i][1];p.handle_left=arch_spans[i-1][2]
obj=bpy.data.objects.new('Pointed arch',data);bpy.context.collection.objects.link(obj)
prepared=og.prepare_sources([obj]);result=og.build_outline(prepared,.05)
assert result['diagnostics']['trimmed_offset_intersections']==1
assert len(result['offset_loops'])==1 and evaluated_area(result)>0
check_width(prepared,result,.05,prepared['tolerance']*1.1)
REPORTS.append({'case':'pointed arch dense arc offsets trim cleanly at convex apex'})

def world_xy(prepared,loop):
    return [tuple(prepared['_origin64'][i]+prepared['_u64'][i]*x+prepared['_v64'][i]*y for i in range(3)) for x,y in loop]

# A sharp join is the intersection of parallel edge offsets, not a round cap
# or a clamped miter. This analytic triangle has an arbitrarily acute apex.
for height in (5.,100.):
    source=poly('Acute sharp tip '+str(height),[[(-1,0),(1,0),(0,height)]])
    before=source_snapshot(source);prepared=og.prepare_sources([source]);width=.1
    result=og.build_outline(prepared,width,direction='OUTWARD',join_style='MITER')
    assert len(result['offset_loops'][0])==3 and result['offset_correspondence']==[[0,1,2]]
    tip=max(world_xy(prepared,result['offset_loops'][0]),key=lambda p:p[1])
    expected=height+width*math.sqrt(height*height+1)
    assert abs(tip[0])<1e-10 and abs(tip[1]-expected)<1e-10,(tip,expected)
    assert result['diagnostics']['round_join_chord_error_bound']==0
    assert source_snapshot(source)==before
    REPORTS.append({'case':f'MITER preserves acute {height:g}-unit tip without rounding or clamping','tip_extension':tip[1]-height})

# The sampled Gothic arch approaches the analytic tangent-defined apex within
# 0.1 mm at this scale; ROUND remains an explicitly different corner option.
prepared=og.prepare_sources([obj]);sharp=og.build_outline(prepared,.05,direction='OUTWARD',join_style='MITER')
rounded=og.build_outline(prepared,.05,direction='OUTWARD',join_style='ROUND')
sharp_tip=max(p[1] for loop in sharp['offset_loops'] for p in world_xy(prepared,loop))
round_tip=max(p[1] for loop in rounded['offset_loops'] for p in world_xy(prepared,loop))
assert abs(sharp_tip-(1+math.sqrt(3)+.05*2/math.sqrt(3)))<1e-4,(sharp_tip,round_tip,prepared['tolerance'])
assert sharp_tip-round_tip>.005,(sharp_tip,round_tip)
assert sharp['offset_correspondence'][0] is not None and not sharp['offset_trimmed'][0]
inward=og.build_outline(prepared,.05,join_style='MITER')
assert inward['offset_trimmed'][0] and inward['offset_correspondence'][0] is None
for result in (sharp,inward):
    expected=abs(sum(og._area(loop) for loop in result['border_loops']))
    assert abs(evaluated_area(result)-expected)/expected<1e-4
REPORTS.append({'case':'curved Gothic arch sharp apex, optional ROUND and trimmed sharp inward fill','sharp_tip':sharp_tip,'round_tip':round_tip})

source=poly('Sharp concave L',[[(0,0),(3,0),(3,1),(1,1),(1,3),(0,3)]])
prepared=og.prepare_sources([source])
for direction in ('INWARD','OUTWARD'):
    result=og.build_outline(prepared,.15,direction=direction,join_style='MITER')
    assert len(result['offset_loops'][0])==6 and result['offset_correspondence'][0]==list(range(6))
    expected=abs(sum(og._area(loop) for loop in result['border_loops']))
    assert abs(evaluated_area(result)-expected)<1e-5
REPORTS.append({'case':'sharp concave corners preserve closed topology in both directions'})

# Adjacent short segments overrun a concave corner, requiring CDT cleanup in
# the same loop as a long sharp apex. Cleanup must retain that legitimate miter
# extension even though it lies farther than width from the original boundary.
corners=[(0,0),(3,0),(3,1),(1,1),(1,2),(2,2),(0,20),(-2,2),(0,2)]
dense=[]
for a,b in zip(corners,corners[1:]+corners[:1]):
    count=math.ceil(math.dist(a,b)/.04)
    dense.extend((a[0]+(b[0]-a[0])*i/count,a[1]+(b[1]-a[1])*i/count) for i in range(count))
source=poly('Sharp apex beside offset overrun',[dense]);prepared=og.prepare_sources([source])
# Polyline simplification normally removes collinear subdivision. Retain it in
# this focused cleanup fixture to exercise the short-edge overrun explicitly.
inverse=prepared['matrix_world'].inverted()
prepared['loops']=[[(p.x,p.y) for p in (inverse@Vector((x,y,0)) for x,y in dense)]]
result=og.build_outline(prepared,.1,direction='OUTWARD',join_style='MITER')
assert result['offset_trimmed'][0] and result['offset_correspondence'][0] is None
tip=max(p[1] for p in world_xy(prepared,result['offset_loops'][0]))
assert abs(tip-(20+.1*math.sqrt(18*18+4)/2))<prepared['tolerance']*.1
expected=abs(sum(og._area(loop) for loop in result['border_loops']))
assert abs(evaluated_area(result)-expected)/expected<1e-4
REPORTS.append({'case':'CDT concave overrun cleanup retains long valid miter apex','tip':tip})

source=poly('Sharp hole',[square,[(-1,-1),(1,-1),(1,1),(-1,1)]])
prepared=og.prepare_sources([source]);result=og.build_outline(prepared,.2,direction='OUTWARD',join_style='MITER')
assert all(len(loop)==4 for loop in result['offset_loops']) and abs(evaluated_area(result)-4.8)<1e-5
rejects(lambda:og.build_outline(prepared,.2,join_style='BEVEL'),'Join style')
source=poly('Sharp genuine collapse',[[(-1,0),(1,0),(0,5)]])
prepared=og.prepare_sources([source]);rejects(lambda:og.build_outline(prepared,1.,join_style='MITER'))
REPORTS.append({'case':'sharp hole fill is hollow and genuine sharp collapse remains rejected'})

# A complete Gothic four-lobe construction, through the actual Shape Builder
# output path. Outside offsets must remove inverted concave-notch fragments,
# remain hollow when Blender evaluates them, and work after mesh conversion.
for selected in bpy.context.selected_objects:selected.select_set(False)
sources=[]
for arm in range(4):
    angle=arm*math.pi/2
    for label,x,y,r in [('C',0,2.065,.45),('L',-.3,1.12,.65),('R',.3,1.12,.65)]:
        cx=x*math.cos(angle)-y*math.sin(angle);cy=x*math.sin(angle)+y*math.cos(angle)
        obj=circle(f'Gothic {arm}{label}',r,Matrix.Translation((cx,cy,0)));obj.select_set(True);sources.append(obj)
bpy.context.view_layer.update();arr,_=sb.build_pen_arrangement(bpy.context)
union_data=cg.curve_data(arr,set(range(len(arr['regions']))));union_obj=bpy.data.objects.new('Gothic union',union_data)
bpy.context.collection.objects.link(union_obj)
matrix=Matrix.Identity(4)
for i,axis in enumerate((arr['u'],arr['v'],arr['normal'])):
    for j in range(3):matrix[j][i]=axis[j]
matrix.translation=arr['origin'];union_obj.matrix_world=matrix
bpy.context.view_layer.update();evaluated=union_obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
mesh=bpy.data.meshes.new_from_object(evaluated);mesh_obj=bpy.data.objects.new('Dense Gothic union mesh',mesh)
bpy.context.collection.objects.link(mesh_obj);mesh_obj.matrix_world=matrix;bpy.context.view_layer.update()
for source in [union_obj,mesh_obj]:
    precise=og.prepare_sources([source]);preview=og.prepare_sources([source],tolerance=precise['scale']*5e-4)
    for mode,prepared in [('precise',precise),('preview',preview)]:
        start=time.perf_counter();result=og.build_outline(prepared,.14,direction='OUTWARD');elapsed=time.perf_counter()-start
        assert result['diagnostics']['topology_preserved'] and len(result['border_loops'])==2
        expected=abs(sum(og._area(loop) for loop in result['border_loops']));filled=evaluated_area(result)
        assert abs(filled-expected)/expected<1e-4,(filled,expected)
        # Check the generated boundary against all original source edges, not
        # merely the local edge that produced it. A notch spike fails this.
        check_width(prepared,result,.14,prepared['tolerance']*3.1,max_samples=256)
        assert elapsed<2.,('Unexpected quadratic outline regression',elapsed)
        REPORTS.append({'case':f'Gothic .14 outside {source.type} {mode}','seconds':elapsed,'points':result['diagnostics']['poly_points'],'evaluated_area':filled})
    if source.type=='MESH':
        assert len(preview['loops'][0])<len(precise['loops'][0])*.6
        # Every original mesh boundary sample stays within the promised preview
        # chord tolerance. Sharp cusp vertices must not move or be flattened.
        edges=[(a,b) for loop in preview['loops'] for a,b in zip(loop,loop[1:]+loop[:1])]
        inverse=preview['matrix_world'].inverted()
        for segment in preview['world_segments']:
            point=inverse@Vector(segment['cp'][0]);point=(point.x,point.y)
            assert min(og._point_segment_sq(point,a,b) for a,b in edges)<(preview['tolerance']*1.01)**2
        source_loop=precise['loops'][0]
        for i,p in enumerate(source_loop):
            incoming=og._sub(p,source_loop[i-1]);outgoing=og._sub(source_loop[(i+1)%len(source_loop)],p)
            turn=math.atan2(og._cross(incoming,outgoing),og._dot(incoming,outgoing))
            if abs(turn)>.3:
                # Same preparation basis is independent of sampling tolerance.
                assert min(math.dist(p,q) for q in preview['loops'][0])<1e-7
        REPORTS.append({'case':'dense mesh preview chord bound and sharp cusp preservation'})
    for width in (.05,.14):
        before=source_snapshot(source);start=time.perf_counter()
        result=og.build_outline(precise,width,direction='OUTWARD',join_style='MITER');elapsed=time.perf_counter()-start
        expected=abs(sum(og._area(loop) for loop in result['border_loops']));filled=evaluated_area(result)
        assert len(result['border_loops'])==2 and abs(filled-expected)/expected<1e-4
        assert elapsed<2. and source_snapshot(source)==before
        check_width(precise,result,width,precise['tolerance']*3.1,max_samples=256)
        REPORTS.append({'case':f'Gothic sharp {width} outside {source.type}','seconds':elapsed,'evaluated_area':filled,'trimmed':result['offset_trimmed']})

directory=Path(__file__).parent/'_artifacts';directory.mkdir(exist_ok=True)
(directory/'outline_geometry_report.json').write_text(json.dumps(REPORTS,indent=2))
print(json.dumps(REPORTS,indent=2));print('PASS Make Outline geometry',len(REPORTS),'checks')
