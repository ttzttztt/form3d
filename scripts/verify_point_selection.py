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
out=ROOT/'experiments/point_selection_20261112';case=json.loads((out/'cases.json').read_text(encoding='utf-8'))[0];store=Store(ROOT/'.data');job=store.job(case['job']);version=job['current_asset_version'];path=store.root/'jobs'/job['id']/'assets'/version/'model.glb';original=store.root/'jobs'/case['source_job']/'model.glb'
a=signature(original);b=signature(path);assert a==b
doc,binary,_=read_glb(path);worlds=node_world_matrices(doc);rows=[]
for part in parts_catalog(doc):
    primitive=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']];vertices=accessor_array(doc,binary,primitive['attributes']['POSITION']);indices=accessor_array(doc,binary,primitive['indices']).ravel();world=(np.c_[vertices,np.ones(len(vertices))]@worlds[part['node']].T)[indices,:3]
    rows.append({'id':part['id'],'name':part['name'],'role':part['selection_role'],'triangles':part['triangles'],'bounds':[world.min(0).tolist(),world.max(0).tolist()],'color':part['base_color_factor']})
selected=next(p for p in rows if p['role']=='selected');height_range=[(selected['bounds'][i][1]-a['bounds'][0][1])/(a['bounds'][1][1]-a['bounds'][0][1]) for i in range(2)];assert height_range[0]>.95
source_sha=hashlib.sha256(original.read_bytes()).hexdigest();assert source_sha==hashlib.sha256((store.root/'jobs'/job['id']/'model.glb').read_bytes()).hexdigest()
result={'job':job['id'],'version':version,'original_world_triangles':a,'edited_world_triangles':b,'exact_triangles_preserved':True,'source_sha256':source_sha,'source_bytes_preserved':True,'selected_height_range_normalized':height_range,'parts':rows}
(out/'geometry_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
