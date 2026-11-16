# -*- coding: utf-8 -*-
"""Render actual finished deliveries; supports watching the real batch."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from render_quality_benchmark import render_model
OUT=ROOT/'experiments/multicategory_20261111'
def read(path):return json.loads(path.read_text(encoding='utf-8'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--watch',action='store_true');parser.add_argument('--case');parser.add_argument('--extra',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    cases=[case for case in read(OUT/'protocol.json')['cases'] if not args.case or args.case==case['id']]
    started=time.monotonic()
    while True:
        pending=0
        for case in cases:
            folder=OUT/case['id'];record=folder/'hunyuan/execution.json'
            if not record.is_file():pending+=1;continue
            execution=read(record)
            if execution['status']!='awaiting_review':continue
            model=folder/'hunyuan/model.glb'
            label='extra' if args.extra else 'model'
            evidence=folder/('renders/'+label+'_render_evidence.json')
            actual_hash=hashlib.sha256(model.read_bytes()).hexdigest()
            if actual_hash!=execution['sha256']['model.glb']:raise ValueError('Model hash mismatch')
            if evidence.is_file() and read(evidence)['model_sha256']==actual_hash:continue
            render_model(model,folder/'renders',label,
                         views_requested=['left','opposite_oblique'] if args.extra else None)
            print('BATCH_RENDER_COMPLETE '+case['id'],flush=True)
        if not args.watch or not pending:break
        if time.monotonic()-started>5400:raise TimeoutError('Watch exceeded 90 minutes; no case declared passed')
        time.sleep(3)
    print('BATCH_RENDER_FINISHED',flush=True)

if __name__=='__main__':main()
