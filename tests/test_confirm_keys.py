"""Ctrl+A routes through each active tool's normal confirmation path only."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from contextlib import nullcontext
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from extension import shortcuts as keys,shape_builder as sb,array_tool as at,shape_library as library

def event(kind='A',**kw):
    values=dict(type=kind,value='PRESS',ctrl=True,alt=False,shift=False,oskey=False,mouse_x=100,mouse_y=100)
    values.update(kw);return NS(**values)

assert keys.confirm_event(event())
assert keys.confirm_event(event('RET',ctrl=False))
assert keys.confirm_event(event('NUMPAD_ENTER',ctrl=False))
assert keys.confirm_event(event(),key='SPACE')
assert keys.confirm_event(event('SPACE',ctrl=False),key='SPACE')
for overrides in (dict(ctrl=False),dict(alt=True),dict(shift=True),dict(oskey=True),dict(value='RELEASE')):
    assert not keys.confirm_event(event(**overrides))

cfg=NS(remove_modifier='ALT',cancel_key='ESC',confirm_key='RET',undo_key='Z')
wm=NS(arch_shape_builder_cut_guides=False,arch_shape_builder_output_type='MESH',keyconfigs=NS(active=None))
context=NS(window_manager=wm,mode='OBJECT')
h=NS(_done=False,_area=NS(type='VIEW_3D'),_mode='ADD',_alt=False,_selected={1,2},_edge_mode=False,
     _sources=[],_arr={},_groups=[{1},{2}],over_controls=lambda e:False,finish=lambda:None,report=lambda *a:None)
with patch.object(sb.shortcuts,'settings',return_value=cfg),patch.object(sb,'commit_fill_groups',return_value=[1,2]) as commit:
    assert sb.VIEW3D_OT_arch_shape_builder.modal(h,context,event())=={'FINISHED'}
    assert commit.call_count==1 and commit.call_args.args[2]==[{1},{2}]

h=NS(_done=False,_area=NS(type='VIEW_3D',regions=[]),_region=NS(width=800),_request=None,
     _sidebar_suspended=False,_inactive=NS(restore=lambda **kw:None),over_controls=lambda e:False,
     _native=NS(clear_objects=lambda:None),
     generate=lambda c:{'FINISHED'})
with patch.object(at,'sidebar_is_active',return_value=True):
    assert at.VIEW3D_OT_harhtools_array.modal(h,context,event())=={'FINISHED'}
    assert at.VIEW3D_OT_harhtools_array.modal(h,context,event(ctrl=False))=={'PASS_THROUGH'}
    h._area.regions=[NS(type='UI',width=300,height=500,x=0,y=0)]
    assert at.VIEW3D_OT_harhtools_array.modal(h,context,event())=={'PASS_THROUGH'}

h=NS(_done=False,_target=(1,2,3),_location=(0,0,0),_rotation=None,_release_pending=None,
     _rename_pending=False,_dragging=True,identifier='fixture',from_row=True,
     update_pointer=lambda *a:None,report=lambda *a:None)
h.finish=lambda:setattr(h,'_done',True)
context=NS(temp_override=lambda **kw:nullcontext())
with patch.dict(library._catalog,{'fixture':{}}),patch.object(library,'insert_shape') as insert:
    assert library.HARHTOOLS_OT_shape_drag.modal(h,context,event())=={'FINISHED'}
    assert insert.call_count==1 and h._done
print('CONFIRM_KEYS_PASS: active builder, array and placement routing; Enter retained; modifiers/releases rejected; UI fields pass through')
