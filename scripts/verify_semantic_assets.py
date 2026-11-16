# -*- coding: utf-8 -*-
"""Independent whole-instance material/movement/export checks, including open-surface facts."""
import hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx,numpy as np,trimesh
from services.api.glb_document import read_glb,parts_catalog,selected_primitives
from edit_asset import accessor_array
from furniture_parts import primitive_data
from complete_part import mesh_stats
OUT=ROOT/'experiments/semantic_parts_20261113'
def geometry(path):
    doc,binary,_=read_glb(path);groups={}
    for p,primitive in selected_primitives(doc,[]):
        _,f,w,_,_,_=primitive_data(doc,binary,p,primitive);groups.setdefault(p.get('logical_group_id') or p['id'],[]).append(trimesh.Trimesh(w,f,process=False))
    result={k:trimesh.util.concatenate(v) for k,v in groups.items()}
    for m in result.values():m.merge_vertices(digits_vertex=8,merge_tex=True,merge_norm=True)
    return result
def check_source_arrays(source,edited):
    original,ob,_=read_glb(source);doc,binary,_=read_glb(edited);lookup={p['id']:p for p in parts_catalog(original)};by_source={}
    for part,primitive in selected_primitives(doc,[]):
        parent=lookup[part['source_part_id']];old=original['meshes'][original['nodes'][parent['node']]['mesh']]['primitives'][parent['primitive']]
        assert primitive['attributes'].keys()==old['attributes'].keys()
        for key,index in old['attributes'].items():assert accessor_array(doc,binary,primitive['attributes'][key]).tobytes()==accessor_array(original,ob,index).tobytes()
        by_source.setdefault(parent['id'],[]).extend(accessor_array(doc,binary,primitive['indices']).reshape(-1,3).tolist())
    for identity,triangles in by_source.items():
        p=lookup[identity];primitive=original['meshes'][original['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];old=accessor_array(original,ob,primitive['indices']).reshape(-1,3);assert sorted(map(tuple,triangles))==sorted(map(tuple,old.tolist()))
def main():
    ui=json.loads((OUT/'ui_results.json').read_text(encoding='utf-8'));assert not ui.get('failure'),ui.get('failure');scans=json.loads((OUT/'scans.json').read_text(encoding='utf-8'));audit=[]
    with httpx.Client(base_url='http://127.0.0.1:8001',timeout=240) as client:
        for case in scans:
            if case['case']=='round_table':continue
            name=case['case'];folder=OUT/name;folder.mkdir(exist_ok=True);root=f'/api/jobs/{case["job"]}/asset';scan_id=ui['scan_id'] if name=='leather_sofa' else case['scan_id'];record={**{k:case[k] for k in ('case','job','source_job','source_sha256')},'scan_id':scan_id,'checks':[]};audit.append(record)
            catalog=client.get(root).json()
            if catalog['version']=='original':
                r=client.post(root+'/versions',json={'operation':'semantic_parts','base_version':'original','semantic_scan_id':scan_id});r.raise_for_status();catalog=r.json()
            scan_folder=ROOT/'.data/jobs'/case['job']/'semantic_scans'/scan_id
            for file in ('model.glb','style.glb','manifest.json','views.json','detections.json','assignments.npz'):
                if (scan_folder/file).exists():shutil.copyfile(scan_folder/file,folder/file)
            check_source_arrays(ROOT/'.data/jobs'/case['job']/'model.glb',folder/'model.glb');record['checks'].append('all_source_attributes_and_triangle_membership_preserved')
            baseline_version=catalog['version'];path=folder/'baseline.glb';path.write_bytes(client.get(catalog['model_url']).content);baseline=geometry(path)
            for i,group in enumerate(catalog['groups'],1):
                ids=group['part_ids'];signatures={p['id']:p['material_signature'] for p in catalog['parts']};r=client.post(root+'/versions',json={'operation':'material','base_version':catalog['version'],'part_ids':ids,'color':'#bd654a','mode':'tint'});r.raise_for_status();catalog=r.json();changed={p['id'] for p in catalog['parts'] if p['material_signature']!=signatures[p['id']]};assert changed==set(ids)
                r=client.post(root+'/versions',json={'operation':'translate_parts','base_version':catalog['version'],'part_ids':ids,'translation':[0,0,1]});r.raise_for_status();catalog=r.json();moved=folder/f'moved_{i}.glb';moved.write_bytes(client.get(catalog['model_url']).content);after=geometry(moved)
                for key,mesh in baseline.items():np.testing.assert_allclose(after[key].triangles,mesh.triangles+([0,0,1] if key==group['id'] else [0,0,0]),atol=5e-7)
                r=client.post(root+'/export-parts',json={'version':catalog['version'],'part_ids':ids});r.raise_for_status();file=folder/f'part_{i}.glb';file.write_bytes(r.content);mesh=trimesh.load(file,force='mesh',process=False);mesh.merge_vertices(digits_vertex=8,merge_tex=True,merge_norm=True)
                record.setdefault('parts',[]).append({'name':group['name'],'group_id':group['id'],'part_ids':ids,'export_file':str(file.relative_to(OUT)).replace('\\','/'),'material_scope_passed':True,'other_groups_unchanged_on_move':True,**mesh_stats(mesh)})
                r=client.post(root+'/versions',json={'operation':'restore_version','base_version':catalog['version'],'source_version':baseline_version});r.raise_for_status();catalog=r.json()
            record['final_version']=catalog['version'];record['model_url']=catalog['model_url'];record['source_unchanged']=hashlib.sha256((ROOT/'.data/jobs'/case['job']/'model.glb').read_bytes()).hexdigest()==case['source_sha256'];assert record['source_unchanged'];record['original_generation_unchanged']=hashlib.sha256((ROOT/'.data/jobs'/case['source_job']/'model.glb').read_bytes()).hexdigest()==case['source_sha256'];assert record['original_generation_unchanged'];record['appearance_acceptance']='needs_review';(OUT/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8');print(name,len(record['parts']),'groups checked; physical closure not assumed',flush=True)
if __name__=='__main__':main()
