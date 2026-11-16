import copy,hashlib,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
OUT=ROOT/'experiments/multifurniture_20261113';OUT.mkdir(exist_ok=True);store=Store(ROOT/'.data');records=[]
cases=[('chair','58218e68edfd42889d295436a8e1ed42','0279b4b8b6d94bb3abb40902b29cac57','椅子底架（已有坐垫）'),('round_table','b51be48468e54d0680a542174c0c873b','original','圆桌'),('bookcase','de3c04312fdd4a99993e29e29bccb388','original','书柜'),('leather_sofa','11c5d7496508427cad48c22c5959f53b','original','皮质沙发'),('corduroy_sofa','0ee3d49864e543bb92a66ad9cf19115b','original','灯芯绒沙发')]
for label,sid,version,name in cases:
    job=copy.deepcopy(store.job(sid));identity=uuid.uuid4().hex
    for k in ('asset_versions','current_asset_version','review'):job.pop(k,None)
    job.update(id=identity,name='多家具拆装验收 · '+name,status='awaiting_review',stage='multifurniture_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=sid)
    for k,v in list(job.items()):
        if isinstance(v,str):job[k]=v.replace(sid,identity)
    folder=store.root/'jobs'/identity;folder.mkdir();parent=store.root/'jobs'/sid
    for p in parent.iterdir():
        if p.is_file() and p.suffix=='.png':shutil.copyfile(p,folder/p.name)
    source=parent/'model.glb' if version=='original' else parent/'assets'/version/'model.glb';shutil.copyfile(source,folder/'model.glb');store.create_job(job,'',identity)
    records.append({'case':label,'name':name,'source_job':sid,'source_version':version,'job':identity,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
(OUT/'cases.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(records,ensure_ascii=False,indent=2))
