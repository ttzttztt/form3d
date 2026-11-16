import json,time
from pathlib import Path
import httpx
OUT=Path(__file__).resolve().parents[1]/'experiments/semantic_parts_20261113';case=next(c for c in json.loads((OUT/'cases.json').read_text()) if c['case']=='round_table');record={**case,'stages':[]}
with httpx.Client(base_url='http://127.0.0.1:8001',timeout=40) as client:
    r=client.post(f'/api/jobs/{case["job"]}/asset/semantic-scans',json={'version':'original','category':'table'});r.raise_for_status();scan=r.json();record['scan_id']=scan['scan_id'];deadline=time.monotonic()+700
    while time.monotonic()<deadline:
        scan=client.get(f'/api/jobs/{case["job"]}/asset/semantic-scans/{record["scan_id"]}').json()
        if not record['stages'] or record['stages'][-1]!=scan['stage']:record['stages'].append(scan['stage']);print(scan['stage'],flush=True)
        if scan['status'] in ('ready','failed'):break
        time.sleep(3)
    record['result']=scan;(OUT/'table_guard_run.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');assert scan['status']=='failed',scan;assert '未识别出多个' in scan['error'],scan;assert client.get(f'/api/jobs/{case["job"]}/asset').json()['version']=='original';print(scan['error'],flush=True)
