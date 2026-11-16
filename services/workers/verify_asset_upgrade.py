"""Exact world triangle multisets and file validity for the real edited exports."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import numpy as np
from services.api.glb_document import read_glb,parts_catalog
from services.api.geometry import validate_glb
from edit_asset import accessor_array,node_world_matrices

def signature(path):
    doc,binary,_=read_glb(path);worlds=node_world_matrices(doc);triangles=[]
    for part in parts_catalog(doc):
        primitive=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
        v=accessor_array(doc,binary,primitive['attributes']['POSITION']);f=accessor_array(doc,binary,primitive['indices']).reshape(-1,3) if 'indices' in primitive else np.arange(len(v)).reshape(-1,3)
        world=np.c_[v,np.ones(len(v))]@worlds[part['node']].T;triangles.append(world[f,:3].astype('<f8').reshape(-1,9))
    data=np.concatenate(triangles);rows=np.ascontiguousarray(data).view(np.dtype((np.void,72))).ravel();rows.sort()
    return {'world_triangle_multiset_sha256':hashlib.sha256(rows.tobytes()).hexdigest(),'triangles':len(data),'bounds':[data.reshape(-1,3).min(0).tolist(),data.reshape(-1,3).max(0).tolist()]}

if __name__=='__main__':
    folder=ROOT/'experiments/asset_upgrade_20261112';cases=json.loads((folder/'real_edits.json').read_text(encoding='utf-8'));results=[]
    for case in cases:
        source=ROOT/'.data/jobs'/case['source_job']/'model.glb';edited=folder/(case['case']+'_edited.glb')
        a=signature(source);b=signature(edited);assert a==b,case['case']
        record={'case':case['case'],'source':a,'edited':b,'exact_world_triangles_preserved':True,'validation':validate_glb(edited),'source_sha256_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==case['source_sha256']}
        assert record['source_sha256_unchanged'];results.append(record);print(case['case']+' verified',flush=True)
    (folder/'geometry_preservation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
