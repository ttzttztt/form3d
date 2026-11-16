import copy,hashlib,json,shutil,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx
from services.api.store import Store,now
from verify_asset_upgrade import signature
OUT=ROOT/'experiments/selection_refinement_20261112';store=Store(ROOT/'.data');client=httpx.Client(base_url='http://127.0.0.1:8001',timeout=240);records=[]
for c in json.loads((OUT/'cases.json').read_text(encoding='utf-8')):
    sid=c['source_job'];job=copy.deepcopy(store.job(sid));identity=uuid.uuid4().hex
    for key in ('asset_versions','current_asset_version','review'):job.pop(key,None)
    job.update(id=identity,name='UV 连续性复测 · '+c['case'],status='awaiting_review',stage='uv_refinement_test',events=[],created_at=now(),updated_at=now(),review_status='pending',test_clone_of=sid)
    for key,value in list(job.items()):
        if isinstance(value,str):job[key]=value.replace(sid,identity)
    directory=store.root/'jobs'/identity;directory.mkdir()
    for p in (store.root/'jobs'/sid).iterdir():
        if p.is_file() and (p.suffix=='.png' or p.name=='model.glb'):shutil.copyfile(p,directory/p.name)
    store.create_job(job,'',identity);root=f'/api/jobs/{identity}/asset';catalog=client.get(root).json();record={'case':c['case'],'job':identity,'source_job':sid,'steps':[],'source_sha256':hashlib.sha256((directory/'model.glb').read_bytes()).hexdigest()};records.append(record)
    def save():(OUT/'uv_runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    def edit(operation,**values):
        global catalog
        t=time.monotonic();r=client.post(root+'/versions',json={'operation':operation,'base_version':catalog['version'],**values});body=r.json();step={'operation':operation,'status':r.status_code,'seconds':round(time.monotonic()-t,3),**values};record['steps'].append(step)
        if r.status_code==201:catalog=body;step.update(version=body['version'],manifest=body['manifest'])
        else:step['error']=body
        save();return r.status_code==201
    assert edit('auto_parts',category=c['category']);base=catalog['version'];group=next((g for g in catalog['groups'] if '桌面' in g['name']),max(catalog['groups'],key=lambda g:g['triangles']));ids=group['part_ids'];record.update(part_ids=ids,selected_group=group,base_version=base);baseline=signature(directory/'model.glb')
    for mode in ['box','proxy']+(['cylinder'] if c['case']=='round_table' else []):
        if catalog['version']!=base:assert edit('restore_version',source_version=base)
        if edit('unwrap_uv',part_ids=ids,uv_unwrap_mode=mode):
            path=OUT/(c['case']+'_'+mode+'.glb');path.write_bytes(client.get(catalog['model_url']).content);assert signature(path)==baseline;record[mode+'_version']=catalog['version'];record[mode+'_world_triangles_exact']=True
    record['source_unchanged']=hashlib.sha256((directory/'model.glb').read_bytes()).hexdigest()==record['source_sha256']==hashlib.sha256((store.root/'jobs'/sid/'model.glb').read_bytes()).hexdigest();assert record['source_unchanged'];save();print(json.dumps({'case':c['case'],'results':[(s.get('uv_unwrap_mode'),s['status']) for s in record['steps'] if s['operation']=='unwrap_uv']}),flush=True)
client.close()
