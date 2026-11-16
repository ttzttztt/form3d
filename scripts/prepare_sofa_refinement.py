# -*- coding: utf-8 -*-
"""Isolated source copies and normalized diagnostic projections; no semantic labels."""
import copy,hashlib,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from PIL import Image,ImageDraw
from services.api.store import Store,now
from services.api.glb_document import read_glb,parts_catalog
from furniture_parts import primitive_data
OUT=ROOT/'experiments/sofa_refinement_20261113';OUT.mkdir(exist_ok=True);store=Store(ROOT/'.data')
CASES=[('leather_sofa','11c5d7496508427cad48c22c5959f53b'),('corduroy_sofa','0ee3d49864e543bb92a66ad9cf19115b'),('accent_chair','6be16d93f7544ac79c5f09cb3be507fa'),('round_table','b51be48468e54d0680a542174c0c873b')]
records=json.loads((OUT/'cases.json').read_text(encoding='utf-8')) if (OUT/'cases.json').exists() else []
for label,sid in CASES:
    record=next((r for r in records if r['case']==label),None)
    if record is None:
        job=copy.deepcopy(store.job(sid));identity=uuid.uuid4().hex
        for k in ('asset_versions','current_asset_version','review'):job.pop(k,None)
        job.update(id=identity,name='坐垫边界与厚度复测 · '+label,status='awaiting_review',stage='sofa_refinement_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=sid)
        for k,v in list(job.items()):
            if isinstance(v,str):job[k]=v.replace(sid,identity)
        folder=store.root/'jobs'/identity;folder.mkdir();source=store.root/'jobs'/sid/'model.glb';shutil.copyfile(source,folder/'model.glb');store.create_job(job,'',identity)
        record={'case':label,'source_job':sid,'job':identity,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()};records.append(record)
    doc,binary,_=read_glb(store.root/'jobs'/sid/'model.glb');part=parts_catalog(doc)[0];p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
    _,f,w,c,n,a=primitive_data(doc,binary,part,p);low=w.min(0);extent=np.ptp(w,axis=0);q=(c-low)/extent
    image=Image.new('RGB',(1440,510),'white');draw=ImageDraw.Draw(image)
    for index,(ax,ay,depth,title) in enumerate([(0,1,2,'XY view from +Z'),(2,1,0,'ZY view from +X'),(0,2,1,'XZ view from +Y')]):
        x0=index*480+45;y0=450;size=400
        px=np.clip((q[:,ax]*size).astype(int),0,size);py=np.clip(((1-q[:,ay])*size).astype(int),0,size)
        order=np.lexsort((-q[:,depth],py*(size+1)+px));keys=py[order]*(size+1)+px[order];keep=np.r_[True,keys[1:]!=keys[:-1]];ids=order[keep]
        light=np.clip(.48+.42*n[ids,depth],.15,.95)
        for j,l in zip(ids,light):
            value=int(l*255);draw.rectangle((x0+int(px[j]),y0-size+int(py[j]),x0+int(px[j])+1,y0-size+int(py[j])+1),fill=(value,value,value))
        for t in np.arange(0,1.01,.1):
            xx=x0+int(t*size);yy=y0-int(t*size);draw.line((xx,y0-size,xx,y0),fill=(210,225,240),width=1);draw.line((x0,yy,x0+size,yy),fill=(210,225,240),width=1);draw.text((xx-5,y0+8),f'{t:.1f}',fill='black');draw.text((x0-28,yy-5),f'{t:.1f}',fill='black')
        draw.text((x0,12),label+' '+title,fill='black')
    image.save(OUT/(label+'_coordinates.png'));record['source_bounds_world']=[low.tolist(),(low+extent).tolist()];record['source_part_id']=part['id']
(OUT/'cases.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(records,ensure_ascii=False,indent=2))
