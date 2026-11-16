"""Run real SAM masks for a frozen image-planning batch; keep stage scopes explicit."""
import argparse,collections,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from generate_partcrafter import digest,write


def run(args):
    output=Path(args.output)
    if output.exists():raise ValueError('Use a new evaluation folder')
    output.mkdir(parents=True);started=time.monotonic()
    cases=json.loads(Path(args.cases).read_text(encoding='utf-8'));vlm=Path(args.vlm)
    annotations={}
    for path in (ROOT/'experiments/parts_first_20261114/initial_photo_annotations.json',ROOT/'experiments/parts_first_20261114/additional_input_observations.json'):
        data=json.loads(path.read_text(encoding='utf-8'));annotations.update(data.get('cases',data))
    rows=[];python=ROOT/'.venv-sam2/Scripts/python.exe'
    for case in cases:
        folder=output/case['case'];folder.mkdir();proposal_path=vlm/case['case']/'semantic_proposal.json'
        row={'case':case['case'],'image_sha256':digest(case['image']),'planning_scope':'selected_target_crop',
            'new_whole_3d_sampling_in_this_evaluation':False,'complete_assembly_accepted':False}
        write(output/'progress.json',{'stage':'segmentation','case':case['case'],'completed_cases':len(rows)})
        if not proposal_path.is_file():row.update(status='not_run',reason='no_completed_vlm_response')
        else:
            proposal=json.loads(proposal_path.read_text(encoding='utf-8'));row['vlm_status']=proposal['status'];row['proposal_sha256']=digest(proposal_path)
            if proposal['status']!='proposal_ready':row.update(status='failed',reason=proposal.get('error','invalid_proposal'))
            else:
                furniture=proposal['furniture'];counts=collections.Counter(p['kind']for f in furniture for p in f['parts'])
                expected=annotations.get(case['case'],{}).get('visible_part_counts',{})
                missing={kind:max(0,count-counts[kind])for kind,count in expected.items()if counts[kind]<count}
                excess={kind:counts[kind]-count for kind,count in expected.items()if counts[kind]>count}
                row.update(proposed_counts=dict(counts),assistant_reference_counts=expected,
                    reference_is_independent_human_ground_truth=False,known_missing_by_assistant_reference=missing,
                    reference_label_count_deficit=missing,reference_label_count_excess=excess,
                    count_difference_may_be_omission_or_misclassification=True,
                    inventory_review='known_missing_parts'if missing else'no_known_minimum_count_deficit_not_accuracy_acceptance')
                command=[str(python),'-X','utf8',str(ROOT/'scripts/segment_assembly_proposal.py'),'--input',case['image'],
                         '--image-id',case['image_id'],'--proposal',str(proposal_path),'--output',str(folder/'masks')]
                with(folder/'sam.log').open('wb')as log:
                    result=subprocess.run(command,cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=300)
                if result.returncode:row.update(status='failed',reason='SAM_worker_failed',returncode=result.returncode)
                else:
                    masks=json.loads((folder/'masks/run.json').read_text(encoding='utf-8'));row.update(status='measured',objects=masks['objects'])
                    for item in masks['objects']:
                        plan_path=folder/'masks'/item.get('folder','missing')/'plan.json'
                        if (missing or excess)and plan_path.is_file():
                            plan=json.loads(plan_path.read_text(encoding='utf-8'));plan['status']='needs_evidence'
                            plan['limitations'].append('标签计数与助手图像参考不一致：'+json.dumps({'deficit':missing,'excess':excess},ensure_ascii=False)+'，可能漏件、重复或误分类，尚待逐图核对；不是独立人工真值。')
                            write(plan_path,plan);item['plan_status']='needs_evidence';item['assistant_inventory_gate']='known_missing_parts'
        rows.append(row);write(folder/'evaluation.json',row);write(output/'evaluation.json',{'cases':rows,'finished_cases':len(rows),'distinct_designs':len({r['case']for r in rows}),
            'scope':'real_image_part_planning_and_masks_not_whole_3d_generation','elapsed_seconds':round(time.monotonic()-started,3)})
        print(json.dumps({'case':case['case'],'status':row['status'],'known_missing':row.get('known_missing_by_assistant_reference')}),flush=True)
    write(output/'progress.json',{'stage':'finished','completed_cases':len(rows)})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cases',required=True);p.add_argument('--vlm',required=True);p.add_argument('--output',required=True);run(p.parse_args())
