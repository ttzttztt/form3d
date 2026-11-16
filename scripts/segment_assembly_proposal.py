"""Ground whole-part VLM proposals using SAM, preserving image coordinates."""
import argparse,gc,hashlib,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.tools/SAM2')]
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'


def run(args):
    import cv2,numpy as np,torch
    from PIL import Image,ImageDraw
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    from services.api.assembly_planning import plan_from_image_observations
    from generate_partcrafter import write,digest
    from detect_semantic_views import box_iou
    from scipy.ndimage import binary_fill_holes
    folder=Path(args.output)
    if folder.exists():raise ValueError('Use a fresh output directory; previous masks are evidence')
    proposal_path=Path(args.proposal);proposal=json.loads(proposal_path.read_text(encoding='utf-8'))
    source=Path(args.input)
    if proposal['status']!='proposal_ready' or proposal['input_sha256']!=digest(source):raise ValueError('Semantic proposal and original image do not match')
    original=Image.open(source).convert('RGBA');width,height=original.size
    torch.set_num_threads(4);started=time.monotonic();folder.mkdir(parents=True)
    predictor=SAM2ImagePredictor(build_sam2('configs/sam2.1/sam2.1_hiera_t.yaml',str(ROOT/'.models/sam2.1-hiera-tiny/sam2.1_hiera_tiny.pt'),device='cuda',apply_postprocessing=False),max_hole_area=0,max_sprinkle_area=0)
    results=[]
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
        for object_index,furniture in enumerate(proposal['furniture']):
            location=folder/f'object_{object_index:02d}';location.mkdir()
            whole_box=np.asarray(furniture['bbox'])*[width/1000,height/1000,width/1000,height/1000]
            pad=round(max(width,height)*.015)
            crop_box=[max(0,int(whole_box[0])-pad),max(0,int(whole_box[1])-pad),min(width,int(whole_box[2])+pad),min(height,int(whole_box[3])+pad)]
            crop=original.crop(crop_box);canvas=Image.new('RGBA',crop.size,'white');canvas.alpha_composite(crop);product=canvas.convert('RGB');product.save(location/'product.png')
            predictor.set_image(np.array(product))
            shifted=whole_box-np.array(crop_box[:2]*2)
            masks,scores,_=predictor.predict(box=shifted.astype(np.float32),multimask_output=False)
            if float(scores[0])<.65:results.append({'object':object_index,'status':'needs_evidence','reason':'uncertain_whole_mask'});continue
            whole=np.asarray(masks[0])>0
            if whole.sum()<300:results.append({'object':object_index,'status':'needs_evidence','reason':'empty_whole_mask'});continue
            # Provided alpha is additional foreground evidence; do not restore
            # a background pixel simply because a semantic box includes it.
            if crop.getchannel('A').getextrema()[0]<128:whole &= np.asarray(crop.getchannel('A'))>128
            inputs=[]
            for part in furniture.get('parts',[]):
                box=np.asarray(part['bbox'])*[width/1000,height/1000,width/1000,height/1000]-np.array(crop_box[:2]*2)
                inputs.append({**part,'box':box})
            accepted=[];rejected=[]
            for ordinal,item in enumerate(inputs):
                box=item['box'];kind=item['kind']
                if kind not in('seat_cushion','back_cushion','bolster','backrest','armrest','frame','body','leg','tabletop','door','drawer','shelf','panel','other','unknown'):
                    rejected.append({'proposal_index':ordinal,'kind':kind,'reason':'unsupported_kind'});continue
                box=np.clip(box,[0,0,0,0],[product.width,product.height,product.width,product.height])
                if min(box[2:]-box[:2])<8:rejected.append({'proposal_index':ordinal,'kind':kind,'reason':'part_outside_instance'});continue
                if kind=='seat_cushion'and box_iou(box,shifted)>.85 and any(p['kind']in('back_cushion','bolster','backrest')for p in inputs):
                    rejected.append({'proposal_index':ordinal,'kind':kind,'reason':'seat_bbox_is_whole_furniture_with_other_parts'});continue
                variants=[(None,None)]
                for fx,fy in((.5,.35),(.5,.6)):
                    point=box[:2]+(box[2:]-box[:2])*[fx,fy];negative=[]
                    for other in inputs:
                        if other is item:continue
                        center=(other['box'][:2]+other['box'][2:])/2
                        if 0<=center[0]<product.width and 0<=center[1]<product.height and np.linalg.norm(center-point)>12:negative.append(center)
                    if kind=='seat_cushion':negative.append([point[0],max(1,min(product.height-2,box[3]-(box[3]-box[1])*.06))])
                    points=np.vstack([point,np.asarray(negative).reshape(-1,2)]).astype(np.float32)
                    variants.append((points,np.r_[1,np.zeros(len(negative),int)]))
                candidates=[]
                for points,labels in variants:
                    masks,scores,_=predictor.predict(box=box.astype(np.float32),point_coords=points,point_labels=labels,multimask_output=True)
                    for mask,score in zip(masks,scores):
                        mask=np.asarray(mask)>0
                        if score<.68 or mask.sum()<100:continue
                        # A broad "seat" box may include the whole sofa. Its
                        # mask cannot own the visible centers of other parts.
                        foreign_centers=[(other['box'][:2]+other['box'][2:])/2 for other in inputs if other is not item]
                        if any(0<=c[0]<product.width and 0<=c[1]<product.height and mask[int(c[1]),int(c[0])] for c in foreign_centers):continue
                        containment=float((mask&whole).sum()/max(mask.sum(),1))
                        bx0,by0,bx1,by1=np.rint(box).astype(int)
                        inside=float(mask[by0:by1,bx0:bx1].sum()/max(mask.sum(),1))
                        fraction=float(mask.sum()/max(whole.sum(),1))
                        limit=.48 if kind in('back_cushion','bolster')else.38 if kind=='armrest'else.85
                        if containment<.88 or inside<.82 or fraction>limit:continue
                        mask&=whole
                        if kind in('seat_cushion','back_cushion','bolster'):
                            filled=binary_fill_holes(mask)
                            if float((filled&~mask).sum()/max(filled.sum(),1))>.03:continue
                        components=cv2.connectedComponentsWithStats(mask.astype('uint8'),8)[2]
                        dominant=float(components[1:,cv2.CC_STAT_AREA].max()/max(mask.sum(),1))if len(components)>1 else 0
                        if dominant<.9:continue
                        yy,xx=np.nonzero(mask);observed_box=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)]
                        agreement=box_iou(box,observed_box)
                        if agreement<.28:continue
                        candidates.append((float(score)*.7+agreement*.3,float(score),mask,observed_box))
                if not candidates:rejected.append({'proposal_index':ordinal,'kind':kind,'bbox':item['bbox'],'reason':'no_supported_whole_part_mask'});continue
                _,quality,mask,observed_box=max(candidates,key=lambda c:c[0])
                duplicate=next((entry for entry in accepted if (mask&entry['mask']).sum()/max((mask|entry['mask']).sum(),1)>.65),None)
                if duplicate is not None:
                    duplicate['unresolved_duplicate']=True;rejected.append({'proposal_index':ordinal,'kind':kind,'reason':'two_semantic_instances_share_one_mask'});continue
                accepted.append({'proposal_index':ordinal,'kind':kind,'description':item.get('description',''),'mask':mask,'sam_quality_prediction':quality,'observed_box':observed_box,'semantic_bbox_1000':item['bbox']})
            # Visible masks for separate parts must not substantially overlap.
            # Reject the broad candidate; do not create a holed part by blindly
            # subtracting neighbors and then claiming it is a whole cushion.
            for i,left in enumerate(accepted):
                for right in accepted[i+1:]:
                    overlap=float((left['mask']&right['mask']).sum()/max(1,min(left['mask'].sum(),right['mask'].sum())))
                    if overlap>.15:
                        if left['mask'].sum()>right['mask'].sum()*2:left['unresolved_overlap']=True
                        elif right['mask'].sum()>left['mask'].sum()*2:right['unresolved_overlap']=True
                        else:left['unresolved_overlap']=True;right['unresolved_overlap']=True
            for item in accepted:
                if item.get('unresolved_overlap'):rejected.append({'proposal_index':item['proposal_index'],'kind':item['kind'],'reason':'mask_contains_another_visible_part'})
            accepted=[item for item in accepted if not item.get('unresolved_overlap')]
            records=[];overlay=np.asarray(product).copy();palette=[(233,167,49),(51,128,199),(156,94,191),(36,170,148),(225,95,116),(122,154,51)]
            for ordinal,item in enumerate(accepted):
                mask=item.pop('mask');overlay[mask]=(overlay[mask]*.6+np.asarray(palette[ordinal%len(palette)])*.4).astype('uint8')
                mask_image=Image.fromarray(mask.astype('uint8')*255);stem=hashlib.sha256(mask.tobytes()).hexdigest()[:32];file=stem+'_mask.png';mask_image.save(location/file)
                rgba=product.convert('RGBA');rgba.putalpha(mask_image);bb=mask_image.getbbox();part_box=[max(0,bb[0]-8),max(0,bb[1]-8),min(product.width,bb[2]+8),min(product.height,bb[3]+8)];rgba.crop(part_box).save(location/(stem+'_part.png'))
                xx0,yy0,xx1,yy1=item['observed_box'];target={'x':(crop_box[0]+xx0)/width,'y':(crop_box[1]+yy0)/height,'width':(xx1-xx0)/width,'height':(yy1-yy0)/height}
                records.append({**item,'kind':'unknown'if item.get('unresolved_duplicate')or item['kind']=='other'else item['kind'],'target':target,'mask_file':file,'mask_sha256':digest(location/file),'part_image_file':stem+'_part.png','part_image_sha256':digest(location/(stem+'_part.png')),'visibility':'partial','evidence_kind':'original_input'})
            overlay=Image.fromarray(overlay);draw=ImageDraw.Draw(overlay)
            for ordinal,row in enumerate(records):draw.text(row['observed_box'][:2],f'{ordinal+1}:{row["kind"]}',fill='#b71e25')
            overlay.save(location/'observations.png');Image.fromarray(whole.astype('uint8')*255).save(location/'whole_mask.png')
            foreground=product.convert('RGBA');foreground.putalpha(Image.fromarray(whole.astype('uint8')*255));foreground.save(location/'generation_input.png')
            target={'x':crop_box[0]/width,'y':crop_box[1]/height,'width':product.width/width,'height':product.height/height}
            plan=plan_from_image_observations(args.image_id,digest(source),furniture['category'],target,records)
            if rejected:plan.status='needs_evidence';plan.limitations.append(f'{len(rejected)} 个语义候选未得到可靠独立掩码，不自动忽略后生成。')
            plan.limitations.append(f'部件语义来自本地 {proposal["model_id"]} 建议，掩码来自 SAM；尚未人工或多视图确认。')
            write(location/'plan.json',plan.model_dump())
            write(location/'observations.json',{'planning_phase':'before_3d_generation','input_sha256':digest(source),'source_crop_pixels':crop_box,
                'semantic_planner':proposal['model_id'],'semantic_planner_revision':proposal['model_revision'],'semantic_proposal_sha256':digest(proposal_path),
                'segmenter':'SAM 2.1 Hiera Tiny','generation_input_sha256':digest(location/'generation_input.png'),'parts':records,'rejected':rejected,
                'expected_observed_parts':len(inputs),'whole_mask_method':'local_vlm_bbox_and_sam','scores_are_accuracy':False,'inpainting':False})
            results.append({'object':object_index,'category':furniture['category'],'expected_observed_parts':len(inputs),'segmented_parts':len(records),'rejected':len(rejected),'plan_status':plan.status,'folder':location.name})
            print(json.dumps(results[-1]),flush=True)
    write(folder/'run.json',{'objects':results,'elapsed_seconds':round(time.monotonic()-started,3),'external_image_requests':False})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--image-id',required=True);p.add_argument('--proposal',required=True);p.add_argument('--output',required=True);run(p.parse_args())
