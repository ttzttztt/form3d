# -*- coding: utf-8 -*-
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from services.api.glb_document import read_glb,parts_catalog
from furniture_parts import primitive_data
from semantic_mapping import map_masks,project_visible
def main(source,folder):
    source=Path(source);folder=Path(folder);doc,binary,_=read_glb(source);part=parts_catalog(doc)[0];p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
    _,f,v,c,n,a=primitive_data(doc,binary,part,p)
    if not (folder/'detections.json').exists():
        for view in json.loads((folder/'views.json').read_text()):
            x,y,valid,error=project_visible(c,{**view,'depth_path':folder/view['depth']});print(view['index'],int(valid.sum()),float(np.median(error)),flush=True)
        return
    labels,groups,diagnostics=map_masks(folder,c,n,a,v);np.savez_compressed(folder/'labels.npz',labels=labels);(folder/'mapping.json').write_text(json.dumps({'groups':groups,'diagnostics':diagnostics},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'groups':groups,'diagnostics':diagnostics},ensure_ascii=False,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--folder',required=True);a=p.parse_args();main(a.input,a.folder)
