# -*- coding: utf-8 -*-
"""Inventory local inputs and fetch a traceable public, real-scene test subset."""
import argparse
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import re
import time
import zipfile

import httpx
from PIL import Image,ImageDraw,ImageFont,ImageOps

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/multicategory_20261111'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def sheet(records,path,title):
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',16)
    cols=5
    canvas=Image.new('RGB',(cols*260,45+((len(records)+cols-1)//cols)*245),'#eef0f2')
    draw=ImageDraw.Draw(canvas)
    draw.text((12,10),title,font=font,fill='black')
    for index,record in enumerate(records):
        x=(index%cols)*260;y=45+(index//cols)*245
        image=Image.open(ROOT/record['path']).convert('RGBA')
        image=Image.alpha_composite(Image.new('RGBA',image.size,'white'),image).convert('RGB')
        image=ImageOps.contain(image,(250,210))
        canvas.paste(image,(x+(260-image.width)//2,y+(210-image.height)//2))
        draw.text((x+7,y+213),str(index)+' '+Path(record['path']).name[:23],font=font,fill='black')
        draw.text((x+7,y+230),record.get('kind','')+' '+record.get('labels',''),font=font,fill='black')
    canvas.save(path)

def inventory():
    import sys
    sys.path.insert(0,str(ROOT))
    from services.api.segmentation import image_background_kind
    records=[]
    for path in sorted((ROOT/'images').iterdir()):
        if path.suffix.lower() not in {'.jpg','.jpeg','.png','.webp'}:continue
        try:
            with Image.open(path) as image:
                size=list(image.size)
            records.append({'path':path.relative_to(ROOT).as_posix(),'size':size,
                'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'kind':image_background_kind(path)})
        except Exception as error:
            records.append({'path':str(path.relative_to(ROOT)),'error':str(error)})
    counts={kind:sum(r.get('kind')==kind for r in records) for kind in ['white_background','provided_alpha','scene']}
    write(OUT/'inventory.json',{'count':len(records),'background_heuristic_only':True,'counts':counts,'images':records})
    selected=[]
    groups=[r'Bookcase|Side Cabinet|Forme Cabinet|Display Cabinet',r'Coffee Table',
            r'Cloud Sofa|Modular Sofa|Castle Sofa|Corduroy Modular',r'Ceramic Vase|Open Ceramic Vase|Hand-Blown Glass Vase',
            r'Artificial Violin|Bamboo bush|Planter|Potted']
    for pattern in groups:
        candidates=[r for r in records if re.search(pattern,r['path'],re.I) and 'error' not in r]
        # Include clean and scene-looking inputs; visually verify before protocol selection.
        clean=[r for r in candidates if r['kind']!='scene'][:4]
        scene=[r for r in candidates if r['kind']=='scene'][:2]
        selected.extend((clean+scene)[:6])
    write(OUT/'inventory_candidates.json',selected)
    sheet(selected,OUT/'inventory_contact.png','本地候选图：背景类型为边缘启发式，需目视确认')
    print(json.dumps({'images':len(records),'heuristic_counts':counts,'contact_sheet_candidates':len(selected)}),flush=True)

def download():
    directory=OUT/'sources/coco128'
    directory.mkdir(parents=True,exist_ok=True)
    archive=directory/'coco128.zip'
    url='https://github.com/ultralytics/assets/releases/download/v0.0.0/coco128.zip'
    if not archive.is_file():
        with httpx.Client(follow_redirects=True,timeout=60) as client:
            for attempt in range(3):
                try:
                    response=client.get(url);response.raise_for_status()
                    if len(response.content)>50*1024*1024:raise ValueError('Unexpected archive size')
                    zipfile.ZipFile(io.BytesIO(response.content)).testzip()
                    archive.write_bytes(response.content)
                    break
                except Exception:
                    if attempt==2:raise
                    time.sleep(2)
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            if re.fullmatch(r'coco128/(images|labels)/train2017/\d+\.(jpg|txt)',entry.filename) or entry.filename in ['coco128/README.txt','coco128/LICENSE']:
                target=(directory/entry.filename).resolve()
                if not target.is_relative_to(directory.resolve()):raise ValueError('Unsafe archive path')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(package.read(entry))
    names={56:'chair',57:'sofa',58:'plant',60:'table',75:'vase'}
    records=[]
    for label in sorted((directory/'coco128/labels/train2017').glob('*.txt')):
        objects=[]
        for line in label.read_text().splitlines():
            values=line.split()
            if len(values)!=5:continue
            category=int(values[0])
            if category in names:
                x,y,w,h=map(float,values[1:])
                if w*h>=.015:
                    objects.append({'category':names[category],'class_id':category,'box_yolo':[x,y,w,h],'area_fraction':w*h})
        if objects:
            path=directory/'coco128/images/train2017'/label.with_suffix('.jpg').name
            records.append({'path':path.relative_to(ROOT).as_posix(),'objects':objects,
                            'labels':','.join(sorted({obj['category'] for obj in objects}))})
    records.sort(key=lambda r: max(obj['area_fraction'] for obj in r['objects']),reverse=True)
    write(OUT/'public_candidates.json',records)
    write(directory/'provenance.json',{'download_url':url,'dataset_home':'https://cocodataset.org/',
        'subset_home':'https://docs.ultralytics.com/datasets/detect/coco128/',
        'downloaded_at_utc':datetime.now(timezone.utc).isoformat(),
        'zip_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'zip_bytes':archive.stat().st_size,
        'annotations':'COCO128 YOLO boxes; not dense segmentation truth or 3D ground truth',
        'rights_note':'COCO annotations are CC BY 4.0; photo rights vary by original Flickr image. This local test archive is not a commercial redistribution clearance.'})
    sheet(records,OUT/'public_contact.png','公开 COCO128 候选：真实场景；标签来自原有检测框，非分割真值')
    print(json.dumps({'public_candidate_images':len(records),'archive_bytes':archive.stat().st_size}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['inventory','download'])
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    inventory() if args.stage=='inventory' else download()
