# -*- coding: utf-8 -*-
import copy,hashlib,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
out=ROOT/'experiments/semantic_refinement_20261113';store=Store(ROOT/'.data');records=[]
if(out/'cases.json').exists():raise SystemExit('Existing cases kept')
for case in json.loads((ROOT/'experiments/semantic_parts_20261113/cases.json').read_text(encoding='utf-8')):
    sid=case['source_job'];job=copy.deepcopy(store.job(sid));identity=uuid.uuid4().hex
    for key in('asset_versions','current_asset_version','review'):job.pop(key,None)
    job.update(id=identity,name='多视角部件边界复测 · '+case['case'],status='awaiting_review',stage='semantic_boundary_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=sid)
    for key,value in list(job.items()):
        if isinstance(value,str):job[key]=value.replace(sid,identity)
    folder=store.root/'jobs'/identity;folder.mkdir();source=store.root/'jobs'/sid/'model.glb';shutil.copyfile(source,folder/'model.glb');store.create_job(job,'',identity);records.append({**case,'job':identity,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
(out/'cases.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(records,ensure_ascii=False))
