# -*- coding: utf-8 -*-
"""Visual evidence only, no synthetic replacement geometry or numeric ratings."""
import argparse
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/multicategory_20261111'
FONT='C:/Windows/Fonts/msyh.ttc'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def composite(path,size):
    with Image.open(path) as source:
        image=source.convert('RGBA')
    image=Image.alpha_composite(Image.new('RGBA',image.size,'white'),image).convert('RGB')
    return ImageOps.contain(image,size)
def make(cases,filename,stage):
    widths=[270,270,270,270,270] if stage=='review' else [400,400,400]
    canvas=Image.new('RGB',(sum(widths),55+len(cases)*325),'#eef0f2')
    draw=ImageDraw.Draw(canvas);font=ImageFont.truetype(FONT,18);small=ImageFont.truetype(FONT,16)
    titles=['原图与检测候选','实际送入 3D 的前景','灰模·观察角度','灰模·另一视角','灰模·侧视'] if stage=='review' else ['原图与检测候选','检测框裁剪','实际前景 / 未执行']
    for i,title in enumerate(titles):draw.text((sum(widths[:i])+10,15),title,font=font,fill='black')
    for row,case in enumerate(cases):
        folder=OUT/case['id'];y=55+row*325
        draw.text((10,y),case['id']+' · '+case['name'],font=font,fill='black')
        review=read(OUT/'visual_review.json')['cases'].get(case['id'],{}) if (OUT/'visual_review.json').is_file() else {}
        preferred=review.get('preferred_view','model_oblique')
        paths=[folder/'detection_overlay.png',folder/'hunyuan/foreground.png',
            folder/('renders/'+preferred+'.png'),folder/'renders/model_rear.png',folder/'renders/model_side.png'] if stage=='review' else [folder/'detection_overlay.png',folder/'hunyuan/prepared.png',folder/'hunyuan/foreground.png']
        for i,path in enumerate(paths):
            x=sum(widths[:i])
            if path.is_file():
                image=composite(path,(widths[i]-12,280))
                canvas.paste(image,(x+(widths[i]-image.width)//2,y+30+(280-image.height)//2))
            else:draw.text((x+12,y+130),'尚无实际输出',font=font,fill='#666666')
    canvas.save(OUT/filename)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['review','input'],default='review');parser.add_argument('--case')
    args=parser.parse_args();cases=read(OUT/'protocol.json')['cases']
    if args.case:cases=[case for case in cases if case['id']==args.case]
    if args.case:make(cases,args.case+'_contact.png',args.stage)
    else:
        make(cases[:5],'clean_'+args.stage+'_contact.png',args.stage)
        make(cases[5:],'scene_'+args.stage+'_contact.png',args.stage)
    print('Contact sheets written; absence of outputs is explicitly displayed',flush=True)
