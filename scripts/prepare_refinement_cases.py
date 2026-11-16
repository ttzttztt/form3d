import copy,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
OUT=ROOT/'experiments/selection_refinement_20261112';OUT.mkdir(exist_ok=True);store=Store(ROOT/'.data');records=[]
for c in json.loads((ROOT/'experiments/part_tools_20261112/cases.json').read_text(encoding='utf-8')):
    sid=c['source_job'];job=copy.deepcopy(store.job(sid));identity=uuid.uuid4().hex
    for key in ('asset_versions','current_asset_version','review'):job.pop(key,None)
    job.update(id=identity,name='多点修正验收 · '+c['case'],status='awaiting_review',stage='refinement_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=sid);job['request']['local_quality']='balanced'
    for key,value in list(job.items()):
        if isinstance(value,str):job[key]=value.replace(sid,identity)
    directory=store.root/'jobs'/identity;directory.mkdir()
    for p in (store.root/'jobs'/sid).iterdir():
        if p.is_file() and (p.suffix=='.png' or p.name=='model.glb'):shutil.copyfile(p,directory/p.name)
    store.create_job(job,'',identity);records.append({**c,'job':identity})
(OUT/'cases.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(records))
