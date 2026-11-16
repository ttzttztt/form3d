"""Eight actual furniture assets, isolated copies, real edit APIs and diagnostics."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from services.api.store import Store,now
OUT=ROOT/'experiments/furniture_workbench_20261112'
CASES=[('round_table','table','b51be48468e54d0680a542174c0c873b'),('alien_table','table','39851a7fca77468b99e438acb41f7255'),('leather_sofa','sofa','11c5d7496508427cad48c22c5959f53b'),('corduroy_sofa','sofa','0ee3d49864e543bb92a66ad9cf19115b'),('white_cabinet','cabinet','212518024ebe4a4b9e4bd3543ee4a13c'),('scene_cabinet','cabinet','eb158dfb587c4239b2cc5ff8cca73645'),('official_chair','chair','1719f8f02b124b249c66c93a94841b6f'),('authored_bookcase','cabinet','de3c04312fdd4a99993e29e29bccb388')]

def main():
    OUT.mkdir(exist_ok=True);store=Store(ROOT/'.data');client=httpx.Client(base_url='http://127.0.0.1:8000',timeout=240);records=[]
    for name,category,source_id in CASES:
        source=store.job(source_id);assert source and source.get('model_url'),source_id
        job=copy.deepcopy(source);identity=uuid.uuid4().hex
        for key in ('asset_versions','current_asset_version','review','reference_image_ids'):job.pop(key,None)
        job.update(id=identity,name='家具完整编辑验收 · '+name,status='awaiting_review',stage='furniture_edit_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=source_id)
        for key,value in list(job.items()):
            if isinstance(value,str):job[key]=value.replace(source_id,identity)
        job['request']['object_category']=category
        if job.get('report'):job['report']['review_status']='pending';job['report'].pop('review',None)
        directory=store.root/'jobs'/identity;directory.mkdir()
        for path in (store.root/'jobs'/source_id).iterdir():
            if path.is_file() and (path.suffix=='.png' or path.name in ('model.glb','metadata.json','quality_report.json')):shutil.copyfile(path,directory/path.name)
        for filename in ('metadata.json','quality_report.json'):
            path=directory/filename
            if path.exists():
                value=json.loads(path.read_text(encoding='utf-8'));value.update(job_id=identity,test_clone_of=source_id,review_status='pending');value.pop('review',None);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        store.create_job(job,'',identity);original=(directory/'model.glb').read_bytes();record={'case':name,'category':category,'source_job':source_id,'test_job':identity,'source_sha256':hashlib.sha256(original).hexdigest(),'steps':[]};records.append(record)
        catalog=client.get(f'/api/jobs/{identity}/asset').json()
        def save(): (OUT/'real_runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        def edit(operation,**values):
            nonlocal catalog
            started=time.monotonic();response=client.post(f'/api/jobs/{identity}/asset/versions',json={'base_version':catalog['version'],'operation':operation,**values});body=response.json();step={'operation':operation,'status':response.status_code,'seconds':round(time.monotonic()-started,3)}
            if response.status_code==201:
                catalog=body;step.update(version=body['version'],metrics=body['metrics'],groups=body['groups'],manifest=body['manifest'])
            else:step['error']=body
            record['steps'].append(step);save();return response.status_code==201
        before=client.get(f'/api/jobs/{identity}/asset/quality');before.raise_for_status();record['quality_before']=before.json();save()
        assert edit('auto_parts',category=category)
        record['auto_version']=catalog['version'];(OUT/(name+'_auto.glb')).write_bytes(client.get(catalog['model_url']).content)
        after=client.get(f'/api/jobs/{identity}/asset/quality');after.raise_for_status();record['quality_after_grouping']=after.json();assert record['quality_before']['whole_model']==record['quality_after_grouping']['whole_model']
        if name=='round_table':
            base=next(g for g in catalog['groups'] if '底座' in g['name']);edit('auto_parts',category='table',part_ids=base['part_ids'],detail_level='fine')
            record['fine_version']=catalog['version'];(OUT/(name+'_fine.glb')).write_bytes(client.get(catalog['model_url']).content)
        # Logical merge of two complete groups, retaining separate materials and transforms.
        groups=catalog['groups'];assert len(groups)>=2
        assert edit('merge_parts',part_ids=groups[0]['part_ids']+groups[1]['part_ids'],name='验收合并部件')
        merged=next(g for g in catalog['groups'] if g['name']=='验收合并部件');first=merged['part_ids'][0]
        sourcepart=next(p for p in catalog['parts'] if p['id']==first)
        assert edit('assign_faces',face_selection=[{'part_id':first,'faces':list(range(min(16,sourcepart['triangles']//2)))}],name='手工拆出区域')
        target=next(g for g in catalog['groups'] if g['name']=='验收合并部件');extracted=next(g for g in catalog['groups'] if g['name']=='手工拆出区域');raw=extracted['part_ids'][0];count=next(p['triangles'] for p in catalog['parts'] if p['id']==raw)
        assert edit('assign_faces',target_part_id=target['part_ids'][0],face_selection=[{'part_id':raw,'faces':list(range(count))}])
        record['edited_version']=catalog['version'];(OUT/(name+'_edited.glb')).write_bytes(client.get(catalog['model_url']).content)
        # Repair source geometry, not artificially separated patch boundaries.
        assert edit('restore_original')
        repaired=edit('repair_geometry',repair_strength='gentle')
        if repaired:
            record['repair_version']=catalog['version'];(OUT/(name+'_repaired.glb')).write_bytes(client.get(catalog['model_url']).content)
            response=client.get(f'/api/jobs/{identity}/asset/quality');response.raise_for_status();record['quality_after_repair']=response.json()
        assert (directory/'model.glb').read_bytes()==original
        assert hashlib.sha256((store.root/'jobs'/source_id/'model.glb').read_bytes()).hexdigest()==record['source_sha256']
        record['original_unchanged']=True;save();print(json.dumps({'case':name,'job':identity,'steps':[(s['operation'],s['status']) for s in record['steps']]},ensure_ascii=False),flush=True)
    client.close()

if __name__=='__main__':main()
