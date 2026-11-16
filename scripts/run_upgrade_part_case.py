# -*- coding: utf-8 -*-
"""Real API optimization run; records outcomes and never adopts a candidate."""
import argparse,json,time,urllib.request
from pathlib import Path
from upgrade_record import OUT,record
p=argparse.ArgumentParser();p.add_argument('--case',required=True);p.add_argument('--part',required=True);p.add_argument('--tag',default='v1');p.add_argument('--views-file');a=p.parse_args()
case=next(c for c in json.loads((OUT/'cases.json').read_text(encoding='utf-8'))if c['case']==a.case)
base='http://127.0.0.1:8001';root=f'/api/jobs/{case["job"]}/asset'
def call(url,data=None):
    request=urllib.request.Request(base+url,data=json.dumps(data).encode()if data is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=60)as response:return json.load(response)
catalog=call(root);group=next(g for g in catalog['groups']if g['name']==a.part)
payload={'version':catalog['version'],'part_ids':group['part_ids'],'candidate_count':3,'target_faces':100000}
if a.views_file:payload['reference_views']=json.loads(Path(a.views_file).read_text(encoding='utf-8'))
task=call(root+'/part-optimizations',payload);identity=task['id'];before=catalog['version'];started=time.monotonic();last=None
output=OUT/f'part_{a.case}_{a.tag}.json'
result={'case':a.case,'job':case['job'],'task':identity,'version_before':before,'request':payload,'appearance_accepted':False}
(OUT/f'part_{a.case}_{a.tag}_live.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');record('real_part_optimization_started',case=a.case,task=identity,part=a.part)
try:
    while time.monotonic()-started<2400:
        state=call(root+'/part-regenerations/'+identity);marker=(state['stage'],state.get('candidate_index'),state.get('sampling_step'))
        if marker!=last:print(marker,flush=True);last=marker
        if state['status']not in('queued','running'):break
        time.sleep(1.5)
    else:
        call(root+'/part-regenerations/'+identity+'/cancel',{});raise TimeoutError('Task polling exceeded 40 minutes; cancellation requested')
    result['terminal_state']=state;result['current_version_unchanged']=call(root)['version']==before
    assert result['current_version_unchanged']
    record('real_part_optimization_finished',case=a.case,task=identity,status=state['status'],selected_seed=state.get('selected_seed'),candidate_statuses=[{'seed':r['seed'],'status':r['status'],'eligible':r['eligible']}for r in state.get('candidate_results',[])])
except Exception as exc:result['failure']=str(exc);raise
finally:
    result['elapsed_seconds']=time.monotonic()-started;output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'case':a.case,'status':state['status'],'task':identity,'error':state.get('error')},ensure_ascii=False))
