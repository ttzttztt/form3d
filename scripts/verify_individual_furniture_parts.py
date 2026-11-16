# -*- coding: utf-8 -*-
"""Independently move, recolor and reopen every requested part, not the full set."""
import json
import numpy as np,trimesh
from benchmark_multifurniture import Bench,CASES,OUT,CLIENT,geometry,mesh_stats,ROOT

def run(c):
    b=Bench(c);b.record=json.loads((OUT/(c['case']+'_run.json')).read_text(encoding='utf-8'));(OUT/(c['case']+'_bulk_trial.json')).write_text(json.dumps(b.record,ensure_ascii=False,indent=2),encoding='utf-8')
    if c['case']=='bookcase':
        assert b.edit('restore_original');names={'node_0_primitive_0':'左侧板','node_1_primitive_0':'右侧板','node_2_primitive_0':'背板','node_3_primitive_0':'底板','node_8_primitive_0':'顶板','node_9_primitive_0':'前踢脚板','node_10_primitive_0':'后踢脚板'}
        for n in range(4,8):names[f'node_{n}_primitive_0']=f'层板 {n-3}'
        for p in b.catalog['parts']:assert b.edit('rename',part_ids=[p['id']],name=names[p['id']])
        b.freeze('organized');b.record['organized_names']=[g['name'] for g in b.catalog['groups']]
    else:assert b.edit('restore_version',source_version=b.record['verified_assembled_version'])
    baseline=b.freeze('individual_baseline');base_version=b.catalog['version'];original=geometry(baseline);groups=list(b.catalog['groups'])
    if c['case']=='chair':groups=[g for g in groups if g['id'] in b.record['groups_checked']]
    b.record['individual_checks']=[];demonstration=None
    for ordinal,g in enumerate(groups,1):
        ids=g['part_ids'];before={p['id']:p['material_signature'] for p in b.catalog['parts']};assert b.edit('material',part_ids=ids,color='#3a918b',roughness=.7,mode='tint');changed={p['id'] for p in b.catalog['parts'] if p['material_signature']!=before[p['id']]};assert changed==set(ids);colored=b.catalog['version']
        if demonstration is None and (c['case']!='bookcase' or g['name']=='层板 2'):demonstration=colored
        assert b.edit('translate_parts',part_ids=ids,translation=[0,0,1.6]);moved=b.freeze(f'individual_{ordinal}_moved');after=geometry(moved)
        for key,mesh in original.items():np.testing.assert_allclose(after[key].triangles,mesh.triangles+([0,0,1.6] if key==g['id'] else [0,0,0]),atol=5e-7)
        response=CLIENT.post(b.root+'/export-parts',json={'version':b.catalog['version'],'part_ids':ids});response.raise_for_status();file=OUT/f"{c['case']}_individual_{ordinal}.glb";file.write_bytes(response.content);m=trimesh.load(file,force='mesh',process=False);m.merge_vertices(digits_vertex=8,merge_tex=True,merge_norm=True);stats=mesh_stats(m);assert stats['watertight'] and stats['winding_consistent'];b.record['individual_checks'].append({'name':g['name'],'group_id':g['id'],'part_ids':ids,'export_file':file.name,'changed_material_ids':sorted(changed),'other_groups_unchanged':True,**stats});b.save();assert b.edit('restore_version',source_version=base_version)
    assert demonstration;assert b.edit('restore_version',source_version=demonstration);b.record['demo_version']=b.catalog['version'];b.freeze('verified_final');b.save()
    if c['case']=='bookcase':
        from services.api.glb_document import read_glb,parts_catalog
        from edit_asset import accessor_array
        def attrs(path):
            d,data,_=read_glb(path);return {p['id']:{k:accessor_array(d,data,i).tobytes() for k,i in d['meshes'][d['nodes'][p['node']]['mesh']]['primitives'][p['primitive']]['attributes'].items()} for p in parts_catalog(d)}
        assert attrs(ROOT/'.data/jobs'/c['job']/'model.glb')==attrs(baseline);b.record['all_geometry_uv_attributes_preserved']=True;b.record['all_parts_geometry']= {key:mesh_stats(m) for key,m in original.items()};b.save()

if __name__=='__main__':
    import sys
    for c in CASES:
        if c['case'] in (set(sys.argv[1:]) or {'chair','round_table','bookcase'}):run(c)
