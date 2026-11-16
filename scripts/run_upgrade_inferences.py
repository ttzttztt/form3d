# -*- coding: utf-8 -*-
"""Actual serialized local inference, independent from acceptance and editing."""
import argparse,hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store
from services.api.geometry import validate_glb,inspect_glb
from services.api.part_regeneration import stop_child
from upgrade_record import OUT,record
store=Store(ROOT/'.data');cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'))
p=argparse.ArgumentParser();p.add_argument('--tag',default='');a=p.parse_args();results_path=OUT/('gpu_executions'+('_'+a.tag if a.tag else'')+'.json')
worker=ROOT/'scripts/generate_hunyuan3d.py';revision=hashlib.sha256(worker.read_bytes()).hexdigest()
corduroy=next(c for c in cases if c['case']=='corduroy_sofa')
reference=ROOT/'.data/jobs/604f3b8d4fb649e098a7117dd8dff0b0/part_regenerations/d28da45342a242ed9558f2f2df91da2a/reference.png'
tasks=[{'case':'corduroy_center','job':corduroy['job'],'seed':seed,'input':reference,'keep_background':True,'folder':store.root/'jobs'/corduroy['job']/'upgrade_inferences'/f'center_seed_{seed}'}for seed in(77,123)]
for case in cases:
    if case['status']!='pending_generation':continue
    image=store.image(case['image_id']);tasks.append({'case':case['case'],'job':case['job'],'seed':42,'input':store.root/image['normalized_path'],'keep_background':False,'folder':store.root/'jobs'/case['job']/'upgrade_inferences'/'whole_seed_42'})
results=[]
for task in tasks:
    checked_at=time.monotonic()
    folder=task['folder'];folder.mkdir(parents=True,exist_ok=True);source_sha=hashlib.sha256(task['input'].read_bytes()).hexdigest()
    existing=folder/'execution.json'
    if existing.exists():
        previous=json.loads(existing.read_text(encoding='utf-8'))
        if previous.get('status')=='completed'and previous.get('worker_revision')==revision and previous.get('input_sha256')==source_sha and(folder/'model.glb').is_file()and hashlib.sha256((folder/'model.glb').read_bytes()).hexdigest()==previous.get('model_sha256'):
            reused={**previous,'new_inference':False,'reused_execution':True,'original_execution_seconds':previous.get('elapsed_wall_seconds'),'elapsed_wall_seconds':time.monotonic()-checked_at}
            results.append(reused);results_path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print(task['case'],task['seed'],'verified reuse',flush=True);continue
        raise SystemExit('Preserve prior failure before creating a new attempt: '+str(folder))
    execution={'case':task['case'],'job':task['job'],'seed':task['seed'],'status':'running','worker_revision':revision,'input_sha256':source_sha,'new_inference':True,'physical_appearance_verified':False}
    existing.write_text(json.dumps(execution,indent=2),encoding='utf-8');record('real_inference_started',**execution)
    command=[str(ROOT/'.venv-hunyuan/Scripts/python.exe'),'-X','utf8',str(worker),'--input',str(task['input']),'--output',str(folder),'--steps','50','--resolution','384','--seed',str(task['seed'])]
    if task['keep_background']:command.append('--keep-background')
    started=time.monotonic()
    try:
        with(folder/'worker.log').open('wb')as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                while process.poll()is None:
                    if time.monotonic()-started>1800:raise TimeoutError('Local shape inference exceeded 30 minutes')
                    time.sleep(1)
            finally:stop_child(process)
        if process.returncode:raise ValueError('Actual local worker failed; see retained worker.log')
        report=validate_glb(folder/'model.glb');summary=json.loads((folder/'local_summary.json').read_text(encoding='utf-8'))
        execution.update(status='completed',model_sha256=summary['model_sha256'],summary=summary,validation=report)
        if task['case'].startswith('new_'):
            job_folder=store.root/'jobs'/task['job'];job=json.loads((job_folder/'planned_job.json').read_text(encoding='utf-8'))
            shutil.copyfile(folder/'model.glb',job_folder/'model.glb');job['metrics']=inspect_glb(job_folder/'model.glb');job['actual_engine']='hunyuan-mini';store.create_job(job,'',job['id'])
            for c in cases:
                if c['job']==task['job']:c.update(status='real_inference_completed',source_sha256=summary['model_sha256'],source_model=str((job_folder/'model.glb').relative_to(ROOT)))
            (OUT/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
        record('real_inference_completed',case=task['case'],seed=task['seed'],duration_seconds=summary['duration_seconds'],triangles=summary['triangles'],new_inference=True)
    except Exception as exc:
        execution.update(status='failed',error=str(exc));record('real_inference_failed',case=task['case'],seed=task['seed'],error=str(exc))
    execution['elapsed_wall_seconds']=time.monotonic()-started;existing.write_text(json.dumps(execution,ensure_ascii=False,indent=2),encoding='utf-8');results.append(execution)
    results_path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print(task['case'],task['seed'],execution['status'],round(execution['elapsed_wall_seconds'],2),flush=True)
if any(r['status']!='completed'for r in results):raise SystemExit(1)
