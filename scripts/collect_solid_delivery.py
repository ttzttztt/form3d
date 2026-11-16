import json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.glb_document import read_glb
from semantic_asset import write_style_preview
out=ROOT/'experiments/solid_parts_20261113';ui=json.loads((out/'final_ui_verified/ui_results.json').read_text(encoding='utf-8'))
assert not ui.get('failure'),ui.get('failure')
source=ROOT/'.data/jobs'/ui['job']/'assets'/ui['solid_version'];folder=out/'delivery/leather_sofa';folder.mkdir(parents=True,exist_ok=True)
for file in ('model.glb','manifest.json'):shutil.copyfile(source/file,folder/file)
doc,binary,extra=read_glb(folder/'model.glb');write_style_preview(doc,binary,extra,folder/'style.glb')
print(str(folder))
