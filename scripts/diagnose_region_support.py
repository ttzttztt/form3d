# -*- coding: utf-8 -*-
"""Trace the saved multiview observations separately from propagated labels."""
import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from services.api.glb_document import read_glb,selected_primitives
from furniture_parts import primitive_data
from semantic_mapping import map_masks
from semantic_asset import refine_regions,merge_opposite_sides,separate_cylinder_from_flat_pillow
OUT=ROOT/'experiments/semantic_refinement_20261113';OUT.mkdir(exist_ok=True);records=[]
for case in json.loads((ROOT/'experiments/semantic_parts_20261113/audit.json').read_text(encoding='utf-8')):
    source=ROOT/'.data/jobs'/case['source_job']/'model.glb';folder=ROOT/'.data/jobs'/case['job']/'semantic_scans'/case['scan_id'];target=OUT/case['case'];target.mkdir(exist_ok=True)
    doc,binary,_=read_glb(source);vs=[];fs=[];cs=[];ns=[];aa=[];offset=0
    for part,p in selected_primitives(doc,[]):
        _,f,w,c,n,a=primitive_data(doc,binary,part,p);vs.append(w);fs.append(f+offset);offset+=len(w);cs.append(c);ns.append(n);aa.append(a)
    vertices=np.vstack(vs);faces=np.vstack(fs);centers=np.vstack(cs);normals=np.vstack(ns);area=np.concatenate(aa);evidence={}
    raw,groups,diagnostics=map_masks(folder,centers,normals,area,vertices,evidence=evidence)
    labels,propagation=refine_regions(vertices,faces,centers,area,raw.copy(),copy.deepcopy(groups));labels,merged,opposite=merge_opposite_sides(labels,copy.deepcopy(groups),centers,normals,area,np.linalg.norm(np.ptp(vertices,axis=0)));final,cylinders=separate_cylinder_from_flat_pillow(labels.copy(),merged,centers,normals,area,np.linalg.norm(np.ptp(vertices,axis=0)))
    np.savez_compressed(target/'evidence.npz',vertices=vertices,faces=faces,centers=centers,normals=normals,area=area,refined=labels,final=final,**evidence)
    record={'case':case['case'],'source':str(source),'scan':str(folder),'groups':groups,'diagnostics':diagnostics,'opposite':opposite,'cylinders':cylinders,'propagation':propagation,'stats':[]};records.append(record)
    for g in groups:
        label=g['label'];r=raw==label;f=final==label;support=evidence['support_views'][label-1];visible=evidence['visible_views']
        record['stats'].append({'label':label,'kind':g['source_kind'],'raw_area':float(area[r].sum()),'final_area':float(area[f].sum()),'grown_area':float(area[f&~r].sum()),'final_multiview_supported_area':float(area[f&(support>=2)].sum()),'final_contradicted_visible_area':float(area[f&(support*2<visible)].sum()),'raw_bounds':np.array([centers[r].min(0),centers[r].max(0)]).tolist(),'final_bounds':np.array([centers[f].min(0),centers[f].max(0)]).tolist() if f.any() else None})
    (target/'diagnosis.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');(OUT/'diagnosis.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'case':case['case'],'stats':record['stats']},ensure_ascii=False),flush=True)
