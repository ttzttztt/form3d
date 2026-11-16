"""Create a separate local review task; never overwrite the source furniture job."""
import argparse,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.models import JobRequest
from services.api.store import Store,now
from services.api.pipeline import run_job
from services.api.assembly_assets import attach_assembly_candidate
from services.api.assembly_models import AssemblyPlan


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--name',required=True);p.add_argument('--preview');args=p.parse_args()
    source=Path(args.source)
    if(source/'workbench_import.json').exists():raise ValueError('An import task already exists for this candidate')
    plan=AssemblyPlan.model_validate_json((source/'plan.json').read_text(encoding='utf-8'));store=Store(ROOT/'.data')
    request=JobRequest(image_id=plan.primary_image_id,name=args.name,route='assistant',target=plan.furniture_target,object_category=plan.object_category)
    identity=uuid.uuid4().hex;job={'id':identity,'name':args.name,'created_at':now(),'updated_at':now(),'request':request.model_dump(),
        'status':'queued','stage':'queued','events':[],'review_status':'pending','provider_task_id':None,'submission_started':False,'error':None}
    store.create_job(job,'','');(source/'workbench_import.json').write_text(json.dumps({'job':identity,'url':f'http://127.0.0.1:8001/?job={identity}','status':'creating'},indent=2),encoding='utf-8')
    run_job(store,identity);result=attach_assembly_candidate(store,identity,source,args.preview)
    (source/'workbench_import.json').write_text(json.dumps({'job':identity,'url':f'http://127.0.0.1:8001/?job={identity}','status':result['status'],'original_jobs_unchanged':True},indent=2),encoding='utf-8')
    print(identity,flush=True)
