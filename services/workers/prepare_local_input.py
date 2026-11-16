# -*- coding: utf-8 -*-
"""Offline alpha preparation, conservative OCR cleanup and clutter screening."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ.setdefault('OMP_NUM_THREADS','4');os.environ.setdefault('TOKENIZERS_PARALLELISM','false')
ROOT=Path(__file__).resolve().parents[2]

def write(path,value):
    temporary=path.with_suffix('.writing');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    for attempt in range(12):
        try:temporary.replace(path);return
        except PermissionError:
            if attempt==11:raise
            time.sleep(.03*(attempt+1))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def inspect_clutter(image,alpha,object_label):
    import inspect
    import numpy as np
    import torch
    from transformers import AutoModelForZeroShotObjectDetection,AutoProcessor
    from input_preflight_rules import RULES
    torch.set_num_threads(4)
    model_path=ROOT/'.models/grounding-dino-tiny'
    processor=AutoProcessor.from_pretrained(str(model_path),local_files_only=True)
    model=AutoModelForZeroShotObjectDetection.from_pretrained(str(model_path),local_files_only=True,disable_custom_kernels=True).to('cuda').eval()
    prompt='cat. dog. person. book. bottle. wine glass. cup. potted plant. flowers.'
    inputs=processor(images=image,text=prompt,return_tensors='pt',size={'shortest_edge':640,'longest_edge':960}).to('cuda')
    with torch.inference_mode():outputs=model(**inputs)
    post=processor.post_process_grounded_object_detection
    key='threshold' if 'threshold' in inspect.signature(post).parameters else 'box_threshold'
    result=post(outputs,input_ids=inputs.input_ids,text_threshold=.25,target_sizes=[(image.height,image.width)],**{key:.30})[0]
    names=result.get('text_labels',result.get('labels',[]));candidates=[]
    chinese=[('cat','猫'),('dog','狗'),('person','人'),('book','书'),('bottle','瓶子'),('glass','杯子'),('cup','杯子'),('plant','盆栽'),('flower','花束')]
    for score,box,name in zip(result['scores'].cpu().tolist(),result['boxes'].cpu().tolist(),names):
        raw=str(name).lower();x0,y0,x1,y1=box
        bounds=[max(0,round(x0)),max(0,round(y0)),min(image.width,round(x1)),min(image.height,round(y1))]
        x0,y0,x1,y1=bounds
        if x1<=x0 or y1<=y0:continue
        box_area=(x1-x0)*(y1-y0);overlap=float(alpha[y0:y1,x0:x1].mean());fraction=box_area/(image.width*image.height)
        protected=bool(('盆栽' in object_label or 'plant' in object_label.lower()) and ('plant' in raw or 'flower' in raw) or
                       ('花瓶' in object_label or 'vase' in object_label.lower()) and any(word in raw for word in ['bottle','glass','cup']))
        label=next((translation for token,translation in chinese if token in raw),raw)
        risky=bool(not protected and score>=RULES['min_clutter_score'] and fraction>=RULES['min_clutter_box_area_fraction'] and overlap>=RULES['min_clutter_alpha_overlap'])
        candidates.append({'raw_label':str(name),'label':label,'score':float(score),'box_pixels':bounds,
            'box_area_fraction':fraction,'foreground_alpha_overlap_fraction':overlap,
            'protected_as_target_category':protected,'requires_attention':risky})
    del model,outputs,inputs;torch.cuda.empty_cache()
    return {'model':'Grounding DINO Tiny','prompt':prompt,'candidates':candidates,
            'score_note':'Detection confidence is not measured correctness; boxes may overlap the product without proving an occlusion.',
            'action':'flag_uncertain_occlusions; no semantic object erase or inpainting'}

def run(args):
    started=time.monotonic();output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    import numpy as np
    from PIL import Image,ImageDraw
    from rapidocr_onnxruntime import RapidOCR
    import rapidocr_onnxruntime
    from input_preflight_rules import mask_metrics,remove_dimension_components,evaluate
    source=Image.open(args.source).convert('RGBA');prepared=Image.open(args.prepared).convert('RGBA')
    image=Image.open(args.input).convert('RGBA')
    if args.presegmented:method='sam2_box'
    elif args.keep_background:method='provided_input_disabled'
    else:
        from local3d_preprocess import remove_product_background
        background=None
        if args.kind=='white_background':
            rgb=np.asarray(source.convert('RGB'));edges=np.concatenate((rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]))
            background=np.median(edges,axis=0).tolist()
        image,method=remove_product_background(image,ROOT/'.models/triposr',white_background_rgb=background)
    image.save(output/'foreground_before_cleanup.png')
    ocr=RapidOCR(intra_op_num_threads=4,inter_op_num_threads=1)
    ocr_started=time.monotonic();ocr_results,ocr_times=ocr(str(args.prepared))
    ocr_seconds=time.monotonic()-ocr_started
    cleaned,erase_mask,text=remove_dimension_components(image,ocr_results)
    cleaned.save(output/'cleaned.png');erase_mask.save(output/'cleanup_mask.png')
    preview=Image.alpha_composite(Image.new('RGBA',cleaned.size,'white'),cleaned).convert('RGB');preview.save(output/'cleaned_preview.png')
    clutter={'model':'Grounding DINO Tiny','candidates':[],'status':'skipped_clean_background'}
    if args.kind=='scene' and not args.skip_clutter:
        raw=Image.alpha_composite(Image.new('RGBA',prepared.size,'white'),prepared).convert('RGB')
        clutter=inspect_clutter(raw,np.asarray(cleaned.getchannel('A'))>127,args.object_label)
        clutter['status']='completed'
    elif args.skip_clutter:clutter['status']='skipped_explicit_offline_replay'
    metrics=mask_metrics(cleaned);decision=evaluate(metrics,prepared.size,clutter['candidates'])
    overlay=Image.alpha_composite(Image.new('RGBA',prepared.size,'white'),prepared).convert('RGB')
    draw=ImageDraw.Draw(overlay)
    for item in text:
        points=[tuple(point) for point in item['polygon']];draw.line(points+[points[0]],fill='#16a34a' if item['action']=='removed_detached_dimension' else '#df930e',width=3)
    for item in clutter['candidates']:
        if item['requires_attention']:draw.rectangle(item['box_pixels'],outline='#ef4444',width=3)
    overlay.save(output/'input_overlay.png')
    package=Path(rapidocr_onnxruntime.__file__).parent
    weights={path.name:sha(path) for path in sorted((package/'models').glob('*.onnx'))}
    summary={**decision,'method':method,'native_roi_size':list(prepared.size),'mask_metrics':metrics,
        'text_cleanup':text,'removed_alpha_pixels':int((np.asarray(erase_mask)>0).sum()),
        'ocr':{'model':'RapidOCR ONNX Runtime 1.4.4','seconds':round(ocr_seconds,3),'cpu_only':True,'weight_sha256':weights},
        'clutter':clutter,'duration_seconds':round(time.monotonic()-started,3),
        'source_sha256':sha(Path(args.source)),'prepared_sha256':sha(Path(args.prepared)),
        'input_sha256':sha(Path(args.input)),'cleaned_sha256':sha(output/'cleaned.png'),
        'worker_revision':sha(Path(__file__)),'rules_revision':sha(ROOT/'services/workers/input_preflight_rules.py'),
        'original_rgb_preserved':bool(np.array_equal(np.asarray(cleaned)[:,:,:3],np.asarray(prepared)[:,:,:3])),
        'hidden_surface_completion':False,'offline':True}
    write(output/'input_quality.json',summary)
    marker=ROOT/'.models/input-preflight/runtime.json';marker.parent.mkdir(exist_ok=True)
    previous={}
    try:previous=json.loads(marker.read_text(encoding='utf-8'))
    except (OSError,ValueError):pass
    write(marker,{'inference_tested':True,'python':str(Path(sys.executable).resolve()),'ocr_weight_sha256':weights,
                  'clutter_inference_tested':clutter['status']=='completed' or bool(previous.get('clutter_inference_tested') and previous.get('worker_revision')==summary['worker_revision']),
                  'worker_revision':summary['worker_revision']})
    print(json.dumps({'status':summary['status'],'reasons':[r['code'] for r in summary['reasons']],
                      'removed_alpha_pixels':summary['removed_alpha_pixels'],'seconds':summary['duration_seconds']},ensure_ascii=True),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--source',required=True);parser.add_argument('--prepared',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--kind',choices=['scene','white_background','provided_alpha'],required=True);parser.add_argument('--object-label',default='')
    parser.add_argument('--presegmented',action='store_true');parser.add_argument('--keep-background',action='store_true');parser.add_argument('--skip-clutter',action='store_true')
    args=parser.parse_args()
    try:run(args)
    except Exception as error:
        out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
        write(out/'input_preflight_failure.json',{'error_type':type(error).__name__,'error':str(error)})
        raise
