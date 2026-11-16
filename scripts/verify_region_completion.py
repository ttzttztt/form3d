# -*- coding: utf-8 -*-
"""Small regression check connecting the new groups to the existing solid worker."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.glb_document import read_glb,parts_catalog,write_glb,compact_static
from reconstruct_parts import reconstruct_parts
OUT=ROOT/'experiments/semantic_refinement_20261113';records=[]
for case,name in [('leather_sofa','圆柱抱枕 1'),('corduroy_sofa','靠枕 5')]:
    source=OUT/'delivery'/case/'model.glb';doc,binary,extra=read_glb(source);ids=[p['id']for p in parts_catalog(doc)if p['name']==name];record={'case':case,'name':name};records.append(record)
    try:
        result=reconstruct_parts(doc,binary,{'part_ids':ids});folder=OUT/'completion_links'/case;folder.mkdir(parents=True,exist_ok=True);write_glb(folder/'model.glb',doc,compact_static(doc,binary),extra);record.update(operation=result,model=str(folder/'model.glb'))
    except ValueError as exc:record['rejected_reason']=str(exc)
    (OUT/'completion_links.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=False),flush=True)
