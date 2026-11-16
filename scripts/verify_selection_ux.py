"""Geometry and source immutability evidence for the real selection/material run."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from verify_asset_upgrade import signature
from edit_asset import accessor_array,node_world_matrices
from services.api.glb_document import read_glb,parts_catalog
from services.api.store import Store
out=ROOT/'experiments/selection_ux_20261112';case=json.loads((out/'cases.json').read_text(encoding='utf-8'))[0];store=Store(ROOT/'.data');job=store.job(case['job']);version=job['current_asset_version'];path=store.root/'jobs'/job['id']/'assets'/version/'model.glb';original=store.root/'jobs'/case['source_job']/'model.glb'
a=signature(original);b=signature(path);assert a==b
doc,binary,_=read_glb(path);worlds=node_world_matrices(doc);rows=[]
for p in parts_catalog(doc):
    primitive=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];v=accessor_array(doc,binary,primitive['attributes']['POSITION']);f=accessor_array(doc,binary,primitive['indices']).ravel();v=(np.c_[v,np.ones(len(v))]@worlds[p['node']].T)[f,:3]
    rows.append({'id':p['id'],'name':p['name'],'role':p['selection_role'],'faces':p['triangles'],'bounds':[v.min(0).tolist(),v.max(0).tolist()],'color':p['base_color_factor']})
record={'job':job['id'],'version':version,'source_signature':a,'edited_signature':b,'exact_world_triangles_preserved':True,'parts':rows,'source_file_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'copy_original_sha256':hashlib.sha256((store.root/'jobs'/job['id']/'model.glb').read_bytes()).hexdigest()}
assert record['source_file_sha256']==record['copy_original_sha256']
selected=next(p for p in rows if p['role']=='selected');record['selected_height_range_normalized']=[(selected['bounds'][i][1]-a['bounds'][0][1])/(a['bounds'][1][1]-a['bounds'][0][1]) for i in range(2)]
(out/'real_table_geometry_check.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=False))
