import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import httpx
from verify_asset_upgrade import signature
OUT=ROOT/'experiments/selection_refinement_20261112';delivery=json.loads((OUT/'delivery_browser.json').read_text(encoding='utf-8'));case=json.loads((OUT/'delivery_case.json').read_text(encoding='utf-8'))
with httpx.Client(base_url='http://127.0.0.1:8001',timeout=120) as client:
    catalog=client.get(f"/api/jobs/{delivery['job']}/asset").json();assert catalog['version']==delivery['material_version'];path=OUT/'multipoint_saved.glb';path.write_bytes(client.get(catalog['model_url']).content)
original=ROOT/'.data/jobs'/case['source_job']/'model.glb';clone=ROOT/'.data/jobs'/case['job']/'model.glb'
result={'job':case['job'],'saved_material_version':catalog['version'],'world_triangles_preserved':signature(original)==signature(path),'source_and_clone_original_identical':hashlib.sha256(original.read_bytes()).hexdigest()==hashlib.sha256(clone.read_bytes()).hexdigest()}
assert result['world_triangles_preserved'] and result['source_and_clone_original_identical'];(OUT/'saved_geometry_check.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(result)
