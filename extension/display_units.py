"""Roblox stud readouts without changing scene scale or model coordinates."""
import bpy
from bpy.props import EnumProperty,FloatProperty

def factor(context=None):
    context=context or bpy.context
    return context.scene.unit_settings.scale_length/.28

def studs(context=None):
    return getattr((context or bpy.context).window_manager,'harhtools_distance_units','STUDS')=='STUDS'

def distance_property(source,label,minimum=0):
    return FloatProperty(name=label+' (studs)',precision=3,step=1,min=minimum,options={'SKIP_SAVE'},
        description='Roblox studs, converted from scene scale; 1 stud = 0.28 m',
        get=lambda self:getattr(self,source)*factor(),
        set=lambda self,value:setattr(self,source,value/factor()))

def draw(layout,cfg,name,context,**kwargs):
    if studs(context):
        name+='_studs'
        if 'text' in kwargs:kwargs['text']+=' (studs)'
    layout.prop(cfg,name,**kwargs)

def format_length(context,value):
    if studs(context):
        amount=value*factor(context)
        return (f'{amount:.3f}' if abs(amount)>=.001 or amount==0 else f'{amount:.3g}')+' studs'
    units=context.scene.unit_settings
    return bpy.utils.units.to_string(units.system,'LENGTH',value*units.scale_length,precision=4)

def register():
    bpy.types.WindowManager.harhtools_distance_units=EnumProperty(name='Distances',default='STUDS',items=[
        ('STUDS','Roblox Studs','Use Roblox units in Harhtools; no geometry or scene scale changes'),
        ('SCENE','Scene Units','Use Blender scene length units')])

def unregister():
    if hasattr(bpy.types.WindowManager,'harhtools_distance_units'):del bpy.types.WindowManager.harhtools_distance_units
