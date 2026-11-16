# -*- coding: utf-8 -*-
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageOps
ROOT=Path(__file__).resolve().parents[1]/'experiments/part_regeneration_20261113'
for folder in ROOT.iterdir():
    path=folder/'references/references.json'
    if not path.exists():continue
    refs=json.loads(path.read_text(encoding='utf-8'))['candidates'];canvas=Image.new('RGB',(1000,260*((len(refs)+3)//4)),'#ededed');draw=ImageDraw.Draw(canvas)
    for i,ref in enumerate(refs):
        image=Image.open(path.parent/ref['preview']).convert('RGB');image=ImageOps.contain(image,(240,225));x=(i%4)*250;y=(i//4)*260;canvas.paste(image,(x+(250-image.width)//2,y+(225-image.height)//2));draw.text((x+5,y+232),f"{i}: {ref['id'][:8]} det={ref['detection']}",fill='black')
    canvas.save(folder/'reference_sheet.png')
