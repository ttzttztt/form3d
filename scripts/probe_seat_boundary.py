"""Diagnose seam evidence, never assume a fixed percentage is a seat bottom."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh
from scipy.ndimage import gaussian_filter1d
from services.api.glb_document import read_glb,selected_primitives
from furniture_parts import primitive_data
from solid_partition import prepare_mesh
records=[]
for case in ('leather_sofa','corduroy_sofa','accent_chair'):
    doc,binary,_=read_glb(ROOT/'experiments/semantic_parts_20261113'/case/'model.glb');meshes=[]
    for part,p in selected_primitives(doc,[]):
        if part['semantic_kind']!='seat':continue
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);meshes.append(trimesh.Trimesh(w,f,process=False))
    if not meshes:continue
    m,_=prepare_mesh(trimesh.util.concatenate(meshes));low,high=m.bounds;h=high[1]-low[1];c=m.triangles_center;n=m.face_normals;area=m.area_faces
    topmask=(n[:,1]>.85)&(c[:,1]>low[1]+h*.2)&(c[:,1]<low[1]+h*.9);hist,edges=np.histogram(c[topmask,1],bins=100,range=(low[1],high[1]),weights=area[topmask]);hist=gaussian_filter1d(hist,1);order=np.argsort(hist)[::-1]
    peaks=[]
    for i in order:
        y=(edges[i]+edges[i+1])/2
        if hist[i]>0 and all(abs(y-p['y'])>h*.05 for p in peaks):peaks.append({'y':y,'score':hist[i]})
        if len(peaks)==4:break
    e=m.vertices[m.face_adjacency_edges];delta=e[:,1]-e[:,0];length=np.linalg.norm(delta,axis=1);middle=e.mean(1);angle=m.face_adjacency_angles;concave=~m.face_adjacency_convex
    horizontal=abs(delta[:,1])/np.maximum(length,1e-12)<.25;valid=concave&horizontal&(angle>.1)&(middle[:,1]>low[1]+h*.15)&(middle[:,1]<peaks[0]['y']-h*.02);score=length*angle
    hh,ee=np.histogram(middle[valid,1],bins=100,range=(low[1],high[1]),weights=score[valid]);hh=gaussian_filter1d(hh,1);seams=[]
    for i in np.argsort(hh)[::-1]:
        y=(ee[i]+ee[i+1])/2
        if hh[i]>0 and all(abs(y-p['y'])>h*.04 for p in seams):seams.append({'y':y,'score':hh[i]})
        if len(seams)==5:break
    records.append({'case':case,'body_bounds':m.bounds.tolist(),'top_peaks':peaks,'seam_peaks':seams});print(json.dumps(records[-1]),flush=True)
(ROOT/'experiments/solid_parts_20261113/seat_boundary_probe.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
