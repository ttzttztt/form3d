"""Read-only topology and boundary-planarity evidence for existing semantic groups."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh
from shapely.geometry import Polygon
from services.api.glb_document import read_glb,selected_primitives
from furniture_parts import primitive_data
OUT=ROOT/'experiments/solid_parts_20261113';OUT.mkdir(exist_ok=True);records=[]
for case in json.loads((ROOT/'experiments/semantic_parts_20261113/audit.json').read_text(encoding='utf-8')):
    path=ROOT/'experiments/semantic_parts_20261113'/case['case']/'model.glb';doc,binary,_=read_glb(path);groups={}
    for part,p in selected_primitives(doc,[]):
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);groups.setdefault(part['logical_group_id'],{'name':part['name'],'meshes':[]})['meshes'].append(trimesh.Trimesh(w,f,process=False))
    for identity,group in groups.items():
        mesh=trimesh.util.concatenate(group['meshes']);mesh.merge_vertices(digits_vertex=8);mesh.remove_unreferenced_vertices();edges,count=np.unique(mesh.edges_sorted,axis=0,return_counts=True);boundary=edges[count==1];adj={}
        for a,b in boundary:adj.setdefault(int(a),[]).append(int(b));adj.setdefault(int(b),[]).append(int(a))
        bad=sum(len(v)!=2 for v in adj.values());unseen=set(adj);loops=[]
        while unseen:
            start=next(iter(unseen));stack=[start];component=[]
            while stack:
                v=stack.pop()
                if v not in unseen:continue
                unseen.remove(v);component.append(v);stack.extend(adj[v])
            if any(len(adj[v])!=2 for v in component):loops.append({'vertices':len(component),'simple':False});continue
            chain=[start];previous=-1;current=start
            while True:
                nxt=next(v for v in adj[current] if v!=previous)
                if nxt==start:break
                chain.append(nxt);previous,current=current,nxt
            points=mesh.vertices[chain];center=points.mean(0);_,singular,basis=np.linalg.svd(points-center,full_matrices=False);xy=(points-center)@basis[:2].T;distance=abs((points-center)@basis[2]);extent=np.linalg.norm(np.ptp(points,axis=0));poly=Polygon(xy);loops.append({'vertices':len(chain),'simple':True,'projected_valid':bool(poly.is_valid),'area_projected':float(poly.area),'perimeter':float(np.linalg.norm(points-np.roll(points,1,axis=0),axis=1).sum()),'max_plane_deviation':float(distance.max()),'relative_plane_deviation':float(distance.max()/max(extent,1e-12)),'bounds':[points.min(0).tolist(),points.max(0).tolist()]})
        records.append({'case':case['case'],'group_id':identity,'name':group['name'],'faces':len(mesh.faces),'components':len(mesh.split(only_watertight=False)),'boundary_edges':len(boundary),'branch_vertices':bad,'loops':sorted(loops,key=lambda l:l['vertices'],reverse=True)});print(case['case'],group['name'],'branches',bad,'loops',[(l['vertices'],l.get('projected_valid'),round(l.get('relative_plane_deviation',0),3)) for l in records[-1]['loops'][:8]],flush=True)
(OUT/'boundary_diagnosis.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
