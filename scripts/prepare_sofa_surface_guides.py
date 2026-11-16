# -*- coding: utf-8 -*-
"""Geometry-guided seat selection after the recorded SAM trial, not SAM accuracy."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from scipy.sparse.csgraph import connected_components
from services.api.glb_document import read_glb,parts_catalog
from furniture_parts import primitive_data,face_graph
OUT=ROOT/'experiments/multifurniture_20261113'
for case in json.loads((OUT/'cases.json').read_text(encoding='utf-8')):
    if 'sofa' not in case['case']:continue
    doc,binary,_=read_glb(ROOT/'.data/jobs'/case['job']/'model.glb');part=parts_catalog(doc)[0];p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']];v,f,w,c,n,area=primitive_data(doc,binary,part,p);low=w.min(0);extent=np.ptp(w,axis=0);ny=(c[:,1]-low[1])/extent[1];up=(n[:,1]>.7)&(ny>.17)&(ny<.67);hist,edges=np.histogram(ny[up],bins=64,range=(0,1),weights=area[up]);peak=(edges[np.argmax(hist)]+edges[np.argmax(hist)+1])/2
    candidate=np.flatnonzero(up&(abs(ny-peak)<.075));graph=face_graph(w,f,c);_,labels=connected_components(graph[candidate][:,candidate],directed=False);weights=np.bincount(labels,weights=area[candidate]);selected=candidate[labels==np.argmax(weights)]
    record={'operation':'complete_part','base_version':'original','part_ids':[],'face_selection':[{'part_id':part['id'],'faces':selected.tolist()}],'completion_profile':'cushion'}
    target=OUT/(case['case']+'_guide_request.json')
    if target.exists():(OUT/(case['case']+'_sam_guide_request.json')).write_bytes(target.read_bytes())
    target.write_text(json.dumps(record,indent=2),encoding='utf-8');(OUT/(case['case']+'_geometry_guide.json')).write_text(json.dumps({'method':'largest connected upward patch near dominant mid-height seat band; manually reviewed geometric seed, not semantic or SAM prediction','selected_faces':len(selected),'seat_height_fraction':peak,'selected_world_bounds':[w[f[selected]].reshape(-1,3).min(0).tolist(),w[f[selected]].reshape(-1,3).max(0).tolist()]},indent=2),encoding='utf-8');print(case['case'],len(selected),peak,flush=True)
