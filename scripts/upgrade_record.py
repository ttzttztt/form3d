# -*- coding: utf-8 -*-
"""Append-only experiment records with actual local timestamps."""
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/autonomous_upgrade_20261113'

def record(event,**facts):
    OUT.mkdir(exist_ok=True)
    value={'time':datetime.now(timezone(timedelta(hours=8))).isoformat(),'event':event,**facts}
    with(OUT/'events.jsonl').open('a',encoding='utf-8')as stream:stream.write(json.dumps(value,ensure_ascii=False)+'\n')
    return value

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('event');p.add_argument('--facts',default='{}');a=p.parse_args();print(json.dumps(record(a.event,**json.loads(a.facts)),ensure_ascii=False))
