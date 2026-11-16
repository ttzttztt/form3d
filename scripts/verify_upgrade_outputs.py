# -*- coding: utf-8 -*-
"""Reload actual GLBs; independent scope/bytes/geometry validation of final edits."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from services.api.glb_document import read_glb,parts_catalog
from services.api.geometry import validate_glb
from edit_asset import accessor_array,node_world_matrices
from upgrade_record import OUT,record
cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'));rows=json.loads((OUT/'static_material_matrix_reviewed.json').read_text(encoding='utf-8'));result=[]
assert len(rows)==len(cases)>=25
def fingerprint(path):
    doc,binary,_=read_glb(path);world=node_world_matrices(doc);data={}
    for p in parts_catalog(doc,binary):
        primitive=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];attrs=primitive['attributes']
        chunks=[world[p['node']].tobytes()]
        for name in('POSITION','NORMAL'):
            if name in attrs:chunks.append(name.encode()+accessor_array(doc,binary,attrs[name]).tobytes())
        if'indices'in primitive:chunks.append(accessor_array(doc,binary,primitive['indices']).tobytes())
        data[p['id']]={'geometry':hashlib.sha256(b''.join(chunks)).hexdigest(),'material':p['material_signature'],'uv':hashlib.sha256(accessor_array(doc,binary,attrs['TEXCOORD_0']).tobytes()).hexdigest()if'TEXCOORD_0'in attrs else None}
    return data
for row in rows:
    assert not row.get('failure'),row
    c=next(c for c in cases if c['case']==row['case']);folder=ROOT/'.data/jobs'/row['job'];source=ROOT/c['source_model'];assert hashlib.sha256(source.read_bytes()).hexdigest()==c['source_sha256']
    original=ROOT/'.data/jobs'/c['job']/'model.glb';assert hashlib.sha256(original.read_bytes()).hexdigest()==c['source_sha256']
    local=folder/'assets'/row['local_material_version']/'model.glb';whole=folder/'assets'/row['whole_material_version']/'model.glb'
    local_manifest=json.loads(local.with_name('manifest.json').read_text(encoding='utf-8'));base=local_manifest['base_version'];before=folder/('model.glb'if base=='original'else'assets/'+base+'/model.glb')
    a,b,d=[fingerprint(p)for p in(before,local,whole)];assert set(a)==set(b)==set(d)
    target=set(row['material_scope']['part_ids']);assert{k for k in a if a[k]['material']!=b[k]['material']}==target
    assert all(a[k]['geometry']==b[k]['geometry']==d[k]['geometry']for k in a)
    assert all(b[k]['uv']==d[k]['uv']and(a[k]['uv']==b[k]['uv']or a[k]['uv']is None)for k in target)
    record_={'case':c['case'],'source_hash_unchanged':True,'reloaded_local_material_scope_exact':True,'all_world_geometry_and_normals_preserved_by_material_edits':True,'existing_target_uv_preserved':True,'first_uv_created_by_material_fallback':[k for k in target if a[k]['uv']is None and b[k]['uv']is not None],'validations':[],'simplification_diagnostics':[]}
    for label,p in [('local',local),('whole',whole)]:
        validation=validate_glb(p);assert validation['errors']==0;record_['validations'].append({'stage':label,'errors':validation['errors'],'warnings':validation.get('warnings',0),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    if row['simplification']['status']=='saved':
        p=folder/'assets'/row['simplification']['version']/'model.glb';validation=validate_glb(p);assert validation['errors']==0
        manifest=json.loads(p.with_name('manifest.json').read_text(encoding='utf-8'));op=manifest['operation']
        diagnostic=[r for r in op['parts']if r.get('diagnostic')];record_['simplification_diagnostics']=diagnostic;assert not diagnostic,(c['case'],diagnostic)
        assert all(r.get('checks',{}).get('passed')for r in op['parts']if r['status']=='simplified')
        record_['validations'].append({'stage':'simplified','errors':0,'warnings':validation.get('warnings',0),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    else:
        operations=[]
        for manifest_path in (folder/'assets').glob('*/manifest.json'):
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest.get('operation',{}).get('operation')=='optimize_mesh':operations.append(manifest['operation'])
        assert operations,'A protected no-op still needs retained diagnostic evidence'
        diagnostic=[p for op in operations for p in op['parts']if p.get('diagnostic')]
        assert not diagnostic,(c['case'],diagnostic)
        record_['preserved_geometry_reasons']=[p.get('reason')for op in operations for p in op['parts']]
    result.append(record_);(OUT/'independent_output_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(c['case'],'verified',flush=True)
record('independent_output_verification_completed',furniture=len(result),glbs=sum(len(r['validations'])for r in result),no_simplification_internal_errors=True)
