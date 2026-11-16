"""Independent world-triangle preservation, and diagnostic group-color copies."""
import copy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from verify_asset_upgrade import signature
from services.api.glb_document import read_glb,write_glb,parts_catalog,material_edit
from services.api.models import AssetEditRequest
from services.api.geometry import validate_glb
from edit_asset import accessor_array,node_world_matrices
OUT=ROOT/'experiments/furniture_workbench_20261112'
COLORS=['#31b5dc','#f3a33a','#b46be2','#69c776','#ec657c','#e3d853','#8794e4','#ac8b73']
results=[]
for case in json.loads((OUT/'real_runs.json').read_text(encoding='utf-8')):
    source=ROOT/'.data/jobs'/case['source_job']/'model.glb';expected=signature(source)
    result={'case':case['case'],'original_sha_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==case['source_sha256'],'source_signature':expected,'stages':{}}
    assert result['original_sha_unchanged']
    for stage in ['auto','edited']+(['fine'] if case['case']=='round_table' else []):
        path=OUT/(case['case']+'_'+stage+'.glb');actual=signature(path);assert actual==expected,(case['case'],stage)
        validation=validate_glb(path);assert validation['errors']==0
        result['stages'][stage]={'exact_world_triangles_preserved':True,'validation':validation}
        if stage!='edited':
            doc,binary,extra=read_glb(path);groups={}
            for part in parts_catalog(doc):groups.setdefault(part.get('logical_group_id') or part['id'],[]).append(part)
            for i,parts in enumerate(groups.values()):material_edit(doc,AssetEditRequest(operation='material',part_ids=[p['id'] for p in parts],color=COLORS[i%len(COLORS)],roughness=.8,metalness=0).model_dump())
            write_glb(OUT/(case['case']+'_'+stage+'_diagnostic.glb'),doc,binary,extra)
            result['stages'][stage]['diagnostic_colors']=[{'name':p[0]['name'],'color':COLORS[i%len(COLORS)]} for i,p in enumerate(groups.values())]
    if case['case']=='round_table':
        doc,binary,_=read_glb(OUT/'round_table_auto.glb');worlds=node_world_matrices(doc)
        top=next(p for p in parts_catalog(doc) if '桌面' in p['name']);primitive=doc['meshes'][doc['nodes'][top['node']]['mesh']]['primitives'][top['primitive']]
        v=accessor_array(doc,binary,primitive['attributes']['POSITION']);f=accessor_array(doc,binary,primitive['indices']).reshape(-1,3);v=(np.c_[v,np.ones(len(v))]@worlds[top['node']].T)[:,:3];tri=v[f];cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);n=cross/np.maximum(np.linalg.norm(cross,axis=1,keepdims=True),1e-15)
        result['top_surface_evidence']={'upward_faces':int((n[:,1]>.82).sum()),'downward_faces':int((n[:,1]<-.82).sum()),'rim_faces_abs_y_below_0_5':int((abs(n[:,1])<.5).sum()),'triangle_count':len(f),'centroid_y_range':[float(tri.mean(1)[:,1].min()),float(tri.mean(1)[:,1].max())]}
        assert result['top_surface_evidence']['downward_faces']>100;assert result['top_surface_evidence']['rim_faces_abs_y_below_0_5']>100
        from furniture_parts import primitive_data
        remainder=next(p for p in parts_catalog(doc) if '底座' in p['name']);primitive=doc['meshes'][doc['nodes'][remainder['node']]['mesh']]['primitives'][remainder['primitive']];_,_,_,centers,_,_=primitive_data(doc,binary,remainder,primitive)
        leftover=int(((centers[:,1]>1.17)&(np.linalg.norm(centers[:,[0,2]],axis=1)>.6)).sum());result['top_surface_evidence']['outer_rim_faces_in_base']=leftover
        assert leftover==0,'Protruding tabletop rim must not be left in the base'
    results.append(result);print(case['case']+' world triangles verified',flush=True)
(OUT/'geometry_preservation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
