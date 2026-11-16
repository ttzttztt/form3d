# -*- coding: utf-8 -*-
import copy,json,sys,hashlib,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from services.api.glb_document import read_glb,selected_primitives,write_glb,compact_static
from asset_operations import append_array
from furniture_parts import replace_primitives
from supported_regions import refine_supported_regions
from semantic_asset import merge_opposite_sides,separate_cylinder_from_flat_pillow,write_style_preview,PALETTE
from semantic_mapping import map_masks
from pillow_footprint import pillow_footprint
OUT=ROOT/'experiments/semantic_refinement_20261113';records=[]
p=argparse.ArgumentParser();p.add_argument('--guided',action='store_true');args=p.parse_args()
for case in ('leather_sofa','corduroy_sofa','accent_chair'):
    folder=OUT/case;cache=np.load(folder/'evidence.npz');d=json.loads((folder/'diagnosis.json').read_text(encoding='utf-8'));vertices=cache['vertices'];faces=cache['faces'];centers=cache['centers'];normals=cache['normals'];area=cache['area']
    if args.guided:
        observation={};raw,raw_groups,_=map_masks(folder/'seat_mask_trial',centers,normals,area,vertices,evidence=observation)
    else:raw,raw_groups,observation=cache['raw_labels'],d['groups'],cache
    labels,groups,evidence=refine_supported_regions(vertices,faces,centers,area,raw,raw_groups,observation)
    diagonal=np.linalg.norm(np.ptp(vertices,axis=0));labels,groups,merged=merge_opposite_sides(labels,groups,centers,normals,area,diagonal);labels,cylinders=separate_cylinder_from_flat_pillow(labels,groups,centers,normals,area,diagonal)
    if args.guided:
        support=observation['support_views'];scores=observation['scores'];visible=observation['visible_views'];footprints=[]
        for merge in merged:
            a,b=merge['from_label']-1,merge['to_label']-1;support[b]=np.minimum(visible,support[b]+support[a]);scores[b]=np.minimum(1,scores[b]+scores[a])
        for group in groups:
            label=group['label'];ids=np.flatnonzero(labels==label);veto=(visible[ids]>=2)&(support[label-1,ids]*2<visible[ids]);labels[ids[veto]]=0
            if group['source_kind']=='pillow'and not group.get('cylinder_fit'):
                ids=np.flatnonzero(labels==label);keep,check=pillow_footprint(vertices,faces,centers,normals,area,ids)
                if check.get('flagged_area_fraction',0)<=.20:labels[ids[~keep]]=0
                else:check['applied']=False;check['reason']='large_change_needs_review'
                footprints.append({'label':label,**check})
        evidence['footprint_checks']=footprints
    groups=[g for g in groups if np.any(labels==g['label'])];records.append({'case':case,'groups':groups,'refinement':evidence,'opposite':merged,'cylinders':cylinders})
    target=folder/('guided_supported_trial'if args.guided else'supported_trial');target.mkdir(exist_ok=True);doc,binary,extra=read_glb(Path(d['source']));lookup={g['label']:g for g in groups};lookup[0]={'label':0,'source_kind':'unknown'};counters={}
    for i,g in enumerate(lookup.values()):
        kind='bolster'if g.get('cylinder_fit')else g['source_kind'];counters[kind]=counters.get(kind,0)+1;g.update(kind=kind,name={'pillow':'靠枕','seat':'坐面与主体','bolster':'圆柱抱枕'}.get(kind,'未确认区域')+' '+str(counters[kind]),id='trial_'+str(g['label']),color=PALETTE[i%len(PALETTE)]if g['label']else'#a9b0bb')
    replacements={};start=0
    from edit_asset import accessor_array
    for part,p in selected_primitives(doc,[]):
        f=accessor_array(doc,binary,p['indices']).reshape(-1,3);current=labels[start:start+len(f)];start+=len(f);made=[]
        for label in np.unique(current):
            g=lookup[int(label)];new=copy.deepcopy(p);new['indices']=append_array(doc,binary,f[current==label].ravel(),'SCALAR',5125,34963);new.setdefault('extras',{}).update(form_part_name=g['name'],form_semantic_color=g['color'],form_semantic_kind=g['kind'],form_logical_group_id=g['id'],form_group_kind='ai_semantic_instance');made.append((new,'part_'+str(start)+'_'+str(label)))
        replacements.setdefault(part['node'],{})[part['primitive']]=made
    replace_primitives(doc,replacements);binary=compact_static(doc,binary);write_glb(target/'model.glb',doc,binary,extra);write_style_preview(doc,binary,extra,target/'style.glb');present=[lookup[int(x)]for x in np.unique(labels)]
    (target/'manifest.json').write_text(json.dumps({'operation':{'groups':present},'refinement':evidence},ensure_ascii=False,indent=2),encoding='utf-8');np.savez_compressed(target/'assignments.npz',labels=labels)
    (OUT/('guided_supported_trials.json'if args.guided else'supported_trials.json')).write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'case':case,'groups':[(g['label'],g['kind'])for g in present],'refinement':evidence},ensure_ascii=False),flush=True)
