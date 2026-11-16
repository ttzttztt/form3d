"""Independent checker copies of all eight furniture cases; original assets retained."""
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.glb_document import read_glb,write_glb,material_edit,compact_static
from services.api.models import AssetEditRequest
from asset_operations import texture_edit
OUT=ROOT/'experiments/selection_refinement_20261112'
for case in json.loads((OUT/'uv_runs.json').read_text(encoding='utf-8')):
    for mode in ('box','proxy','cylinder'):
        source=OUT/(case['case']+'_'+mode+'.glb')
        if not source.exists():continue
        doc,binary,extra=read_glb(source)
        request=AssetEditRequest(operation='material',part_ids=case['part_ids'],color='#ffffff',roughness=.85,uv_scale=3).model_dump()
        request['_texture_paths']={'base_color_image':str(ROOT/'experiments/asset_upgrade_20261112/base_color_image.png')}
        material_edit(doc,request);texture_edit(doc,binary,request);binary=compact_static(doc,binary)
        write_glb(OUT/(case['case']+'_'+mode+'_checker.glb'),doc,binary,extra)
print('17 checker copies prepared; no source asset or product material changed',flush=True)
