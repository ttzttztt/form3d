import json
from benchmark_multifurniture import Bench,CASES,OUT
c=next(c for c in CASES if c['case']=='round_table');b=Bench(c);b.record=json.loads((OUT/'round_table_run.json').read_text(encoding='utf-8'));(OUT/'round_table_initial_run.json').write_text(json.dumps(b.record,ensure_ascii=False,indent=2),encoding='utf-8');assert b.edit('restore_version',source_version=b.record['slab_split_version']);original=next(s['evidence'] for s in b.record['steps'] if s['operation']=='complete_part');base=original['remainder_group_id'];ids=next(g['part_ids'] for g in b.catalog['groups'] if g['id']==base)
values={'part_ids':ids,'completion_profile':'support','detail_level':'fine','name':'支脚'};plan=b.plan(**values)
if b.edit('complete_part',completion_bounds=plan['completion_bounds'],**values):
    evidence=b.catalog['manifest']['operation'];supports=evidence['part_group_ids'];joint=evidence['remainder_group_id'];joint_ids=next(g['part_ids'] for g in b.catalog['groups'] if g['id']==joint);assert b.edit('rename',part_ids=joint_ids,name='公共连接座');b.record.update(support_group_ids=supports,joint_group_id=joint);b.exercise(original['part_group_ids']+[joint]+supports)
