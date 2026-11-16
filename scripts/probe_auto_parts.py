import json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store
from services.api.glb_document import read_glb,parts_catalog
store=Store(ROOT/'.data');out=ROOT/'experiments/photo_guided_parts_20261113'
for name,sid,snapshot,part,kind in [('corduroy','0ee3d49864e543bb92a66ad9cf19115b','semantic_refinement_20261113/delivery/corduroy_sofa/model.glb','靠枕 1','pillow'),('leather','11c5d7496508427cad48c22c5959f53b','solid_parts_20261113/delivery/leather_sofa/model.glb','坐面与主体 1','cushion')]:
    folder=out/(name+'_auto_v1');folder.mkdir(exist_ok=True)
    old=ROOT/'experiments/part_regeneration_20261113'/('corduroy_pillow'if name=='corduroy'else'leather_cushion')/'references'
    if not(folder/'references').exists():shutil.copytree(old,folder/'references')
    source=ROOT/'experiments'/snapshot;doc,_,_=read_glb(source);job=store.job(sid);image=store.image(job['request']['image_id'])
    context={'source':str(source),'part_ids':[p['id']for p in parts_catalog(doc)if p['name']==part],'kind':kind,'photo':str(store.root/image['normalized_path']),'source_folder':str(store.root/'jobs'/sid),'original_request':job['request']}
    (folder/'context.json').write_text(json.dumps(context),encoding='utf-8')
    command=[str(ROOT/'.venv-hunyuan/Scripts/python.exe'),'-X','utf8',str(ROOT/'scripts/auto_part_optimization.py'),'--folder',str(folder)]
    with(folder/'analyze.log').open('wb')as log:r=subprocess.run(command+['--stage','analyze'],stdout=log,stderr=subprocess.STDOUT)
    print(name,'analysis',r.returncode,flush=True)
