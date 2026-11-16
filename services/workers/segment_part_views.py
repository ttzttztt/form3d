"""Real offline SAM 2 point prompts on rendered views, no semantic accuracy claims."""
import argparse,json,os,sys,time
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'.tools/SAM2'))
def main(folder):
    import numpy as np
    import torch
    from PIL import Image
    from scipy.ndimage import label
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    started=time.monotonic();torch.set_num_threads(4)
    if not torch.cuda.is_available():raise ValueError('SAM 2 CUDA 不可用')
    model=build_sam2('configs/sam2.1/sam2.1_hiera_t.yaml',str(ROOT/'.models/sam2.1-hiera-tiny/sam2.1_hiera_tiny.pt'),device='cuda',apply_postprocessing=False);predictor=SAM2ImagePredictor(model,max_hole_area=0,max_sprinkle_area=0);request=json.loads((folder/'request.json').read_text(encoding='utf-8'));results=[]
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
        for i,view in enumerate(request['views']):
            image=Image.open(folder/f'view_{i}.png').convert('RGB');w,h=image.size;prompts=view.get('points') or [{**view['point'],'label':1}];point=np.array([[min(w-1,p['x']*w),min(h-1,p['y']*h)] for p in prompts],dtype=np.float32);labels=np.array([p['label'] for p in prompts]);predictor.set_image(np.array(image));masks,scores,_=predictor.predict(point_coords=point,point_labels=labels,multimask_output=True);options=[]
            for index,mask in enumerate(masks):
                connected,_=label(mask);key=connected[int(point[0,1]),int(point[0,0])];component=connected==key
                obeys=all(bool(component[int(p[1]),int(p[0])])==bool(label) for p,label in zip(point,labels))
                if key and obeys and np.isfinite(scores[index]) and scores[index]>=.5 and .0005<component.mean()<.85:options.append((component.sum(),index,component))
            if not options:raise ValueError('没有得到可信的点击候选，请换个位置或使用涂抹')
            options.sort(key=lambda item:item[0]);choices={name:options[k] for name,k in [('small',0),('medium',len(options)//2),('large',len(options)-1)]};details={}
            for name,(_,choice,mask) in choices.items():
                Image.fromarray(np.uint8(mask)*255).save(folder/f'mask_{name}_{i}.png');details[name]={'predicted_iou':float(scores[choice]),'mask_pixels':int(mask.sum()),'chosen_candidate':choice}
            selected=request.get('candidate_range','small');Image.open(folder/f'mask_{selected}_{i}.png').save(folder/f'mask_{i}.png');results.append({'view':i,'prompt_count':len(prompts),'negative_count':int((labels==0).sum()),'candidates':details,**details[selected]})
    (folder/'result.json').write_text(json.dumps({'model':'SAM 2.1 Hiera Tiny','prompt':'positive/negative points; all visible prompts must be satisfied','ranges':['small','medium','large'],'views':results,'seconds':round(time.monotonic()-started,3),'score_note':'Predicted mask quality, not measured accuracy; review 3D boundary.'},indent=2),encoding='utf-8')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--folder',required=True);main(Path(parser.parse_args().folder))
