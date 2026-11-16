"""Actual higher-resolution inference checks; no automatic appearance acceptance."""
import json,time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/selection_refinement_20261112';client=httpx.Client(base_url='http://127.0.0.1:8001',timeout=240);records=[]
cases=[('chair_triposr_structure','6be16d93f7544ac79c5f09cb3be507fa','triposr'),('chair_hunyuan_structure','6be16d93f7544ac79c5f09cb3be507fa','hunyuan-mini'),('cabinet_hunyuan_structure','212518024ebe4a4b9e4bd3543ee4a13c','hunyuan-mini')]
for name,source,engine in cases:
    r=client.post(f'/api/jobs/{source}/reconstruction-comparison',json={'engine':engine,'quality':'structure'});r.raise_for_status();job=r.json();records.append({'case':name,'source_job':source,'job':job['id'],'requested_engine':engine,'quality':'structure'})
(OUT/'structure_runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');last={};deadline=time.monotonic()+2400
while time.monotonic()<deadline:
    done=True
    for record in records:
        r=client.get('/api/jobs/'+record['job']);r.raise_for_status();job=r.json();record['snapshot']=job;state=(job['status'],job['stage'])
        if state!=last.get(job['id']):print(json.dumps({'case':record['case'],'job':job['id'],'status':state,'error':job.get('error')},ensure_ascii=True),flush=True);last[job['id']]=state
        if job['status'] in ('queued','running'):done=False
    (OUT/'structure_runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    if done:break
    time.sleep(4)
else:raise RuntimeError('Generation monitor deadline reached; actual last states retained')
client.close()
