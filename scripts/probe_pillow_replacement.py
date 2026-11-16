# -*- coding: utf-8 -*-
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.api.glb_document import read_glb,parts_catalog
source=ROOT/'experiments/semantic_refinement_20261113/delivery/corduroy_sofa/model.glb';doc,_,_=read_glb(source);ids=[p['id']for p in parts_catalog(doc)if p['name']=='靠枕 1'];folder=ROOT/'experiments/part_regeneration_20261113/corduroy_pillow';request={'kind':'pillow','part_ids':ids};(folder/'replace_request.json').write_text(json.dumps(request),encoding='utf-8')
with(folder/'alignment.log').open('wb')as log:r=subprocess.run([str(ROOT/'.venv-hunyuan/Scripts/python.exe'),'-X','utf8',str(ROOT/'scripts/replace_generated_part.py'),'--input',str(source),'--candidate',str(folder/'generated_v1/model.glb'),'--request',str(folder/'replace_request.json'),'--output',str(folder/'replacement_v1')],stdout=log,stderr=subprocess.STDOUT)
print(r.returncode)
