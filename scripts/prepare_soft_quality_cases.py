import copy,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
from services.api.geometry import inspect_glb
out=ROOT/'experiments/soft_part_quality_20261113';store=Store(ROOT/'.data')
if(out/'cases.json').exists():raise SystemExit('Existing cases preserved')
old=json.loads((ROOT/'experiments/part_regeneration_20261113/cases.json').read_text(encoding='utf-8'));records=[]
for c in old:
    identity=uuid.uuid4().hex;job=copy.deepcopy(store.job(c['source_job']))
    job.update(id=identity,name='软包体积修复复测 · '+c['case'],status='awaiting_review',stage='soft_volume_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=c['source_job'])
    for key in('asset_versions','current_asset_version','quality_report'):job.pop(key,None)
    job['model_url']=f'/api/jobs/{identity}/files/model.glb';folder=store.root/'jobs'/identity;folder.mkdir()
    shutil.copyfile(store.root/'jobs'/c['job']/'model.glb',folder/'model.glb');job['metrics']=inspect_glb(folder/'model.glb')
    store.create_job(job,'',identity);records.append({**c,'job':identity})
(out/'cases.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(records,ensure_ascii=False))
