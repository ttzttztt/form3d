# -*- coding: utf-8 -*-
"""Read-only diagnosis of source versus saved surface selection."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from scipy.sparse.csgraph import connected_components
from services.api.glb_document import read_glb,parts_catalog
from furniture_parts import primitive_data,face_graph
from mesh_quality import geometry_stats
OUT=ROOT/'experiments/complete_cushion_20261112';OUT.mkdir(exist_ok=True)
source='6be16d93f7544ac79c5f09cb3be507fa';delivery=json.loads((ROOT/'experiments/selection_refinement_20261112/delivery_browser.json').read_text(encoding='utf-8'))
def arrays(path,identity=None):
    doc,binary,_=read_glb(path);part=next(p for p in parts_catalog(doc) if identity is None or p['id']==identity);p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']];v,f,w,c,n,a=primitive_data(doc,binary,part,p);return w,f,c,n,a
v,f,c,n,a=arrays(ROOT/'.data/jobs'/source/'model.glb')
sv,sf,sc,sn,sa=arrays(ROOT/'.data/jobs'/delivery['job']/'assets'/delivery['split_version']/'model.glb',delivery['part_ids'][0])
assert np.array_equal(v,sv)
lookup={tuple(row):i for i,row in enumerate(f)};selected=np.array([lookup[tuple(row)] for row in sf]);mask=np.zeros(len(f),dtype=bool);mask[selected]=True
stats={}
for label,faces in [('source',f),('selected_surface',sf),('remainder',f[~mask])]:
    used=np.unique(faces);m=np.full(len(v),-1);m[used]=np.arange(len(used));stat,_=geometry_stats(v[used],m[faces]);graph=face_graph(v,faces,v[faces].mean(1));count,cc=connected_components(graph,directed=False);stat.update(bounds=[v[used].min(0).tolist(),v[used].max(0).tolist()],connected_components=int(count),largest_components=sorted(np.bincount(cc).tolist(),reverse=True)[:10]);stats[label]=stat
stats['source_job']=source;stats['selection_job']=delivery['job'];stats['selection_version']=delivery['split_version'];stats['selection_part']=delivery['part_ids'][0];stats['selection_normal_area']={key:float(sa[sn[:,i]*sign>.7].sum()/sa.sum()) for key,i,sign in [('right',0,1),('left',0,-1),('top',1,1),('bottom',1,-1),('front',2,1),('back',2,-1)]}
np.savez_compressed(OUT/'source_selection.npz',vertices=v,faces=f,selected=selected);(OUT/'initial_diagnosis.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(stats,ensure_ascii=False,indent=2))
