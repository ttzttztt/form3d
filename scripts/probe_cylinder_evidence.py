import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from services.api.glb_document import read_glb,parts_catalog
from furniture_parts import primitive_data
from cylinder_evidence import fit_cylinder
if '--debug' in sys.argv:
    def trace(frame,event,arg):
        if event=='return' and frame.f_code.co_name=='fit_cylinder':
            values=frame.f_locals;print('FIT_DEBUG',{k:(values[k].tolist() if isinstance(values[k],np.ndarray) else values[k]) for k in ('eigen','axis','best_count','radius','angular_bins','lo','hi') if k in values},flush=True)
        return trace
    sys.settrace(trace)
OUT=ROOT/'experiments/semantic_parts_20261113';records=[]
for name,sid in [('leather','11c5d7496508427cad48c22c5959f53b'),('corduroy','0ee3d49864e543bb92a66ad9cf19115b')]:
    folder=OUT/(name+'_views');doc,binary,_=read_glb(ROOT/'.data/jobs'/sid/'model.glb');part=parts_catalog(doc)[0];p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']];_,f,v,c,n,a=primitive_data(doc,binary,part,p);labels=np.load(folder/'assignments.npz')['labels'];groups=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))['operation']['groups']
    for group in groups:
        if group['kind'] not in ('pillow','bolster'):continue
        ids=np.flatnonzero(labels==group['label']);result=fit_cylinder(c[ids],n[ids],a[ids],np.linalg.norm(np.ptp(v,axis=0)));record={'case':name,'name':group['name'],'fit':None if result is None else result[1]};records.append(record);print(json.dumps(record),flush=True)
(OUT/'cylinder_probe.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
