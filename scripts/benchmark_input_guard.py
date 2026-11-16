# -*- coding: utf-8 -*-
"""Fresh real jobs on the frozen 11 cases; preserve old failure evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'experiments/multicategory_20261111'
OUT=ROOT/'experiments/input_guard_20261111'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--case');parser.add_argument('--attempt',default='batch',choices=['batch','attempt_002']);args=parser.parse_args()
    protocol=read(BASE/'protocol.json');OUT.mkdir(exist_ok=True)
    freeze={'baseline_protocol_sha256':sha(BASE/'protocol.json'),'cases':[c['id'] for c in protocol['cases']],
            'comparison':'Same source image IDs, target boxes, category labels and Hunyuan 30/42/256. New jobs, no baseline file overwritten.',
            'checks':['verify original input hash','record actual routing and cleanup','blocked jobs cannot publish GLB or enter shape inference','controls preserve recognizable geometry'],
            'limitations':['Rules were motivated by known cases, not a held-out benchmark','No inpainting or semantic object erasure; clutter candidates cause input attention','Passing preflight does not guarantee 3D quality']}
    if not (OUT/'protocol.json').exists():write(OUT/'protocol.json',freeze)
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=60) as api:
        for case in protocol['cases']:
            if args.case and args.case!=case['id']:continue
            folder=OUT/args.attempt/case['id'];folder.mkdir(parents=True,exist_ok=True)
            baseline=read(BASE/case['id']/'hunyuan/job.json')
            assert sha(ROOT/case['path'])==case['sha256']
            body={**baseline['request'],'name':'输入清理复测 · '+case['name']}
            key='input-guard-v1-'+('' if args.attempt=='batch' else args.attempt+'-')+hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:20]
            response=api.post('/api/jobs',json=body,headers={'Idempotency-Key':key});response.raise_for_status();job=response.json()
            write(folder/'job.json',job);started=time.monotonic();previous=None
            while job['status'] in ['queued','running']:
                if job['stage']!=previous:print(case['id']+' '+job['id']+' / '+job['stage'],flush=True);previous=job['stage']
                if time.monotonic()-started>1600:raise TimeoutError('Preserved task still running '+job['id'])
                time.sleep(1);response=api.get('/api/jobs/'+job['id']);response.raise_for_status();job=response.json()
            write(folder/'job.json',job)
            hashes={}
            for name in ['prepared.png','cleaned.png','cleaned_preview.png','foreground_before_cleanup.png','cleanup_mask.png','input_overlay.png','input_quality.json',
                         'segmented.png','segmentation_mask.png','segmentation_overlay.png','segmentation_summary.json',
                         'model.glb','foreground.png','model_input.png','local_summary.json','quality_report.json']:
                response=api.get('/api/jobs/'+job['id']+'/files/'+name)
                if response.status_code==200:
                    (folder/name).write_bytes(response.content);hashes[name]=hashlib.sha256(response.content).hexdigest()
                elif response.status_code not in [404,409]:response.raise_for_status()
            directory=ROOT/'.data/jobs'/job['id']
            for name in ['input_preflight.log','local3d.log','segmentation.log','input_preflight_failure.json']:
                if (directory/name).is_file():shutil.copyfile(directory/name,folder/name)
            blocked=job['status']=='awaiting_input' and job.get('attention_kind')=='local_input'
            if blocked:
                assert not job.get('model_url')
                assert not (directory/'model.glb').exists()
                assert not (directory/'local3d.log').exists(),'3D worker must not start for blocked input'
            quality=job.get('input_quality')
            write(folder/'execution.json',{'status':job['status'],'job_id':job['id'],'url':'http://127.0.0.1:8000/?job='+job['id'],
                'input_quality':quality,'summary':job.get('report',{}).get('local_inference'),
                'technical_validation':job.get('report',{}).get('gltf_validation'),
                'gate_blocked':blocked,'blocked_before_3d_verified':blocked,
                'baseline_selection_mode':read(BASE/case['id']/'detection_record.json')['selection_mode'],
                'sha256':hashes,'error':job.get('error'),'visual_review':'not_yet_reviewed'})
            print(case['id']+' finished '+job['status']+' / '+str([r['code'] for r in (quality or {}).get('reasons',[])]),flush=True)
    print('INPUT_GUARD_BATCH_FINISHED',flush=True)

if __name__=='__main__':main()
