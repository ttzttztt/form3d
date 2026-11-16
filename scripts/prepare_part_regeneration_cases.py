"""Create isolated test jobs; leave original generation and edit history intact."""
import copy,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
from services.api.geometry import validate_glb,inspect_glb
from services.api.glb_document import read_glb,parts_catalog

store=Store(ROOT/'.data');out=ROOT/'experiments/part_regeneration_20261113';records=[]
if (out/'cases.json').exists():raise SystemExit('Existing test cases preserved')
cases=[('corduroy_pillow','0ee3d49864e543bb92a66ad9cf19115b','semantic_refinement_20261113/delivery/corduroy_sofa/model.glb','靠枕 1','pillow'),
       ('leather_cushion','11c5d7496508427cad48c22c5959f53b','solid_parts_20261113/delivery/leather_sofa/model.glb','坐面与主体 1','cushion')]
for name,source_job,snapshot,part_name,kind in cases:
    identity=uuid.uuid4().hex;job=copy.deepcopy(store.job(source_job))
    job.update(id=identity,name='部件重新生成试验 · '+('靠枕'if kind=='pillow'else'坐垫'),status='awaiting_review',stage='part_regeneration_test',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=source_job)
    for key in('asset_versions','current_asset_version','quality_report'):job.pop(key,None)
    job['model_url']=f'/api/jobs/{identity}/files/model.glb'
    folder=store.root/'jobs'/identity;folder.mkdir();shutil.copyfile(ROOT/'experiments'/snapshot,folder/'model.glb')
    validation=validate_glb(folder/'model.glb');job['metrics']=inspect_glb(folder/'model.glb');job['validation']=validation
    store.create_job(job,'',identity)
    parts=parts_catalog(read_glb(folder/'model.glb')[0]);ids=[p['id']for p in parts if p['name']==part_name]
    records.append({'case':name,'source_job':source_job,'job':identity,'part_name':part_name,'part_ids':ids,'kind':kind,'reference_automatic_success':kind=='pillow','appearance_review':'unreviewed'})
    print(identity,flush=True)
(out/'cases.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
