import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import trimesh,numpy as np,pymeshlab
from winding_surface import winding_surface
from solid_partition import prepare_mesh
from services.api.glb_document import read_glb,selected_primitives
from furniture_parts import primitive_data
from complete_part import mesh_stats
out=ROOT/'experiments/solid_parts_20261113';records=[]
for case,ordinals in [('leather_sofa',[0,1,2]),('corduroy_sofa',[0])]:
    doc,binary,_=read_glb(ROOT/'experiments/semantic_parts_20261113'/case/'model.glb');groups={}
    for part,p in selected_primitives(doc,[]):
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);groups.setdefault(part['logical_group_id'],[]).append(trimesh.Trimesh(w,f,process=False))
    for i,group in enumerate(groups.values()):
        if i not in ordinals:continue
        source,_=prepare_mesh(trimesh.util.concatenate(group));mesh,e=winding_surface(source);components=sorted(mesh.split(only_watertight=False),key=lambda m:m.area,reverse=True);discarded=1-components[0].area/mesh.area;mesh,_=prepare_mesh(components[0]);ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(mesh.vertices,mesh.faces.astype(np.int32)));ms.compute_selection_by_self_intersections_per_face();rng=np.random.default_rng(20261113);ids=rng.choice(len(source.faces),8000,p=source.area_faces/source.area);_,d,_=trimesh.proximity.closest_point(mesh,source.triangles_center[ids]);diag=np.linalg.norm(source.extents);file=f'{case}_smooth_{i}.glb';mesh.export(out/file);records.append({'case':case,'ordinal':i,'file':file,'after':mesh_stats(mesh),'discarded_reconstructed_area_fraction':discarded,'self_intersection_faces':int(ms.current_mesh().face_selection_array().sum()),'distance_p95':float(np.quantile(d,.95)/diag),'distance_p99':float(np.quantile(d,.99)/diag),'distance_max':float(d.max()/diag),'bounds_delta_ratio':float(np.max(abs(mesh.bounds-source.bounds))/diag),'evidence':e});(out/'smoothed_probe.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print(json.dumps(records[-1]),flush=True)
