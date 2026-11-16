"""Real existing model edits via HTTP on isolated test copies; no reconstruction quality claim."""
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
from PIL import Image,ImageDraw
from services.api.store import Store,now

OUTPUT=ROOT/'experiments/asset_upgrade_20261112'
CASES=[('table','b51be48468e54d0680a542174c0c873b'),('plant','6eab9c5a4a9545febbfc0835fd89ee4e'),
       ('scene_sofa','11c5d7496508427cad48c22c5959f53b'),('cabinet','212518024ebe4a4b9e4bd3543ee4a13c'),
       ('vase','98b4389eb9e240cab5aa94934e089b6f'),('authored_vase','5263b3b68058479bbe614c43b6819f5a')]


def main():
    OUTPUT.mkdir(exist_ok=True);store=Store(ROOT/'.data');client=httpx.Client(base_url='http://127.0.0.1:8000',timeout=240)
    images={}
    for slot in ('base_color_image','normal_image','roughness_image'):
        path=OUTPUT/(slot+'.png');image=Image.new('RGB',(128,128),(128,128,255) if slot=='normal_image' else (200,200,200))
        if slot=='base_color_image':
            draw=ImageDraw.Draw(image)
            for y in range(0,128,16):
                for x in range(0,128,16):draw.rectangle((x,y,x+15,y+15),fill=(200,170,110) if (x+y)//16%2 else (70,90,120))
        image.save(path)
        with path.open('rb') as file:response=client.post('/api/images',files={'file':(path.name,file,'image/png')})
        response.raise_for_status();images[slot]=response.json()['id']
    results=json.loads((OUTPUT/'real_edits.json').read_text(encoding='utf-8')) if (OUTPUT/'real_edits.json').exists() else []
    for name,source_id in CASES:
        if any(r['case']==name and r.get('original_unchanged') for r in results):continue
        source=store.job(source_id);assert source and source.get('model_url')
        identity=uuid.uuid4().hex;job=copy.deepcopy(source)
        for field in ('asset_versions','current_asset_version','review'):job.pop(field,None)
        job.update(id=identity,name='编辑扩展实测 · '+name,status='awaiting_review',stage='asset_edit_test',created_at=now(),updated_at=now(),
                   review_status='pending',events=[],model_url=f'/api/jobs/{identity}/files/model.glb',test_clone_of=source_id)
        directory=store.root/'jobs'/identity;directory.mkdir()
        for path in (store.root/'jobs'/source_id).iterdir():
            if path.is_file() and (path.suffix=='.png' or path.name in ('model.glb','metadata.json','quality_report.json')):shutil.copyfile(path,directory/path.name)
        if job.get('report'):
            job['report']['review_status']='pending';job['report'].pop('review',None)
        for filename in ('metadata.json','quality_report.json'):
            path=directory/filename
            if path.exists():
                value=json.loads(path.read_text(encoding='utf-8'));value['review_status']='pending';value.pop('review',None);value['test_clone_of']=source_id
                path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        for key,value in list(job.items()):
            if isinstance(value,str) and f'/api/jobs/{source_id}/' in value:job[key]=value.replace(source_id,identity)
        store.create_job(job,'',identity)
        original=(directory/'model.glb').read_bytes();record={'case':name,'source_job':source_id,'test_job':identity,'source_sha256':hashlib.sha256(original).hexdigest(),'steps':[]}
        results.append(record)
        catalog=client.get(f'/api/jobs/{identity}/asset').json();base='original'
        def edit(operation,**values):
            nonlocal catalog,base
            start=time.monotonic();response=client.post(f'/api/jobs/{identity}/asset/versions',json={'base_version':base,'operation':operation,**values})
            body=response.json();step={'operation':operation,'status':response.status_code,'seconds':round(time.monotonic()-start,3)}
            if response.status_code==201:
                catalog=body;base=body['version'];step.update(version=base,metrics=body['metrics'],evidence=body['manifest']['operation'],validation=body['manifest']['validation'],positions_unchanged=body['manifest']['positions_unchanged'])
            else:step['error']=body
            record['steps'].append(step)
            (OUTPUT/'real_edits.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            return response.status_code==201
        edit('decimate',lod_ratio=.7,note='LOD test; not visually accepted')
        edit('restore_original')
        first=catalog['parts'][0];faces=list(range(min(first['triangles']//3,15000)))
        assert edit('face_group',face_selection=[{'part_id':first['id'],'faces':faces}],name='人工选面测试')
        ids=[p['id'] for p in catalog['parts']];chosen=catalog['parts'][1]['id']
        assert edit('rename',part_ids=[chosen],name='测试局部部件')
        assert ids==[p['id'] for p in catalog['parts']]
        assert edit('material',part_ids=[chosen],color='#ffffff',roughness=1,**images,uv_scale=2,uv_rotation=30)
        assert ids==[p['id'] for p in catalog['parts']]
        record['final_edited_version']=base
        model=client.get(catalog['model_url']).content;(OUTPUT/(name+'_edited.glb')).write_bytes(model)
        response=client.post(f'/api/jobs/{identity}/assets/{base}/annotation',json={'note':'真实模型编辑流程实测；未通过商品外观验收','archived':True});assert response.status_code==200,response.text
        comparison=client.get(f'/api/jobs/{identity}/asset/compare',params={'left':'original','right':base});comparison.raise_for_status();record['comparison']=comparison.json()['delta']
        reference=client.post(f'/api/jobs/{identity}/reference-views',json={'image_ids':[images['base_color_image']]});assert reference.status_code==200
        assert reference.json()['reference_views'][-1]['role']=='reference_only'
        assert edit('restore_original')
        assert client.get(catalog['model_url']).content==original
        record['storage']=client.post(f'/api/jobs/{identity}/asset/compact-storage').json()
        assert (directory/'model.glb').read_bytes()==original;record['original_unchanged']=True
        (OUTPUT/'real_edits.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'case':name,'job':identity,'steps':[(s['operation'],s['status']) for s in record['steps']]},ensure_ascii=False),flush=True)
    client.close()

if __name__=='__main__':main()
