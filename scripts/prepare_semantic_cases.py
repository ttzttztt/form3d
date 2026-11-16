import copy,hashlib,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
out=ROOT/'experiments/semantic_parts_20261113';out.mkdir(exist_ok=True);store=Store(ROOT/'.data');records=[]
if (out/'cases.json').exists():raise SystemExit('Existing cases kept; do not recreate')
for name,sid in [('leather_sofa','11c5d7496508427cad48c22c5959f53b'),('corduroy_sofa','0ee3d49864e543bb92a66ad9cf19115b'),('accent_chair','6be16d93f7544ac79c5f09cb3be507fa'),('round_table','b51be48468e54d0680a542174c0c873b')]:
    job=copy.deepcopy(store.job(sid));identity=uuid.uuid4().hex
    for key in ('asset_versions','current_asset_version','review'):job.pop(key,None)
    job.update(id=identity,name='AI semantic parts · '+name,status='awaiting_review',stage='semantic_parts_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=sid)
    for key,value in list(job.items()):
        if isinstance(value,str):job[key]=value.replace(sid,identity)
    folder=store.root/'jobs'/identity;folder.mkdir();source=store.root/'jobs'/sid/'model.glb';shutil.copyfile(source,folder/'model.glb');store.create_job(job,'',identity)
    records.append({'case':name,'job':identity,'source_job':sid,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
(out/'cases.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print(json.dumps(records))
