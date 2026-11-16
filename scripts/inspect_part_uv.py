import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from services.api.glb_document import read_glb,parts_catalog
from edit_asset import accessor_array,node_world_matrices
OUT=ROOT/'experiments/part_tools_20261112';records=json.loads((OUT/'real_edits.json').read_text(encoding='utf-8'))
for c in records:
    def inspect(path,planar):
        doc,binary,_=read_glb(path);part=next(p for p in parts_catalog(doc) if p['id']==c['part_ids'][0]);p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']];v=accessor_array(doc,binary,p['attributes']['POSITION']);f=accessor_array(doc,binary,p['indices']).reshape(-1,3)
        if planar:
            axes=np.argsort(np.ptp(v,axis=0))[-2:];uv=v[:,axes];uv=(uv-uv.min(0))/np.maximum(np.ptp(uv,axis=0),1e-9)
        else:uv=accessor_array(doc,binary,p['attributes']['TEXCOORD_0'])
        t=uv[f];e=t[:,1]-t[:,0];d=t[:,2]-t[:,0];area=abs(e[:,0]*d[:,1]-e[:,1]*d[:,0])/2;world=(np.c_[v,np.ones(len(v))]@node_world_matrices(doc)[part['node']].T)[:,:3];t=world[f];geometry=np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1)/2
        return {'triangles':len(f),'uv_zero_area_faces_at_1e_12':int((area<1e-12).sum()),'geometry_area_fraction_with_collapsed_uv':float(geometry[area<1e-12].sum()/max(geometry.sum(),1e-15)),'threshold_note':'UV area below 1e-12; diagnostic, not texture resemblance or all stretching.'}
    c['planar_uv_diagnostic']=inspect(OUT/(c['case']+'_grouped.glb'),True);c['final_uv_diagnostic']=inspect(OUT/(c['case']+'_uv.glb'),False);c['source_sha256']=__import__('hashlib').sha256((ROOT/'.data/jobs'/c['source_job']/'model.glb').read_bytes()).hexdigest()
(OUT/'real_edits.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print('UV diagnostics updated')
