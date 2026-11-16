"""Run actual candidates serially; preserve failed attempts and execution logs."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
EXPERIMENT=ROOT/'experiments'/'quality_20261111'


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',choices=['all','alien','chair','armchair'],default='all')
    parser.add_argument('--steps',type=int,choices=[20,30,50],default=30)
    parser.add_argument('--resolution',type=int,choices=[256,384],default=256)
    args=parser.parse_args()
    protocol=json.loads((EXPERIMENT/'protocol.json').read_text(encoding='utf-8'))
    worker=ROOT/'scripts'/'generate_hunyuan3d.py'
    revision=hashlib.sha256(worker.read_bytes()).hexdigest()
    results=[]
    for case in protocol['cases']:
        if args.case!='all' and case['id']!=args.case:
            continue
        case_root=EXPERIMENT/case['id']
        source=case_root/'foreground.png'
        candidate=case_root/'hunyuan'
        candidate.mkdir(parents=True,exist_ok=True)
        source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
        found=None
        for previous in sorted(candidate.glob('attempt_*/execution.json')):
            item=json.loads(previous.read_text(encoding='utf-8'))
            if (item.get('status')=='completed' and item.get('worker_revision')==revision
                and item.get('input_sha256')==source_hash and item.get('resolution')==args.resolution
                and item.get('steps')==args.steps and (previous.parent/'model.glb').is_file()
                and hashlib.sha256((previous.parent/'model.glb').read_bytes()).hexdigest()==item.get('summary',{}).get('model_sha256')):
                found=previous.parent
        if found:
            print(case['id']+': reusing verified execution '+found.name,flush=True)
            results.append({'case':case['id'],'directory':str(found.relative_to(ROOT)),'status':'completed'})
            continue
        number=len(list(candidate.glob('attempt_*')))+1
        directory=candidate/('attempt_%03d'%number)
        directory.mkdir()
        command=[str(ROOT/'.venv-hunyuan'/'Scripts'/'python.exe'),'-u',str(worker),
                 '--input',str(source),'--output',str(directory),'--keep-background',
                 '--steps',str(args.steps),'--resolution',str(args.resolution),'--seed','42']
        execution={'status':'running','case':case['id'],'worker_revision':revision,
                   'input_sha256':source_hash,'steps':args.steps,'resolution':args.resolution,
                   'seed':42,'command':command,'started_at':datetime.now(timezone(timedelta(hours=8))).isoformat()}
        save(directory/'execution.json',execution)
        started=time.monotonic()
        with (directory/'worker.log').open('wb') as log:
            process=subprocess.Popen(command,cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            sequence=None
            try:
                while process.poll() is None:
                    try:
                        progress=json.loads((directory/'local_progress.json').read_text(encoding='utf-8'))
                        if progress['sequence']!=sequence:
                            print(case['id']+' '+directory.name+': '+progress['message'],flush=True)
                            sequence=progress['sequence']
                    except (OSError,ValueError,KeyError):
                        pass
                    if time.monotonic()-started>1200:
                        raise TimeoutError('Candidate exceeded 20 minutes')
                    time.sleep(1)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
        execution.update(returncode=process.returncode,elapsed_wall_seconds=round(time.monotonic()-started,3))
        if process.returncode:
            execution.update(status='failed',visual_acceptance='not_evaluated',technical_acceptance=False)
            save(directory/'execution.json',execution)
            print(case['id']+': FAILED; log and failure record preserved at '+str(directory),flush=True)
            results.append({'case':case['id'],'directory':str(directory.relative_to(ROOT)),'status':'failed'})
            continue
        validation=subprocess.run(['node',str(ROOT/'scripts'/'check_asset.cjs'),str(directory/'model.glb')],
                                  capture_output=True,check=True,text=True,timeout=60)
        report=json.loads(validation.stdout)
        save(directory/'gltf_validation.json',report)
        summary=json.loads((directory/'local_summary.json').read_text(encoding='utf-8'))
        execution.update(status='completed' if report['status']=='pass' else 'validation_failed',technical_acceptance=report['status']=='pass',
                         visual_acceptance='not_yet_reviewed',summary=summary,validation=report)
        save(directory/'execution.json',execution)
        if execution['technical_acceptance']:
            save(ROOT/'.models'/'hunyuan3d-2mini'/'runtime.json',{
                'available':True,'inference_tested':True,'python':command[0],
                'device':summary['device'],'model':'Hunyuan3D-2mini','mode':'geometry_only',
                'validated_execution':str(directory.relative_to(ROOT)),
                'validation':report,'worker_revision':revision,'appearance_accepted':False})
        results.append({'case':case['id'],'directory':str(directory.relative_to(ROOT)),'status':execution['status']})
        print(case['id']+': completed in '+str(summary['duration_seconds'])+' seconds; visual review still required',flush=True)
    save(EXPERIMENT/('candidate_runs_'+args.case+'.json'),results)
    if any(item['status']!='completed' for item in results):
        raise SystemExit(1)


if __name__=='__main__':
    main()
