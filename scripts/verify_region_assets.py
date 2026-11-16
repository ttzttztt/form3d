# -*- coding: utf-8 -*-
"""Check unchanged evidence, whole-group operations and comparable observation conflicts."""
import copy,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh
from services.api.glb_document import read_glb,parts_catalog,selected_primitives,material_edit,write_glb,compact_static
from services.api.models import AssetEditRequest
from edit_asset import accessor_array
from furniture_parts import primitive_data
from part_tools import translate_parts,export_parts
from supported_regions import merge_observation_evidence
from complete_part import mesh_stats
OUT=ROOT/'experiments/semantic_refinement_20261113';runs=json.loads((OUT/'api_runs_validated.json').read_text(encoding='utf-8'));ui=json.loads((OUT/'ui_results.json').read_text(encoding='utf-8'));assert not ui.get('failure');records=[]

def geometry(doc,binary):
    result={}
    for part,p in selected_primitives(doc,[]):
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);result.setdefault(part['logical_group_id'],[]).append(trimesh.Trimesh(w,f,process=False))
    return {k:trimesh.util.concatenate(ms)for k,ms in result.items()}

for run in runs:
    source=Path('.data/jobs')/run['source_job']/'model.glb';assert hashlib.sha256(source.read_bytes()).hexdigest()==run['source_sha256']
    if run['case']=='round_table':continue
    name=run['case'];scan_id=ui['scan_id']if name=='corduroy_sofa'else run['scan_id'];folder=ROOT/'.data/jobs'/run['job']/'semantic_scans'/scan_id;out=OUT/'delivery'/name;out.mkdir(parents=True,exist_ok=True)
    for file in('model.glb','style.glb','manifest.json','mapping_evidence.npz','assignments.npz'):shutil.copyfile(folder/file,out/file)
    original,ob,_=read_glb(source);doc,binary,extra=read_glb(out/'model.glb');lookup={p['id']:p for p in parts_catalog(original)};membership={};parts=parts_catalog(doc);baseline=geometry(doc,binary)
    for part,p in selected_primitives(doc,[]):
        old=lookup[part['source_part_id']];op=selected_primitives(original,[old['id']])[0][1];assert p['attributes'].keys()==op['attributes'].keys()
        for key,index in op['attributes'].items():np.testing.assert_array_equal(accessor_array(original,ob,index),accessor_array(doc,binary,p['attributes'][key]))
        assert part['material_signature']==old['material_signature'];membership.setdefault(old['id'],[]).append(accessor_array(doc,binary,p['indices']).reshape(-1,3))
    for identity,arrays in membership.items():
        p=selected_primitives(original,[identity])[0][1];a=accessor_array(original,ob,p['indices']).reshape(-1,3);b=np.vstack(arrays);np.testing.assert_array_equal(a[np.lexsort(a.T[::-1])],b[np.lexsort(b.T[::-1])])
    record={'case':name,'job':run['job'],'scan_id':scan_id,'source_sha256':run['source_sha256'],'source_unchanged':True,'all_source_attributes_materials_and_triangles_preserved':True,'groups':[]};records.append(record)
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'));op=manifest['operation'];record['unconfirmed_area_fraction']=op['propagation']['unassigned_area_fraction'];record['recognized_groups']=sum(g['kind']!='unknown'for g in op['groups'])
    for ordinal,(group,mesh)in enumerate(baseline.items()):
        ids=[p['id']for p in parts if p['logical_group_id']==group];edited=copy.deepcopy(doc);material_edit(edited,AssetEditRequest(operation='material',part_ids=ids,color='#287c89').model_dump());before={p['id']:p['material_signature']for p in parts};changed={p['id']for p in parts_catalog(edited)if p['material_signature']!=before[p['id']]};assert changed==set(ids)
        moved=copy.deepcopy(doc);mb=bytearray(binary);translate_parts(moved,mb,{'part_ids':ids,'translation':[0,0,1]});after=geometry(moved,mb)
        for key,m in baseline.items():np.testing.assert_allclose(after[key].triangles,m.triangles+([0,0,1]if key==group else[0,0,0]),atol=5e-7)
        exported=copy.deepcopy(doc);eb=bytearray(binary);export_parts(exported,eb,{'part_ids':ids});file=out/f'part_{ordinal}.glb';write_glb(file,exported,compact_static(exported,eb),extra);loaded=trimesh.load(file,force='mesh',process=False);loaded.merge_vertices(digits_vertex=8)
        g=next(g for g in op['groups']if g['id']==group);record['groups'].append({'id':group,'name':g['name'],'kind':g['kind'],'label':g['label'],'material_scope_passed':True,'neighbours_unchanged_on_move':True,'export':str(file.relative_to(OUT)).replace('\\','/'),**mesh_stats(loaded)})
    cache=np.load(OUT/name/'evidence.npz');d=json.loads((OUT/name/'diagnosis.json').read_text(encoding='utf-8'));support={'support_views':cache['support_views'].copy(),'scores':cache['scores'].copy(),'visible_views':cache['visible_views']};merge_observation_evidence(support,d['opposite']);area=cache['area'];old=cache['final'];new=np.load(OUT/name/'saved_masks/assignments.npz')['labels'];comparisons=[]
    for label in np.unique(old):
        if not label:continue
        votes=support['support_views'][label-1];visible=support['visible_views'];old_mask=old==label;new_mask=new==label;bad=(visible>=2)&(votes*2<visible);observed=(votes>=2)&old_mask
        comparisons.append({'label':int(label),'old_area':float(area[old_mask].sum()),'new_area':float(area[new_mask].sum()),'old_visible_conflict_area':float(area[old_mask&bad].sum()),'new_visible_conflict_area':float(area[new_mask&bad].sum()),'old_multiview_observed_area_retained_ratio':float(area[observed&new_mask].sum()/max(area[observed].sum(),1e-12)),'not_semantic_accuracy':True})
    record['same_saved_masks_comparison']=comparisons
    (OUT/'verification.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(name,len(record['groups']),flush=True)
saved=ROOT/'.data/jobs'/ui['job']/'assets'/ui['semantic_version']/'model.glb';preview=ROOT/'.data/jobs'/ui['job']/'semantic_scans'/ui['scan_id']/'model.glb';assert saved.read_bytes()==preview.read_bytes();print('Exact semantic preview bytes preserved',flush=True)
