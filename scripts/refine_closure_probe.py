import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh
from solid_partition import stitch_collinear_boundaries,clean_labelled
from complete_part import mesh_stats
OUT=ROOT/'experiments/solid_parts_20261113';records=[]
for row in json.loads((OUT/'closure_probe.json').read_text(encoding='utf-8')):
    path=OUT/(Path(row['file']).stem+'.npz');d=np.load(path);mesh=trimesh.Trimesh(d['vertices'].astype(np.float32),d['faces'],process=False);labels=d['inferred'];mesh.merge_vertices(digits_vertex=8);mesh,labels=clean_labelled(mesh,labels);mesh,labels,split=stitch_collinear_boundaries(mesh,labels,np.linalg.norm(mesh.extents)*1e-7);components=mesh.split(only_watertight=False);stats=mesh_stats(mesh);record={**{k:row[k] for k in ('case','group','name','file')},'after':stats,'stitches':split,'components':sorted([{'faces':len(m.faces),'area_fraction':float(m.area/mesh.area),'closed':bool(m.is_watertight),'volume':float(m.volume) if m.is_watertight else None} for m in components],key=lambda m:m['area_fraction'],reverse=True)};records.append(record);np.savez_compressed(OUT/(Path(row['file']).stem+'_stitched.npz'),vertices=mesh.vertices,faces=mesh.faces,inferred=labels);mesh.export(OUT/(Path(row['file']).stem+'_stitched.glb'));print(row['case'],row['name'],stats,'components',record['components'][:3],flush=True)
(OUT/'closure_stitched.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
