# -*- coding: utf-8 -*-
"""Local SAM refinement of pillow masks using automatically projected frame exclusions."""
import json,os,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.tools/SAM2')]
os.environ['HF_HUB_OFFLINE']='1'
import numpy as np,torch
from PIL import Image,ImageDraw
from scipy.ndimage import distance_transform_edt,binary_dilation
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor
from semantic_mapping import project_visible
from semantic_prompts import spread_points
OUT=ROOT/'experiments/semantic_refinement_20261113';summary=[];torch.set_num_threads(4)
predictor=SAM2ImagePredictor(build_sam2('configs/sam2.1/sam2.1_hiera_t.yaml',str(ROOT/'.models/sam2.1-hiera-tiny/sam2.1_hiera_tiny.pt'),device='cuda',apply_postprocessing=False),max_hole_area=0,max_sprinkle_area=0)
for case in ('leather_sofa','corduroy_sofa'):
    root=OUT/case;d=json.loads((root/'diagnosis.json').read_text(encoding='utf-8'));source=Path(d['scan']);target=root/'pillow_mask_trial';target.mkdir(exist_ok=True)
    for f in source.iterdir():
        if f.suffix in('.png','.json'):shutil.copyfile(f,target/f.name)
    cache=np.load(root/'evidence.npz');centers=cache['centers'];area=cache['area'];height=float(np.ptp(cache['vertices'][:,1]));top=json.loads((root/'seat_mask_trial/geometry_prompts.json').read_text())['seat_top_source_units'];views=json.loads((source/'views.json').read_text());data=json.loads((source/'detections.json').read_text());checks=[]
    for record,view in zip(data['views'],views):
        image=Image.open(source/view['image']).convert('RGB');x,y,seen,_=project_visible(centers,{**view,'depth_path':source/view['depth']});lower=seen&(centers[:,1]<top-height*.035);upper=seen&(centers[:,1]>top+height*.04);lo=np.zeros((image.height,image.width),bool);hi=lo.copy();lo[y[lower],x[lower]]=True;hi[y[upper],x[upper]]=True;lo=binary_dilation(lo,iterations=2);hi=binary_dilation(hi,iterations=2);new_masks=[]
        with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
            predictor.set_image(np.array(image))
            for ordinal,mask_record in enumerate(record['masks']):
                if mask_record['kind']!='pillow':new_masks.append(mask_record);continue
                old=np.asarray(Image.open(source/mask_record['mask_file']))>127;inside=distance_transform_edt(old);negative=lo&old&(inside>=2);positive=hi&old&(inside>=3)
                if negative.sum()<8 or positive.sum()<20:new_masks.append(mask_record);continue
                yy,xx=np.nonzero(positive);pick=int(np.argmax(inside[yy,xx]));pos=np.array([[xx[pick],yy[pick]]],np.float32);ny,nx=np.nonzero(negative);neg=np.asarray(spread_points(np.c_[nx,ny],inside[ny,nx],count=4,min_spacing=10),np.float32);points=np.vstack([pos,neg]);labels=np.r_[1,np.zeros(len(neg),int)];box=np.asarray(record['detections'][mask_record['detection']]['box'],np.float32);masks,scores,_=predictor.predict(box=box,point_coords=points,point_labels=labels,multimask_output=True);accepted=[]
                for index,(mask,score)in enumerate(zip(masks,scores)):
                    mask=np.asarray(mask)>0
                    q=np.rint(points).astype(int);hits=mask[q[:,1],q[:,0]];retained=float((mask&positive).sum()/positive.sum());iou=float((mask&old).sum()/max((mask|old).sum(),1))
                    if score>=.65 and hits[0]and not hits[1:].any()and retained>=.70 and iou>=.3:accepted.append((float(score),mask,index,retained,iou))
                check={'view':view['index'],'source_mask':mask_record['mask_file'],'negative_points':neg.tolist(),'positive_point':pos.tolist(),'accepted':bool(accepted)};checks.append(check)
                if not accepted:continue
                score,mask,index,retained,iou=max(accepted,key=lambda item:item[0]);file=f'pillow_refined_{view["index"]}_{ordinal}.png';Image.fromarray(np.uint8(mask)*255).save(target/file);new_masks.append({**mask_record,'mask_file':file,'mask_quality_prediction':score,'prompt':'automatic_pillow_interior_and_frame_exclusions','pixels':int(mask.sum())});check.update(retained_upper_source_projection=retained,iou_to_previous_mask=iou,removed_pixels=int((old&~mask).sum()))
        record['masks']=new_masks;print(case,view['index'],len(new_masks),flush=True)
    data['automatic_pillow_refinement']=checks;(target/'detections.json').write_text(json.dumps(data,indent=2),encoding='utf-8');summary.append({'case':case,'checks':checks});(OUT/'pillow_mask_trials.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
