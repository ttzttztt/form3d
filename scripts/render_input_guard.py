# -*- coding: utf-8 -*-
"""Watch the fresh guard batch and render only models actually generated."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from render_quality_benchmark import render_model
OUT=ROOT/'experiments/input_guard_20261111'
cases=json.loads((ROOT/'experiments/multicategory_20261111/protocol.json').read_text(encoding='utf-8'))['cases']
parser=argparse.ArgumentParser();parser.add_argument('--attempt',default='batch');parser.add_argument('--cases',nargs='*')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
if args.cases:cases=[case for case in cases if case['id'] in args.cases]
started=time.monotonic()
while True:
    pending=0
    for case in cases:
        folder=OUT/args.attempt/case['id'];record=folder/'execution.json'
        if not record.exists():pending+=1;continue
        value=json.loads(record.read_text(encoding='utf-8'))
        if value['status']!='awaiting_review':continue
        evidence=folder/'renders/model_render_evidence.json'
        if evidence.exists():continue
        render_model(folder/'model.glb',folder/'renders','model',views_requested=['front','oblique','side','rear','left','opposite_oblique'])
        print('INPUT_GUARD_RENDERED '+case['id'],flush=True)
    if not pending:break
    if time.monotonic()-started>5400:raise TimeoutError('Batch incomplete, no quality claim')
    time.sleep(3)
print('INPUT_GUARD_RENDERS_FINISHED',flush=True)
