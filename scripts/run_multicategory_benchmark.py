# -*- coding: utf-8 -*-
"""Real API regression with immutable inputs, explicit selection and no fake scores."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import time

import httpx
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/multicategory_20261111'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.writing')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    for attempt in range(10):
        try:temp.replace(path);return
        except PermissionError:
            if attempt==9:raise
            time.sleep(.05)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def freeze():
    if (OUT/'protocol.json').exists():raise ValueError('Protocol already frozen; do not change cases after observing outputs')
    inventory=read(OUT/'inventory.json')['images']
    public=read(OUT/'public_candidates.json')
    cases=[]
    selections=[
        ('clean_cabinet','cabinet','0305_','拱顶展示柜',['完整拱顶与外框','上下层分隔','底部双门及腿','中空层板空间']),
        ('clean_table','table','0030_','三支撑圆茶几',['薄圆桌面','三根分开支撑','底座曲线','桌面与底座比例']),
        ('clean_sofa','sofa','0080_','灯芯绒双人沙发',['双扶手','靠背与坐垫分隔','整体软包轮廓','不把背景当成结构']),
        ('clean_vase','vase','0358_','彩绘陶瓷花瓶',['瓶口与细颈','宽瓶身轮廓','底足','口部是否被封死；彩绘另行标注为无纹理']),
        ('clean_plant','plant','0048_','仿真琴叶榕盆栽',['花盆保留','树干独立','叶片与枝干分离情况','尺寸标注没有变成几何']),
        ('scene_cabinet','cabinet','0304_','场景拱顶柜',['保留完整柜框','剔除墙面和邻近座椅','拱顶和下部双门','柜内陈列品属于干扰风险，未做补全']),
        ('scene_sofa_local','sofa','0423_','室内皮质沙发',['沙发扶手及坐垫','剔除地毯与墙面','旁边盆栽不粘连','整体轮廓']),
    ]
    for identity,category,prefix,name,features in selections:
        record=next(r for r in inventory if Path(r['path']).name.startswith(prefix))
        cases.append({'id':identity,'category':category,'name':name,'path':record['path'],
                      'source':'user_images','sha256':record['sha256'],
                      'background_expected':'clean' if identity.startswith('clean') else 'scene',
                      'fallback_target':{'x':0,'y':0,'width':1,'height':1} if identity.startswith('clean') else None,
                      'critical_features':features})
    for identity,category,image_id,name,features in [
        ('scene_sofa_cat','sofa',599,'猫和遥控器遮挡的沙发',['选择沙发而非猫','遮挡未补全须判明','剔除右侧盆栽','可见扶手与靠背']),
        ('scene_table_glass','table',283,'有酒瓶酒杯的玻璃餐桌',['桌面与桌腿可辨','剔除瓶杯及椅子','玻璃反射是否进入几何','画面裁断与遮挡限制']),
        ('scene_vase_flowers','vase',30,'窗边插花瓶',['识别花瓶而非整束植物','保留瓶身与底座','花束与背景不能替代瓶口','被花遮挡处未补全']),
        ('scene_plant_small','plant',560,'浴室角落小盆栽',['找到左侧小盆栽','剔除洗手盆与镜框','保留花盆与叶冠','低像素输入的细节限制']),
    ]:
        record=next(r for r in public if Path(r['path']).stem==f'{image_id:012d}')
        obj=max([obj for obj in record['objects'] if obj['category']==category],key=lambda obj:obj['area_fraction'])
        x,y,w,h=obj['box_yolo'];left=max(0,x-w/2);top=max(0,y-h/2)
        target={'x':left,'y':top,'width':min(1,x+w/2)-left,'height':min(1,y+h/2)-top}
        cases.append({'id':identity,'category':category,'name':name,'path':record['path'],
                      'source':'public_coco128_real_photo','sha256':sha(ROOT/record['path']),
                      'background_expected':'scene','annotation_bbox':target,'fallback_target':target,
                      'annotation_note':'Original COCO128 detection box only, not dense mask or 3D truth',
                      'source_url':f'https://images.cocodataset.org/train2017/{image_id:012d}.jpg',
                      'explore_url':f'https://cocodataset.org/#explore?id={image_id}',
                      'critical_features':features})
    protocol={'date':'2026-11-11','frozen_at_utc':datetime.now(timezone.utc).isoformat(),
              'sampling':'Purposive diagnostic set, selected from photo inspection before detection/segmentation/3D. Not a random benchmark or held-out evaluation; model training overlap is unknown.',
              'engine':'hunyuan-mini','steps':30,'seed':42,'resolution':256,'segmentation':'auto',
              'selection':'Choose largest detected candidate of the predeclared intended category. Record UI default largest-priority-furniture separately; category-guided selection is not the same as default auto-pick.',
              'fallback':'If intended category is missing, record detection miss. Only run separate diagnostic with predeclared annotation/full-image box; never count this as automatic selection success. Scene without predeclared fallback is skipped.',
              'review':'Assistant visually checks original, actual foreground and fixed GLB front/oblique/side/rear. No dense masks or true 3D; no accuracy/Chamfer/hidden-geometry scores. User approval remains pending.',
              'cases':cases}
    write(OUT/'protocol.json',protocol)
    print('Frozen '+str(len(cases))+' cases before inference',flush=True)

def api_json(api,method,url,**kwargs):
    response=api.request(method,url,**kwargs);response.raise_for_status();return response.json()

def iou(a,b):
    x=max(a['x'],b['x']);y=max(a['y'],b['y'])
    right=min(a['x']+a['width'],b['x']+b['width']);bottom=min(a['y']+a['height'],b['y']+b['height'])
    area=max(0,right-x)*max(0,bottom-y)
    return area/max(a['width']*a['height']+b['width']*b['height']-area,1e-9)

def detect(api,case):
    folder=OUT/case['id'];folder.mkdir(exist_ok=True)
    if (folder/'detection_record.json').is_file():
        record=read(folder/'detection_record.json')
        if record['source_sha256']!=case['sha256']:raise ValueError('Source changed')
        print(case['id']+' detection: reuse preserved result',flush=True);return record
    path=ROOT/case['path']
    assert sha(path)==case['sha256'],'Source changed'
    response=api.post('/api/images',files={'file':(path.name,path.read_bytes(),'image/'+('jpeg' if path.suffix.lower()=='.jpg' else path.suffix[1:]))})
    response.raise_for_status();image=response.json()
    cached=image.get('analysis',{}).get('status')=='completed'
    started=time.monotonic()
    image=api_json(api,'POST','/api/images/'+image['id']+'/analysis')
    while image.get('analysis',{}).get('status') in ['queued','running']:
        if time.monotonic()-started>360:raise TimeoutError('Detection timeout')
        time.sleep(1);image=api_json(api,'GET','/api/images/'+image['id'])
    analysis=image.get('analysis',{})
    objects=analysis.get('objects',[])
    priority=[obj for obj in objects if obj['category'] in ['cabinet','sofa','table','chair']]
    auto=max(priority or objects,key=lambda obj:obj['target']['width']*obj['target']['height'],default=None)
    expected=[obj for obj in objects if obj['category']==case['category']]
    selected=max(expected,key=lambda obj:obj['target']['width']*obj['target']['height'],default=None)
    mode='category_guided_detection' if selected else 'annotation_diagnostic' if case.get('annotation_bbox') else 'full_image_diagnostic' if case.get('fallback_target') else 'no_target'
    target=selected['target'] if selected else case.get('fallback_target')
    annotation_iou=iou(selected['target'],case['annotation_bbox']) if selected and case.get('annotation_bbox') else None
    # Cache timing is labeled; do not reuse cached historical model time as fresh wall time.
    record={'image':image,'source_sha256':case['sha256'],'detection_wall_seconds':round(time.monotonic()-started,3),
        'cached_analysis':cached,'analysis':analysis,'intended_category_detected':bool(expected),
        'ui_default_auto_pick':auto,'ui_default_category_matches':bool(auto and auto['category']==case['category']),
        'selected':selected,'target':target,'selection_mode':mode,
        'selected_bbox_iou_vs_coco_annotation':annotation_iou,
        'iou_note':'Single detection-box overlap with existing COCO128 annotation; not mask IoU, correctness probability, or 3D accuracy'}
    write(folder/'detection_record.json',record)
    source=Image.open(ROOT/'.data'/image['normalized_path']).convert('RGB')
    source.save(folder/'original.png')
    draw=ImageDraw.Draw(source)
    for obj in objects:
        box=obj['target'];w,h=source.size
        bounds=[round(box['x']*w),round(box['y']*h),round((box['x']+box['width'])*w),round((box['y']+box['height'])*h)]
        color='#16a34a' if selected and obj['id']==selected['id'] else '#e24545'
        draw.rectangle(bounds,outline=color,width=max(2,source.width//250))
        font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',max(13,source.width//55))
        draw.text((bounds[0],max(0,bounds[1]-font.size-2)),obj['label']+' '+str(obj['score']),font=font,fill=color)
    source.save(folder/'detection_overlay.png')
    print(case['id']+' detection: '+mode+' / '+str(len(objects))+' objects',flush=True)
    return record

def generate(api,case,record):
    folder=OUT/case['id'];output=folder/'hunyuan';output.mkdir(exist_ok=True)
    if not record['target']:
        write(output/'execution.json',{'status':'skipped','reason':'Intended category missing and no predeclared fallback','automatic_target_success':False});return
    body={'image_id':record['image']['id'],'name':'多品类验收 · '+case['name'],
          'route':'local','local_engine':'hunyuan-mini','local_segmentation':'auto',
          'local_remove_background':True,'target':record['target'],
          'object_label':record['selected']['label'] if record['selected'] else '',
          'object_id':record['selected']['id'] if record['selected'] else ''}
    identity=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:20]
    job=api_json(api,'POST','/api/jobs',json=body,headers={'Idempotency-Key':'multi-20261111-'+identity})
    write(output/'job.json',job)
    start=time.monotonic();stage=None
    while job['status'] in ['queued','running']:
        if job['stage']!=stage:
            print(case['id']+' '+job['id']+' / '+job['stage'],flush=True);stage=job['stage']
        if time.monotonic()-start>1600:raise TimeoutError('Task still running '+job['id'])
        time.sleep(1);job=api_json(api,'GET','/api/jobs/'+job['id'])
    write(output/'job.json',job)
    artifacts=['prepared.png','foreground.png','model_input.png','local_summary.json','quality_report.json','model.glb',
               'segmented.png','segmentation_mask.png','segmentation_overlay.png','segmentation_summary.json']
    hashes={}
    for name in artifacts:
        response=api.get('/api/jobs/'+job['id']+'/files/'+name)
        if response.status_code==200:
            (output/name).write_bytes(response.content);hashes[name]=hashlib.sha256(response.content).hexdigest()
    for name in ['local3d.log','segmentation.log','segmentation_failure.json']:
        source=ROOT/'.data/jobs'/job['id']/name
        if source.is_file():shutil.copyfile(source,output/name)
    execution={'status':job['status'],'job_id':job['id'],'url':str(api.base_url)+'?job='+job['id'],
        'selection_mode':record['selection_mode'],'automatic_target_success':record['selection_mode']=='category_guided_detection',
        'sha256':hashes,'technical_validation':job.get('report',{}).get('gltf_validation'),
        'summary':job.get('report',{}).get('local_inference'),'error':job.get('error'),
        'visual_acceptance':'not_yet_reviewed','user_review_status':job.get('review_status')}
    write(output/'execution.json',execution)
    print(case['id']+' finished: '+job['status'],flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['freeze','detect','generate']);parser.add_argument('--case');parser.add_argument('--base',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    if args.stage=='freeze':freeze();return
    protocol=read(OUT/'protocol.json')
    with httpx.Client(base_url=args.base,timeout=60) as api:
        for case in protocol['cases']:
            if args.case and case['id']!=args.case:continue
            try:
                record=detect(api,case)
                if args.stage=='generate':generate(api,case,record)
            except Exception as error:
                write(OUT/case['id']/('runner_failure_'+args.stage+'.json'),{'error':str(error),'type':type(error).__name__})
                print(case['id']+' RUNNER FAILURE '+str(error),flush=True)
    print('Batch stage '+args.stage+' finished; inspect every case record for actual status',flush=True)

if __name__=='__main__':main()
