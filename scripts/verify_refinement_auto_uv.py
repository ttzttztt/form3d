"""Verify guarded auto mode through real API versions on existing test clones."""
import hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx
from verify_asset_upgrade import signature
OUT=ROOT/'experiments/selection_refinement_20261112';records=[]
with httpx.Client(base_url='http://127.0.0.1:8001',timeout=420) as client:
    for c in json.loads((OUT/'uv_runs.json').read_text(encoding='utf-8')):
        root=f"/api/jobs/{c['job']}/asset";catalog=client.get(root).json();record={'case':c['case'],'job':c['job']};records.append(record)
        r=client.post(root+'/versions',json={'operation':'restore_version','base_version':catalog['version'],'source_version':c['base_version']});r.raise_for_status();catalog=r.json();start=time.monotonic()
        r=client.post(root+'/versions',json={'operation':'unwrap_uv','base_version':catalog['version'],'part_ids':c['part_ids'],'uv_unwrap_mode':'auto'});record.update(status=r.status_code,seconds=round(time.monotonic()-start,3))
        if r.status_code==201:
            catalog=r.json();record.update(version=catalog['version'],operation=catalog['manifest']['operation']);path=OUT/(c['case']+'_auto.glb');path.write_bytes(client.get(catalog['model_url']).content)
            for part in record['operation']['parts']:
                comparison=part.get('auto_quality_comparison')
                if comparison:assert part['algorithm']==('proxy_xatlas_transfer' if comparison['proxy_selected'] else 'six_normal_charts')
            record['exact_world_triangles']=signature(path)==signature(ROOT/'.data/jobs'/c['source_job']/'model.glb');assert record['exact_world_triangles']
        else:record['error']=r.json()
        record['original_unchanged']=hashlib.sha256((ROOT/'.data/jobs'/c['source_job']/'model.glb').read_bytes()).hexdigest()==c['source_sha256'];assert record['original_unchanged']
        (OUT/'auto_uv_runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=True),flush=True)
        assert r.status_code==201
