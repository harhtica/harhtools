"""Editable depth and perimeter-only bevels for flat mesh borders."""
import math
import json
from collections import Counter
import bpy
from . import outline_profiles

DEPTH_NAME='Harhtools Border Depth'
BEVEL_NAME='Harhtools Border Bevel'
WEIGHT_NAME='harhtools_border_bevel_weight'
PROFILES={'ROUND':.5,'CHAMFER':.25,'CONCAVE':.15,'SQUARE':.75}
DEPTH_PROPS=('thickness','offset','use_even_offset','bevel_convex')
BEVEL_PROPS=('limit_method','edge_weight','offset_type','width','segments','profile_type',
             'profile','affect','miter_outer','miter_inner','use_clamp_overlap','harden_normals')


def weight_name():
    # Blender 4.2 uses the fixed attribute; newer versions can name it.
    return WEIGHT_NAME if 'edge_weight' in bpy.types.BevelModifier.bl_rna.properties else 'bevel_weight_edge'


def _weights(obj):
    if obj.type!='MESH' or not obj.data.polygons:
        raise ValueError('Select a flat mesh border with faces to bevel.')
    data=obj.data
    counts=Counter(tuple(sorted((a,b))) for face in data.polygons
                   for a,b in zip(list(face.vertices),list(face.vertices)[1:]+list(face.vertices)[:1]))
    if not counts or any(count>2 for count in counts.values()) or not any(count==1 for count in counts.values()):
        raise ValueError('Border Bevel needs a flat mesh with open perimeter edges.')
    origin=data.vertices[data.polygons[0].vertices[0]].co
    normal=data.polygons[0].normal
    extent=max((v.co-origin).length for v in data.vertices)
    if normal.length<.5 or any(abs(math.fsum((v.co[i]-origin[i])*normal[i] for i in range(3)))>max(extent*2e-6,1e-7) for v in data.vertices):
        raise ValueError('Border Bevel adds depth to flat faces; use it on the original flat border.')
    existing=data.attributes.get(weight_name())
    if existing and (existing.data_type!='FLOAT' or existing.domain!='EDGE'):
        raise ValueError('The border bevel weight attribute has an incompatible type.')
    for name,kind in ((DEPTH_NAME,'SOLIDIFY'),(BEVEL_NAME,'BEVEL')):
        mod=obj.modifiers.get(name)
        if mod and mod.type!=kind:raise ValueError('A different modifier already uses a Harhtools border modifier name.')
    names=[mod.name for mod in obj.modifiers]
    if BEVEL_NAME in names and (DEPTH_NAME not in names or names.index(BEVEL_NAME)<names.index(DEPTH_NAME)):
        raise ValueError('Place Harhtools Border Depth before Harhtools Border Bevel in the modifier stack.')
    return [1.0 if counts[tuple(sorted(edge.vertices))]==1 else 0.0 for edge in data.edges]


def _configure(obj,depth,width,segments,profile,shape,attribute_name,profile_data=''):
    solid=obj.modifiers.get(DEPTH_NAME) or obj.modifiers.new(DEPTH_NAME,'SOLIDIFY')
    solid.thickness=depth;solid.offset=-1;solid.use_even_offset=True;solid.bevel_convex=0
    bevel=obj.modifiers.get(BEVEL_NAME) or obj.modifiers.new(BEVEL_NAME,'BEVEL')
    bevel.limit_method='WEIGHT'
    if hasattr(bevel,'edge_weight'):bevel.edge_weight=attribute_name
    bevel.offset_type='OFFSET';bevel.width=width
    bevel.segments=1 if profile=='CHAMFER' else segments
    bevel.profile_type='SUPERELLIPSE';bevel.profile=shape;bevel.affect='EDGES'
    if profile in outline_profiles.NAMES:
        bevel.profile_type='CUSTOM'
        outline_profiles.configure(bevel.custom_profile,profile,segments)
    elif profile=='EDITED':
        bevel.profile_type='CUSTOM'
        outline_profiles.restore(bevel.custom_profile,json.loads(profile_data),segments)
    bevel.miter_outer='MITER_SHARP';bevel.miter_inner='MITER_SHARP'
    bevel.use_clamp_overlap=True;bevel.harden_normals=True
    obj.update_tag()


def apply(objects,*,depth,width,segments=6,profile='ROUND',custom_shape=.5,profile_data=''):
    """Update only our modifiers/weights, rolling back the whole batch on failure."""
    depth=float(depth);width=float(width);segments=int(segments)
    shape=float(custom_shape) if profile=='CUSTOM' else .5 if profile in outline_profiles.NAMES or profile=='EDITED' else PROFILES.get(profile)
    if profile=='EDITED' and not profile_data:raise ValueError('Choose or edit a custom profile first.')
    if not all(math.isfinite(v) and v>0 for v in (depth,width)):
        raise ValueError('Border depth and bevel width must be positive.')
    if shape is None or not math.isfinite(shape) or not 0<=shape<=1 or not 1<=segments<=128:
        raise ValueError('Choose a valid bevel profile and 1 to 128 segments.')
    objects=list(objects)
    if not objects:raise ValueError('Select a mesh border to update its bevel.')
    plans=[(obj,_weights(obj)) for obj in objects]
    attribute_name=weight_name()
    snapshots=[]
    try:
        for obj,weights in plans:
            attr=obj.data.attributes.get(attribute_name)
            saved=dict(obj=obj,weights=[p.value for p in attr.data] if attr else None,
                       custom_profile=outline_profiles.snapshot(obj.modifiers[BEVEL_NAME].custom_profile) if obj.modifiers.get(BEVEL_NAME) else None,
                       modifiers={name:({key:getattr(obj.modifiers[name],key) for key in props if hasattr(obj.modifiers[name],key)} if obj.modifiers.get(name) else None)
                                  for name,props in ((DEPTH_NAME,DEPTH_PROPS),(BEVEL_NAME,BEVEL_PROPS))})
            snapshots.append(saved)
            if attr is None:attr=obj.data.attributes.new(attribute_name,'FLOAT','EDGE')
            for item,value in zip(attr.data,weights):item.value=value
            if profile_data:_configure(obj,depth,width,segments,profile,shape,attribute_name,profile_data)
            else:_configure(obj,depth,width,segments,profile,shape,attribute_name)
        return objects
    except Exception:
        for saved in reversed(snapshots):
            obj=saved['obj'];attr=obj.data.attributes.get(attribute_name)
            if saved['weights'] is None:
                if attr:obj.data.attributes.remove(attr)
            elif attr:
                for item,value in zip(attr.data,saved['weights']):item.value=value
            for name,properties in saved['modifiers'].items():
                mod=obj.modifiers.get(name)
                if properties is None:
                    if mod:obj.modifiers.remove(mod)
                elif mod:
                    for key,value in properties.items():setattr(mod,key,value)
                    if name==BEVEL_NAME and saved['custom_profile'] is not None:
                        outline_profiles.restore(mod.custom_profile,saved['custom_profile'],mod.segments)
            obj.update_tag()
        raise


def options(cfg):
    result=dict(depth=cfg.bevel_depth,width=cfg.bevel_width,segments=cfg.bevel_segments,
                profile=cfg.bevel_profile,custom_shape=cfg.bevel_shape)
    if cfg.bevel_profile=='EDITED':
        from . import profile_editor
        result['profile_data']=profile_editor.serialize(cfg.edited_profile)
    return result
