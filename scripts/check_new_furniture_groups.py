"""Check full-surface proposal editing on the new real inference outputs, isolated copies."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx
from services.api.store import Store,now
from services.api.glb_document import read_glb,write_glb,parts_catalog,material_edit
from services.api.models import AssetEditRequest
from verify_asset_upgrade import signature
OUT=ROOT/'experiments/furniture_workbench_20261112';store=Store(ROOT/'.data');client=httpx.Client(base_url='http://127.0.0.1:8000',timeout=240);cases=json.loads((OUT/'new_generation_runs.json').read_text(encoding='utf-8'))+[json.loads((OUT/'engine_comparison.json').read_text(encoding='utf-8'))];records=[]
for case in cases:
    source_id=case['job'];source=store.job(source_id);identity=uuid.uuid4().hex;job=copy.deepcopy(source)
    for key in ('asset_versions','current_asset_version','review'):job.pop(key,None)
    job.update(id=identity,name='新增家具编辑验收 · '+case['case'],status='awaiting_review',stage='new_furniture_edit_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=source_id)
    for key,value in list(job.items()):
        if isinstance(value,str):job[key]=value.replace(source_id,identity)
    directory=store.root/'jobs'/identity;directory.mkdir()
    for path in (store.root/'jobs'/source_id).iterdir():
        if path.is_file() and (path.suffix=='.png' or path.name=='model.glb'):shutil.copyfile(path,directory/path.name)
    store.create_job(job,'',identity);record={'case':case['case'],'source_job':source_id,'test_job':identity};root=f'/api/jobs/{identity}/asset';current=client.get(root).json();response=client.post(root+'/versions',json={'operation':'auto_parts','base_version':current['version'],'category':job['request']['object_category']});record['status']=response.status_code;body=response.json()
    if response.status_code==201:
        record.update(version=body['version'],groups=body['groups'],metrics=body['metrics']);path=OUT/(case['case']+'_auto.glb');path.write_bytes(client.get(body['model_url']).content);record['geometry_signature']=signature(path);assert record['geometry_signature']==signature(directory/'model.glb');record['exact_triangles_preserved']=True
        doc,binary,extra=read_glb(path)
        for i,g in enumerate(body['groups']):material_edit(doc,AssetEditRequest(operation='material',part_ids=g['part_ids'],color=['#31b5dc','#f3a33a','#b46be2','#69c776','#ec657c'][i%5],roughness=.8,metalness=0).model_dump())
        write_glb(OUT/(case['case']+'_auto_diagnostic.glb'),doc,binary,extra)
    else:
        assert response.status_code==409;record['error']=body
    record['source_unchanged']=hashlib.sha256((store.root/'jobs'/source_id/'model.glb').read_bytes()).hexdigest()==hashlib.sha256((directory/'model.glb').read_bytes()).hexdigest();assert record['source_unchanged'];records.append(record);(OUT/'new_generation_group_checks.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'case':case['case'],'status':record['status'],'groups':len(record.get('groups',[]))}),flush=True)
