# -*- coding: utf-8 -*-
"""Real API previews on isolated copies. Bounds are manually chosen, not AI recognition."""
import hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx,numpy as np
from services.api.glb_document import read_glb,parts_catalog
from furniture_parts import primitive_data
OUT=ROOT/'experiments/sofa_refinement_20261113';BASE='http://127.0.0.1:8001'
BOUNDS={'leather_sofa':[[0,.385,0],[1,.523,1]],'corduroy_sofa':[[0,.415,.64],[.70,.57,.935]]}
def main():
    client=httpx.Client(base_url=BASE,timeout=240)
    cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'))
    for case in cases:
        label=case['case']
        if len(sys.argv)>1 and label not in sys.argv[1:]:continue
        record={'case':label,'job':case['job'],'method':'manual normalized volume bounds with source-surface guide; not semantic recognition'}
        try:
            root=f'/api/jobs/{case["job"]}/asset';catalog=client.get(root).json()
            if catalog['version']!='original':raise ValueError('Benchmark needs untouched isolated source copy')
            doc,binary,_=read_glb(ROOT/'.data/jobs'/case['job']/'model.glb');part=parts_catalog(doc)[0];p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
            _,f,w,c,n,a=primitive_data(doc,binary,part,p);q=(c-w.min(0))/np.ptp(w,axis=0)
            request={'operation':'complete_part','base_version':'original','name':'坐垫范围复测' if 'sofa' in label else '回归部件','completion_profile':'cushion','completion_shape':'box','part_ids':[]}
            if label in BOUNDS:
                bounds=BOUNDS[label];selected=np.flatnonzero(np.all((q>=bounds[0])&(q<=bounds[1]),axis=1));request.update(completion_bounds=bounds,face_selection=[{'part_id':part['id'],'faces':selected.tolist()}])
            elif label=='accent_chair':
                saved=np.load(ROOT/'experiments/complete_cushion_20261112/source_selection.npz');np.testing.assert_array_equal(w,saved['vertices']);request.update(completion_shape='contour',face_selection=[{'part_id':part['id'],'faces':saved['selected'].tolist()}])
            else:request.update(completion_profile='slab',completion_shape='contour',part_ids=[part['id']],face_selection=[])
            plan=client.post(root+'/completion-plan',json=request);record['plan_status']=plan.status_code;record['plan']=plan.json();plan.raise_for_status()
            request.setdefault('completion_bounds',record['plan']['completion_bounds']);(OUT/(label+'_request.json')).write_text(json.dumps(request,indent=2),encoding='utf-8')
            started=time.monotonic();response=client.post(root+'/completion-preview',json=request);record.update(preview_status=response.status_code,preview_seconds=round(time.monotonic()-started,3),preview=response.json());response.raise_for_status()
            assert client.get(root).json()['version']=='original';record['preview_did_not_publish']=True
            preview=record['preview'];diagnostic=client.get(preview['preview_url']);diagnostic.raise_for_status();(OUT/(label+'_diagnostic.glb')).write_bytes(diagnostic.content)
            previewdir=ROOT/'.data/jobs'/case['job']/'completion_previews'/preview['preview_id'];raw=(previewdir/'model.glb').read_bytes();(OUT/(label+'_preview.glb')).write_bytes(raw)
            record['source_unchanged']=hashlib.sha256((ROOT/'.data/jobs'/case['job']/'model.glb').read_bytes()).hexdigest()==case['source_sha256'];assert record['source_unchanged']
            record['preview_model_sha256']=hashlib.sha256(raw).hexdigest()
        except Exception as exc:record['error']=repr(exc)
        (OUT/(label+'_run.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:record[k] for k in ('case','preview_status','preview_seconds','error') if k in record},ensure_ascii=False),flush=True)
    client.close()
if __name__=='__main__':main()
