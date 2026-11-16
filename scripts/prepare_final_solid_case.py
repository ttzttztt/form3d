import copy,json,shutil,sys,uuid,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
out=ROOT/'experiments/solid_parts_20261113';store=Store(ROOT/'.data');path=out/'cases_final.json'
if path.exists():raise SystemExit('Existing final case kept')
cases=json.loads((out/'cases.json').read_text(encoding='utf-8'));case=cases[0];sid=case['source_job'];job=copy.deepcopy(store.job(sid));identity=uuid.uuid4().hex
for key in ('asset_versions','current_asset_version','review'):job.pop(key,None)
job.update(id=identity,name='完整圆柱抱枕与部件补全 · 皮革沙发',status='awaiting_review',stage='solid_parts_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=sid)
for key,value in list(job.items()):
    if isinstance(value,str):job[key]=value.replace(sid,identity)
folder=store.root/'jobs'/identity;folder.mkdir();source=out/'refined_semantic_v2/leather_sofa/model.glb';shutil.copyfile(source,folder/'model.glb');store.create_job(job,'',identity)
cases[0]={**case,'job':identity,'source_grouping_snapshot':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()};path.write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(cases[0],ensure_ascii=False))
