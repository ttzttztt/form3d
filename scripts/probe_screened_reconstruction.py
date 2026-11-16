"""Measured local screened-surface trials; generated geometry remains explicitly inferred."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh,pymeshlab
from services.api.glb_document import read_glb,selected_primitives
from furniture_parts import primitive_data
from solid_partition import prepare_mesh
from complete_part import mesh_stats
OUT=ROOT/'experiments/solid_parts_20261113';records=[]
for case in json.loads((ROOT/'experiments/semantic_parts_20261113/audit.json').read_text(encoding='utf-8')):
    if len(sys.argv)>1 and case['case'] not in sys.argv[1:]:continue
    doc,binary,_=read_glb(ROOT/'experiments/semantic_parts_20261113'/case['case']/'model.glb');groups={}
    for part,p in selected_primitives(doc,[]):
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);groups.setdefault(part['logical_group_id'],{'name':part['name'],'meshes':[]})['meshes'].append(trimesh.Trimesh(w,f,process=False))
    for ordinal,(identity,group) in enumerate(groups.items()):
        started=time.monotonic();source,removed=prepare_mesh(trimesh.util.concatenate(group['meshes']));center=source.bounds.mean(0);diagonal=np.linalg.norm(source.extents);v=(source.vertices-center)/diagonal;n=source.vertex_normals;record={'case':case['case'],'group_id':identity,'name':group['name'],'before':mesh_stats(source)};records.append(record)
        try:
            ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(vertex_matrix=v,face_matrix=source.faces.astype(np.int32),v_normals_matrix=n));ms.generate_surface_reconstruction_screened_poisson(depth=8,fulldepth=5,pointweight=8,samplespernode=1.5,threads=6);result=ms.current_mesh();mesh=trimesh.Trimesh(result.vertex_matrix()*diagonal+center,result.face_matrix(),process=False);mesh,removed_output=prepare_mesh(mesh);components=sorted(mesh.split(only_watertight=False),key=lambda m:m.area,reverse=True);record['raw_components']=[{'area_fraction':float(m.area/mesh.area),'closed':bool(m.is_watertight)} for m in components[:5]]
            mesh=components[0];mesh,removed_output=prepare_mesh(mesh);stats=mesh_stats(mesh);record['after']=stats
            rng=np.random.default_rng(20261113);ids=rng.choice(len(source.faces),8000,p=source.area_faces/source.area);triangles=source.triangles[ids];r=rng.random((8000,2));r[:,0]=np.sqrt(r[:,0]);points=triangles[:,0]*(1-r[:,0,None])+triangles[:,1]*(r[:,0]*(1-r[:,1]))[:,None]+triangles[:,2]*(r[:,0]*r[:,1])[:,None];_,distance,_=trimesh.proximity.closest_point(mesh,points);record['sampled_source_distance']={'samples':8000,'mean_ratio':float(distance.mean()/diagonal),'p95_ratio':float(np.quantile(distance,.95)/diagonal),'max_ratio':float(distance.max()/diagonal),'not_hausdorff':True};record['bounds_delta_ratio']=float(np.max(abs(mesh.bounds-source.bounds))/diagonal)
            check=pymeshlab.MeshSet();check.add_mesh(pymeshlab.Mesh(mesh.vertices,mesh.faces.astype(np.int32)));check.compute_selection_by_self_intersections_per_face();record['self_intersection_faces']=int(check.current_mesh().face_selection_array().sum());file=f'{case["case"]}_poisson_{ordinal}.glb';mesh.export(OUT/file);record['file']=file
        except Exception as exc:record['error']=repr(exc)
        record['seconds']=round(time.monotonic()-started,3);(OUT/'screened_probe.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=False),flush=True)
