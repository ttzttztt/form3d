# -*- coding: utf-8 -*-
"""Add three structurally different references; do not pad with color variants."""
import hashlib,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image,ImageOps
from services.api.store import Store,now
from services.api.models import JobRequest
from upgrade_record import OUT,record
store=Store(ROOT/'.data');cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'));added=[]
for prefix,title,category in[('0018','Air Frame 折叠椅','chair'),('0034','Arden 藤编床','other'),('0036','Arden 升降茶几','table')]:
    name='new_'+prefix
    if any(c['case']==name for c in cases):continue
    photo=next((ROOT/'images').glob(prefix+'_*'));image_id=uuid.uuid4().hex;image_folder=store.root/'images'/image_id;image_folder.mkdir()
    image=ImageOps.exif_transpose(Image.open(photo)).convert('RGBA');image.thumbnail((2048,2048));image.save(image_folder/'normalized.png');image.convert('RGB').save(image_folder/'preview.jpg')
    store.put_image({'id':image_id,'name':photo.name,'width':image.width,'height':image.height,'normalized_path':str((image_folder/'normalized.png').relative_to(store.root))})
    identity=uuid.uuid4().hex;folder=store.root/'jobs'/identity;folder.mkdir()
    job={'id':identity,'name':'扩展家具自主复测 · '+title,'status':'awaiting_review','stage':'autonomous_upgrade_test','created_at':now(),'updated_at':now(),'events':[],'review_status':'pending','model_url':f'/api/jobs/{identity}/files/model.glb','request':JobRequest(image_id=image_id,name=title,object_category=category,route='assistant').model_dump()}
    (folder/'planned_job.json').write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
    cases.append({'case':name,'title':title,'job':identity,'image_id':image_id,'category':category,'source_job':None,'origin':'new_real_local_inference','source_model':None,'source_photo':str(photo.relative_to(ROOT)),'status':'pending_generation','appearance_verified':False,'normalized_photo_sha256':hashlib.sha256((image_folder/'normalized.png').read_bytes()).hexdigest()});added.append(name)
for case in cases:
    if case['case']=='new_0017':case['title']='Aero 铝合金座椅'
assert len({c['normalized_photo_sha256']for c in cases})==len(cases)
(OUT/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
record('test_registry_extended',total_product_references=len(cases),added=added,reason='The yellow fleece and molded sculptural chairs share a design family; add folding chair, bed and lift-top coffee table rather than count color/material variants as independent families')
print(json.dumps({'total':len(cases),'added':added},ensure_ascii=False))
