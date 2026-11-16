# -*- coding: utf-8 -*-
import json,time
from pathlib import Path
import httpx
OUT=Path(__file__).resolve().parents[1]/'experiments/semantic_refinement_20261113';records=[]
with httpx.Client(base_url='http://127.0.0.1:8001',timeout=40)as client:
    for case in json.loads((OUT/'cases.json').read_text(encoding='utf-8')):
        root=f'/api/jobs/{case["job"]}/asset';r=client.post(root+'/semantic-scans',json={'version':'original','category':'sofa'if'sofa'in case['case']else'chair'if'chair'in case['case']else'table'});r.raise_for_status();records.append({**case,'scan_id':r.json()['scan_id'],'states':[]});print(case['case'],'started',flush=True)
    deadline=time.monotonic()+1200;pending=list(records)
    while pending and time.monotonic()<deadline:
        for record in list(pending):
            scan=client.get(f'/api/jobs/{record["job"]}/asset/semantic-scans/{record["scan_id"]}').json()
            if not record['states']or record['states'][-1]!=scan['stage']:record['states'].append(scan['stage']);print(record['case'],scan['stage'],flush=True)
            if scan['status']in('ready','failed'):record['result']=scan;pending.remove(record)
        (OUT/'api_runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        if pending:time.sleep(3)
    if pending:raise RuntimeError('Real scans did not finish before measured deadline')
