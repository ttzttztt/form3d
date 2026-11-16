"""Reuse saved RGB/depth/masks to test geometry grouping without new inference."""
import json,sys,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
records=[]
for case in json.loads((ROOT/'experiments/semantic_parts_20261113/audit.json').read_text(encoding='utf-8')):
    if case['case']!='leather_sofa':continue
    source=ROOT/'.data/jobs'/case['job']/'semantic_scans'/case['scan_id']
    target=ROOT/'experiments/solid_parts_20261113/refined_semantic_v2'/case['case'];target.mkdir(parents=True,exist_ok=True)
    for path in source.iterdir():
        if path.suffix in ('.json','.png'):shutil.copyfile(path,target/path.name)
    raw=ROOT/'.data/jobs'/case['source_job']/'model.glb'
    with (target/'group.log').open('wb') as log:result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/build_semantic_asset.py'),'--input',str(raw),'--folder',str(target)],stdout=log,stderr=subprocess.STDOUT)
    records.append({'case':case['case'],'input':str(raw),'folder':str(target),'returncode':result.returncode})
    print(json.dumps(records[-1]),flush=True)
(ROOT/'experiments/solid_parts_20261113/refined_semantic_v2_result.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
