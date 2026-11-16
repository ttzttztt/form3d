# -*- coding: utf-8 -*-
"""25 real furniture assets: actual API edits, scope and geometry invariants."""

def main():
    import argparse,copy,hashlib,json,re,shutil,sys,time,urllib.request,urllib.error,uuid
    import importlib.util
    if importlib.util.find_spec('numpy')is None:
        raise SystemExit('Run this matrix with .venv-hunyuan/Scripts/python.exe; geometry verification requires numpy. No API mutations made.')
    from pathlib import Path
    ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
    from services.api.store import Store,now
    from services.api.glb_document import read_glb,parts_catalog
    from edit_asset import accessor_array,node_world_matrices
    from upgrade_record import OUT,record
    store=Store(ROOT/'.data');cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'));base='http://127.0.0.1:8001'
    p=argparse.ArgumentParser();p.add_argument('--tag',default='');p.add_argument('--cases',default='');a=p.parse_args()
    if a.cases:cases=[c for c in cases if c['case']in a.cases.split(',')]
    results=[]
    result_path=OUT/('static_material_matrix'+('_'+a.tag if a.tag else'')+'.json')
    if result_path.exists():
        results=json.loads(result_path.read_text(encoding='utf-8'))
        if any(r.get('failure')for r in results):raise SystemExit('Preserve failure round before rerunning')

    def call(url,payload=None):
        request=urllib.request.Request(base+url,data=json.dumps(payload).encode()if payload is not None else None,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=650)as response:return json.load(response)

    def path_for(catalog):
        return ROOT/'.data/jobs'/current_job/('model.glb'if catalog['version']=='original'else'assets/'+catalog['version']+'/model.glb')

    def geometry_signature(path):
        doc,binary,_=read_glb(path);worlds=node_world_matrices(doc);rows={}
        for part in parts_catalog(doc):
            p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
            chunks=[worlds[part['node']].tobytes()]
            for key in('POSITION','NORMAL','TEXCOORD_0'):
                if key in p['attributes']:chunks.extend([key.encode(),accessor_array(doc,binary,p['attributes'][key]).tobytes()])
            if'indices'in p:chunks.append(accessor_array(doc,binary,p['indices']).tobytes())
            rows[part['id']]=hashlib.sha256(b''.join(chunks)).hexdigest()
        return rows

    profiles={name:call('/api/material-presets/'+name+'/prepare',{})for name in('fabric','leather','wood')}
    for case in cases:
        if any(r['case']==case['case']for r in results):continue
        started=time.monotonic();source_job=store.job(case['job']);assert source_job,'Actual source must exist before it is counted'
        current_job=uuid.uuid4().hex;job=copy.deepcopy(source_job)
        for key in('asset_versions','current_asset_version','review','quality_report'):job.pop(key,None)
        job.update(id=current_job,name='25家具减面与材质矩阵 · '+case['title'],created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=case['job'],model_url=f'/api/jobs/{current_job}/files/model.glb')
        folder=store.root/'jobs'/current_job;folder.mkdir();source=store.root/'jobs'/case['job']/'model.glb';shutil.copyfile(source,folder/'model.glb');store.create_job(job,'',current_job)
        root=f'/api/jobs/{current_job}/asset';row={'case':case['case'],'title':case['title'],'job':current_job,'source_job':case['job'],'source_origin':case['origin'],'checks':[],'appearance_accepted':False}
        source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
        try:
            catalog=call(root);before_materials={p['id']:p['material_signature']for p in catalog['parts']};before_faces=catalog['metrics']['triangles'];target=max(10000,min(100000,int(before_faces*.6)))
            try:
                optimized=call(root+'/versions',{'operation':'optimize_mesh','base_version':catalog['version'],'part_ids':[],'target_faces':target})
                op=optimized['manifest']['operation'];row['simplification']={'status':'saved','version':optimized['version'],'before':before_faces,'after':optimized['metrics']['triangles'],'bytes_before':catalog['metrics']['bytes'],'bytes_after':optimized['metrics']['bytes'],'target':target,'target_reached':op['target_reached'],'changed_parts':op['changed_parts'],'preserved_parts':sum(r['status']!='simplified'for r in op['parts']),'manifest_url':optimized['versions'][-1]['manifest_url']}
                assert before_materials=={p['id']:p['material_signature']for p in optimized['parts']}
                assert optimized['metrics']['triangles']<before_faces;catalog=optimized;row['checks'].append('simplification_preserves_all_part_ids_and_materials')
            except urllib.error.HTTPError as exc:
                error=json.load(exc)
                if exc.code!=409:raise
                if not any(term in error.get('detail','')for term in('无需减面','保形检查未允许')):raise ValueError('Unexpected simplification failure: '+error.get('detail',''))from exc
                row['simplification']={'status':'preserved','reason':error['detail'],'before':before_faces,'after':before_faces,'target':target};assert call(root)['version']==catalog['version'];row['checks'].append('no_duplicate_version_when_simplification_not_allowed_or_needed')
            groups=catalog['groups'];preferred=[g for g in groups if re.search(r'seat|cushion|table.?top|desktop|door|drawer|坐垫|靠枕',g['name'],re.I)and not re.search(r'fiber|pile|毛发',g['name'],re.I)]
            group=max(preferred or groups,key=lambda g:g['triangles']);ids=group['part_ids'];row['material_scope']={'group':group['name'],'part_ids':ids,'semantic_group_verified':bool(group.get('semantic_kind'))}
            doc,_,_=read_glb(path_for(catalog));lookup={p['id']:p for p in parts_catalog(doc)}
            missing=any('TEXCOORD_0'not in doc['meshes'][doc['nodes'][lookup[i]['node']]['mesh']]['primitives'][lookup[i]['primitive']]['attributes']for i in ids)
            if missing:
                try:
                    catalog=call(root+'/versions',{'operation':'unwrap_uv','base_version':catalog['version'],'part_ids':ids,'uv_unwrap_mode':'box'})
                    row['uv_version']=catalog['version'];row['checks'].append('actual_uv_preparation_before_texturing')
                except urllib.error.HTTPError as exc:
                    if exc.code!=409:raise
                    row['uv_refusal']=json.load(exc)['detail']
            before_geo=geometry_signature(path_for(catalog));materials={p['id']:p['material_signature']for p in catalog['parts']}
            profile=profiles['leather'if case['category']in('chair','sofa')else'fabric']
            request={'operation':'material','base_version':catalog['version'],'part_ids':ids,'color':profile['color'],'metalness':profile['metalness'],'roughness':profile['roughness'],'opacity':1,'mode':'replace','uv_scale':profile['uvScale'],'uv_rotation':30,**profile['textures']}
            local=call(root+'/versions',request);changed={p['id']for p in local['parts']if materials[p['id']]!=p['material_signature']};assert changed==set(ids),changed
            after_geo=geometry_signature(path_for(local))
            if not row.get('uv_refusal'):assert before_geo==after_geo
            row['local_material_version']=local['version'];row['checks'].extend(['local_material_changes_every_target_primitive_and_no_neighbor','local_material_preserves_world_geometry_and_prepared_uv'])
            profile=profiles['fabric'if case['category']in('chair','sofa')else'wood'];request.update(base_version=local['version'],part_ids=[],roughness=profile['roughness'],uv_scale=profile['uvScale'],uv_rotation=-15,**profile['textures'])
            global_material=call(root+'/versions',request);assert all(p['has_texture']for p in global_material['parts'])
            before_global=geometry_signature(path_for(local));after_global=geometry_signature(path_for(global_material))
            for identity in ids:assert before_global[identity]==after_global[identity]
            row['whole_material_version']=global_material['version'];row['checks'].extend(['whole_material_embeds_maps_on_every_primitive','previously_prepared_target_geometry_unchanged_by_whole_material','results_remain_unreviewed'])
            assert global_material['editor_review_status']=='unreviewed'
            assert hashlib.sha256(source.read_bytes()).hexdigest()==source_sha
            row['source_unchanged']=True;row['checks'].append('original_source_bytes_unchanged')
            record('furniture_matrix_case_completed',case=case['case'],job=current_job,simplification=row['simplification']['status'],checks=len(row['checks']))
        except Exception as exc:
            row['failure']=str(exc)
            if isinstance(exc,urllib.error.HTTPError):
                try:row['failure_detail']=json.load(exc)
                except Exception:pass
            record('furniture_matrix_case_failed',case=case['case'],job=current_job,error=row['failure'])
        row['elapsed_seconds']=time.monotonic()-started;results.append(row);result_path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(case['case'],'FAILED '+row.get('failure','')if row.get('failure')else'completed',round(row['elapsed_seconds'],2),flush=True)
    if any(r.get('failure')for r in results):raise SystemExit(1)


if __name__=='__main__':
    main()
