# -*- coding: utf-8 -*-
"""25 distinct furniture references; identity is not a seed, primitive or clone."""
import copy,hashlib,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image,ImageOps
from services.api.store import Store,now
from services.api.geometry import inspect_glb
from services.api.models import JobRequest
from services.api.glb_document import read_glb,parts_catalog
from upgrade_record import OUT,record
store=Store(ROOT/'.data');OUT.mkdir(exist_ok=True)

def image_for(path):
    identity=uuid.uuid4().hex;folder=store.root/'images'/identity;folder.mkdir()
    image=ImageOps.exif_transpose(Image.open(path)).convert('RGBA');image.thumbnail((2048,2048));image.save(folder/'normalized.png')
    image.convert('RGB').save(folder/'preview.jpg')
    store.put_image({'id':identity,'name':Path(path).name,'width':image.width,'height':image.height,'normalized_path':str((folder/'normalized.png').relative_to(store.root)),'preview_url':f'/api/images/{identity}/preview'})
    return identity

def create_case(name,source,photo,title,category='other',source_job=None,origin='existing_reference_model',pending=False):
    identity=uuid.uuid4().hex
    if source_job:
        job=copy.deepcopy(store.job(source_job));image_id=job['request']['image_id']
        for key in('asset_versions','current_asset_version','quality_report','review'):job.pop(key,None)
    else:
        image_id=image_for(photo);job={'request':JobRequest(image_id=image_id,name=title,object_category=category,route='assistant').model_dump()}
    job.update(id=identity,name='25家具自主优化复测 · '+title,status='awaiting_review',stage='autonomous_upgrade_test',created_at=now(),updated_at=now(),events=[],review_status='pending',model_url=f'/api/jobs/{identity}/files/model.glb')
    if source_job:job['test_clone_of']=source_job
    folder=store.root/'jobs'/identity;folder.mkdir()
    row={'case':name,'title':title,'job':identity,'image_id':image_id,'category':category,'source_job':source_job,'origin':origin,'source_model':str(source.relative_to(ROOT))if source else None,'source_photo':str(photo.relative_to(ROOT))if photo and photo.is_relative_to(ROOT)else str(photo)if photo else None,'status':'pending_generation'if pending else'existing_model','appearance_verified':False}
    if not pending:
        shutil.copyfile(source,folder/'model.glb');job['metrics']=inspect_glb(folder/'model.glb');store.create_job(job,'',identity)
        row['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    else:(folder/'planned_job.json').write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
    image=store.image(image_id);row['normalized_photo_sha256']=hashlib.sha256((store.root/image['normalized_path']).read_bytes()).hexdigest()
    return row

if(OUT/'cases.json').exists():raise SystemExit('Existing case registry preserved')
records=[]
for name,sid,path,title,cat in[
 ('corduroy_sofa','0ee3d49864e543bb92a66ad9cf19115b','experiments/semantic_refinement_20261113/delivery/corduroy_sofa/model.glb','灯芯绒双人沙发','sofa'),
 ('leather_sofa','11c5d7496508427cad48c22c5959f53b','experiments/solid_parts_20261113/delivery/leather_sofa/model.glb','室内皮革沙发','sofa'),
 ('accent_chair','6be16d93f7544ac79c5f09cb3be507fa','experiments/semantic_refinement_20261113/delivery/accent_chair/model.glb','蓝色软包扶手椅','chair'),
 ('round_table','b51be48468e54d0680a542174c0c873b',None,'圆形茶几','table'),
 ('bookcase','de3c04312fdd4a99993e29e29bccb388',None,'五层红木书柜','cabinet'),
 ('alien_table','6b42f4e4a12f4954837b22cad0b660e0',None,'三眼外星人床头桌','table')]:
    source=ROOT/path if path else store.root/'jobs'/sid/'model.glb'
    records.append(create_case(name,source,None,title,cat,sid,'existing_ai_shape'if cat=='sofa'or name in('accent_chair','round_table')else'existing_reference_procedural_model'))
catalog=json.loads((ROOT/'library/catalog.json').read_text(encoding='utf-8'))
models=next(g['models']for g in catalog if g['id']=='catalog24')
references={r['number']:Path(r['source'])for r in json.loads((ROOT/'assets/catalog23_20261110/references.json').read_text(encoding='utf-8'))}
selected=[1,2,5,6,7,8,9,11,12,14,15,16,17,20,22,23]
for number in selected:
    model=next(m for m in models if m['asset_id'].startswith(f'catalog24__{number:02d}')and'22b_'not in m['asset_id'])
    key=model['asset_id'];category='chair'if any(s in key for s in('chair','lounge'))else'cabinet'if any(s in key for s in('cabinet','sideboard','shelf'))else'table'
    records.append(create_case(key,ROOT/model['path'],references[number],model['title'],category))
for prefix,title,category in [('0013','亚克力边桌','table'),('0014','Adea 桶形软包椅','chair'),('0017','Aero 铝合金凳','chair')]:
    photo=next((ROOT/'images').glob(prefix+'_*'));records.append(create_case('new_'+prefix,None,photo,title,category,origin='new_real_local_inference',pending=True))
assert len(records)==25
assert len({r['normalized_photo_sha256']for r in records})==25,'Duplicate photos must not be counted twice'
(OUT/'cases.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
record('case_registry_created',distinct_furniture=len(records),existing_models=sum(r['status']!='pending_generation'for r in records),pending_real_inferences=sum(r['status']=='pending_generation'for r in records))
print(json.dumps({'distinct_furniture':len(records),'jobs':[{'case':r['case'],'job':r['job'],'origin':r['origin']}for r in records]},ensure_ascii=False))
