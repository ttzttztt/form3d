"""Compare old failed candidates with evidence-guided geometry, no new AI claim."""
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.glb_document import read_glb,parts_catalog
out=ROOT/'experiments/soft_part_quality_20261113';out.mkdir(exist_ok=True)
for label,snapshot,part_name,kind,method,candidate in [
    ('corduroy_pillow','semantic_refinement_20261113/delivery/corduroy_sofa/model.glb','靠枕 1','pillow','ai_regeneration','part_regeneration_20261113/corduroy_pillow/generated_v1/model.glb'),
    ('leather_seat','solid_parts_20261113/delivery/leather_sofa/model.glb','坐面与主体 1','cushion','source_seam',None),
]:
    folder=out/label
    if (folder/'manifest.json').exists():print('Existing trial preserved',label);continue
    folder.mkdir(exist_ok=True);source=ROOT/'experiments'/snapshot;doc,_,_=read_glb(source)
    ids=[p['id']for p in parts_catalog(doc)if p['name']==part_name]
    request={'kind':kind,'part_ids':ids,'method':method};request_path=out/(label+'_request.json');request_path.write_text(json.dumps(request),encoding='utf-8')
    command=[str(ROOT/'.venv-hunyuan/Scripts/python.exe'),'-X','utf8',str(ROOT/'scripts/replace_generated_part.py'),'--input',str(source),'--request',str(request_path),'--output',str(folder)]
    if candidate:command.extend(['--candidate',str(ROOT/'experiments'/candidate)])
    with(out/(label+'_worker.log')).open('wb')as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    print(label,result.returncode,flush=True)
