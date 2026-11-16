# -*- coding: utf-8 -*-
"""Immutable checked-result clone for repeatable browser flow, no inference."""
import argparse,copy,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.store import Store,now
from upgrade_record import OUT,record
p=argparse.ArgumentParser();p.add_argument('--tag',required=True);a=p.parse_args()
target=OUT/f'ui_clone_{a.tag}.json'
if target.exists():raise SystemExit('Preserve existing browser attempt; choose a new tag')
store=Store(ROOT/'.data');run=json.loads((OUT/'part_corduroy_sofa_v3.json').read_text(encoding='utf-8'));old=store.job(run['job']);job=copy.deepcopy(old);identity=uuid.uuid4().hex
for key in('asset_versions','current_asset_version','review','quality_report'):job.pop(key,None)
job.update(id=identity,name='优化浏览器复测 '+a.tag,test_clone_of=old['id'],created_at=now(),updated_at=now(),events=[],review_status='pending',model_url=f'/api/jobs/{identity}/files/model.glb')
folder=store.root/'jobs'/identity;folder.mkdir();shutil.copyfile(store.root/'jobs'/old['id']/'model.glb',folder/'model.glb')
shutil.copytree(store.root/'jobs'/old['id']/'part_regenerations'/run['task'],folder/'part_regenerations'/run['task']);store.create_job(job,'',identity)
target.write_text(json.dumps({**run,'job':identity,'source_model':str((folder/'model.glb').relative_to(ROOT))},ensure_ascii=False,indent=2),encoding='utf-8');record('ui_checked_result_clone_prepared',job=identity,source_task=run['task'],new_inference=False,tag=a.tag);print(identity)
