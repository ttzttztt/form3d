"""Read-only test of the seam repair guard on an additional real chair."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.glb_document import read_glb,parts_catalog
from replace_generated_part import replace_generated
source=ROOT/'experiments/semantic_refinement_20261113/delivery/accent_chair/model.glb'
before=hashlib.sha256(source.read_bytes()).hexdigest();doc,binary,_=read_glb(source)
ids=[p['id']for p in parts_catalog(doc)if p.get('semantic_kind')=='seat']
result={'case':'accent_chair','source':str(source.relative_to(ROOT)),'read_only':True}
try:
    operation=replace_generated(doc,binary,{'kind':'cushion','part_ids':ids,'method':'source_seam'})
    result.update(status='candidate_computed_but_not_saved',operation=operation)
except ValueError as exc:result.update(status='rejected',reason=str(exc))
result['source_file_unchanged']=before==hashlib.sha256(source.read_bytes()).hexdigest()
assert result['source_file_unchanged']
(ROOT/'experiments/soft_part_quality_20261113/additional_guard_case.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
