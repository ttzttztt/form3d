"""Real API no-op check on the already closed seat; never changes its version."""

def main():
    import json,time,urllib.request,urllib.error
    from pathlib import Path
    ROOT=Path(__file__).resolve().parents[2];out=ROOT/'experiments/photo_guided_parts_20261113'
    ui=json.loads((out/'leather_seat_ui.json').read_text(encoding='utf-8'));base='http://127.0.0.1:8001';root=f'/api/jobs/{ui["job"]}/asset'
    def call(url,data=None):
        request=urllib.request.Request(base+url,data=json.dumps(data).encode()if data is not None else None,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=60)as response:return json.load(response)
    catalog=call(root);before=catalog['version'];task=call(root+'/part-optimizations',{'version':before,'part_ids':ui['adopted_part_ids']});last=None
    (out/'keep_live.json').write_text(json.dumps({'job':ui['job'],'task':task['id']}),encoding='utf-8')
    for _ in range(600):
        state=call(root+'/part-regenerations/'+task['id'])
        if state['stage']!=last:print(state['stage'],flush=True);last=state['stage']
        if state['status']not in('queued','running'):break
        time.sleep(1)
    result={'job':ui['job'],'task':task['id'],'state':state,'version_before':before,'checks':[]}
    try:
        assert state['status']=='ready',state
        assert state['automatic_plan']['route']=='keep',state['automatic_plan']
        assert state['photo_checks']['can_adopt']is False
        assert not state.get('generated_valid')and not state.get('inference_this_task')
        assert call(root)['version']==before
        try:call(root+'/versions',{'base_version':before,'part_ids':ui['adopted_part_ids'],'operation':'replace_part','regeneration_preview_id':task['id']})
        except urllib.error.HTTPError as exc:assert exc.code==409;result['adoption_refusal']=json.load(exc)
        else:raise AssertionError('No-op must not publish a replacement')
        result['checks']=['closed_seat_automatically_kept','no_new_hunyuan_generation','no_op_replacement_refused_by_api','current_version_unchanged']
    except Exception as exc:result['failure']=str(exc);raise
    finally:(out/'keep_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':result['checks'],'task':task['id']},ensure_ascii=False))


if __name__=='__main__':
    main()
