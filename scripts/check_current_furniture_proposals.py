"""Compare current proposal partitions to the eight validated API exports."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from services.api.glb_document import read_glb,parts_catalog,set_part_ids
from services.api.models import AssetEditRequest
from furniture_parts import auto_parts,primitive_data
OUT=ROOT/'experiments/furniture_workbench_20261112'
def partitions(doc,binary):
    groups={}
    for part in parts_catalog(doc):
        p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']];_,faces,world,_,_,_=primitive_data(doc,binary,part,p);groups.setdefault(part['name'],[]).append(world[faces].astype('<f8').reshape(-1,9))
    result={}
    for name,arrays in groups.items():
        values=np.concatenate(arrays);rows=np.ascontiguousarray(values).view(np.dtype((np.void,72))).ravel();rows.sort();result[name]={'triangles':len(values),'world_triangle_sha256':hashlib.sha256(rows.tobytes()).hexdigest()}
    return result
results=[]
for case in json.loads((OUT/'real_runs.json').read_text(encoding='utf-8')):
    doc,binary,_=read_glb(ROOT/'.data/jobs'/case['source_job']/'model.glb');set_part_ids(doc);evidence=auto_parts(doc,binary,AssetEditRequest(operation='auto_parts',category=case['category']).model_dump());actual=partitions(doc,binary);old,oldbin,_=read_glb(OUT/(case['case']+'_auto.glb'));expected=partitions(old,oldbin);assert actual==expected,case['case'];results.append({'case':case['case'],'same_full_partition_world_triangles':True,'groups_by_name':actual,'current_evidence':evidence});print(case['case']+' current partitions match',flush=True)
(OUT/'current_proposals_regression.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
