"""Independent saved-file checks, distinct from inference and appearance review."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.glb_document import read_glb,parts_catalog
from services.api.geometry import validate_glb
from edit_asset import accessor_array,node_world_matrices
from replace_generated_part import selected_group
from reconstruct_parts import intersections

out=ROOT/'experiments/soft_part_quality_20261113'
cases=json.loads((out/'cases.json').read_text(encoding='utf-8'));rows=[];files=[]
def signature(path):
    doc,binary,_=read_glb(path);worlds=node_world_matrices(doc);result={}
    for part in parts_catalog(doc):
        p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
        data=[worlds[part['node']].tobytes(),part['material_signature'].encode()]
        for key,index in sorted(p['attributes'].items()):data.extend([key.encode(),accessor_array(doc,binary,index).tobytes()])
        if'indices'in p:data.append(accessor_array(doc,binary,p['indices']).tobytes())
        result[part['id']]=hashlib.sha256(b''.join(data)).hexdigest()
    return result

for case,result_file in [(cases[0],'ui_results.json'),(cases[1],'ui_source_result.json')]:
    result=json.loads((out/result_file).read_text(encoding='utf-8'));assert not result.get('failure'),result.get('failure')
    job=ROOT/'.data/jobs'/case['job'];task=job/'part_regenerations'/result.get('regeneration_id',result.get('task'))
    before=signature(job/'model.glb');after=signature(task/'preview/model.glb')
    untouched={key:value for key,value in before.items()if key not in case['part_ids']}
    assert {key:after.get(key)for key in untouched}==untouched
    saved=job/'assets'/result['saved_version']/'model.glb';material=job/'assets'/result['material_version']/'model.glb'
    assert saved.read_bytes()==(task/'preview/model.glb').read_bytes()
    doc,binary,_=read_glb(saved);manifest=json.loads((task/'preview/manifest.json').read_text(encoding='utf-8'))
    ids=[p['id']for p in parts_catalog(doc)if p['logical_group_id']in manifest['operation']['part_group_ids']]
    _,_,part=selected_group(doc,binary,[ids[0]])
    assert part.is_watertight and part.is_winding_consistent and len(part.split())==1
    count=intersections(part);assert count==0,count
    a={p['id']:p['material_signature']for p in parts_catalog(doc)};b={p['id']:p['material_signature']for p in parts_catalog(read_glb(material)[0])}
    assert {key for key in a if a[key]!=b[key]}==set(ids)
    rows.append({'case':case['case'],'job':case['job'],'unrelated_primitives_unchanged':len(untouched),'closed_one_component':True,'self_intersection_faces':count,'exact_preview_adoption':True,'material_changes_only_selected_logical_group':True,'logical_part_primitives':len(ids),'output_triangles':len(part.faces),'appearance':'candidate_only; not physical accuracy'})
    files.extend(task/'preview'/name for name in('model.glb','part.glb','diagnostic.glb'))
    files.extend([saved,material])
    if(task/'generated/model.glb').exists():files.append(task/'generated/model.glb')
for folder in('pillow_rebuilt_v3','seat_rebuilt_v3'):
    files.extend(out/folder/name for name in('model.glb','part.glb','diagnostic.glb'))
files.extend([out/'browser_regenerated_pillow.glb',out/'browser_repaired_seat.glb',out/'mochi_pillow_generated/model.glb'])
reports=[]
for path in files:
    report=validate_glb(path);assert report['status']=='pass',report
    reports.append({'file':str(path.relative_to(ROOT)).replace('\\','/'),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'errors':report['errors'],'warnings':report['warnings']})
verification={'cases':rows,'file_checks':len(reports),'unique_file_contents':len({r['sha256']for r in reports}),'files':reports,'physical_accuracy_verified':False}
(out/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in verification.items()if k!='files'},ensure_ascii=False))
