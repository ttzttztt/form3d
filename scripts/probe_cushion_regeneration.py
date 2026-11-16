"""Geometry feasibility only, using an explicitly inferred, visually failed reference."""
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.glb_document import read_glb,parts_catalog
source=ROOT/'experiments/solid_parts_20261113/delivery/leather_sofa/model.glb'
doc,_,_=read_glb(source);ids=[p['id']for p in parts_catalog(doc)if p['name']=='坐面与主体 1']
folder=ROOT/'experiments/part_regeneration_20261113/leather_cushion'
output=folder/'replacement_outline_trial_v2'
if output.exists():raise SystemExit('Existing outline trial preserved')
(folder/'replace_request.json').write_text(json.dumps({'kind':'cushion','part_ids':ids}),encoding='utf-8')
with(folder/'alignment_trial.log').open('wb')as log:
    result=subprocess.run([str(ROOT/'.venv-hunyuan/Scripts/python.exe'),'-X','utf8',str(ROOT/'scripts/replace_generated_part.py'),'--input',str(source),'--candidate',str(folder/'generated_trial_v1/model.glb'),'--request',str(folder/'replace_request.json'),'--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
print(result.returncode)
