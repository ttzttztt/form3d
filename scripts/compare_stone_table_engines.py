"""Same photo, second local engine; no automatic appearance acceptance."""
import json
from pathlib import Path
import time
import uuid
import httpx
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/furniture_workbench_20261112';client=httpx.Client(base_url='http://127.0.0.1:8000',timeout=240)
first=next(r for r in json.loads((OUT/'new_generation_runs.json').read_text(encoding='utf-8')) if r['case']=='stone_table')
response=client.post('/api/jobs',json={'image_id':first['image_id'],'name':'同图引擎对照 · 石材茶几 Hunyuan-mini','route':'local','object_category':'table','local_engine':'hunyuan-mini','local_auto_retry':False,'local_segmentation':'auto'},headers={'Idempotency-Key':'stone-table-engine-comparison-'+uuid.uuid4().hex});response.raise_for_status();job=response.json();record={'case':'stone_table_hunyuan','filename':first['filename'],'image_id':first['image_id'],'job':job['id'],'requested_engine':'hunyuan-mini','auto_retry':False,'comparison_job':first['job']};last=None
deadline=time.monotonic()+1200
while time.monotonic()<deadline:
    response=client.get('/api/jobs/'+record['job']);response.raise_for_status();job=response.json();record['snapshot']=job;(OUT/'engine_comparison.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    state=(job['status'],job['stage'])
    if state!=last:print(json.dumps({'job':record['job'],'status':state,'error':job.get('error')},ensure_ascii=True),flush=True);last=state
    if job['status'] not in {'queued','running'}:break
    time.sleep(4)
client.close()
