"""No Shape Builder/library insertion autosave; explicit '+' still stores curves."""
import ast
import hashlib
import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / '_artifacts'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
import sys
import tempfile

import bpy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from extension import shape_builder as sb,shape_library as lib

lib._storage_override=Path(tempfile.mkdtemp(prefix='manual_library_',dir=OUTPUT_DIR))
lib._catalog.clear()
checks={}

def disk():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in lib._storage_override.iterdir() if p.is_file()}

def square(name,x,y=0):
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata(((x,y,0),(x+2,y,0),(x+2,y+2,0),(x,y+2,0)),
                     ((0,1),(1,2),(2,3),(3,0)),())
    obj=bpy.data.objects.new(name,mesh)
    bpy.context.collection.objects.link(obj);obj.select_set(True)
    return obj

for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
a=square('Guide A',0);b=square('Guide B',1,.7)
bpy.context.view_layer.objects.active=a
bpy.context.view_layer.update()
bpy.utils.register_class(lib.HARHTOOLS_OT_shape_save)
try:
    assert bpy.ops.harhtools.shape_save()=={'FINISHED'}
    assert len(lib._catalog)==1
    baseline_files=disk();baseline_ids=set(lib._catalog)
    baseline_catalog=json.dumps(lib._catalog,sort_keys=True)
    checks['manual_plus_operator_saves_selected_guide']=True

    arrangement,_=sb.build_pen_arrangement(bpy.context,gap_snap=0)
    assert len(arrangement['regions'])==3
    writes=[];original_write=lib._atomic_write
    def forbidden_write(*args,**kwargs):
        writes.append(str(args[0]))
        raise AssertionError('Automatic library write attempted')
    lib._atomic_write=forbidden_write
    try:
        curve=sb.commit_shape(bpy.context,arrangement,{0},output_type='CURVE')
        mesh=sb.commit_shape(bpy.context,arrangement,{1},output_type='MESH')
        for obj in bpy.context.selected_objects:obj.select_set(False)
        a.select_set(True);b.select_set(True);bpy.context.view_layer.objects.active=a
        cut_calls=[];original_cut=sb.cut_original_guides
        def cut_once(context,expected):
            cut_calls.append({obj.name for obj in context.selected_objects})
            assert cut_calls[-1]=={a.name,b.name},cut_calls[-1]
        sb.cut_original_guides=cut_once
        try:
            outputs=sb.commit_fill_groups(bpy.context,arrangement,[{0},{1}],
                                          output_type='CURVE',cut_guides=True)
            assert len(outputs)==2 and all(obj.type=='CURVE' for obj in outputs)
            assert len(cut_calls)==1
            checks['batch_commit_cuts_original_guides_once']=True

            before_objects=set(bpy.data.objects.keys());before_curves=set(bpy.data.curves.keys())
            original_geometry=sb.curve_geometry.curve_data;calls=[]
            def fail_second(*args,**kwargs):
                calls.append(1)
                if len(calls)==2:raise RuntimeError('Injected second fill construction failure')
                return original_geometry(*args,**kwargs)
            sb.curve_geometry.curve_data=fail_second
            try:
                try:sb.commit_fill_groups(bpy.context,arrangement,[{0},{1}],output_type='CURVE',cut_guides=True)
                except RuntimeError as error:assert 'Injected second fill' in str(error)
                else:raise AssertionError('Injected failure did not abort the batch')
            finally:
                sb.curve_geometry.curve_data=original_geometry
            assert set(bpy.data.objects.keys())==before_objects
            assert set(bpy.data.curves.keys())==before_curves
            assert len(cut_calls)==1,'Failed construction should not cut guides'
            checks['failed_batch_discards_all_outputs_before_cutting_guides']=True
        finally:
            sb.cut_original_guides=original_cut
    finally:
        lib._atomic_write=original_write
    assert not writes, writes
    assert curve.type=='CURVE' and mesh.type=='MESH'
    assert set(lib._catalog)==baseline_ids
    assert json.dumps(lib._catalog,sort_keys=True)==baseline_catalog
    assert disk()==baseline_files
    checks['curve_and_mesh_commits_never_write_library']=True
    checks['commits_leave_library_items_and_existing_files_unchanged']=True

    for obj in bpy.context.selected_objects:obj.select_set(False)
    curve.select_set(True);bpy.context.view_layer.objects.active=curve
    assert bpy.ops.harhtools.shape_save()=={'FINISHED'}
    assert len(lib._catalog)==2
    saved_id=next(i for i in lib._catalog if i not in baseline_ids)
    assert lib._catalog[saved_id]['object_type']=='CURVE'
    checks['manual_plus_operator_saves_generated_editable_curve']=True

    # File load/refresh may refresh existing thumbnails, but cannot add scene objects.
    before=set(lib._catalog);files=disk()
    assert lib.refresh_library()==2
    assert set(lib._catalog)==before and disk()==files
    restored=lib.insert_shape(saved_id)
    assert restored.type=='CURVE' and set(lib._catalog)==before and disk()==files
    assert bpy.ops.harhtools.shape_save()=={'FINISHED'}
    assert len(lib._catalog)==2
    checks['refresh_and_insertion_do_not_capture_scene_objects']=True
    checks['explicit_duplicate_save_reuses_existing_preset']=True

    # Guard against a second automatic capture call hiding in builder/array code.
    offenders=[]
    for path in (ROOT/'extension').glob('*.py'):
        if path.name=='shape_library.py':continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if not isinstance(node,ast.Call):continue
            called=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
            if called in {'capture_created_shape','capture_shape'}:
                offenders.append(f'{path.name}:{node.lineno}')
    assert not offenders,offenders
    checks['no_automatic_capture_calls_in_builder_array_or_other_modules']=True
finally:
    bpy.utils.unregister_class(lib.HARHTOOLS_OT_shape_save)

report={'passed':all(checks.values()),'checks':checks,'storage':str(lib._storage_override)}
(OUTPUT_DIR/'manual_library_only_results.json').write_text(json.dumps(report,indent=2))
print('MANUAL_LIBRARY_ONLY_TESTS',json.dumps(report))
