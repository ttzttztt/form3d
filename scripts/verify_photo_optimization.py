"""Independently inspect actual outputs and exact-byte adoption; no accuracy claim."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.glb_document import read_glb,parts_catalog
from services.api.geometry import validate_glb
from services.api.store import Store
from services.api.part_regeneration import digest
from edit_asset import accessor_array,node_world_matrices
from replace_generated_part import selected_group,cushion_slot
from reconstruct_parts import intersections

out=ROOT/'experiments/photo_guided_parts_20261113';store=Store(ROOT/'.data')
cases=json.loads((out/'cases.json').read_text(encoding='utf-8'));rows=[];files=[]

def signatures(path):
    doc,binary,_=read_glb(path);world=node_world_matrices(doc);result={}
    for part in parts_catalog(doc):
        primitive=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
        chunks=[world[part['node']].tobytes(),part['material_signature'].encode()]
        for key,index in sorted(primitive['attributes'].items()):chunks.extend([key.encode(),accessor_array(doc,binary,index).tobytes()])
        if'indices'in primitive:chunks.append(accessor_array(doc,binary,primitive['indices']).tobytes())
        result[part['id']]=hashlib.sha256(b''.join(chunks)).hexdigest()
    return result

for case in cases:
    ui=json.loads((out/(case['case']+'_ui.json')).read_text(encoding='utf-8'));assert not ui.get('failure'),ui.get('failure')
    folder=store.root/'jobs'/case['job'];task=folder/'part_regenerations'/ui['task'];state=json.loads((task/'status.json').read_text(encoding='utf-8'))
    assert digest(folder/'model.glb')==digest(ROOT/'experiments'/case['snapshot'])
    row={'case':case['case'],'job':case['job'],'task':ui['task'],'status':state['status'],'original_snapshot_unchanged':True,'appearance_accepted':False,'ui_checks':len(ui['checks'])}
    if state['status']=='ready':
        ready=json.loads((task/'ready.json').read_text(encoding='utf-8'));manifest=json.loads((task/'preview/manifest.json').read_text(encoding='utf-8'))
        assert all(digest(task/name)==sha for name,sha in ready['photo_evidence_sha256'].items())
        assert manifest['operation']['photo_checks']==json.loads((task/'checks.json').read_text(encoding='utf-8'))
        before=signatures(folder/'model.glb');after=signatures(task/'preview/model.glb');unchanged={k:v for k,v in before.items()if k not in case['part_ids']}
        assert {key:after.get(key)for key in unchanged}==unchanged
        doc,binary,_=read_glb(task/'preview/model.glb');ids=[p['id']for p in parts_catalog(doc)if p.get('logical_group_id')in manifest['operation']['part_group_ids']]
        _,_,mesh=selected_group(doc,binary,ids);count=intersections(mesh)
        assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0 and len(mesh.split(only_watertight=False))==1 and count==0
        row.update(unrelated_primitives_unchanged=len(unchanged),part_triangles=len(mesh.faces),closed_single_component=True,self_intersection_faces=count,logical_part_primitives=len(ids),checks=manifest['operation']['photo_checks'],bound_photo_evidence_files=len(ready['photo_evidence_sha256']))
        if ui.get('saved_version'):
            saved=folder/'assets'/ui['saved_version']/'model.glb';material=folder/'assets'/ui['material_version']/'model.glb'
            assert saved.read_bytes()==(task/'preview/model.glb').read_bytes()
            a={p['id']:p['material_signature']for p in parts_catalog(read_glb(saved)[0])};b={p['id']:p['material_signature']for p in parts_catalog(read_glb(material)[0])}
            assert {k for k in a if a[k]!=b[k]}==set(ids)
            row.update(exact_preview_adoption=True,material_changes_only_complete_target_group=True)
            files.extend([saved,material])
        else:assert store.job(case['job']).get('current_asset_version','original')=='original'
        files.extend(task/'preview'/name for name in('model.glb','part.glb','diagnostic.glb'))
        files.append(out/(case['case']+'_download.glb'))
    else:
        assert store.job(case['job']).get('current_asset_version','original')=='original'
        row['source_version_preserved']=True
    if state.get('generated_valid'):files.append(task/'generated/model.glb')
    rows.append(row)

# A third real furniture asset: read-only refusal, never counted as a repair.
chair=ROOT/'experiments/semantic_refinement_20261113/delivery/accent_chair/model.glb';before=digest(chair);doc,binary,_=read_glb(chair)
ids=[p['id']for p in parts_catalog(doc)if p.get('semantic_kind')=='seat']
try:
    _,_,source=selected_group(doc,binary,ids);cushion_slot(source)
except ValueError as exc:chair_result={'case':'accent_chair','status':'refused','reason':str(exc),'read_only':True,'file_unchanged':digest(chair)==before}
else:raise AssertionError('Expected known open chair source to be refused')
(out/'additional_chair_guard.json').write_text(json.dumps(chair_result,ensure_ascii=False,indent=2),encoding='utf-8')

# The first inference is retained even though its old-projection task was cancelled.
raw=store.root/'jobs'/cases[0]['job']/'part_regenerations/d28da45342a242ed9558f2f2df91da2a/generated/model.glb'
if raw.exists():files.append(raw)
reports=[]
for path in files:
    report=validate_glb(path);assert report['status']=='pass',report
    reports.append({'file':str(path.relative_to(ROOT)).replace('\\','/'),'sha256':digest(path),'errors':report['errors'],'warnings':report['warnings']})
result={'cases':rows,'additional_chair_guard':chair_result,'file_checks':len(reports),'unique_file_contents':len({r['sha256']for r in reports}),'files':reports,'physical_accuracy_verified':False}
(out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in result.items()if k!='files'},ensure_ascii=False))
