# -*- coding: utf-8 -*-
"""Compact evidence panel: source crops and actual renders, no image generation."""
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/multicategory_20261111'
protocol=json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
reviews=json.loads((OUT/'visual_review.json').read_text(encoding='utf-8'))['cases']
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',20)
small=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',17)
canvas=Image.new('RGB',(1500,900),'#eef0f2');draw=ImageDraw.Draw(canvas)
draw.text((18,12),'11 个真实任务的代表样本：上排可作几何候选，下排不通过；完整记录见报告',font=font,fill='black')
ids=['clean_table','clean_sofa','scene_sofa_local','scene_cabinet','scene_sofa_cat','scene_table_glass']
for index,identity in enumerate(ids):
    case=next(case for case in protocol['cases'] if case['id']==identity)
    review=reviews[identity];x=(index%3)*500;y=55+(index//3)*415
    draw.text((x+12,y),case['name'],font=font,fill='black')
    preferred=review.get('preferred_view','model_oblique')
    for column,path in enumerate([OUT/identity/'hunyuan/prepared.png',OUT/identity/('renders/'+preferred+'.png')]):
        with Image.open(path) as image:
            image=image.convert('RGBA');image=Image.alpha_composite(Image.new('RGBA',image.size,'white'),image).convert('RGB')
        image=ImageOps.contain(image,(240,325))
        canvas.paste(image,(x+column*250+(250-image.width)//2,y+38+(325-image.height)//2))
    draw.text((x+15,y+365),'输入裁剪',font=small,fill='#343a45')
    draw.text((x+265,y+365),'实际 GLB 灰模',font=small,fill='#343a45')
draw.text((18,873),'3 可作候选 / 3 需修正 / 5 不通过；无商品纹理，尺寸与不可见结构未核实。数量不代表准确率。',font=small,fill='black')
canvas.save(OUT/'examples_overview.png')
print('Representative actual-input / actual-GLB panel written')
