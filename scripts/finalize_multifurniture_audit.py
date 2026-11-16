# -*- coding: utf-8 -*-
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np,httpx
from services.api.glb_document import read_glb
from complete_part import completion_plan
from benchmark_multifurniture import geometry
OUT=ROOT/'experiments/multifurniture_20261113';audit=[]
with httpx.Client(base_url='http://127.0.0.1:8001',timeout=120) as client:
    for c in json.loads((OUT/'cases.json').read_text(encoding='utf-8')):
        path=OUT/(c['case']+'_run.json');r=json.loads(path.read_text(encoding='utf-8'));base=ROOT/'.data/jobs'/c['job']/'model.glb';source=ROOT/'.data/jobs'/c['source_job']/('model.glb' if c['source_version']=='original' else 'assets/'+c['source_version']+'/model.glb');assert hashlib.sha256(base.read_bytes()).hexdigest()==c['source_sha256']==hashlib.sha256(source.read_bytes()).hexdigest();r['source_unchanged']=True
        catalog=client.get(f"/api/jobs/{c['job']}/asset").json()
        if c['case']=='round_table':
            group=next(g for g in catalog['groups'] if g['name']=='桌面');material=next(s for s in reversed(r['steps']) if s['operation']=='material' and set(s['request'].get('part_ids',[]))==set(group['part_ids']));reply=client.post(f"/api/jobs/{c['job']}/asset/versions",json={'operation':'restore_version','base_version':catalog['version'],'source_version':material['version']});reply.raise_for_status();catalog=reply.json();r['demo_version']=catalog['version'];(OUT/'round_table_verified_final.glb').write_bytes(client.get(catalog['model_url']).content)
        if 'sofa' in c['case']:
            doc,binary,_=read_glb(base);request=json.loads((OUT/(c['case']+'_guide_request.json')).read_text(encoding='utf-8'));plan=completion_plan(doc,binary,request);r['review_plan']=plan;assert plan['thickness_underconstrained'];decision='reject';note='本轮外观未通过：顶面引导产生的坐垫候选偏薄；皮质沙发还带入靠垫底部。闭合和导出通过，不能当作完整坐垫或自动分割成功。'
            r['acceptance']='appearance_rejected';r['reason']=note
        else:
            assert r.get('individual_checks');assert all(p['watertight'] and p['winding_consistent'] and p['other_groups_unchanged'] for p in r['individual_checks']);decision='accept';note='本轮操作与固定视角目测验收通过：独立材质、逐件移动、导出重开。保留原生成模型缺陷；几何候选不证明真实隐藏结构、支撑数量或制造尺寸。';r['acceptance']='editing_checks_passed'
        response=client.post(f"/api/jobs/{c['job']}/assets/{catalog['version']}/review",json={'decision':decision,'note':note});response.raise_for_status();r['reviewed_version']=catalog['version'];r['editor_review_status']=response.json()['editor_review_status'];r['final_groups']=response.json()['groups'];r['demo_version']=catalog['version']
        if c['case']=='bookcase':
            original=geometry(base);organized=geometry(OUT/'bookcase_organized.glb')
            for key,m in original.items():np.testing.assert_array_equal(organized[key].triangles,m.triangles)
            r['organized_world_triangles_unchanged']=True
        path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');audit.append({'case':c['case'],'job':c['job'],'version':catalog['version'],'decision':decision,'groups':len(catalog['groups']),'source_unchanged':True})
(OUT/'final_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(audit,ensure_ascii=False,indent=2))
