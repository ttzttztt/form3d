# -*- coding: utf-8 -*-
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from PIL import Image,ImageDraw,ImageFont,ImageOps
from services.api.store import Store
from upgrade_record import OUT
cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'));store=Store(ROOT/'.data');font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',18)
for page in range((len(cases)+13)//14):
    canvas=Image.new('RGB',(1120,7*235),(255,255,255));draw=ImageDraw.Draw(canvas)
    for index,c in enumerate(cases[page*14:page*14+14]):
        x=(index%2)*560;y=(index//2)*235
        draw.text((x+8,y+5),f'{page*14+index+1:02d} {c["title"]}',font=font,fill='#172b45')
        paths=[store.root/store.image(c['image_id'])['normalized_path'],OUT/'renders'/(c['case']+'__original.png')]
        for j,path in enumerate(paths):
            image=Image.open(path).convert('RGBA');background=Image.new('RGBA',image.size,'white');background.alpha_composite(image);image=ImageOps.contain(background.convert('RGB'),(270,190));canvas.paste(image,(x+j*280+(280-image.width)//2,y+32+(190-image.height)//2))
    canvas.save(OUT/f'visual_sources_and_originals_{page+1}.png')
