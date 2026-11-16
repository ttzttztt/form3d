"""Additional real pillow instances, automatically matched without hand-picked refs."""
import json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.glb_document import read_glb,parts_catalog
base=ROOT/'experiments/photo_guided_parts_20261113/corduroy_auto_v1';context=json.loads((base/'context.json').read_text())
doc,_,_=read_glb(context['source']);rows=[]
for name in('靠枕 2','靠枕 3','靠枕 4','靠枕 5'):
    folder=base.parent/('corduroy_'+name[-1]+'_auto');folder.mkdir(exist_ok=True)
    if not(folder/'references').exists():shutil.copytree(base/'references',folder/'references')
    if not(folder/'camera.json').exists():shutil.copyfile(base/'camera.json',folder/'camera.json')
    data={**context,'part_ids':[p['id']for p in parts_catalog(doc)if p['name']==name]};(folder/'context.json').write_text(json.dumps(data),encoding='utf-8')
    command=[str(ROOT/'.venv-hunyuan/Scripts/python.exe'),'-X','utf8',str(ROOT/'scripts/auto_part_optimization.py'),'--folder',str(folder)]
    with(folder/'analyze.log').open('wb')as log:r=subprocess.run(command+['--stage','analyze'],stdout=log,stderr=subprocess.STDOUT)
    if r.returncode:rows.append({'part':name,'analysis_failed':True});continue
    plan=json.loads((folder/'analysis.json').read_text(encoding='utf-8'));row={'part':name,'route':plan['route'],'association':plan['photo_association']}
    if plan['route']=='photo_pillow':
        with(folder/'optimize.log').open('wb')as log:r=subprocess.run(command+['--stage','optimize'],stdout=log,stderr=subprocess.STDOUT)
        row['optimization_returncode']=r.returncode
        if(folder/'checks.json').exists():row['checks']=json.loads((folder/'checks.json').read_text(encoding='utf-8'))
    rows.append(row);(base.parent/'additional_pillows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');print(name,plan['route'],row.get('optimization_returncode'),flush=True)
