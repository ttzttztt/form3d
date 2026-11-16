# -*- coding: utf-8 -*-
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--case',required=True);p.add_argument('--index',type=int,required=True);p.add_argument('--generation',default='generated_v1');a=p.parse_args();folder=ROOT/'experiments/part_regeneration_20261113'/a.case;refs=json.loads((folder/'references/references.json').read_text(encoding='utf-8'))['candidates'];reference=refs[a.index];source=folder/'references'/reference['file'];assert source.is_file();out=folder/a.generation
if out.exists():raise SystemExit('Existing generation kept')
(folder/('generation_choice_'+a.generation+'.json')).write_text(json.dumps({'reference_id':reference['id'],'index':a.index,'selection_method':'assistant_visual_review_of_original_photo_candidates','source_image_sha256':reference['source_image_sha256'],'input':str(source)},ensure_ascii=False,indent=2),encoding='utf-8')
with(folder/(a.generation+'.log')).open('wb')as log:r=subprocess.run([str(ROOT/'.venv-hunyuan/Scripts/python.exe'),'-X','utf8',str(ROOT/'scripts/generate_hunyuan3d.py'),'--input',str(source),'--output',str(out),'--keep-background','--steps','50','--resolution','384'],stdout=log,stderr=subprocess.STDOUT)
print(json.dumps({'case':a.case,'returncode':r.returncode,'output':str(out)}),flush=True)
