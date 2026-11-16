"""Revalidate repair on separate existing test clones after topology review finding."""
import hashlib
import json
from pathlib import Path
import shutil
import time
import httpx
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/furniture_workbench_20261112';client=httpx.Client(base_url='http://127.0.0.1:8000',timeout=240)
records=json.loads((OUT/'real_runs.json').read_text(encoding='utf-8'));old={c['case']:c for c in json.loads((OUT/'real_runs_before_rim_fix.json').read_text(encoding='utf-8'))}
shutil.copyfile(OUT/'real_runs.json',OUT/'real_runs_before_topology_fix.json')
for case in records:
    job=old[case['case']]['test_job'];root=f'/api/jobs/{job}/asset';current=client.get(root).json();response=client.post(root+'/versions',json={'operation':'restore_original','base_version':current['version']});response.raise_for_status();current=response.json()
    started=time.monotonic();response=client.post(root+'/versions',json={'operation':'repair_geometry','base_version':current['version'],'repair_strength':'gentle'});step={'operation':'repair_geometry','status':response.status_code,'seconds':round(time.monotonic()-started,3)};case['repair_test_job']=job
    if response.status_code==201:
        body=response.json();step.update(version=body['version'],metrics=body['metrics'],groups=body['groups'],manifest=body['manifest']);case['repair_version']=body['version'];path=OUT/(case['case']+'_repaired.glb')
        if path.exists():shutil.copyfile(path,path.with_name(case['case']+'_repaired_before_topology_fix.glb'))
        path.write_bytes(client.get(body['model_url']).content);quality=client.get(root+'/quality');quality.raise_for_status();case['quality_after_repair']=quality.json();before=case['quality_before']['whole_model'];after=quality.json()['whole_model']
        assert after['boundary_edges']<=before['boundary_edges'];assert after['nonmanifold_edges']<=before['nonmanifold_edges'];assert not before['watertight'] or after['watertight'];assert after['degenerate_faces']<=before['degenerate_faces']
        assert all(p['max_displacement_ratio']<=.00200001 for p in step['manifest']['operation']['parts'])
    else:
        assert response.status_code==409;step['error']=response.json();case.pop('repair_version',None);case.pop('quality_after_repair',None)
    case['steps']=[s if s['operation']!='repair_geometry' else step for s in case['steps']]
    assert hashlib.sha256((ROOT/'.data/jobs'/case['source_job']/'model.glb').read_bytes()).hexdigest()==case['source_sha256']
    (OUT/'real_runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'case':case['case'],'status':step['status'],'topology_safe':response.status_code==201},ensure_ascii=True),flush=True)
client.close()
