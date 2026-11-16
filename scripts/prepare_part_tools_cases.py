"""Isolated copies for two tables, two chairs, two sofas and two cabinets."""
import copy,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
OUT=ROOT/'experiments/part_tools_20261112';OUT.mkdir(exist_ok=True);store=Store(ROOT/'.data');records=[]
cases=[('round_table','table','b51be48468e54d0680a542174c0c873b'),('alien_table','table','39851a7fca77468b99e438acb41f7255'),('official_chair','chair','1719f8f02b124b249c66c93a94841b6f'),('accent_chair','chair','6be16d93f7544ac79c5f09cb3be507fa'),('leather_sofa','sofa','11c5d7496508427cad48c22c5959f53b'),('corduroy_sofa','sofa','0ee3d49864e543bb92a66ad9cf19115b'),('white_cabinet','cabinet','212518024ebe4a4b9e4bd3543ee4a13c'),('authored_bookcase','cabinet','de3c04312fdd4a99993e29e29bccb388')]
for name,category,source_id in cases:
    job=copy.deepcopy(store.job(source_id));identity=uuid.uuid4().hex
    for key in ('asset_versions','current_asset_version','review'):job.pop(key,None)
    job.update(id=identity,name='新一轮部件工具验收 · '+name,status='awaiting_review',stage='part_tools_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=source_id);job['request']['object_category']=category
    for key,value in list(job.items()):
        if isinstance(value,str):job[key]=value.replace(source_id,identity)
    directory=store.root/'jobs'/identity;directory.mkdir()
    for p in (store.root/'jobs'/source_id).iterdir():
        if p.is_file() and (p.suffix=='.png' or p.name=='model.glb'):shutil.copyfile(p,directory/p.name)
    store.create_job(job,'',identity);records.append({'case':name,'category':category,'source_job':source_id,'job':identity})
(OUT/'cases.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(records))
