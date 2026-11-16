import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh,pymeshlab
from services.api.glb_document import read_glb,selected_primitives
from furniture_parts import primitive_data
from solid_partition import prepare_mesh
from complete_part import mesh_stats
from soft_shapes import pillow_sheets,bolster_profile
OUT=ROOT/'experiments/solid_parts_20261113';records=[]
for case in json.loads((ROOT/'experiments/semantic_parts_20261113/audit.json').read_text(encoding='utf-8')):
    if case['case']=='accent_chair':continue
    doc,binary,_=read_glb(ROOT/'experiments/semantic_parts_20261113'/case['case']/'model.glb');groups={}
    for part,p in selected_primitives(doc,[]):
        if part['semantic_kind'] not in ('pillow','bolster'):continue
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);groups.setdefault(part['logical_group_id'],{'name':part['name'],'kind':part['semantic_kind'],'meshes':[]})['meshes'].append(trimesh.Trimesh(w,f,process=False))
    for ordinal,(identity,group) in enumerate(groups.items()):
        source,_=prepare_mesh(trimesh.util.concatenate(group['meshes']));record={'case':case['case'],'name':group['name'],'group_id':identity};records.append(record);started=time.monotonic()
        try:
            mesh,evidence=(bolster_profile if group['kind']=='bolster' else pillow_sheets)(source);mesh,_=prepare_mesh(mesh);record.update(after=mesh_stats(mesh),components=len(mesh.split(only_watertight=False)),evidence=evidence);rng=np.random.default_rng(20261113);ids=rng.choice(len(source.faces),8000,p=source.area_faces/source.area);_,d,_=trimesh.proximity.closest_point(mesh,source.triangles_center[ids]);diag=np.linalg.norm(source.extents);record['sampled_source_distance']={'samples':8000,'p95_ratio':float(np.quantile(d,.95)/diag),'p99_ratio':float(np.quantile(d,.99)/diag),'max_ratio':float(d.max()/diag),'mean_ratio':float(d.mean()/diag)};ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(mesh.vertices,mesh.faces.astype(np.int32)));ms.compute_selection_by_self_intersections_per_face();record['self_intersection_faces']=int(ms.current_mesh().face_selection_array().sum());file=f'{case["case"]}_shape_{ordinal}.glb';mesh.export(OUT/file);record['file']=file
        except Exception as exc:record['error']=repr(exc)
        record['seconds']=round(time.monotonic()-started,3);(OUT/'soft_shape_probe.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=False),flush=True)
