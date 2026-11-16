"""Independent real-source clones; preserve all previous deliveries and experiments."""
import copy,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
from services.api.geometry import inspect_glb
from services.api.glb_document import read_glb,parts_catalog

out=ROOT/'experiments/photo_guided_parts_20261113';store=Store(ROOT/'.data')
if(out/'cases.json').exists():raise SystemExit('Existing cases preserved')
records=[]
for name,sid,snapshot,part,kind in [
    ('corduroy_center','0ee3d49864e543bb92a66ad9cf19115b','semantic_refinement_20261113/delivery/corduroy_sofa/model.glb','靠枕 3','pillow'),
    ('corduroy_side','0ee3d49864e543bb92a66ad9cf19115b','semantic_refinement_20261113/delivery/corduroy_sofa/model.glb','靠枕 1','pillow'),
    ('leather_seat','11c5d7496508427cad48c22c5959f53b','solid_parts_20261113/delivery/leather_sofa/model.glb','坐面与主体 1','cushion'),
]:
    identity=uuid.uuid4().hex;job=copy.deepcopy(store.job(sid))
    job.update(id=identity,name='原图约束自动部件优化 · '+part+' · '+name,status='awaiting_review',stage='photo_part_optimization_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=sid)
    for key in('asset_versions','current_asset_version','quality_report','review'):job.pop(key,None)
    job['model_url']=f'/api/jobs/{identity}/files/model.glb';folder=store.root/'jobs'/identity;folder.mkdir()
    shutil.copyfile(ROOT/'experiments'/snapshot,folder/'model.glb');job['metrics']=inspect_glb(folder/'model.glb')
    store.create_job(job,'',identity);doc,_,_=read_glb(folder/'model.glb')
    ids=[p['id']for p in parts_catalog(doc)if p['name']==part]
    assert ids,part
    records.append({'case':name,'source_job':sid,'job':identity,'part_name':part,'part_ids':ids,'kind':kind,'snapshot':snapshot,'appearance_review':'unreviewed'})
(out/'cases.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(records,ensure_ascii=False))
