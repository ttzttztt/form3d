import copy,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
OUT=ROOT/'experiments/complete_cushion_20261112';store=Store(ROOT/'.data');run=json.loads((OUT/'actual_run.json').read_text(encoding='utf-8'));original=store.job(run['job']);job=copy.deepcopy(original);identity=uuid.uuid4().hex
for k in ('asset_versions','current_asset_version','review'):job.pop(k,None)
job.update(id=identity,name='坐垫完整拆分 · 浏览器验收',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=run['job'])
for k,v in list(job.items()):
    if isinstance(v,str):job[k]=v.replace(run['job'],identity)
folder=store.root/'jobs'/identity;folder.mkdir()
for p in (store.root/'jobs'/run['job']).iterdir():
    if p.is_file() and (p.suffix=='.png' or p.name=='model.glb'):shutil.copyfile(p,folder/p.name)
store.create_job(job,'',identity);(OUT/'browser_case.json').write_text(json.dumps({'job':identity},indent=2),encoding='utf-8');print(identity)
