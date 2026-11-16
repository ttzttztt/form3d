# -*- coding: utf-8 -*-
import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from pillow_neck_cut import pillow_neck_cut
from services.api.glb_document import read_glb,write_glb,selected_primitives,compact_static
from furniture_parts import replace_primitives
from asset_operations import append_array
from semantic_asset import write_style_preview
from edit_asset import accessor_array
OUT=ROOT/'experiments/semantic_refinement_20261113';records=[]
for case in ('leather_sofa','corduroy_sofa'):
    root=OUT/case;cache=np.load(root/'evidence.npz');original=root/'saved_masks';manifest=json.loads((original/'manifest.json').read_text(encoding='utf-8'));labels=np.load(original/'assignments.npz')['labels'];top=json.loads((root/'seat_mask_trial/geometry_prompts.json').read_text())['seat_top_source_units'];checks=[]
    for group in manifest['operation']['groups']:
        if group['kind']!='pillow':continue
        ids=np.flatnonzero(labels==group['label']);keep,evidence=pillow_neck_cut(cache['vertices'],cache['faces'],cache['centers'],cache['normals'],cache['area'],ids,top);labels[ids[~keep]]=0;checks.append({'label':group['label'],'name':group['name'],**evidence})
    target=root/'neck_trial';target.mkdir(exist_ok=True);doc,binary,extra=read_glb(Path(json.loads((root/'diagnosis.json').read_text(encoding='utf-8'))['source']));replacements={};start=0;lookup={g['label']:g for g in manifest['operation']['groups']}
    for part,p in selected_primitives(doc,[]):
        f=accessor_array(doc,binary,p['indices']).reshape(-1,3);current=labels[start:start+len(f)];start+=len(f);made=[]
        for label in np.unique(current):
            g=lookup[int(label)];new=copy.deepcopy(p);new['indices']=append_array(doc,binary,f[current==label].ravel(),'SCALAR',5125,34963);new.setdefault('extras',{}).update(form_part_name=g['name'],form_semantic_color=g['color'],form_semantic_kind=g['kind'],form_logical_group_id=g['id']);made.append((new,'neck_'+str(start)+'_'+str(label)))
        replacements.setdefault(part['node'],{})[part['primitive']]=made
    replace_primitives(doc,replacements);binary=compact_static(doc,binary);write_glb(target/'model.glb',doc,binary,extra);write_style_preview(doc,binary,extra,target/'style.glb');manifest['neck_checks']=checks;(target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');np.savez_compressed(target/'assignments.npz',labels=labels);records.append({'case':case,'checks':checks});(OUT/'neck_trials.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(records[-1],ensure_ascii=False),flush=True)
