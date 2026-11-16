# -*- coding: utf-8 -*-
import argparse,json,sys,shutil,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/semantic_refinement_20261113';p=argparse.ArgumentParser();p.add_argument('--variant',choices=['saved_masks','pillow_masks'],required=True);a=p.parse_args();records=[]
for case in ('leather_sofa','corduroy_sofa','accent_chair'):
    root=OUT/case;d=json.loads((root/'diagnosis.json').read_text(encoding='utf-8'));scan=root/'pillow_mask_trial'if a.variant=='pillow_masks'and case!='accent_chair'else Path(d['scan']);target=root/a.variant
    if target.exists():raise SystemExit('Existing experiment kept: '+str(target))
    target.mkdir()
    for file in scan.iterdir():
        if file.suffix in('.png','.json'):shutil.copyfile(file,target/file.name)
    with (target/'group.log').open('wb')as log:r=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/build_semantic_asset.py'),'--input',d['source'],'--folder',str(target)],stdout=log,stderr=subprocess.STDOUT)
    record={'case':case,'source':d['source'],'source_sha256':hashlib.sha256(Path(d['source']).read_bytes()).hexdigest(),'variant':a.variant,'returncode':r.returncode,'folder':str(target)};records.append(record)
    if r.returncode==0:
        op=json.loads((target/'manifest.json').read_text(encoding='utf-8'))['operation'];record.update(groups=[{'name':g['name'],'kind':g['kind'],'faces':g['faces'],'label':g['label']}for g in op['groups']],unconfirmed_area_fraction=op['propagation']['unassigned_area_fraction'])
    (OUT/(a.variant+'_runs.json')).write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=False),flush=True)
