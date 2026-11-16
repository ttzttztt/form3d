import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import trimesh
from services.api.glb_document import read_glb,parts_catalog
from replace_generated_part import selected_group
from part_registration import register_part
from soft_part_repair import fill_paper_pillow
from solid_partition import prepare_mesh
from complete_part import mesh_stats
from reconstruct_parts import intersections
d,b,_=read_glb(ROOT/'experiments/semantic_refinement_20261113/delivery/corduroy_sofa/model.glb')
ids=[p['id']for p in parts_catalog(d)if p['name']=='靠枕 1'];_,_,target=selected_group(d,b,ids)
candidate,_=prepare_mesh(trimesh.load(ROOT/'experiments/part_regeneration_20261113/corduroy_pillow/generated_v1/model.glb',force='mesh',process=False))
aligned,p=register_part(candidate,target);rebuilt,e=fill_paper_pillow(aligned,target,p)
out=ROOT/'experiments/soft_part_quality_20261113';rebuilt.export(out/'pillow_debug.glb')
for label,m in[('raw',rebuilt),('stored',prepare_mesh(rebuilt)[0])]:print(label,json.dumps(mesh_stats(m)),intersections(m),flush=True)
print(json.dumps(e))
