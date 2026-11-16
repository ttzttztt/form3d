# -*- coding: utf-8 -*-
"""Actual chair API edits on a fresh clone, preserving all earlier evidence."""
import copy,hashlib,json,shutil,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx,numpy as np,trimesh
from services.api.store import Store,now
from services.api.glb_document import read_glb,parts_catalog
from furniture_parts import primitive_data
from complete_part import mesh_stats
OUT=ROOT/'experiments/complete_cushion_20261112';store=Store(ROOT/'.data');old=json.loads((ROOT/'experiments/selection_refinement_20261112/delivery_browser.json').read_text(encoding='utf-8'));source=store.job(old['job']);identity=uuid.uuid4().hex;job=copy.deepcopy(source)
for k in ('asset_versions','current_asset_version','review'):job.pop(k,None)
job.update(id=identity,name='坐垫完整拆分 · 推测接合面验收副本',status='awaiting_review',stage='complete_part_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=source['id'])
for k,v in list(job.items()):
    if isinstance(v,str):job[k]=v.replace(source['id'],identity)
folder=store.root/'jobs'/identity;folder.mkdir()
for p in (store.root/'jobs'/source['id']).iterdir():
    if p.is_file() and p.suffix=='.png':shutil.copyfile(p,folder/p.name)
original=store.root/'jobs'/source['id']/'assets'/old['split_version']/'model.glb';shutil.copyfile(original,folder/'model.glb');store.create_job(job,'',identity)
record={'job':identity,'source_job':source['id'],'source_version':old['split_version'],'source_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'steps':[]}
def save():(OUT/'actual_run.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
def groups_geometry(path):
    doc,binary,_=read_glb(path);groups={}
    for p in parts_catalog(doc):
        primitive=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];_,f,w,_,_,_=primitive_data(doc,binary,p,primitive);groups.setdefault(p['logical_group_id'],[]).append(trimesh.Trimesh(w,f,process=False))
    result={}
    for key,meshes in groups.items():m=trimesh.util.concatenate(meshes);m.merge_vertices(digits_vertex=8);m.remove_unreferenced_vertices();result[key]=m
    return result
with httpx.Client(base_url='http://127.0.0.1:8001',timeout=240) as client:
    root=f'/api/jobs/{identity}/asset';catalog=client.get(root).json();payload={'operation':'complete_part','base_version':catalog['version'],'part_ids':old['part_ids'],'name':'坐垫（接合面为推测）'}
    start=time.monotonic();r=client.post(root+'/completion-plan',json=payload);r.raise_for_status();plan=r.json();record['plan']=plan;record['plan_seconds']=round(time.monotonic()-start,3);assert client.get(root).json()['versions']==[];save()
    def edit(operation,**values):
        global catalog
        start=time.monotonic();r=client.post(root+'/versions',json={'operation':operation,'base_version':catalog['version'],**values});body=r.json();step={'operation':operation,'status':r.status_code,'seconds':round(time.monotonic()-start,3)};record['steps'].append(step)
        if r.status_code==201:catalog=body;step.update(version=body['version'],evidence=body['manifest']['operation'])
        else:step['error']=body
        save();return r.status_code==201
    default_ok=edit('complete_part',part_ids=old['part_ids'],completion_bounds=plan['completion_bounds'],name=payload['name']);record['default_bounds_succeeded']=default_ok
    if not default_ok:
        bound=np.array([[-.55,.27,-.40],[.55,1.15,.82]]);source_bounds=np.array(plan['source_bounds_world']);normalized=((bound-source_bounds[0])/(source_bounds[1]-source_bounds[0])).tolist();assert edit('complete_part',part_ids=old['part_ids'],completion_bounds=normalized,name=payload['name']);record['review_adjusted_bounds']=normalized
    evidence=catalog['manifest']['operation'];record['completion_version']=catalog['version'];record['part_group_id']=evidence['part_group_id'];record['remainder_group_id']=evidence['remainder_group_id'];ids=next(g['part_ids'] for g in catalog['groups'] if g['id']==evidence['part_group_id']);record['part_ids']=ids
    complete_path=OUT/'complete_candidate.glb';complete_path.write_bytes(client.get(catalog['model_url']).content);geometry=groups_geometry(complete_path);record['reloaded_groups']={k:mesh_stats(m) for k,m in geometry.items()};assert all(m.is_watertight for m in geometry.values());before={p['id']:p['material_signature'] for p in catalog['parts']}
    assert edit('material',part_ids=ids,color='#297cb5',roughness=.85);record['material_version']=catalog['version'];changed=[p['id'] for p in catalog['parts'] if p['material_signature']!=before[p['id']]];assert set(changed)==set(ids);record['material_changed_ids']=changed;(OUT/'complete_colored.glb').write_bytes(client.get(catalog['model_url']).content)
    r=client.post(root+'/export-parts',json={'version':catalog['version'],'part_ids':ids});r.raise_for_status();(OUT/'cushion_export.glb').write_bytes(r.content);exported=trimesh.load(OUT/'cushion_export.glb',force='mesh',process=False);exported.merge_vertices(digits_vertex=8);record['exported_part']=mesh_stats(exported);assert exported.is_watertight;assert len(exported.faces)==len(geometry[evidence['part_group_id']].faces)
    assert edit('translate_parts',part_ids=ids,translation=[0,0,1.8]);record['moved_version']=catalog['version'];moved=OUT/'complete_moved.glb';moved.write_bytes(client.get(catalog['model_url']).content);after=groups_geometry(moved)
    for key,mesh in geometry.items():
        np.testing.assert_allclose(after[key].triangles,mesh.triangles+([0,0,1.8] if key==evidence['part_group_id'] else [0,0,0]),atol=5e-7)
    record['part_moved_other_geometry_unchanged']=True;record['source_unchanged']=hashlib.sha256(original.read_bytes()).hexdigest()==record['source_sha256']==hashlib.sha256((folder/'model.glb').read_bytes()).hexdigest();assert record['source_unchanged'];save()
print(json.dumps({'job':identity,'default_bounds_succeeded':record['default_bounds_succeeded'],'versions':[(s['operation'],s['status']) for s in record['steps']],'groups':record['reloaded_groups'],'export':record['exported_part']},ensure_ascii=False,indent=2))
