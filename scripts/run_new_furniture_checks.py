"""Two additional user-image local reconstructions; record actual outcomes, no auto acceptance."""
import json
from pathlib import Path
import time
import uuid
import httpx
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/furniture_workbench_20261112';client=httpx.Client(base_url='http://127.0.0.1:8000',timeout=240)
cases=[('accent_chair','0012_Accent Chair.png','chair','hunyuan-mini'),('stone_table','0043_Aristea Travertine Geometric Coffee Table.jpg','table','triposr')];records=[]
for name,filename,category,engine in cases:
    with (ROOT/'images'/filename).open('rb') as file:r=client.post('/api/images',files={'file':(filename,file)})
    r.raise_for_status();image=r.json();r=client.post('/api/jobs',json={'image_id':image['id'],'name':'新增家具生成实测 · '+name,'route':'local','object_category':category,'local_engine':engine,'local_auto_retry':True,'local_segmentation':'auto'},headers={'Idempotency-Key':'furniture-quality-'+name+'-'+uuid.uuid4().hex});r.raise_for_status();job=r.json();records.append({'case':name,'filename':filename,'image_id':image['id'],'job':job['id'],'requested_engine':engine,'submitted_at':time.time()})
(OUT/'new_generation_runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
deadline=time.monotonic()+1800;last={}
while time.monotonic()<deadline:
    done=True
    for record in records:
        job=client.get('/api/jobs/'+record['job']).json();record['snapshot']=job
        state=(job['status'],job['stage'])
        if state!=last.get(job['id']):print(json.dumps({'case':record['case'],'job':job['id'],'status':job['status'],'stage':job['stage'],'error':job.get('error')},ensure_ascii=False),flush=True);last[job['id']]=state
        if job['status'] in {'queued','running'}:done=False
    (OUT/'new_generation_runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    if done:break
    time.sleep(4)
else:print('MONITOR_DEADLINE_REACHED; last actual states retained',flush=True)
client.close()
