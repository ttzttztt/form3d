import copy,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
OUT=ROOT/'experiments/selection_refinement_20261112';store=Store(ROOT/'.data');c=next(c for c in json.loads((OUT/'cases.json').read_text(encoding='utf-8')) if c['case']=='accent_chair');sid=c['source_job'];job=copy.deepcopy(store.job(sid));identity=uuid.uuid4().hex
for key in ('asset_versions','current_asset_version','review'):job.pop(key,None)
job.update(id=identity,name='最终多点选区与材质验收副本',status='awaiting_review',stage='refinement_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=sid)
for key,value in list(job.items()):
    if isinstance(value,str):job[key]=value.replace(sid,identity)
directory=store.root/'jobs'/identity;directory.mkdir()
for p in (store.root/'jobs'/sid).iterdir():
    if p.is_file() and (p.suffix=='.png' or p.name=='model.glb'):shutil.copyfile(p,directory/p.name)
store.create_job(job,'',identity);(OUT/'delivery_case.json').write_text(json.dumps({**c,'job':identity},ensure_ascii=False,indent=2),encoding='utf-8');print(identity)
