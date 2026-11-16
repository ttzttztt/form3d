"""Create isolated real-model copies for editing UX acceptance. No 3D inference."""
import copy
import json
from pathlib import Path
import shutil
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
OUT=ROOT/'experiments/selection_ux_20261112';OUT.mkdir(exist_ok=True)
store=Store(ROOT/'.data');cases=[]
for name,source_id in [('table','b51be48468e54d0680a542174c0c873b'),('plant','6eab9c5a4a9545febbfc0835fd89ee4e'),('cabinet','212518024ebe4a4b9e4bd3543ee4a13c')]:
    source=store.job(source_id);job=copy.deepcopy(source);identity=uuid.uuid4().hex
    for key in ('asset_versions','current_asset_version','review','reference_image_ids'):job.pop(key,None)
    job.update(id=identity,name={'table':'圆桌 · 表面选择验收','plant':'盆栽 · 编辑界面验收','cabinet':'柜子 · 编辑界面验收'}[name],created_at=now(),updated_at=now(),events=[],status='awaiting_review',stage='ux_test',review_status='pending',test_clone_of=source_id)
    for key,value in list(job.items()):
        if isinstance(value,str):job[key]=value.replace(source_id,identity)
    if job.get('report'):job['report']['review_status']='pending';job['report'].pop('review',None)
    directory=store.root/'jobs'/identity;directory.mkdir()
    for path in (store.root/'jobs'/source_id).iterdir():
        if path.is_file() and (path.suffix=='.png' or path.name in ('model.glb','quality_report.json','metadata.json')):shutil.copyfile(path,directory/path.name)
    store.create_job(job,'',identity);cases.append({'case':name,'job':identity,'source_job':source_id})
(OUT/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(cases,ensure_ascii=False))
