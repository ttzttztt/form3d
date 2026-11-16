import hashlib,json,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx,numpy as np
from services.api.glb_document import read_glb
from verify_asset_upgrade import signature
from test_part_tools import triangles
OUT=ROOT/'experiments/part_tools_20261112';records=json.loads((OUT/'real_edits.json').read_text(encoding='utf-8'));shutil.copyfile(OUT/'real_edits.json',OUT/'real_edits_before_uv_budget_fix.json');client=httpx.Client(base_url='http://127.0.0.1:8001',timeout=240)
for case in records:
    if not case.get('uv_not_published'):continue
    root=f'/api/jobs/{case["job"]}/asset';catalog=client.get(root).json();selected=case['part_ids'];source=ROOT/'.data/jobs'/case['source_job']/'model.glb'
    for operation,extra in [('unwrap_uv',{}),('translate_parts',{'translation':[.08,0,0]})]:
        started=time.monotonic();response=client.post(root+'/versions',json={'base_version':catalog['version'],'operation':operation,'part_ids':selected,**extra});body=response.json();assert response.status_code==201,body;catalog=body;case['steps'].append({'operation':operation,'status':response.status_code,'seconds':round(time.monotonic()-started,3),'version':body['version'],'manifest':body['manifest']});path=OUT/(case['case']+('_uv.glb' if operation=='unwrap_uv' else '_moved.glb'));path.write_bytes(client.get(body['model_url']).content)
        if operation=='unwrap_uv':
            assert signature(path)==signature(source);case['world_triangles_retained_after_uv']=True;case['uv_version']=body['version'];doc,binary,_=read_glb(path);expected=triangles(doc,binary)
            export=client.post(root+'/export-parts',json={'version':catalog['version'],'part_ids':selected});assert export.status_code==200;part=OUT/(case['case']+'_part.glb');part.write_bytes(export.content);doc,blob,_=read_glb(part);actual=triangles(doc,blob);assert list(actual)==selected;np.testing.assert_array_equal(actual[selected[0]],expected[selected[0]]);case['subset_export_exact']=True
        else:
            doc,binary,_=read_glb(path);after=triangles(doc,binary);errors=[float(abs(after[key]-(v+([.08,0,0] if key in selected else [0,0,0]))).max()) for key,v in expected.items()];assert max(errors)<2e-6;case['max_world_translation_error']=max(errors);case['moved_version']=body['version']
    case.pop('uv_not_published');case['uv_budget_fix_retested']=True;(OUT/'real_edits.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(case['case']+' UV/export/translation retry passed',flush=True)
client.close()
