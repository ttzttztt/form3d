import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.glb_document import read_glb
from complete_part import completion_plan
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--request',required=True);parser.add_argument('--output',required=True);a=parser.parse_args();doc,binary,_=read_glb(a.input);result=completion_plan(doc,binary,json.loads(Path(a.request).read_text(encoding='utf-8')));Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
