# -*- coding: utf-8 -*-
"""Separate immutable seed candidates; select only after all evidence checks."""
import json,shutil,time
from .asset_editor import ROOT
from .local3d import local_python
from .gpu import GPU_LOCK
from .completion_preview import RECONSTRUCTION_LOCK
from .geometry import validate_glb
from .part_regeneration import digest,write_json,run_command,gpu_wait


def wait_cpu(folder):
    started=time.monotonic()
    while not RECONSTRUCTION_LOCK.acquire(timeout=.35):
        if(folder/'cancel_requested').exists():raise ValueError('已取消，原模型保留')
        if time.monotonic()-started>600:raise ValueError('几何处理持续忙碌，请稍后重试')


def run_candidates(store,job,folder,state,context,stage):
    from .part_optimization import copy_generation_cache
    results=[];inferences=[]
    seeds=(42,77,123)[:context.get('candidate_count',3)]
    for index,seed in enumerate(seeds,1):
        child=folder/'candidates'/f'seed_{seed}';child.mkdir(parents=True)
        state.update(candidate_index=index,candidate_total=len(seeds));stage('preparing_candidate')
        for name in('context.json','analysis.json','camera.json'):
            shutil.copyfile(folder/name,child/name)
        shutil.copytree(folder/'references',child/'references')
        if(folder/'views').exists():shutil.copytree(folder/'views',child/'views')
        shutil.copyfile(folder/'reference.png',child/'reference.png')
        result={'seed':seed,'index':index,'status':'running','eligible':False};results.append(result)
        state['candidate_results']=results;write_json(folder/'status.json',state)
        try:
            cache=copy_generation_cache(store,job,state,child/'generated',seed)
            if cache:
                result.update(inference_this_candidate=False,generation_cache=cache);stage('reusing_generation')
            else:
                stage('waiting_gpu');gpu_wait(folder)
                def progress():
                    path=child/'generated/local_progress.json'
                    if path.exists():
                        try:data=json.loads(path.read_text(encoding='utf-8'))
                        except ValueError:return
                        if data.get('sequence')!=state.get('progress_sequence'):
                            state.update(progress_sequence=data.get('sequence'),sampling_step=data.get('sampling_step'),sampling_steps=data.get('sampling_steps'));write_json(folder/'status.json',state)
                try:
                    state.update(progress_sequence=None,sampling_step=None,sampling_steps=None);stage('generating')
                    result['inference_this_candidate']=True;inferences.append(seed)
                    command=[local_python('hunyuan-mini'),'-X','utf8',str(ROOT/'scripts/generate_hunyuan3d.py'),'--input',str(child/'reference.png'),'--output',str(child/'generated'),'--keep-background','--steps','50','--resolution','384','--seed',str(seed)]
                    run_command(child,command,1800,progress,cancel_folder=folder)
                finally:
                    GPU_LOCK.release()
                    if(child/'worker.log').exists():shutil.copyfile(child/'worker.log',child/'generation_worker.log')
            validate_glb(child/'generated/model.glb')
            summary=json.loads((child/'generated/local_summary.json').read_text(encoding='utf-8'))
            if summary['input_sha256']!=state['reference_sha256']or digest(child/'generated/model.glb')!=summary['model_sha256']:raise ValueError('候选生成来源校验失败')
            write_json(child/'generation.json',{'generated_valid':True,'seed':seed,'reference_sha256':state['reference_sha256'],'model_sha256':summary['model_sha256']})
            result['generated_valid']=True
            stage('waiting_cpu');wait_cpu(folder)
            try:
                state['optimization_phase']=None
                def cpu_progress():
                    path=child/'optimization_progress.json'
                    if path.exists():
                        try:info=json.loads(path.read_text(encoding='utf-8'))
                        except ValueError:return
                        if info.get('phase')!=state.get('optimization_phase'):state['optimization_phase']=info.get('phase');write_json(folder/'status.json',state)
                stage('optimizing_shape');run_command(child,[local_python('hunyuan-mini'),'-X','utf8',str(ROOT/'scripts/auto_part_optimization.py'),'--folder',str(child),'--stage','optimize'],600,cpu_progress,cancel_folder=folder)
            finally:RECONSTRUCTION_LOCK.release()
            for name in('model.glb','part.glb','diagnostic.glb'):validate_glb(child/'preview'/name)
            checks=json.loads((child/'checks.json').read_text(encoding='utf-8'));manifest=json.loads((child/'preview/manifest.json').read_text(encoding='utf-8'))
            result.update(status='completed',eligible=checks['can_adopt'],score=checks['ranking']['score'],photo_iou=checks['part_silhouette_iou_after'],reason=checks['reason'],triangles=next(d for d in checks['quality_dimensions']if d['key']=='performance')['metrics']['triangles'],simplification=manifest['operation'].get('simplification'))
        except Exception as exc:
            if(folder/'cancel_requested').exists():raise ValueError('已取消，原模型保留')from exc
            result.update(status='failed',reason=str(exc)if isinstance(exc,ValueError)else'该候选处理未完成，诊断记录保留')
        finally:
            write_json(child/'result.json',result);state['candidate_results']=results;write_json(folder/'status.json',state)
    completed=[r for r in results if r['status']=='completed']
    selection=max(completed,key=lambda r:(r['eligible'],r['score']))if completed else next((r for r in results if r.get('generated_valid')),None)
    state.update(inference_this_task=bool(inferences),inference_seeds=inferences)
    if selection:
        child=folder/'candidates'/f'seed_{selection["seed"]}';(folder/'generated').mkdir()
        for name in('model.glb','foreground.png','local_summary.json'):shutil.copyfile(child/'generated'/name,folder/'generated'/name)
        state.update(generated_valid=True,selected_seed=selection['seed'])
    write_json(folder/'status.json',state)
    if not completed:
        write_json(folder/'candidate_rankings.json',{'candidates':results,'selected_seed':None,'is_product_accuracy':False})
        raise ValueError('所有候选均未完成装配检查，原模型保留；生成文件和原因可查看')
    child=folder/'candidates'/f'seed_{selection["seed"]}'
    shutil.copytree(child/'preview',folder/'preview')
    for name in('checks.json','comparison.png','before.png','after.png'):shutil.copyfile(child/name,folder/name)
    for index,_ in enumerate(context.get('views',[])):
        for name in('before.png','after.png'):
            path=child/'views'/str(index)/name
            if path.exists():shutil.copyfile(path,folder/'views'/str(index)/name)
    write_json(folder/'candidate_rankings.json',{'candidates':results,'selected_seed':selection['seed'],'selection_policy':'eligible first, then documented evidence score; no physical accuracy claim','is_product_accuracy':False})
    return selection
