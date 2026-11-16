"""Cancellable bridge from FastAPI to the isolated, offline 3D worker."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import time

from .gpu import GPU_LOCK
from .provider import Cancelled
from .segmentation import choose_segmentation, segmentation_python, segmentation_status
from .preflight import InputNeedsAttention, preflight_python
from .output_quality import OutputNeedsAttention, target_category

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".models" / "triposr"


def local_python(engine="triposr"):
    configured = os.getenv("HUNYUAN_PYTHON" if engine == "hunyuan-mini" else "LOCAL3D_PYTHON")
    environment = ".venv-hunyuan" if engine == "hunyuan-mini" else ".venv-3d"
    candidate = Path(configured) if configured else ROOT / environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(candidate.resolve()) if candidate.is_file() else None


def engine_status(engine):
    hunyuan = engine == "hunyuan-mini"
    directory = ROOT / ".models" / "hunyuan3d-2mini" if hunyuan else MODEL
    files = (["hunyuan3d-dit-v2-mini/model.fp16.safetensors", "hunyuan3d-dit-v2-mini/config.yaml", "provenance.json"] if hunyuan else
             ["model.ckpt", "config.yaml", "dino_config.json", "u2netp.onnx", "provenance.json"])
    weights = all((directory / name).is_file() for name in files)
    source = (ROOT / ".tools" / "Hunyuan3D-2" / "hy3dgen" / "shapegen" / "pipelines.py").is_file() if hunyuan else (ROOT / ".tools" / "TripoSR" / "tsr" / "system.py").is_file()
    runtime = {}
    try:
        runtime = json.loads((directory / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    interpreter = local_python(engine)
    checked = bool(interpreter and runtime.get("available") and
                   os.path.normcase(interpreter) == os.path.normcase(runtime.get("python", "")))
    tested = bool(runtime.get("inference_tested")) if hunyuan else True
    return {"available": bool(weights and source and checked and tested), "model": "Hunyuan3D-2mini" if hunyuan else "TripoSR",
            "mode": "local", "weights_ready": weights, "runtime_ready": checked,
            "device": runtime.get("device"), "requires_key": False,
            "output": "geometry_only" if hunyuan else "predicted_vertex_colors",
            "inference_tested": tested, "appearance_accepted": False}


def local3d_status():
    baseline = engine_status("triposr")
    return {**baseline, "engines": {"triposr": dict(baseline), "hunyuan-mini": engine_status("hunyuan-mini")}}


def generate_local(store, job_id, input_path, directory, check_cancelled, remove_background=True, engine="triposr", segmentation="auto"):
    if not engine_status(engine)["available"]:
        raise ValueError("本地图生 3D 尚未就绪，请完成模型安装并执行运行环境检查")
    store.event(job_id, "waiting_gpu", "等待本地显卡空闲")
    while not GPU_LOCK.acquire(timeout=.25):
        check_cancelled()
    process = None
    try:
        check_cancelled()
        pipeline_started=time.monotonic()
        segmentation_summary=None
        selection={'requested':segmentation,'selected':'disabled','background_kind':None}
        job=store.job(job_id)
        image=store.image(job['request']['image_id'])
        category=target_category(job['request'],image)
        original_path=store.root/image['normalized_path']
        prepared_path=input_path
        if remove_background:
            selected,kind=choose_segmentation(input_path,segmentation,segmentation_status()['available'],source_path=original_path)
            selection.update(selected=selected,background_kind=kind,routing_basis='original_source_or_provided_alpha',
                             white_tight_crop_refinement=bool(selected=='sam2' and segmentation=='auto' and kind=='white_background'))
            if selected=='sam2':
                job=store.job(job_id)
                image=store.image(job['request']['image_id'])
                target=job['request']['target']
                store.event(job_id,'segment','SAM 2 正在按目标框精细分割')
                segment_command=[segmentation_python(),'-u',str(ROOT/'scripts'/'segment_target.py'),
                    '--input',str(store.root/image['normalized_path']),'--prepared',str(input_path),
                    '--target',*[str(target[key]) for key in ('x','y','width','height')],
                    '--output',str(directory)]
                with (directory/'segmentation.log').open('wb') as log:
                    process=subprocess.Popen(segment_command,stdout=log,stderr=subprocess.STDOUT,cwd=str(ROOT),
                                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    segment_started=time.monotonic()
                    while process.poll() is None:
                        check_cancelled()
                        if time.monotonic()-segment_started>300:
                            raise ValueError('SAM 2 分割超过 5 分钟，已停止本次任务')
                        time.sleep(.25)
                check_cancelled()
                if process.returncode:
                    raise ValueError('SAM 2 分割失败，未回退到基础去背景；详情见任务 segmentation.log')
                segmentation_summary=json.loads((directory/'segmentation_summary.json').read_text(encoding='utf-8'))
                input_path=directory/'segmented.png'
                if not input_path.is_file(): raise ValueError('SAM 2 未输出可用的主体图片')
                store.event(job_id,'segment_ready','目标分割完成；掩码可查看，继续检查输入质量',
                    segmented_url='/api/jobs/%s/files/segmented.png'%job_id,
                    segmentation_mask_url='/api/jobs/%s/files/segmentation_mask.png'%job_id,
                    segmentation_overlay_url='/api/jobs/%s/files/segmentation_overlay.png'%job_id,
                    segmentation=segmentation_summary)
        from .segmentation import image_background_kind
        if not preflight_python():raise ValueError('输入清理环境尚未安装，请安装 requirements-preflight.txt')
        store.event(job_id,'input_check','检查尺寸文字、主体掩码与遮挡物')
        preflight_command=[preflight_python(),'-u',str(ROOT/'scripts/prepare_local_input.py'),
            '--input',str(input_path),'--source',str(original_path),'--prepared',str(prepared_path),
            '--output',str(directory),'--kind',image_background_kind(original_path),
            '--object-label',category if category not in {'unknown','other'} else job['request'].get('object_label','')]
        if segmentation_summary:preflight_command.append('--presegmented')
        if not remove_background:preflight_command.append('--keep-background')
        with (directory/'input_preflight.log').open('wb') as log:
            process=subprocess.Popen(preflight_command,stdout=log,stderr=subprocess.STDOUT,cwd=str(ROOT),
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            preflight_started=time.monotonic()
            while process.poll() is None:
                check_cancelled()
                if time.monotonic()-preflight_started>300:raise ValueError('输入清理超过 5 分钟，请查看 input_preflight.log')
                time.sleep(.25)
        check_cancelled()
        if process.returncode:raise ValueError('输入清理检查失败，未绕过质量检查继续生成；详情见 input_preflight.log')
        input_quality=json.loads((directory/'input_quality.json').read_text(encoding='utf-8'))
        input_path=directory/'cleaned.png'
        store.event(job_id,'input_checked','输入检查已完成',
                    cleaned_url=f'/api/jobs/{job_id}/files/cleaned.png',
                    input_overlay_url=f'/api/jobs/{job_id}/files/input_overlay.png',
                    input_quality_url=f'/api/jobs/{job_id}/files/input_quality.json',input_quality=input_quality)
        if input_quality['status']=='blocked':
            raise InputNeedsAttention('；'.join(reason['message'] for reason in input_quality['reasons']))
        def run_worker(command,log_path,timeout,progress_path=None):
            nonlocal process
            seen=None;started=time.monotonic()
            with log_path.open('wb') as log:
                process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,cwd=str(ROOT),
                                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                while True:
                    check_cancelled()
                    if progress_path:
                        try:
                            value=json.loads(progress_path.read_text(encoding='utf-8'))
                            marker=(value['sequence'],value['stage'])
                            if marker!=seen:
                                store.event(job_id,value['stage'],value['message']);seen=marker
                        except (OSError,ValueError,KeyError):pass
                    if process.poll() is not None:break
                    if time.monotonic()-started>timeout:raise ValueError('本地处理超时，已停止本次任务，请查看阶段日志')
                    time.sleep(.25)
                check_cancelled()
            return process.returncode
        engines=[engine]
        alternative='triposr' if engine=='hunyuan-mini' else 'hunyuan-mini'
        if job['request'].get('local_auto_retry',True) and engine_status(alternative)['available']:
            engines.append(alternative)
        attempts=[];summary=None;quality=None
        def publish_attempts():
            manifest={'max_attempts':len(engines),'category':category,'attempts':attempts,
                      'policy':'At most one local alternative; never retry input blockers, never invoke paid providers'}
            (directory/'attempts.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            store.event(job_id,'geometry_checked','输出检查记录已保存',output_attempts=attempts,
                        output_quality=quality,output_quality_url=f'/api/jobs/{job_id}/files/geometry_quality.json')
        for index,candidate_engine in enumerate(engines,1):
            candidate=directory/'attempts'/('%02d_%s'%(index,candidate_engine));candidate.mkdir(parents=True,exist_ok=True)
            hunyuan=candidate_engine=='hunyuan-mini'
            detail=job['request'].get('local_quality','balanced')=='structure'
            resolution=(384 if detail else 256) if hunyuan else (256 if detail else 192)
            command=[local_python(candidate_engine),'-u',str(ROOT/'scripts'/('generate_hunyuan3d.py' if hunyuan else 'generate_local3d.py')),
                     '--input',str(input_path),'--output',str(candidate),'--resolution',str(resolution),'--keep-background']
            if hunyuan:command+=['--steps','50' if detail else '30']
            store.event(job_id,'shape_attempt','本地生成尝试 %d/%d：%s'%(index,len(engines),candidate_engine))
            code=run_worker(command,candidate/'local3d.log',1200,candidate/'local_progress.json')
            item={'index':index,'engine':candidate_engine,'status':'worker_failed',
                  'candidate_url':f'/api/jobs/{job_id}/attempts/{index}/model.glb'}
            if code or not (candidate/'model.glb').exists():
                item['message']='本地生成未成功，日志保留';attempts.append(item);publish_attempts()
                if index<len(engines):
                    store.event(job_id,'output_retry','首次生成未成功，改用另一本地模型，最多再尝试一次');continue
                raise ValueError('本地生成尝试均未成功，日志保留；未发布模型')
            store.event(job_id,'geometry_check','检查输出体积、方块退化和几何连通片')
            quality_command=[local_python(candidate_engine),'-u',str(ROOT/'scripts/analyze_geometry.py'),
                             '--input',str(candidate/'model.glb'),'--output',str(candidate/'geometry_quality.json'),'--category',category]
            if run_worker(quality_command,candidate/'geometry_check.log',120):
                raise ValueError('输出几何检查未能完成，未发布未经检查的候选')
            quality=json.loads((candidate/'geometry_quality.json').read_text(encoding='utf-8'))
            shutil.copyfile(candidate/'geometry_quality.json',directory/'geometry_quality.json')
            item.update(status='geometry_blocked' if quality['status']=='blocked' else 'geometry_pass',quality=quality)
            attempts.append(item);publish_attempts()
            if quality['status']=='blocked':
                if index<len(engines):
                    store.event(job_id,'output_retry','输出几何异常，改用另一本地模型，最多再尝试一次');continue
                raise OutputNeedsAttention('；'.join(reason['message'] for reason in quality['reasons']))
            summary=json.loads((candidate/'local_summary.json').read_text(encoding='utf-8'))
            summary['quality_profile']=job['request'].get('local_quality','balanced')
            for filename in ['model.glb','foreground.png','model_input.png','local3d.log']:
                shutil.copyfile(candidate/filename,directory/filename)
            summary.update(actual_engine=candidate_engine,geometry_quality=quality,attempts=attempts)
            store.event(job_id,'geometry_pass','输出几何检查通过，继续文件校验；外观仍需审核',actual_engine=candidate_engine)
            break
        if summary is None:raise OutputNeedsAttention('未产生通过输出检查的候选')
        summary['segmentation_selection']=selection
        summary['total_local_wall_seconds']=round(time.monotonic()-pipeline_started,3)
        summary['generator_background_method']=summary['background_method']
        summary['background_method']=input_quality['method']
        summary['input_preparation']=input_quality
        if segmentation_summary:
            summary['segmentation']=segmentation_summary
        temporary=directory/'local_summary.enriched.tmp'
        temporary.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        for attempt in range(12):
            try:
                temporary.replace(directory/'local_summary.json')
                break
            except PermissionError:
                if attempt==11: raise
                time.sleep(.025*(attempt+1))
        return summary
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        GPU_LOCK.release()
