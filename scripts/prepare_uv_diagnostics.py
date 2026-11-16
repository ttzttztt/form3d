"""Same checker material, separate copies; no source or user material overwritten."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.glb_document import read_glb,write_glb,material_edit,compact_static
from services.api.models import AssetEditRequest
from asset_operations import texture_edit
OUT=ROOT/'experiments/part_tools_20261112';records=json.loads((OUT/'real_edits.json').read_text(encoding='utf-8'))
for case in records:
    for name,suffix in [('planar','grouped'),('unwrapped','uv')]:
        doc,binary,extra=read_glb(OUT/(case['case']+'_'+suffix+'.glb'));request=AssetEditRequest(operation='material',part_ids=case['part_ids'],color='#ffffff',roughness=.85,uv_scale=3).model_dump();request['_texture_paths']={'base_color_image':str(ROOT/'experiments/asset_upgrade_20261112/base_color_image.png')};material_edit(doc,request);texture_edit(doc,binary,request);binary=compact_static(doc,binary);write_glb(OUT/(case['case']+'_'+name+'_checker.glb'),doc,binary,extra)
print('Checker copies prepared; diagnostic patterns, not recovered product textures')
