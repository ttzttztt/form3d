import copy,json,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api.store import Store,now
store=Store(ROOT/'.data');sid='b51be48468e54d0680a542174c0c873b';job=copy.deepcopy(store.job(sid));identity=uuid.uuid4().hex
for k in ('asset_versions','current_asset_version','review'):job.pop(k,None)
job.update(id=identity,name='Cut preview commit UI check',status='awaiting_review',stage='sofa_refinement_ui',created_at=now(),updated_at=now(),events=[],review_status='pending',test_clone_of=sid)
for k,v in list(job.items()):
    if isinstance(v,str):job[k]=v.replace(sid,identity)
folder=store.root/'jobs'/identity;folder.mkdir();shutil.copyfile(store.root/'jobs'/sid/'model.glb',folder/'model.glb');store.create_job(job,'',identity)
(ROOT/'experiments/sofa_refinement_20261113/ui_commit_case.json').write_text(json.dumps({'job':identity}),encoding='utf-8');print(identity)
