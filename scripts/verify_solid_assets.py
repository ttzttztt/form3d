"""Independent round-trip, logical movement, material and export verification."""
import copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh
from services.api.glb_document import read_glb,write_glb,parts_catalog,selected_primitives,material_edit,compact_static
from services.api.models import AssetEditRequest
from part_tools import translate_parts,export_parts
from furniture_parts import primitive_data
from solid_partition import prepare_mesh
from complete_part import mesh_stats
from reconstruct_parts import intersections
from edit_asset import accessor_array
OUT=ROOT/'experiments/solid_parts_20261113';ui=json.loads((OUT/'final_ui_verified/ui_results.json').read_text(encoding='utf-8'))
if ui.get('failure'):raise SystemExit(ui['failure'])
cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'));records=[]

def geometries(doc,binary):
    groups={}
    for part,p in selected_primitives(doc,[]):
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);groups.setdefault(part.get('logical_group_id')or part['id'],[]).append(trimesh.Trimesh(w,f,process=False))
    return {key:prepare_mesh(trimesh.util.concatenate(ms))[0] for key,ms in groups.items()}

for case in cases:
    name=case['case'];folder=OUT/'verified'/name;folder.mkdir(parents=True,exist_ok=True)
    source=ROOT/'.data/jobs'/case['job']/'assets'/ui['solid_version']/'model.glb' if name=='leather_sofa' else OUT/name/'model.glb'
    doc,binary,extra=read_glb(source);baseline=geometries(doc,binary);parts=parts_catalog(doc);groups=list(baseline)
    record={'case':name,'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'groups':[]};records.append(record)
    for ordinal,group in enumerate(groups):
        ids=[p['id']for p in parts if(p.get('logical_group_id')or p['id'])==group]
        md=copy.deepcopy(doc);signatures={p['id']:p['material_signature']for p in parts};material_edit(md,AssetEditRequest(operation='material',part_ids=ids,color='#257f91').model_dump());changed={p['id']for p in parts_catalog(md)if p['material_signature']!=signatures[p['id']]};assert changed==set(ids)
        moved=copy.deepcopy(doc);mb=bytearray(binary);translate_parts(moved,mb,{'part_ids':ids[:1] if parts[[p['id'] for p in parts].index(ids[0])]['group_kind']=='reconstructed_logical_part' else ids,'translation':[0,0,1]});after=geometries(moved,mb)
        # Translation uses node transforms and retains the ordered source triangles.
        for key,mesh in baseline.items():np.testing.assert_allclose(after[key].triangles,mesh.triangles+([0,0,1]if key==group else[0,0,0]),atol=5e-7)
        exported=copy.deepcopy(doc);eb=bytearray(binary);export_parts(exported,eb,{'part_ids':ids[:1] if parts[[p['id'] for p in parts].index(ids[0])]['group_kind']=='reconstructed_logical_part' else ids});file=folder/f'part_{ordinal}.glb';write_glb(file,exported,compact_static(exported,eb),extra);ed,bb,_=read_glb(file);meshes=geometries(ed,bb);assert list(meshes)==[group];mesh=meshes[group]
        checked={'id':group,'name':next(p['name']for p in parts if p['id']in ids),'material_scope_passed':True,'other_groups_unchanged_on_move':True,'export':str(file.relative_to(OUT)).replace('\\','/'),'parts':ids,**mesh_stats(mesh),'components':len(mesh.split(only_watertight=False)),'self_intersection_faces':intersections(mesh)}
        record['groups'].append(checked)
    # Unchanged source groups from a rejected reconstruction retain all vertex
    # attributes, indices, world triangles and materials.
    if name!='leather_sofa':
        original,ob,_=read_glb(Path(case['source_grouping_snapshot']));old=geometries(original,ob);op=json.loads((OUT/name/'manifest.json').read_text(encoding='utf-8'))['operation'];kept=[g['id']for g in op['groups']if g['status']=='kept_source']
        for key in kept:np.testing.assert_array_equal(old[key].triangles,baseline[key].triangles)
        for original_part,original_p in selected_primitives(original,[]):
            if original_part.get('logical_group_id') not in kept:continue
            current_part,current_p=selected_primitives(doc,[original_part['id']])[0]
            assert original_p['attributes'].keys()==current_p['attributes'].keys()
            for attribute,index in original_p['attributes'].items():np.testing.assert_array_equal(accessor_array(original,ob,index),accessor_array(doc,binary,current_p['attributes'][attribute]))
            np.testing.assert_array_equal(accessor_array(original,ob,original_p['indices']),accessor_array(doc,binary,current_p['indices']))
            assert original_part['material_signature']==current_part['material_signature']
        record['kept_source_geometry_unchanged']=kept
    record['test_original_unchanged']=hashlib.sha256((ROOT/'.data/jobs'/case['job']/'model.glb').read_bytes()).hexdigest()==case['source_sha256'];assert record['test_original_unchanged']
    record['generation_source_sha256']=hashlib.sha256((ROOT/'.data/jobs'/case['source_job']/'model.glb').read_bytes()).hexdigest()
    (OUT/'verification.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(name,len(record['groups']),flush=True)
preview=ROOT/'.data/jobs'/ui['job']/'completion_previews'/ui['preview_id']/'model.glb';saved=ROOT/'.data/jobs'/ui['job']/'assets'/ui['solid_version']/'model.glb';assert preview.read_bytes()==saved.read_bytes();assert hashlib.sha256(saved.read_bytes()).hexdigest()==ui['model_sha256']
print('Exact preview bytes preserved; all technical patches export together',flush=True)
