"""Real Shader Editor texture routing, ordered layout and cancellable tweens."""
import bpy,sys,json,time
from pathlib import Path
from types import SimpleNamespace
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import texture_connect as t


def fixture():
    mat=bpy.data.materials.new('Texture button test');mat.use_nodes=True
    tree=mat.node_tree;shader=next(n for n in tree.nodes if n.type=='BSDF_PRINCIPLED')
    for node in tree.nodes:node.select=False
    shader.location=(500,100)
    nodes={}
    # The exact four suffixes shown in the user's Shader Editor screenshot.
    for index,(role,suffix) in enumerate(zip(t.ROLES,('ColorMap','MetalnessMap','RoughnessMap','NormalMap'))):
        image=bpy.data.images.new('DefaultMaterial1_'+suffix+'.png',width=2,height=2,alpha=True)
        image.pixels=[.5,.5,1.,1.]*4;image.colorspace_settings.name='sRGB'
        node=tree.nodes.new('ShaderNodeTexImage');node.image=image;node.select=True
        node.location=(-100+index*70,-index*50);nodes[role]=node
    tree.nodes.active=nodes['Normal']
    return mat,tree,shader,nodes


def linked(source,target):return any(link.from_socket==source for link in target.links)
def check(result):
    shader=result['shader'];nodes=result['maps']
    for role in ('Base Color','Metallic','Roughness'):
        assert linked(nodes[role].outputs['Color'],shader.inputs[role])
    normal=shader.inputs['Normal'].links[0].from_node
    assert normal.bl_idname=='ShaderNodeNormalMap' and normal.space=='TANGENT'
    assert linked(nodes['Normal'].outputs['Color'],normal.inputs['Color'])
    assert all(nodes[role].image.colorspace_settings.name=='Non-Color' for role in ('Metallic','Roughness','Normal'))
    assert nodes['Base Color'].image.colorspace_settings.name=='sRGB'
    return normal


t.register()
try:
    mat,tree,shader,nodes=fixture()
    result=t.connect_textures(tree);normal=check(result)
    assert not result['alpha'] and not shader.inputs['Alpha'].is_linked,'Opaque RGBA should not enable alpha'
    counts=(len(tree.nodes),len(tree.links),len(bpy.data.images))
    repeated=t.connect_textures(tree)
    assert check(repeated)==normal and counts==(len(tree.nodes),len(tree.links),len(bpy.data.images)),'Repeat must not duplicate converters, links or images'
    pixels=[.5,.5,.5,1.]*4;pixels[-1]=.35
    nodes['Base Color'].image.pixels=pixels
    result=t.connect_textures(tree)
    assert result['alpha'] and linked(nodes['Base Color'].outputs['Alpha'],shader.inputs['Alpha'])
    nodes['Base Color'].image.alpha_mode='CHANNEL_PACKED'
    assert not t.transparent_alpha(nodes['Base Color'].image)
    nodes['Base Color'].image.alpha_mode='NONE'
    assert not t.transparent_alpha(nodes['Base Color'].image)
    for filename,role in [('stone_base_color_2K.png','Base Color'),('stone_albedo.jpg','Base Color'),
                          ('stone_METALLIC.tif','Metallic'),('stone_RoughnessMap.png','Roughness'),
                          ('stone_nor_gl_4k.exr','Normal'),('stone_NormalGL.png','Normal'),
                          ('stone_AO.png',None),('stone_ORM.png',None),('stone_MetallicRoughness.png',None),
                          ('stone_OcclusionRoughnessMetallic.png',None),('abnormal.png',None)]:
        assert t.role_from_name(filename)==role,(filename,t.role_from_name(filename))
    # Selected duplicates must be resolved before any graph or image change.
    extra=tree.nodes.new('ShaderNodeTexImage');extra.image=nodes['Roughness'].image;extra.select=True
    before=t._snapshot(tree)
    try:t.connect_textures(tree);raise AssertionError('Expected ambiguous map rejection')
    except ValueError as exc:assert 'Multiple Roughness' in str(exc)
    assert before['links']==[(l.from_socket,l.to_socket) for l in tree.links]
    extra.select=False
    assert t.connect_textures(tree)['maps']['Roughness']==nodes['Roughness']
    # A shared image's global color space must not change another material.
    mat2,tree2,shader2,nodes2=fixture()
    other=bpy.data.materials.new('Other image user');other.use_nodes=True
    shared=nodes2['Metallic'].image
    other_node=other.node_tree.nodes.new('ShaderNodeTexImage');other_node.image=shared
    t.connect_textures(tree2)
    assert other_node.image==shared and shared.colorspace_settings.name=='sRGB'
    assert nodes2['Metallic'].image!=shared and nodes2['Metallic'].image.colorspace_settings.name=='Non-Color'
    # Missing shader/output are created and wired without duplicate nodes.
    mat3,tree3,shader3,nodes3=fixture();tree3.nodes.remove(shader3)
    for n in list(tree3.nodes):
        if n.type=='OUTPUT_MATERIAL':tree3.nodes.remove(n)
    result3=t.connect_textures(tree3);check(result3)
    output=next(n for n in tree3.nodes if n.type=='OUTPUT_MATERIAL')
    assert linked(result3['shader'].outputs['BSDF'],output.inputs['Surface'])
    # Button uses a real Node Editor area and real Blender operator routing.
    obj=bpy.context.active_object;obj.data.materials.clear();obj.data.materials.append(mat3)
    area=bpy.context.screen.areas[0];area.type='NODE_EDITOR';area.spaces.active.tree_type='ShaderNodeTree'
    with bpy.context.temp_override(area=area,region=next(r for r in area.regions if r.type=='WINDOW')):
        assert t.NODE_OT_harhtools_connect_textures.poll(bpy.context)
        assert bpy.ops.node.harhtools_connect_textures('EXEC_DEFAULT')=={'FINISHED'}
        ys=[t._position(nodes3[role]).y for role in t.ROLES]
        assert all(a>b for a,b in zip(ys,ys[1:])),ys
        assert len({round(t._position(nodes3[role]).x,5) for role in t.ROLES})==1
    # Staggered movement and sequential links use the same implementation as UI.
    mat4,tree4,shader4,nodes4=fixture();snapshot=t._snapshot(tree4)
    result4=t.connect_textures(tree4);targets={n:Vector(p) for n,p in t.layout_targets(result4).items()}
    starts={n:t._position(n) for n in targets};steps=t.connection_steps(result4)
    t._restore_links(tree4,snapshot['links'])
    state=SimpleNamespace(_tree=tree4,_targets=targets,_starts=starts,_steps=steps,_connected=0,_area=None)
    t.NODE_OT_harhtools_connect_textures._tick(state,.25)
    assert nodes4['Base Color'].outputs['Color'].is_linked and not nodes4['Normal'].outputs['Color'].is_linked
    assert (t._position(nodes4['Base Color'])-starts[nodes4['Base Color']]).length>0
    assert (t._position(nodes4['Base Color'])-targets[nodes4['Base Color']]).length>0
    t._restore(tree4,snapshot)
    assert snapshot['nodes']==set(tree4.nodes)
    assert all(n.location==p for n,p in snapshot['positions'].items())
    assert all(image.colorspace_settings.name==space for image,space in snapshot['spaces'].items())
    result4=t.connect_textures(tree4);state._targets={n:Vector(p) for n,p in t.layout_targets(result4).items()}
    state._starts={n:t._position(n) for n in state._targets};state._steps=t.connection_steps(result4);state._connected=0
    t._restore_links(tree4,snapshot['links']);t.NODE_OT_harhtools_connect_textures._tick(state,1.)
    check(result4)
    assert all((t._position(n)-p).length<1e-5 for n,p in state._targets.items())
    assert 'UNDO' in t.NODE_OT_harhtools_connect_textures.bl_options
    calls=[]
    layout=SimpleNamespace(separator=lambda:None,operator=lambda *args,**kwargs:calls.append((args,kwargs)))
    context=SimpleNamespace(space_data=SimpleNamespace(type='NODE_EDITOR',tree_type='ShaderNodeTree',shader_type='OBJECT'))
    t.draw_header(SimpleNamespace(layout=layout),context)
    assert calls[0][0]==('node.harhtools_connect_textures',) and calls[0][1]['text']=='Connect Textures'
    for kind,shader_type in [('ShaderNodeTree','WORLD'),('GeometryNodeTree','OBJECT'),('CompositorNodeTree','OBJECT')]:
        context.space_data.tree_type=kind;context.space_data.shader_type=shader_type
        t.draw_header(SimpleNamespace(layout=layout),context)
    assert len(calls)==1
    assert 'NODE_MATERIAL' in bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items.keys()
    # Invoke/modal/cancel lifecycle, with real nodes and only the UI event pump
    # substituted. Includes shared-image copies and full rollback on Escape.
    class Harness:
        invoke=t.NODE_OT_harhtools_connect_textures.invoke
        modal=t.NODE_OT_harhtools_connect_textures.modal
        _tick=t.NODE_OT_harhtools_connect_textures._tick
        _cleanup=t.NODE_OT_harhtools_connect_textures._cleanup
        _report=lambda self,result:None
        report=lambda self,*args:None
    class Manager:
        def event_timer_add(self,*args,**kwargs):return object()
        def event_timer_remove(self,timer):self.removed=timer
        def modal_handler_add(self,handler):self.handler=handler
    mat5,tree5,shader5,nodes5=fixture();snapshot=t._snapshot(tree5)
    shared=nodes5['Metallic'].image;other_node.image=shared
    images_before=set(bpy.data.images)
    manager=Manager();ctx=SimpleNamespace(space_data=SimpleNamespace(type='NODE_EDITOR',tree_type='ShaderNodeTree',
        shader_type='OBJECT',edit_tree=tree5,node_tree=tree5),window_manager=manager,window=None,area=None)
    state=Harness();assert state.invoke(ctx,None)=={'RUNNING_MODAL'}
    assert bpy.app.driver_namespace[t.STATE_KEY]==state
    state._start=time.perf_counter()-.2
    # Match the real bpy.types.Event interface; it has no `timer` attribute.
    assert 'timer' not in bpy.types.Event.bl_rna.properties
    timer_event=SimpleNamespace(type='TIMER',value='NOTHING')
    assert state.modal(ctx,timer_event)=={'RUNNING_MODAL'}
    connected=state._connected
    assert state.modal(ctx,timer_event)=={'RUNNING_MODAL'}
    assert state._connected==connected,'Extra timer events must not advance the connection sequence'
    assert state.modal(ctx,SimpleNamespace(type='ESC',value='PRESS'))=={'CANCELLED'}
    assert not bpy.app.driver_namespace.get(t.STATE_KEY) and set(bpy.data.images)==images_before
    assert snapshot['nodes']==set(tree5.nodes)
    assert all(n.location==p for n,p in snapshot['positions'].items())
    assert snapshot['links']==[(l.from_socket,l.to_socket) for l in tree5.links]
    state=Harness();assert state.invoke(ctx,None)=={'RUNNING_MODAL'}
    state._start=time.perf_counter()-1.
    assert state.modal(ctx,timer_event)=={'FINISHED'}
    check(state._result)
    assert not bpy.app.driver_namespace.get(t.STATE_KEY)
    print(json.dumps({'maps':list(result4['maps']),'ordered_rows':True,'normal_converter_reused':True,
                      'actual_alpha_detected':True,'shared_images_isolated':True,'tween_cancel_restores_graph':True}))
    print('SHADER TEXTURE CONNECT PASS')
finally:
    t.unregister()
