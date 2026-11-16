import json,time,sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/semantic_parts_20261113';cases=json.loads((OUT/'cases.json').read_text());records=[]
with httpx.Client(base_url='http://127.0.0.1:8001',timeout=40) as client:
    for c in cases:
        if len(sys.argv)>1 and c['case'] not in sys.argv[1:]:continue
        response=client.post(f'/api/jobs/{c["job"]}/asset/semantic-scans',json={'version':'original','category':'sofa' if 'sofa' in c['case'] else 'chair' if 'chair' in c['case'] else 'table'});response.raise_for_status();value=response.json();records.append({**c,'scan_id':value['scan_id'],'states':[]});print(c['case'],value['scan_id'],flush=True)
    deadline=time.monotonic()+1100
    pending=list(records)
    while pending and time.monotonic()<deadline:
        for r in list(pending):
            value=client.get(f'/api/jobs/{r["job"]}/asset/semantic-scans/{r["scan_id"]}').json();stage=value.get('stage')
            if not r['states'] or r['states'][-1]['stage']!=stage:r['states'].append({'stage':stage,'at':time.time()});print(r['case'],stage,flush=True)
            if value.get('status') in ('ready','failed'):
                r['result']=value;pending.remove(r)
        (OUT/'scans.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        if pending:time.sleep(3)
    if pending:raise RuntimeError('Scans did not finish within measured deadline')
