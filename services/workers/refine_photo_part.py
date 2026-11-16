"""SAM2 segmentation using the projected part as points, not as a final mask."""
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'.tools/SAM2'))
os.environ['HF_HUB_OFFLINE']='1'

def points_in(mask,count):
    import cv2,numpy as np
    distance=cv2.distanceTransform(mask.astype('uint8'),cv2.DIST_L2,5);points=[]
    for _ in range(count):
        _,value,_,location=cv2.minMaxLoc(distance)
        if value<2:break
        points.append(location);cv2.circle(distance,location,max(12,int(value*1.6)),0,-1)
    return points

def run(a):
    import cv2,numpy as np,torch
    from PIL import Image
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    folder=Path(a.output);data=json.loads((folder/'references.json').read_text(encoding='utf-8'))
    product=Image.open(folder/'product.png').convert('RGB');hint=cv2.imread(a.hint,0)>127;other=cv2.imread(a.other,0)>127
    positive=points_in(hint,3);negative=points_in(other,6)
    if not positive:raise ValueError('投影部件过小，未自动提示分割')
    yy,xx=np.nonzero(hint);box=np.array([xx.min(),yy.min(),xx.max(),yy.max()],dtype='float32')
    coordinates=np.asarray(positive+negative,dtype='float32');labels=np.r_[np.ones(len(positive)),np.zeros(len(negative))].astype(int)
    torch.set_num_threads(4)
    model=build_sam2('configs/sam2.1/sam2.1_hiera_t.yaml',str(ROOT/'.models/sam2.1-hiera-tiny/sam2.1_hiera_tiny.pt'),device='cuda',apply_postprocessing=False)
    predictor=SAM2ImagePredictor(model,max_hole_area=0,max_sprinkle_area=0)
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
        predictor.set_image(np.array(product));masks,scores,_=predictor.predict(box=box,point_coords=coordinates,point_labels=labels,multimask_output=True)
    existing={c['id']for c in data['candidates']}
    for mask,score in zip(masks,scores):
        if score<.65 or mask.sum()<300:continue
        mask=mask.astype('uint8');identity=hashlib.sha256(mask.tobytes()).hexdigest()[:32]
        if identity in existing:continue
        alpha=Image.fromarray(mask*255);bounds=alpha.getbbox();crop=[max(0,bounds[0]-8),max(0,bounds[1]-8),min(product.width,bounds[2]+8),min(product.height,bounds[3]+8)]
        rgba=product.convert('RGBA');rgba.putalpha(alpha);part=rgba.crop(crop);part.save(folder/(identity+'.png'))
        white=Image.new('RGBA',part.size,'white');white.alpha_composite(part);white.convert('RGB').save(folder/(identity+'_preview.png'));alpha.save(folder/(identity+'_mask.png'))
        data['candidates'].append({'id':identity,'file':identity+'.png','preview':identity+'_preview.png','mask_file':identity+'_mask.png','source_crop_in_product_pixels':crop,'label':'投影辅助参考','detection':'projected_part_hint','sam_score_prediction':float(score),'score_is_accuracy':False,'hidden_regions_completed':False,'prompt':'projected_positive_and_neighbour_negative_points','positive_points':positive,'negative_points':negative})
    (folder/'references.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--hint',required=True);p.add_argument('--other',required=True);run(p.parse_args())
