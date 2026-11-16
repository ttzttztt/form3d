# -*- coding: utf-8 -*-
"""Measured local open-vocabulary part detections, before choosing an integration."""
import inspect,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/semantic_parts_20261113';OUT.mkdir(exist_ok=True)
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['TOKENIZERS_PARALLELISM']='false'
import torch
from PIL import Image,ImageDraw
from transformers import AutoProcessor,AutoModelForZeroShotObjectDetection
torch.set_num_threads(4)
processor=AutoProcessor.from_pretrained(str(ROOT/'.models/grounding-dino-tiny'),local_files_only=True)
model=AutoModelForZeroShotObjectDetection.from_pretrained(str(ROOT/'.models/grounding-dino-tiny'),local_files_only=True,disable_custom_kernels=True).to('cuda').eval()
records=[]
for name in ('leather_sofa','corduroy_sofa'):
    for kind in ('source_front','reference'):
        path=ROOT/'experiments'/('sofa_refinement_20261113' if kind=='source_front' else 'multifurniture_20261113')/(name+'_'+kind+'.png')
        image=Image.open(path).convert('RGB');record={'case':name,'image':str(path),'prompts':[]};records.append(record)
        for prompt in ('seat cushion. pillow. bolster pillow. sofa frame.','pillow.','seat cushion.','cylindrical bolster pillow.'):
            start=time.monotonic();inputs=processor(images=image,text=prompt,return_tensors='pt',size={'shortest_edge':640,'longest_edge':960}).to('cuda')
            with torch.inference_mode():outputs=model(**inputs)
            threshold_key='threshold' if 'threshold' in inspect.signature(processor.post_process_grounded_object_detection).parameters else 'box_threshold'
            raw=processor.post_process_grounded_object_detection(outputs,input_ids=inputs.input_ids,text_threshold=.18,target_sizes=[(image.height,image.width)],**{threshold_key:.18})[0]
            items=[{'score':round(float(score),4),'box':[round(x,2) for x in box],'label':str(label)} for score,box,label in zip(raw['scores'].cpu().tolist(),raw['boxes'].cpu().tolist(),raw.get('text_labels',raw.get('labels',[])))]
            record['prompts'].append({'prompt':prompt,'seconds':round(time.monotonic()-start,3),'detections':items})
            print(name,kind,prompt,items,flush=True)
        canvas=image.copy();draw=ImageDraw.Draw(canvas)
        for i,item in enumerate(record['prompts'][0]['detections']):draw.rectangle(item['box'],outline=['red','blue','green','orange'][i%4],width=3);draw.text(item['box'][:2],item['label']+str(item['score']),fill='red')
        canvas.save(OUT/(name+'_'+kind+'_detections.png'));(OUT/'detector_probe.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
