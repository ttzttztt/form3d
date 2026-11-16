"""Exercise real production reconstruction and keep every rejected group's reason."""
import json,sys,time,hashlib,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.glb_document import read_glb,write_glb,parts_catalog,compact_static
from reconstruct_parts import reconstruct_parts
from semantic_asset import write_style_preview
p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,default=ROOT/'experiments/semantic_parts_20261113');p.add_argument('--output-root',type=Path,default=ROOT/'experiments/solid_parts_20261113');p.add_argument('--cases',nargs='+',default=['leather_sofa','corduroy_sofa','accent_chair']);args=p.parse_args()
out=args.output_root;out.mkdir(parents=True,exist_ok=True);records=[]
if (out/'production_audit.json').exists():raise SystemExit('Existing measured run kept; choose a new output directory')
for case in args.cases:
    folder=out/case;folder.mkdir(exist_ok=True)
    source=args.source_root/case/'model.glb'
    doc,binary,extra=read_glb(source);started=time.monotonic()
    record={'case':case,'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()};records.append(record)
    try:
        operation=reconstruct_parts(doc,binary,{'part_ids':[p['id'] for p in parts_catalog(doc)]});binary=compact_static(doc,binary)
        write_glb(folder/'model.glb',doc,binary,extra);write_style_preview(doc,binary,extra,folder/'style.glb')
        manifest={'operation':operation,'source_sha256':record['source_sha256'],'model_sha256':hashlib.sha256((folder/'model.glb').read_bytes()).hexdigest(),'appearance_review':'unreviewed'}
        (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');record.update(operation=operation,output=str(folder/'model.glb'))
    except Exception as exc:record['error']=repr(exc)
    record['seconds']=round(time.monotonic()-started,3);(out/'production_audit.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=False),flush=True)
