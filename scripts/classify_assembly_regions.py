"""Classify individual SAM regions locally; these crops are not new furniture tests."""
import argparse,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'


def run(args):
    import torch
    from PIL import Image,ImageDraw
    from transformers import AutoProcessor,Qwen3VLForConditionalGeneration,BitsAndBytesConfig
    from generate_partcrafter import digest,write
    source=Path(args.source);output=Path(args.output)
    if output.exists():raise ValueError('Preserve previous classifications')
    manifest=json.loads((source/'observations.json').read_text(encoding='utf-8'));product=Image.open(source/'product.png').convert('RGB')
    output.mkdir(parents=True);torch.set_num_threads(4);model_path=ROOT/'.models/assembly-vlm-qwen3-4b'
    provenance=json.loads((model_path/'provenance.json').read_text(encoding='utf-8'))
    quant=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_compute_dtype=torch.float16,bnb_4bit_use_double_quant=True)
    model=Qwen3VLForConditionalGeneration.from_pretrained(str(model_path),dtype=torch.float16,quantization_config=quant,device_map={'':0},local_files_only=True,attn_implementation='sdpa').eval()
    processor=AutoProcessor.from_pretrained(str(model_path),local_files_only=True,min_pixels=112*112,max_pixels=384*384)
    prompt='Classify the SINGLE masked furniture part. A square or rectangular throw pillow or back cushion is back_cushion. A cylindrical bolster is bolster. A seating pad is seat_cushion. A structural sofa arm is armrest. If it contains multiple parts or is unclear, choose unknown. Return only a JSON object with one key kind and one of these values: back_cushion, bolster, seat_cushion, armrest, unknown.'
    if args.context_highlight:
        prompt='Classify the SINGLE TARGET highlighted in magenta in its original furniture context. Highlight shows visible pixels only; the object may be partly occluded. Use the surrounding furniture to identify the whole target. A soft square/rectangular throw pillow or back cushion is back_cushion. A cylindrical pillow is bolster. A seating pad is seat_cushion. A structural sofa arm is armrest. If the highlight mixes parts or identity is unclear, choose unknown. Return only JSON with key kind and one value: back_cushion, bolster, seat_cushion, armrest, unknown.'
    rows=[]
    for index,part in enumerate(manifest['parts']):
        if part['kind']!='unknown':continue
        started=time.monotonic();folder=output/f'region_{index:02d}';folder.mkdir();mask_path=source/part['mask_file']
        if digest(mask_path)!=part['mask_sha256']:raise ValueError('Source region mask changed')
        alpha=Image.open(mask_path).convert('L');bounds=alpha.getbbox()
        if not bounds:raise ValueError('Empty region')
        rgba=product.convert('RGBA');rgba.putalpha(alpha);crop=rgba.crop(bounds)
        canvas=Image.new('RGBA',crop.size,'white');canvas.alpha_composite(crop);image=canvas.convert('RGB');image.save(folder/'input.png')
        if args.context_highlight:
            overlay=Image.new('RGB',product.size,'#e034ca');highlight=alpha.point(lambda p:round(p*.3));image=Image.composite(overlay,product,highlight)
            ImageDraw.Draw(image).rectangle(bounds,outline='#d020ba',width=2)
            padding=round(max(bounds[2]-bounds[0],bounds[3]-bounds[1])*.65)
            context_bounds=[max(0,bounds[0]-padding),max(0,bounds[1]-padding),min(product.width,bounds[2]+padding),min(product.height,bounds[3]+padding)]
            image=image.crop(context_bounds);image.save(folder/'input.png')
        write(output/'progress.json',{'stage':'classifying_region','source_region':index,'completed_regions':len(rows)})
        messages=[{'role':'user','content':[{'type':'image','image':image},{'type':'text','text':prompt}]}]
        inputs=processor.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt').to('cuda')
        with torch.inference_mode():generated=model.generate(**inputs,do_sample=False,max_new_tokens=80)
        raw=processor.batch_decode(generated[:,inputs['input_ids'].shape[-1]:],skip_special_tokens=True)[0]
        (folder/'raw_response.txt').write_text(raw,encoding='utf-8')
        kind='unknown';error=None
        try:
            kind=json.loads(raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())['kind']
            if kind not in('back_cushion','bolster','seat_cushion','armrest','unknown'):raise ValueError('Unsupported region kind')
        except (ValueError,TypeError,KeyError)as exc:kind='unknown';error=str(exc)
        row={'source_region':index,'source_mask_sha256':part['mask_sha256'],'source_target':part['target'],'kind':kind,
             'model_id':provenance['model_id'],'model_revision':provenance['model_revision'],'runtime_quantization':'nf4',
             'crop_input_sha256':digest(folder/'input.png'),'input_preparation':'original_context_with_target_highlight_no_inpainting'if args.context_highlight else'original_mask_pixels_on_white_no_inpainting',
             'semantic_verified':False,'error':error,'elapsed_seconds':round(time.monotonic()-started,3)}
        write(folder/'classification.json',row);rows.append(row);write(output/'classifications.json',{'source_manifest_sha256':digest(source/'observations.json'),
            'scope':'classifications_of_regions_from_one_furniture_not_independent_designs','external_image_requests':False,'regions':rows})
        del inputs,generated;torch.cuda.empty_cache();print(json.dumps(row),flush=True)
    write(output/'progress.json',{'stage':'finished','completed_regions':len(rows)})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--context-highlight',action='store_true');run(p.parse_args())
