"""Evaluate predeclared sparse diagnostic points; do not claim dense mask accuracy."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'experiments'/'segmentation_20261111'


def main():
    protocol=json.loads((FOLDER/'protocol.json').read_text(encoding='utf-8'))
    original=Image.open(ROOT/protocol['prepared_reference']).convert('RGB')
    old=Image.open(ROOT/protocol['old_foreground']).convert('RGBA')
    source=np.asarray(original)
    cropped=np.asarray(old.convert('RGB'))
    # Recover the old cropped alpha's exact location by unchanged source RGB.
    opaque=np.asarray(old.getchannel('A'))==255
    if int(opaque.sum())<64: raise ValueError('Insufficient opaque pixels for exact source alignment')
    match=cv2.matchTemplate(source,cropped,cv2.TM_SQDIFF,mask=opaque.astype(np.uint8)*255)
    _,_,location,_=cv2.minMaxLoc(match)
    x,y=location
    if not np.array_equal(source[y:y+old.height,x:x+old.width][opaque],cropped[opaque]):
        raise ValueError('Old cutout RGB does not align exactly; cannot reconstruct its full mask honestly')
    old_mask=Image.new('L',original.size,0)
    old_mask.paste(old.getchannel('A'),location)
    directory=FOLDER/'armchair'
    directory.mkdir(parents=True,exist_ok=True)
    old_mask.save(directory/'old_mask_aligned.png')
    paths={'u2netp':directory/'old_mask_aligned.png',
           'sam2':directory/'sam2_box'/'segmentation_mask.png'}
    results={}
    marked=original.copy()
    draw=ImageDraw.Draw(marked)
    text_font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',18)
    for method,path in paths.items():
        mask=Image.open(path).convert('L')
        if mask.size!=original.size: raise ValueError('Mask size mismatch')
        records=[]
        for index,point in enumerate(protocol['points_in_prepared_roi_normalized'],1):
            px=min(original.width-1,round(point['xy'][0]*original.width))
            py=min(original.height-1,round(point['xy'][1]*original.height))
            kept=mask.getpixel((px,py))>127
            records.append({'name':point['name'],'pixel':[px,py],
                'expected_foreground':point['expected_foreground'],'mask_keeps_point':kept,
                'matches_diagnostic_expectation':kept==point['expected_foreground']})
            if method=='sam2':
                color='#1d6cd8' if point['expected_foreground'] else '#ce2e98'
                draw.ellipse((px-6,py-6,px+6,py+6),fill=color,outline='white',width=2)
                draw.text((px+9,py-10),str(index),font=text_font,fill=color,stroke_fill='white',stroke_width=2)
        results[method]={'points':records,
            'foreground_points_retained':sum(item['mask_keeps_point'] for item in records if item['expected_foreground']),
            'foreground_points_total':sum(item['expected_foreground'] for item in records),
            'background_points_excluded':sum(not item['mask_keeps_point'] for item in records if not item['expected_foreground']),
            'background_points_total':sum(not item['expected_foreground'] for item in records),
            'mask_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    marked.save(directory/'diagnostic_points.png')
    report={'method':'predeclared sparse photo inspection points, not dense ground truth',
            'old_alignment_validation':'all fully opaque cutout RGB pixels exactly match their source locations; transparent RGB ignored',
            'old_mask_location_recovered_from_exact_rgb':list(location),
            'old_foreground_sha256':hashlib.sha256((ROOT/protocol['old_foreground']).read_bytes()).hexdigest(),
            'dense_iou':None,'segmentation_accuracy':None,'results':results}
    (FOLDER/'point_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:{name:value for name,value in item.items() if name!='points'} for key,item in results.items()},ensure_ascii=True,indent=2))


if __name__=='__main__':
    main()
