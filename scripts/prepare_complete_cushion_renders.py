import json,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.glb_document import read_glb,write_glb,parts_catalog,compact_static,material_edit
from services.api.models import AssetEditRequest
from part_tools import export_parts
OUT=ROOT/'experiments/complete_cushion_20261112';r=json.loads((OUT/'actual_run.json').read_text(encoding='utf-8'));old=json.loads((ROOT/'experiments/selection_refinement_20261112/delivery_browser.json').read_text(encoding='utf-8'))
path=ROOT/'.data/jobs'/old['job']/'assets'/old['split_version']/'model.glb';doc,binary,extra=read_glb(path);export_parts(doc,binary,{'part_ids':old['part_ids']});binary=compact_static(doc,binary);write_glb(OUT/'old_surface.glb',doc,binary,extra)
doc,binary,extra=read_glb(OUT/'complete_candidate.glb');parts=parts_catalog(doc)
for role,color in [('observed_surface','#82a2bf'),('inferred_interface','#f0a044')]:
    ids=[p['id'] for p in parts if p['completion_role']==role and p['logical_group_id']==r['part_group_id']];material_edit(doc,AssetEditRequest(operation='material',part_ids=ids,color=color,roughness=.85).model_dump())
export_parts(doc,binary,{'part_ids':r['part_ids']});binary=compact_static(doc,binary);write_glb(OUT/'cushion_inferred_diagnostic.glb',doc,binary,extra)
shutil.copyfile(ROOT/'.data/jobs/6be16d93f7544ac79c5f09cb3be507fa/prepared.png',OUT/'reference.png')
