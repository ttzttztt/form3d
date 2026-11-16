import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh,pymeshlab
from complete_part import mesh_stats
OUT=ROOT/'experiments/solid_parts_20261113';records=[]
for row in json.loads((OUT/'closure_probe.json').read_text(encoding='utf-8')):
    d=np.load(OUT/(Path(row['file']).stem+'.npz'));mesh=trimesh.Trimesh(d['vertices'],d['faces'],process=False);ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(mesh.vertices,mesh.faces.astype(np.int32)));ms.meshing_close_holes(maxholesize=32,selected=False,newfaceselected=True,selfintersection=False,refinehole=False);m=ms.current_mesh();v=m.vertex_matrix();f=m.face_matrix();result=trimesh.Trimesh(v.astype(np.float32),f,process=False);result.merge_vertices(digits_vertex=8);record={k:row[k] for k in ('case','group','name','file')};record.update(after=mesh_stats(result),components=len(result.split(only_watertight=False)))
    if result.is_watertight:
        ms.compute_selection_by_self_intersections_per_face();selected=ms.current_mesh().face_selection_array();record['self_intersection_faces']=int(selected.sum());record['new_intersection_faces']=int(selected[len(mesh.faces):].sum());record['cap_intersection_faces']=int(selected[:len(mesh.faces)][d['inferred']].sum())
    result.export(OUT/(Path(row['file']).stem+'_sealed.glb'));np.savez_compressed(OUT/(Path(row['file']).stem+'_sealed.npz'),vertices=v,faces=f);records.append(record);(OUT/'closure_sealed.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=False),flush=True)
