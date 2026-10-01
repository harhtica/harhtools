"""Recoverable circle/arc controls with a fixed full-circle sampling grid."""
import json
import math
import bpy
from mathutils import Vector
from bpy.props import BoolProperty,FloatProperty,IntProperty,PointerProperty,StringProperty

_updating=False
BUSY=('arch_tools_shape_builder','harhtools_outline_preview','harhtools_array_preview')


def definition(obj):
    if obj.type=='MESH':
        data=obj.data;n=len(data.vertices)
        if not 3<=n<=8192 or len(data.edges)!=n or len(data.polygons)>1:raise ValueError('Select a single complete circle outline.')
        neighbors=[[] for _ in range(n)]
        for edge in data.edges:
            a,b=edge.vertices;neighbors[a].append(b);neighbors[b].append(a)
        if any(len(row)!=2 for row in neighbors):raise ValueError('The circle must be one closed, unbranched loop.')
        order=[0];previous=-1;current=0
        while True:
            following=next(i for i in sorted(neighbors[current]) if i!=previous)
            if following==0:break
            if following in order:raise ValueError('Select one circle, not disconnected loops.')
            order.append(following);previous,current=current,following
        if len(order)!=n:raise ValueError('Select one circle, not disconnected loops.')
        points=[tuple(data.vertices[i].co) for i in order];segments=n
    elif obj.type=='CURVE':
        if len(obj.data.splines)!=1:raise ValueError('Select a single circle spline.')
        spline=obj.data.splines[0]
        if not spline.use_cyclic_u or spline.type not in {'POLY','BEZIER'}:raise ValueError('Select a closed Poly or Bezier circle.')
        points=[tuple(p.co[:3]) for p in (spline.bezier_points if spline.type=='BEZIER' else spline.points)]
        if len(points)<3:raise ValueError('The circle needs at least three anchors.')
        segments=len(points)*(max(1,obj.data.resolution_u) if spline.type=='BEZIER' else 1)
    else:raise ValueError('Select a mesh or curve circle.')
    # Work in local coordinates; transforms, center and radius never change.
    p=Vector(points[0]);a=max((Vector(q)-p for q in points),key=lambda q:q.length_squared)
    b=max((Vector(q)-p for q in points),key=lambda q:a.cross(q).length_squared)
    normal=a.cross(b)
    if normal.length_squared<1e-24:raise ValueError('This outline is not a circle.')
    center=p+(a.length_squared*b.cross(normal)+b.length_squared*normal.cross(a))/(2*normal.length_squared)
    radius=(p-center).length
    if radius<1e-9:raise ValueError('This circle has zero radius.')
    normal.normalize();u=(p-center).normalized();v=normal.cross(u).normalized()
    if (Vector(points[1])-center).dot(v)<0:v.negate();normal.negate()
    tolerance=max(radius*2e-4,1e-7)
    if any(abs((Vector(q)-center).dot(normal))>tolerance or abs((Vector(q)-center).length-radius)>tolerance for q in points):
        raise ValueError('The selected outline is not circular. Original geometry was not changed.')
    if obj.type=='CURVE' and spline.type=='BEZIER':
        # Four corner anchors alone also describe a square: require curved,
        # tangential handles before treating those anchors as a circle.
        for anchor in spline.bezier_points:
            radial=(anchor.co-center).normalized()
            for handle in (anchor.handle_left,anchor.handle_right):
                delta=handle-anchor.co
                if delta.length<radius*.01 or abs(delta.dot(radial))>max(tolerance,delta.length*.002):
                    raise ValueError('Select a circular Bezier spline with tangent handles.')
        samples=[]
        for i in range(segments):
            t=math.tau*i/segments;samples.append(tuple(center+radius*(u*math.cos(t)+v*math.sin(t))))
        points=samples
    angles=[math.atan2((Vector(q)-center).dot(v),(Vector(q)-center).dot(u))%math.tau for q in points]
    angles=[0. if min(t,math.tau-t)<1e-6 else t for t in angles]
    return dict(center=list(center),u=list(u),v=list(v),radius=radius,segments=segments,
                points=points,angles=angles,original_properties={k:obj[k] for k in
                ('harh_circle','harh_arc_role','harh_arc_intervals') if k in obj})


def geometry(info,segments,start,amount):
    full=amount>=math.tau-1e-6;start=start%math.tau
    grid=list(zip(info['angles'],info['points'])) if segments==info['segments'] else [
        (math.tau*i/segments,None) for i in range(segments)]
    def point(t):
        return tuple(info['center'][i]+info['radius']*(info['u'][i]*math.cos(t)+info['v'][i]*math.sin(t)) for i in range(3))
    if full:
        # Start chooses the cut, not a new sampling phase. Full circles and
        # partial arcs share the same grid so changing angle keeps snaps stable.
        coords=[tuple(q) if q is not None else point(t) for t,q in grid]
    else:
        rows=[((t-start)%math.tau,q,t) for t,q in grid if 1e-6<(t-start)%math.tau<amount-1e-6]
        coords=[point(start)]+[tuple(q) if q is not None else point(t) for _,q,t in sorted(rows)]+[point(start+amount)]
    edges=[(i,i+1) for i in range(len(coords)-1)]
    if full:edges.append((len(coords)-1,0))
    return coords,edges,full


def rebuild(cfg):
    obj=cfg.id_data;info=json.loads(cfg.definition)
    coords,edges,full=geometry(info,cfg.segments,cfg.start_angle,cfg.arc_amount)
    original=obj.data;data=original.copy();name=original.name
    try:
        if obj.type=='MESH':
            data.clear_geometry();data.from_pydata(coords,edges,[tuple(range(len(coords)))] if cfg.fill and len(coords)>2 else [])
            data.update()
        else:
            data.splines.clear();spline=data.splines.new('POLY');spline.points.add(len(coords)-1);spline.use_cyclic_u=full or cfg.fill
            for p,co in zip(spline.points,coords):p.co=(*co,1)
            data.fill_mode='BOTH' if cfg.fill else 'NONE'
        obj.data=data
    except Exception:
        (bpy.data.meshes if obj.type=='MESH' else bpy.data.curves).remove(data);raise
    if original.users==0:
        (bpy.data.meshes if obj.type=='MESH' else bpy.data.curves).remove(original);data.name=name
    # Shape Builder must use these actual polygon/arc edges, including triangles.
    if 'harh_circle' in obj:obj['harh_circle']=False
    cfg.error=''


def changed(cfg,context):
    if _updating or not cfg.active:return
    try:rebuild(cfg)
    except Exception as exc:cfg.error=str(exc)


class HARHTOOLS_PG_circle_arc(bpy.types.PropertyGroup):
    active:BoolProperty(default=False)
    source_mesh:PointerProperty(type=bpy.types.Mesh)
    source_curve:PointerProperty(type=bpy.types.Curve)
    definition:StringProperty()
    error:StringProperty()
    segments:IntProperty(name='Sides / Segments',default=64,min=3,max=8192,soft_max=512,update=changed,
                         description='Full-circle resolution: 3 gives a triangle; more sides approach a circle')
    start_angle:FloatProperty(name='Start Angle',default=0,min=0,max=math.tau,subtype='ANGLE',update=changed)
    arc_amount:FloatProperty(name='Arc Amount',default=math.tau,min=math.radians(.01),max=math.tau,subtype='ANGLE',update=changed)
    fill:BoolProperty(name='Fill',default=False,update=changed,description='Close and fill the outline; partial arcs close with a straight chord')


class OBJECT_OT_harhtools_edit_circle(bpy.types.Operator):
    bl_idname='object.harhtools_edit_circle';bl_label='Edit Circle / Arc';bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):
        return context.mode=='OBJECT' and context.active_object is not None and context.active_object.type in {'MESH','CURVE'} and not any(bpy.app.driver_namespace.get(k) for k in BUSY)
    def execute(self,context):
        global _updating
        obj=context.active_object;cfg=obj.harhtools_circle_arc
        if cfg.active:return {'FINISHED'}
        try:
            info=definition(obj);_updating=True
            cfg.definition=json.dumps(info);cfg.segments=info['segments'];cfg.start_angle=0;cfg.arc_amount=math.tau
            cfg.fill=bool(obj.data.polygons) if obj.type=='MESH' else obj.data.dimensions=='2D' and obj.data.fill_mode!='NONE'
            if obj.type=='MESH':cfg.source_mesh=obj.data
            else:cfg.source_curve=obj.data
            cfg.active=True
            # Preserve the initial circle exactly until the first slider edit.
            obj.data=obj.data.copy();obj.data.name=obj.name+' Arc'
            cfg.error='';return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}
        finally:_updating=False


class OBJECT_OT_harhtools_restore_circle(bpy.types.Operator):
    bl_idname='object.harhtools_restore_circle';bl_label='Restore Original Circle';bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):
        return OBJECT_OT_harhtools_edit_circle.poll(context) and context.active_object.harhtools_circle_arc.active
    def execute(self,context):
        obj=context.active_object;cfg=obj.harhtools_circle_arc;source=cfg.source_mesh or cfg.source_curve
        if source is None:self.report({'ERROR'},'The original circle data is missing.');return {'CANCELLED'}
        old=obj.data;info=json.loads(cfg.definition);obj.data=source
        for key,value in info.get('original_properties',{}).items():obj[key]=value
        cfg.active=False;cfg.source_mesh=None;cfg.source_curve=None;cfg.definition='';cfg.error=''
        if old.users==0:(bpy.data.meshes if obj.type=='MESH' else bpy.data.curves).remove(old)
        return {'FINISHED'}


def draw_panel(layout,context):
    obj=context.active_object
    if obj is None or obj.type not in {'MESH','CURVE'}:return
    cfg=obj.harhtools_circle_arc
    if not cfg.active:
        try:info=definition(obj)
        except ValueError:return
    box=layout.box();box.label(text='Circle / Arc')
    controls=box.column();controls.enabled=context.mode=='OBJECT' and not any(bpy.app.driver_namespace.get(k) for k in BUSY)
    if not cfg.active:
        controls.label(text=f'Current resolution: {info["segments"]}')
        controls.operator('object.harhtools_edit_circle',icon='CURVE_BEZCIRCLE')
        return
    controls.prop(cfg,'segments',slider=True);controls.prop(cfg,'start_angle',slider=True)
    controls.prop(cfg,'arc_amount',slider=True)
    if obj.type=='MESH' or obj.data.dimensions=='2D':controls.prop(cfg,'fill')
    if obj.type=='MESH':
        triangles=sum(len(face.vertices)-2 for face in obj.data.polygons)
        controls.label(text=f'{len(obj.data.vertices)} vertices · {triangles} triangles')
    else:controls.label(text=f'{len(obj.data.splines[0].points)} points · Poly curve')
    controls.label(text='3 sides = triangle · 360° = closed')
    controls.operator('object.harhtools_restore_circle',icon='LOOP_BACK')
    if cfg.error:box.label(text=cfg.error,icon='ERROR')


CLASSES=(HARHTOOLS_PG_circle_arc,OBJECT_OT_harhtools_edit_circle,OBJECT_OT_harhtools_restore_circle)
def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Object.harhtools_circle_arc=PointerProperty(type=HARHTOOLS_PG_circle_arc)
def unregister():
    if hasattr(bpy.types.Object,'harhtools_circle_arc'):del bpy.types.Object.harhtools_circle_arc
    for cls in reversed(CLASSES):
        if hasattr(cls,'bl_rna'):
            try:bpy.utils.unregister_class(cls)
            except RuntimeError:pass
