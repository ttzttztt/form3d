"""Real nonplanar hole filling trials; do not publish or overwrite source assets."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh,pymeshlab
from services.api.glb_document import read_glb,selected_primitives
from furniture_parts import primitive_data
from complete_part import mesh_stats
from solid_partition import prepare_mesh
OUT=ROOT/'experiments/solid_parts_20261113';OUT.mkdir(exist_ok=True);records=[]
for case in json.loads((ROOT/'experiments/semantic_parts_20261113/audit.json').read_text(encoding='utf-8')):
    doc,binary,_=read_glb(ROOT/'experiments/semantic_parts_20261113'/case['case']/'model.glb');groups={}
    for part,p in selected_primitives(doc,[]):
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);groups.setdefault(part['logical_group_id'],{'name':part['name'],'meshes':[]})['meshes'].append(trimesh.Trimesh(w,f,process=False))
    for ordinal,(identity,group) in enumerate(groups.items()):
        started=time.monotonic();source,removed=prepare_mesh(trimesh.util.concatenate(group['meshes']));record={'case':case['case'],'group':identity,'name':group['name'],'before':mesh_stats(source),'source_cleanup_faces':removed};records.append(record)
        try:
            ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(source.vertices.astype(float),source.faces.astype(np.int32)));ms.meshing_repair_non_manifold_vertices(vertdispratio=0);ms.meshing_close_holes(maxholesize=3000,selected=False,newfaceselected=True,selfintersection=True,refinehole=False);m=ms.current_mesh();selected=m.face_selection_array().copy();mesh=trimesh.Trimesh(m.vertex_matrix(),m.face_matrix(),process=False);mesh.merge_vertices(digits_vertex=8);record.update(after=mesh_stats(mesh),new_faces=int(selected.sum()),components=len(mesh.split(only_watertight=False)));file=f'{case["case"]}_trial_{ordinal}.glb';mesh.export(OUT/file);record['file']=file
            np.savez_compressed(OUT/f'{case["case"]}_trial_{ordinal}.npz',vertices=m.vertex_matrix(),faces=m.face_matrix(),inferred=selected)
        except Exception as exc:record['error']=repr(exc)
        record['seconds']=round(time.monotonic()-started,3);(OUT/'closure_probe.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in record.items() if k not in ('before',)},ensure_ascii=False),flush=True)
