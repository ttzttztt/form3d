# -*- coding: utf-8 -*-
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store
OUT=ROOT/'experiments/part_regeneration_20261113';OUT.mkdir(exist_ok=True);store=Store(ROOT/'.data');records=[]
for name,source,kind in [('corduroy_pillow','0ee3d49864e543bb92a66ad9cf19115b','pillow'),('leather_cushion','11c5d7496508427cad48c22c5959f53b','cushion')]:
    job=store.job(source);image=store.image(job['request']['image_id']);folder=OUT/name;folder.mkdir(exist_ok=True);command=[str(ROOT/'.venv-sam2/Scripts/python.exe'),'-X','utf8',str(ROOT/'scripts/prepare_part_reference.py'),'--input',str(store.root/image['normalized_path']),'--output',str(folder/'references'),'--kind',kind,'--target',*[str(job['request']['target'][k])for k in('x','y','width','height')]]
    with(folder/'reference.log').open('wb')as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    records.append({'case':name,'source_job':source,'kind':kind,'returncode':result.returncode});(OUT/'reference_trials.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print(json.dumps(records[-1]),flush=True)
