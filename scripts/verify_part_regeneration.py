"""Independent file, neighbour and material checks on real generated artifacts."""
import hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.tools/geometry_extra')]
from services.api.glb_document import read_glb,parts_catalog
from services.api.geometry import validate_glb
from edit_asset import accessor_array,node_world_matrices
from replace_generated_part import selected_group

OUT=ROOT/'experiments/part_regeneration_20261113'
ui=json.loads((OUT/'ui_results.json').read_text(encoding='utf-8'))
assert not ui.get('failure'),ui.get('failure')
case=next(c for c in json.loads((OUT/'cases.json').read_text(encoding='utf-8'))if c['case']=='corduroy_pillow')
job=ROOT/'.data/jobs'/case['job'];task=job/'part_regenerations'/ui['regeneration_id']

def signatures(path):
    doc,binary,_=read_glb(path);world=node_world_matrices(doc);result={}
    for part in parts_catalog(doc):
        p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
        chunks=[world[part['node']].tobytes(),part['material_signature'].encode()]
        for key,index in sorted(p['attributes'].items()):chunks.extend([key.encode(),accessor_array(doc,binary,index).tobytes()])
        if'indices'in p:chunks.append(accessor_array(doc,binary,p['indices']).tobytes())
        result[part['id']]=hashlib.sha256(b''.join(chunks)).hexdigest()
    return result

before=signatures(job/'model.glb');after=signatures(task/'preview/model.glb')
unrelated={key:value for key,value in before.items()if key not in case['part_ids']}
assert {key:after.get(key)for key in unrelated}==unrelated
adopted=job/'assets'/ui['saved_version']/'model.glb'
assert adopted.read_bytes()==(task/'preview/model.glb').read_bytes()
doc,binary,_=read_glb(adopted);_,_,part=selected_group(doc,binary,case['part_ids'])
assert part.is_watertight and part.is_winding_consistent and len(part.split())==1
material=job/'assets'/ui['material_version']/'model.glb'
a={p['id']:p['material_signature']for p in parts_catalog(doc)}
b={p['id']:p['material_signature']for p in parts_catalog(read_glb(material)[0])}
assert {key for key in a if a[key]!=b[key]}==set(case['part_ids'])

files=[OUT/'corduroy_pillow/generated_v1/model.glb',OUT/'leather_cushion/generated_trial_v1/model.glb',OUT/'browser_regenerated_pillow.glb',adopted,material,task/'generated/model.glb']
for folder in [OUT/'corduroy_pillow/replacement_v1',OUT/'leather_cushion/replacement_surface_only_trial',OUT/'leather_cushion/replacement_outline_trial_v2',task/'preview']:
    files.extend(folder/name for name in('model.glb','part.glb','diagnostic.glb'))
reports=[]
for path in files:
    report=validate_glb(path)
    assert report['status']=='pass',report
    reports.append({'path':str(path.relative_to(ROOT)).replace('\\','/'),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'status':report['status'],'errors':report['errors'],'warnings':report['warnings']})

result={'file_checks':len(reports),'unique_glb_contents':len({r['sha256']for r in reports}),'glbs':reports,
        'unrelated_primitive_count':len(unrelated),'unrelated_attributes_indices_world_transforms_materials_unchanged':True,
        'adopted_exact_preview_bytes':True,'material_changes_only_target_group':True,
        'regenerated_part_closed_single_component':True,'appearance_acceptance':False,
        'scope':'technical checks, not product resemblance or hidden-shape accuracy'}
(OUT/'independent_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({key:value for key,value in result.items()if key!='glbs'},ensure_ascii=False))
