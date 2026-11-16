import copy,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
OUT=ROOT/'experiments/multifurniture_20261113';store=Store(ROOT/'.data');case=next(c for c in json.loads((OUT/'cases.json').read_text(encoding='utf-8')) if c['case']=='chair');job=copy.deepcopy(store.job(case['job']));identity=uuid.uuid4().hex
for k in ('asset_versions','current_asset_version','review'):job.pop(k,None)
job.update(id=identity,name='底架续拆 · 界面验收副本',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=case['job'])
for k,v in list(job.items()):
    if isinstance(v,str):job[k]=v.replace(case['job'],identity)
folder=store.root/'jobs'/identity;folder.mkdir()
for p in (store.root/'jobs'/case['job']).iterdir():
    if p.is_file() and (p.name=='model.glb' or p.suffix=='.png'):shutil.copyfile(p,folder/p.name)
store.create_job(job,'',identity);(OUT/'ui_case.json').write_text(json.dumps({'job':identity},indent=2),encoding='utf-8');print(identity)
