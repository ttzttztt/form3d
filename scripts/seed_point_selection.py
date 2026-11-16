"""Isolated existing model copies for point-selection UX, no inference."""
import copy
import json
from pathlib import Path
import shutil
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
out=ROOT/'experiments/point_selection_20261112';out.mkdir(exist_ok=True);store=Store(ROOT/'.data');cases=[]
for name,source_id in [('table','b51be48468e54d0680a542174c0c873b'),('cabinet','212518024ebe4a4b9e4bd3543ee4a13c'),('sofa','11c5d7496508427cad48c22c5959f53b')]:
    job=copy.deepcopy(store.job(source_id));identity=uuid.uuid4().hex
    for key in ('asset_versions','current_asset_version','review','reference_image_ids'):job.pop(key,None)
    job.update(id=identity,name={'table':'圆桌 · 点选区域验收','cabinet':'柜子 · 点选区域验收','sofa':'沙发 · 点选失败控制'}[name],created_at=now(),updated_at=now(),events=[],status='awaiting_review',stage='point_selection_test',review_status='pending',test_clone_of=source_id)
    for key,value in list(job.items()):
        if isinstance(value,str):job[key]=value.replace(source_id,identity)
    if job.get('report'):job['report']['review_status']='pending';job['report'].pop('review',None)
    directory=store.root/'jobs'/identity;directory.mkdir()
    for path in (store.root/'jobs'/source_id).iterdir():
        if path.is_file() and (path.suffix=='.png' or path.name in ('model.glb','quality_report.json','metadata.json')):shutil.copyfile(path,directory/path.name)
    store.create_job(job,'',identity);cases.append({'case':name,'job':identity,'source_job':source_id})
(out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(cases,ensure_ascii=False))
