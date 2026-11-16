# -*- coding: utf-8 -*-
"""Real local SAM trials with automatic positive seat and negative frame points."""
import json,os,sys,shutil,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.tools/SAM2')]
os.environ['HF_HUB_OFFLINE']='1'
import numpy as np,torch
from PIL import Image,ImageDraw
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor
from semantic_prompts import seat_geometry_prompts,seat_prompt_variants
OUT=ROOT/'experiments/semantic_refinement_20261113';records=[];torch.set_num_threads(4)
predictor=SAM2ImagePredictor(build_sam2('configs/sam2.1/sam2.1_hiera_t.yaml',str(ROOT/'.models/sam2.1-hiera-tiny/sam2.1_hiera_tiny.pt'),device='cuda',apply_postprocessing=False),max_hole_area=0,max_sprinkle_area=0)
for case in ('leather_sofa','corduroy_sofa','accent_chair'):
    folder=OUT/case;d=json.loads((folder/'diagnosis.json').read_text(encoding='utf-8'));source=Path(d['scan']);cache=np.load(folder/'evidence.npz');views=json.loads((source/'views.json').read_text(encoding='utf-8'));cues=seat_geometry_prompts(cache['vertices'],cache['centers'],cache['normals'],cache['area'],views,source);target=folder/'seat_mask_trial';target.mkdir(exist_ok=True)
    for f in source.iterdir():
        if f.suffix in('.png','.json'):shutil.copyfile(f,target/f.name)
    (target/'geometry_prompts.json').write_text(json.dumps(cues,indent=2),encoding='utf-8');data=json.loads((source/'detections.json').read_text(encoding='utf-8'))
    if cues['available']:
        for record,view,cue in zip(data['views'],views,cues['views']):
            record['masks']=[m for m in record['masks']if m['kind']!='seat'];image=Image.open(source/view['image']).convert('RGB');drawn=image.copy();draw=ImageDraw.Draw(drawn)
            for point in cue['positive_points']:x,y=point;draw.ellipse((x-4,y-4,x+4,y+4),fill='lime')
            for point in cue['negative_points']:x,y=point;draw.ellipse((x-4,y-4,x+4,y+4),fill='red')
            drawn.save(target/f'geometry_points_{view["index"]}.png')
            with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
                predictor.set_image(np.asarray(image))
                for di,detection in enumerate(record['detections']):
                    if detection['kind']!='seat':continue
                    box=np.asarray(detection['box'],np.float32)
                    for pi,(points,labels) in enumerate(seat_prompt_variants(box,cue)):
                        masks,scores,_=predictor.predict(box=box,point_coords=points,point_labels=labels,multimask_output=True)
                        for mi,(mask,score) in enumerate(zip(masks,scores)):
                            xy=np.rint(points).astype(int);included=mask[xy[:,1],xy[:,0]]
                            if score<.68 or mask.sum()<250 or not included[labels==1].all() or included[labels==0].any():continue
                            filename=f'seat_guided_{view["index"]}_{di}_{pi}_{mi}.png';Image.fromarray(np.uint8(mask)*255).save(target/filename);record['masks'].append({'kind':'seat','detector_score':detection['detector_score'],'mask_quality_prediction':float(score),'detection':di,'prompt':'automatic_seat_points_and_exclusions','mask_file':filename,'pixels':int(mask.sum())})
            print(case,view['index'],len([m for m in record['masks']if m['kind']=='seat']),flush=True)
    data['geometry_cues']=cues;(target/'detections.json').write_text(json.dumps(data,indent=2),encoding='utf-8');records.append({'case':case,'cues':cues,'seat_masks':sum(m['kind']=='seat'for r in data['views']for m in r['masks'])});(OUT/'seat_mask_trials.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
