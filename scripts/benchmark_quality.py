"""Execute and preserve real quality-comparison runs. Never invent metrics."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / 'experiments' / 'quality_20261111'


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['baseline'], default='baseline')
    parser.add_argument('--base', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    protocol = json.loads((EXPERIMENT / 'protocol.json').read_text(encoding='utf-8'))
    with httpx.Client(base_url=args.base, timeout=30) as api:
        for case in protocol['cases']:
            folder = EXPERIMENT / case['id']
            baseline = folder / 'triposr'
            baseline.mkdir(parents=True, exist_ok=True)
            existing=baseline/'execution.json'
            if existing.is_file():
                record=json.loads(existing.read_text(encoding='utf-8'))
                previous=json.loads((baseline/'job.json').read_text(encoding='utf-8'))
                if previous['request']['image_id']!=case['image_id'] or previous['request']['target']!=case['target']:
                    raise ValueError('Case inputs changed; use a new experiment directory instead of overwriting measured data')
                if (record.get('status')=='completed' and (baseline/'model.glb').is_file()
                    and hashlib.sha256((baseline/'model.glb').read_bytes()).hexdigest()==record.get('sha256',{}).get('model.glb')):
                    print(case['id']+' baseline: reusing recorded, hash-verified execution',flush=True)
                    continue
            body = {'image_id':case['image_id'], 'name':'质量对比基线 · '+case['name'],
                    'route':'local', 'local_engine':'triposr', 'local_remove_background':True, 'target':case['target']}
            identity = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
            response = api.post('/api/jobs', json=body,
                                headers={'Idempotency-Key':'quality-20261111-triposr-'+identity})
            response.raise_for_status()
            job = response.json()
            save_json(baseline / 'job.json', job)
            started = time.monotonic()
            stage = None
            while job['status'] in ('queued','running'):
                if job['stage'] != stage:
                    print(case['id']+' baseline: '+job['stage'], flush=True)
                    stage = job['stage']
                if time.monotonic() - started > 1200:
                    raise TimeoutError('Baseline task still running: '+job['id'])
                time.sleep(1)
                response = api.get('/api/jobs/'+job['id'])
                response.raise_for_status()
                job = response.json()
            save_json(baseline / 'job.json', job)
            if job['status'] != 'awaiting_review':
                raise RuntimeError('Baseline failed; real task preserved: '+str(job.get('error')))
            hashes = {}
            for name in ('model.glb','prepared.png','foreground.png','model_input.png','local_summary.json','quality_report.json'):
                response = api.get('/api/jobs/'+job['id']+'/files/'+name)
                response.raise_for_status()
                (baseline / name).write_bytes(response.content)
                hashes[name] = hashlib.sha256(response.content).hexdigest()
            # Each candidate uses exactly the baseline's actual foreground.
            shutil.copyfile(baseline / 'foreground.png', folder / 'foreground.png')
            shutil.copyfile(baseline / 'prepared.png', folder / 'reference.png')
            save_json(baseline / 'execution.json', {
                'status':'completed', 'source':'real FastAPI task and local CUDA worker',
                'job_id':job['id'], 'observed_date':'2026-11-11', 'sha256':hashes,
                'technical_validation':job['report']['gltf_validation'],
                'visual_acceptance':'not_yet_reviewed',
                'summary':job['report']['local_inference'],
            })
            print(case['id']+' baseline completed: '+job['id'], flush=True)


if __name__ == '__main__':
    main()
