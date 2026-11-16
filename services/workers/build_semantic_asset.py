import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'services/workers')]
from services.api.glb_document import read_glb,write_glb,compact_static
from semantic_asset import create_semantic_asset,write_style_preview
p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--folder',required=True);a=p.parse_args();source=Path(a.input);folder=Path(a.folder);doc,binary,extra=read_glb(source);operation=create_semantic_asset(doc,binary,folder);binary=compact_static(doc,binary);write_glb(folder/'model.glb',doc,binary,extra);write_style_preview(doc,binary,extra,folder/'style.glb');manifest={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'model_sha256':hashlib.sha256((folder/'model.glb').read_bytes()).hexdigest(),'positions_unchanged':True,'operation':operation};(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(operation,ensure_ascii=False))
