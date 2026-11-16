import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh,pymeshlab
from services.api.glb_document import read_glb,selected_primitives
from furniture_parts import primitive_data
from solid_partition import prepare_mesh
from complete_part import mesh_stats
from bounded_surface import bounded_field_mesh
OUT=ROOT/'experiments/solid_parts_20261113';records=[]
for case in json.loads((ROOT/'experiments/semantic_parts_20261113/audit.json').read_text(encoding='utf-8')):
    if len(sys.argv)>1 and case['case'] not in sys.argv[1:]:continue
    doc,binary,_=read_glb(ROOT/'experiments/semantic_parts_20261113'/case['case']/'model.glb');groups={}
    for part,p in selected_primitives(doc,[]):
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);groups.setdefault(part['logical_group_id'],{'name':part['name'],'meshes':[]})['meshes'].append(trimesh.Trimesh(w,f,process=False))
    for ordinal,(identity,group) in enumerate(groups.items()):
        guidepath=OUT/f'{case["case"]}_poisson_{ordinal}.glb'
        if not guidepath.exists():continue
        started=time.monotonic();source,_=prepare_mesh(trimesh.util.concatenate(group['meshes']));guide=trimesh.load(guidepath,force='mesh',process=False);record={'case':case['case'],'group':identity,'name':group['name']};records.append(record)
        try:
            mesh,evidence=bounded_field_mesh(source,guide,resolution=160);mesh,_=prepare_mesh(mesh);record.update(after=mesh_stats(mesh),components=len(mesh.split(only_watertight=False)),evidence=evidence);rng=np.random.default_rng(20261113);ids=rng.choice(len(source.faces),8000,p=source.area_faces/source.area);points=source.triangles_center[ids];_,d,_=trimesh.proximity.closest_point(mesh,points);diag=np.linalg.norm(source.extents);record['sampled_source_distance']={'samples':8000,'p95_ratio':float(np.quantile(d,.95)/diag),'max_ratio':float(d.max()/diag),'mean_ratio':float(d.mean()/diag)};record['bounds_delta_ratio']=float(np.max(abs(mesh.bounds-source.bounds))/diag)
            ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(mesh.vertices,mesh.faces.astype(np.int32)));ms.compute_selection_by_self_intersections_per_face();record['self_intersection_faces']=int(ms.current_mesh().face_selection_array().sum());file=f'{case["case"]}_bounded_{ordinal}.glb';mesh.export(OUT/file);record['file']=file
        except Exception as exc:record['error']=repr(exc)
        record['seconds']=round(time.monotonic()-started,3);(OUT/'bounded_probe.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=False),flush=True)
