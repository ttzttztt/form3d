# -*- coding: utf-8 -*-
"""Commit the exact preview, exercise material/movement/export, record honest reviews."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx,numpy as np,trimesh
from services.api.glb_document import read_glb,parts_catalog,selected_primitives
from furniture_parts import primitive_data
from complete_part import mesh_stats
OUT=ROOT/'experiments/sofa_refinement_20261113'
def geometry(path):
    doc,binary,_=read_glb(path);groups={}
    for part,p in selected_primitives(doc,[]):
        _,f,v,_,_,_=primitive_data(doc,binary,part,p);key=part.get('logical_group_id') or part['id'];groups.setdefault(key,[]).append(trimesh.Trimesh(v,f,process=False))
    result={key:trimesh.util.concatenate(meshes) for key,meshes in groups.items()}
    for m in result.values():m.merge_vertices(digits_vertex=8,merge_tex=True,merge_norm=True)
    return result
def main():
    cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'));audit=[]
    with httpx.Client(base_url='http://127.0.0.1:8001',timeout=240) as client:
        for c in cases:
            name=c['case'];root=f'/api/jobs/{c["job"]}/asset';record={'case':name,'job':c['job']};audit.append(record)
            try:
                run=json.loads((OUT/(name+'_run.json')).read_text(encoding='utf-8'));request=json.loads((OUT/(name+'_request.json')).read_text(encoding='utf-8'));preview=run['preview']
                # Trial 1 remains the delivered negative specimen. Trial 2 is a separate comparison.
                request['completion_preview_id']=preview['preview_id'];r=client.post(root+'/versions',json=request);r.raise_for_status();catalog=r.json();record['split_version']=catalog['version'];record['preview_id']=preview['preview_id']
                def freeze(stage):
                    r=client.get(catalog['model_url']);r.raise_for_status();path=OUT/(name+'_'+stage+'.glb');path.write_bytes(r.content);return path
                assembled=freeze('final_assembled');assert hashlib.sha256(assembled.read_bytes()).hexdigest()==run['preview_model_sha256'];record['saved_equals_preview_bytes']=True
                baseline=geometry(assembled);key=catalog['manifest']['operation']['part_group_id'];ids=[p['id'] for p in catalog['parts'] if p.get('logical_group_id')==key];record['selected_ids']=ids;record['part']=mesh_stats(baseline[key]);record['part_y_extent']=float(baseline[key].extents[1]);record['source_y_fraction']=record['part_y_extent']/(c['source_bounds_world'][1][1]-c['source_bounds_world'][0][1])
                material_before={p['id']:p['material_signature'] for p in catalog['parts']}
                r=client.post(root+'/versions',json={'operation':'material','base_version':catalog['version'],'part_ids':ids,'color':'#458999','mode':'tint'});r.raise_for_status();catalog=r.json();material_version=catalog['version'];record['material_version']=material_version
                changed={p['id'] for p in catalog['parts'] if p['material_signature']!=material_before[p['id']]};assert changed==set(ids);record['material_changes_selected_only']=True
                r=client.post(root+'/versions',json={'operation':'translate_parts','base_version':catalog['version'],'part_ids':ids,'translation':[0,0,1.6]});r.raise_for_status();catalog=r.json();moved=freeze('moved');after=geometry(moved)
                for group,m in baseline.items():np.testing.assert_allclose(after[group].triangles,m.triangles+([0,0,1.6] if group==key else [0,0,0]),atol=5e-7)
                record['other_groups_unchanged_on_move']=True
                r=client.post(root+'/export-parts',json={'version':catalog['version'],'part_ids':ids});r.raise_for_status();partfile=OUT/(name+'_export.glb');partfile.write_bytes(r.content);m=trimesh.load(partfile,force='mesh',process=False);m.merge_vertices(digits_vertex=8,merge_tex=True,merge_norm=True);record['export']=mesh_stats(m);assert m.is_watertight and m.is_winding_consistent
                r=client.post(root+'/versions',json={'operation':'restore_version','base_version':catalog['version'],'source_version':material_version});r.raise_for_status();catalog=r.json();record['final_version']=catalog['version'];freeze('final_demo')
                decision='reject' if 'sofa' in name else 'accept';note='外观未通过：范围和厚度可编辑，但仍有明显推测平面/相邻结构粘连，不能认定完整坐垫。' if decision=='reject' else '本轮编辑回归通过：预览保存一致、局部材质、移动与导出通过；不代表原图或实物几何准确。'
                r=client.post(f'/api/jobs/{c["job"]}/assets/{catalog["version"]}/review',json={'decision':decision,'note':note});r.raise_for_status();record['review_status']=r.json()['editor_review_status'];record['review_note']=note
                record['source_unchanged']=hashlib.sha256((ROOT/'.data/jobs'/c['job']/'model.glb').read_bytes()).hexdigest()==c['source_sha256'];assert record['source_unchanged']
                if 'sofa' in name:
                    old=trimesh.load(ROOT/'experiments/multifurniture_20261113'/(name+'_verified_part_1.glb'),force='mesh',process=False);record['previous_y_extent']=float(old.extents[1])
            except Exception as exc:record['error']=repr(exc)
            (OUT/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
