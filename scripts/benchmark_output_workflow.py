# -*- coding: utf-8 -*-
"""Real bounded local retry and control runs, all artifacts preserved."""
import hashlib
import json
from pathlib import Path
import shutil
import time
import httpx
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/output_quality_20261111';OUT.mkdir(exist_ok=True)
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=60) as api:
    cases=[('flat_vase','clean_vase','vase'),('table_control','clean_table','table'),('blocked_cat','scene_sofa_cat','sofa')]
    for identity,baseline,category in cases:
        source=read(ROOT/'experiments/multicategory_20261111'/baseline/'hunyuan/job.json')
        body={**source['request'],'name':'输出质检实测 · '+identity,'object_category':category,'local_auto_retry':True}
        response=api.post('/api/jobs',json=body,headers={'Idempotency-Key':'output-qc-v1-'+identity});response.raise_for_status();job=response.json()
        folder=OUT/'real_runs'/identity;write(folder/'job.json',job);started=time.monotonic();stage=None
        while job['status'] in ['queued','running']:
            if job['stage']!=stage:print(identity+' '+job['id']+' / '+job['stage'],flush=True);stage=job['stage']
            if time.monotonic()-started>2000:raise TimeoutError('Task preserved '+job['id'])
            time.sleep(1);response=api.get('/api/jobs/'+job['id']);response.raise_for_status();job=response.json()
        write(folder/'job.json',job)
        directory=ROOT/'.data/jobs'/job['id']
        files=['model.glb','quality_report.json','local_summary.json','geometry_quality.json','attempts.json','prepared.png','cleaned.png','input_quality.json','model_input.png']
        for name in files:
            if (directory/name).is_file():shutil.copyfile(directory/name,folder/name)
        if (directory/'attempts').exists():shutil.copytree(directory/'attempts',folder/'attempts',dirs_exist_ok=True)
        attempts=job.get('output_attempts',[])
        assert len(attempts)<=2
        if job['status']=='awaiting_input':assert not job.get('model_url')
        if identity=='blocked_cat':assert not attempts,'Input blockers must not trigger shape retries'
        write(folder/'execution.json',{'status':job['status'],'job_id':job['id'],'url':'http://127.0.0.1:8000/?job='+job['id'],
                                     'attempts':attempts,'actual_engine':job.get('actual_engine'),'error':job.get('error')})
        print(identity+' FINISHED '+job['status']+' attempts='+str(len(attempts)),flush=True)
print('REAL_OUTPUT_WORKFLOW_FINISHED',flush=True)
