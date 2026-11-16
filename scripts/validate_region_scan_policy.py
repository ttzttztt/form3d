# -*- coding: utf-8 -*-
import json
from pathlib import Path
import httpx
OUT=Path(__file__).resolve().parents[1]/'experiments/semantic_refinement_20261113';records=json.loads((OUT/'api_runs.json').read_text(encoding='utf-8'))
with httpx.Client(base_url='http://127.0.0.1:8001',timeout=40)as client:
    for record in records:
        root=f'/api/jobs/{record["job"]}/asset';scan=client.get(root+'/semantic-scans/'+record['scan_id']).json();record['validated_result']=scan
        if record['case']=='round_table':
            assert scan['status']=='failed'and'未可靠区分'in scan['error'];assert client.get(root).json()['version']=='original';r=client.post(root+'/versions',json={'operation':'semantic_parts','base_version':'original','semantic_scan_id':record['scan_id']});assert r.status_code==409;assert client.get(root+'/semantic-scans/'+record['scan_id']+'/style.glb').status_code==404;record['invalid_adoption_refused']=True;record['invalid_preview_hidden']=True
        else:assert scan['status']=='ready'
    (OUT/'api_runs_validated.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print([(r['case'],r['validated_result']['status'])for r in records])
