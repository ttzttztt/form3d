import json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx,numpy as np
from services.api.glb_document import read_glb,parts_catalog
from services.api.geometry import validate_glb
from test_part_tools import triangles
OUT=ROOT/'experiments/part_tools_20261112';records=json.loads((OUT/'real_edits.json').read_text(encoding='utf-8'));client=httpx.Client(base_url='http://127.0.0.1:8001',timeout=180);results=[]
for c in records:
    path=OUT/(c['case']+'_part.glb');old_bytes=path.stat().st_size;shutil.copyfile(path,path.with_name(c['case']+'_part_before_resource_prune.glb'));response=client.post(f'/api/jobs/{c["job"]}/asset/export-parts',json={'version':c['uv_version'],'part_ids':c['part_ids']});assert response.status_code==200,response.text;path.write_bytes(response.content);doc,binary,_=read_glb(path);source,blob,_=read_glb(OUT/(c['case']+'_uv.glb'));expected=triangles(source,blob);actual=triangles(doc,binary);assert set(actual)==set(c['part_ids'])
    for identity in c['part_ids']:np.testing.assert_array_equal(actual[identity],expected[identity])
    active_meshes={n['mesh'] for n in doc['nodes'] if 'mesh' in n};assert active_meshes==set(range(len(doc['meshes'])));assert sum(len(m['primitives']) for m in doc['meshes'])==len(c['part_ids']);validation=validate_glb(path);assert validation['errors']==0;results.append({'case':c['case'],'only_selected_geometry_in_document':True,'exact_world_triangles':True,'before_bytes':old_bytes,'after_bytes':path.stat().st_size,'validation':validation});print(c['case']+' subset geometry and resources verified',flush=True)
(OUT/'part_export_resource_checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');client.close()
