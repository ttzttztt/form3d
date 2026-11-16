import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,trimesh
from complete_part import mesh_stats,context,contour_planes
from services.api.glb_document import read_glb
OUT=ROOT/'experiments/complete_cushion_20261112';result={}
for name in ('cushion_export.glb','browser_cushion_export.glb'):
    m=trimesh.load(OUT/name,force='mesh',process=False);m.merge_vertices(digits_vertex=8);result[name]=mesh_stats(m);assert m.is_watertight and m.is_winding_consistent
trial=OUT/'vertex_move_trial_export.glb'
if trial.exists():
    m=trimesh.load(trial,force='mesh',process=False);m.merge_vertices(digits_vertex=8);result['earlier_vertex_move_trial']=mesh_stats(m)
run=json.loads((OUT/'actual_run.json').read_text(encoding='utf-8'));old=json.loads((ROOT/'experiments/selection_refinement_20261112/delivery_browser.json').read_text(encoding='utf-8'));doc,binary,_=read_glb(ROOT/'.data/jobs'/run['job']/'model.glb');_,_,_,source,guide=context(doc,binary,{'part_ids':old['part_ids']});original_area=guide.area;planes,_=contour_planes(source,guide);bounds=np.array(run['plan']['bounds_world'])
for axis in range(3):
    for side in (0,1):planes.append((np.eye(3)[axis]*bounds[side,axis],np.eye(3)[axis]*(1 if side==0 else -1)))
for o,n in planes:guide=trimesh.intersections.slice_mesh_plane(guide,n,o,cap=False)
result['retained_guide_surface_area_fraction']=float(guide.area/original_area);assert result['retained_guide_surface_area_fraction']>.98
(OUT/'export_geometry_check.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
