# -*- coding: utf-8 -*-
"""Second recorded manual trial: lower upper cap to reduce fused pillow stumps."""
import json,sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/sofa_refinement_20261113'
with httpx.Client(base_url='http://127.0.0.1:8001',timeout=240) as client:
    for name,top in [('leather_sofa',.512),('corduroy_sofa',.55)]:
        run=json.loads((OUT/(name+'_run.json')).read_text(encoding='utf-8'));request=json.loads((OUT/(name+'_request.json')).read_text(encoding='utf-8'));request['completion_bounds'][1][1]=top
        request['name']='降低上边界试验';(OUT/(name+'_trial2_request.json')).write_text(json.dumps(request,ensure_ascii=False),encoding='utf-8')
        r=client.post(f'/api/jobs/{run["job"]}/asset/completion-preview',json=request);record={'case':name,'job':run['job'],'request_file':name+'_trial2_request.json','status':r.status_code,'preview':r.json(),'review':'pending'}
        if r.status_code==200:
            preview=record['preview'];folder=ROOT/'.data/jobs'/run['job']/'completion_previews'/preview['preview_id'];(OUT/(name+'_trial2_preview.glb')).write_bytes((folder/'model.glb').read_bytes());(OUT/(name+'_trial2_diagnostic.glb')).write_bytes((folder/'diagnostic.glb').read_bytes())
        (OUT/(name+'_trial2_run.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');print(name,r.status_code,flush=True)
