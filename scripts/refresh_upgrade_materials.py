# -*- coding: utf-8 -*-
"""Retest all 28 existing scopes after tuning bundled normal maps; no new QEM."""
import copy,hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx
from services.api.glb_document import read_glb,parts_catalog
from edit_asset import accessor_array,node_world_matrices
from upgrade_record import OUT,record
original=OUT/'static_material_matrix_before_normal_tuning.json'
if not original.exists():original.write_bytes((OUT/'static_material_matrix_reviewed.json').read_bytes())
rows=json.loads(original.read_text(encoding='utf-8'));cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'));output=OUT/'material_refresh_normal_v1.json'
if output.exists():raise SystemExit('Preserve previous material refresh; do not overwrite a run')
client=httpx.Client(base_url='http://127.0.0.1:8001',timeout=240);results=[]
def call(url,payload=None):
    r=client.get(url)if payload is None else client.post(url,json=payload);r.raise_for_status();return r.json()
def model(job,catalog):return ROOT/'.data/jobs'/job/('model.glb'if catalog['version']=='original'else'assets/'+catalog['version']+'/model.glb')
def geometry(path):
    doc,binary,_=read_glb(path);world=node_world_matrices(doc);rows={}
    for p in parts_catalog(doc):
        primitive=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];chunks=[world[p['node']].tobytes()]
        for key in('POSITION','NORMAL'):
            if key in primitive['attributes']:chunks.append(key.encode()+accessor_array(doc,binary,primitive['attributes'][key]).tobytes())
        if'indices'in primitive:chunks.append(accessor_array(doc,binary,primitive['indices']).tobytes())
        rows[p['id']]=hashlib.sha256(b''.join(chunks)).hexdigest()
    return rows
profiles={name:call('/api/material-presets/'+name+'/prepare',{})for name in('fabric','leather','wood')}
try:
    for old in rows:
        row=copy.deepcopy(old);case=next(c for c in cases if c['case']==row['case']);job=row['job'];root=f'/api/jobs/{job}/asset';started=time.monotonic()
        try:
            manifest=json.loads((ROOT/'.data/jobs'/job/'assets'/row['local_material_version']/'manifest.json').read_text(encoding='utf-8'));catalog=call(root)
            restored=call(root+'/versions',{'operation':'restore_version','base_version':catalog['version'],'source_version':manifest['base_version']})
            before=geometry(model(job,restored));materials={p['id']:p['material_signature']for p in restored['parts']};ids=row['material_scope']['part_ids']
            profile=profiles['leather'if case['category']in('chair','sofa')else'fabric']
            payload={'operation':'material','base_version':restored['version'],'part_ids':ids,'color':profile['color'],'roughness':profile['roughness'],'metalness':0,'opacity':1,'mode':'replace','uv_scale':profile['uvScale'],'uv_rotation':30,**profile['textures']}
            local=call(root+'/versions',payload);assert before==geometry(model(job,local));assert{p['id']for p in local['parts']if p['material_signature']!=materials[p['id']]}==set(ids)
            profile=profiles['fabric'if case['category']in('chair','sofa')else'wood'];payload.update(base_version=local['version'],part_ids=[],roughness=profile['roughness'],uv_scale=profile['uvScale'],uv_rotation=-15,**profile['textures'])
            whole=call(root+'/versions',payload);assert before==geometry(model(job,whole));assert all(p['has_texture']for p in whole['parts']);assert whole['editor_review_status']=='unreviewed'
            row['previous_material_versions']={'local':row['local_material_version'],'whole':row['whole_material_version']};row.update(local_material_version=local['version'],whole_material_version=whole['version'],material_preset_revision='softened_bundled_normals_v1',material_refresh_restore_version=restored['version'],material_refresh_seconds=time.monotonic()-started)
            record('softened_material_scope_retested',case=row['case'],job=job,local_version=local['version'],whole_version=whole['version']);print(row['case'],'passed',flush=True)
        except Exception as exc:row['failure']=str(exc);raise
        finally:results.append(row);output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    assert len(results)==28
    (OUT/'static_material_matrix_reviewed.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
finally:client.close()
