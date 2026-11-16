"""Local single-user workbench. Bind to loopback; not a multi-tenant server."""
import hashlib
import io
import json
import os
import uuid
import threading
import subprocess
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from .models import JobRequest, ReviewRequest, AssetEditRequest,VersionAnnotation,ReferenceViews
from .models import PartExportRequest,PartPromptRequest,AlternativeRequest,SemanticScanRequest
from .models import PartReferenceRequest,PartRegenerationRequest,PartSurfaceRepairRequest,PartOptimizationRequest
from .part_regeneration import start_surface_repair
from .part_optimization import start_optimization
from .material_presets import prepare_preset
from .textures import texture_image
from .part_regeneration import start_reference,start_regeneration,state_result as part_task_result,folder_for as part_task_folder,cancel_task as cancel_part_task,recover_part_regenerations
from .part_prompt import propose_part
from .completion_preview import preview_completion
from .semantic_parts import semantic_status,start_scan,scan_result,scan_folder,recover_interrupted_scans
from .asset_editor import catalog as asset_catalog,edit_asset,deduplicate_model,source_for,inspect_quality,plan_completion
from .detection import analyze_image, detector_status, DETECTOR_REVISION
from .local3d import local3d_status
from .segmentation import segmentation_status
from .preflight import preflight_status
from .pipeline import run_job, write_json
from .store import Store, now

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
MAX_UPLOAD = 12 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 24_000_000


def create_app(data_dir=None):
    store = Store(Path(data_dir or os.environ.get("IMG3D_DATA_DIR", ROOT / ".data")))
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="img3d")

    @asynccontextmanager
    async def lifespan(application):
        recover_interrupted_scans(store)
        recover_part_regenerations(store)
        # Local deterministic steps can restart. Remote submissions never repeat.
        for job in store.jobs():
            if job["status"] in ("queued", "running"):
                if job["request"]["route"] == "meshy" and job.get("submission_started") and not job.get("provider_task_id"):
                    store.event(job["id"], "attention", "服务重启时云端提交状态不确定，请核对供应商后台", status="awaiting_input")
                else:
                    executor.submit(run_job, store, job["id"])
        for image in store.images():
            if image.get("analysis", {}).get("status") in ("queued", "running"):
                if detector_status()["available"]:
                    executor.submit(analyze_image, store, image["id"])
                else:
                    store.update_image(image["id"], lambda item: item.update(analysis={"status": "failed", "objects": [], "error": "识别服务重启，请在模型准备好后重试"}))
        yield
        executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(title="FORM · img_to3D", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.executor = executor

    @app.post('/api/material-presets/{name}/prepare')
    def prepare_example_material(name:str):
        try:return prepare_preset(store,name)
        except ValueError as exc:raise HTTPException(409,str(exc))
    edit_locks={}

    @app.middleware("http")
    async def local_origin_guard(request: Request, call_next):
        # No cross-origin access from arbitrary websites to the local paid API.
        origin = request.headers.get("origin")
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return Response("Host not allowed", status_code=403)
        port = request.url.port or 80
        allowed = {"http://127.0.0.1:%s" % port, "http://localhost:%s" % port,
                   "http://127.0.0.1:5173", "http://localhost:5173", "http://testserver"}
        if request.url.path.startswith("/api") and origin and origin not in allowed:
            return Response("Origin not allowed", status_code=403)
        return await call_next(request)

    def find_job(job_id):
        item = store.job(job_id)
        if not item:
            raise HTTPException(404, "任务不存在")
        return item

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "mode": "local_single_user"}

    @app.get("/api/config")
    def configuration():
        return {"providers": {"local": local3d_status(), "assistant": {"available": True}, "template": {"available": True}, "meshy": {"available": bool(os.getenv("MESHY_API_KEY"))}},
                "max_upload_mb": 12, "templates": ["shelf", "table", "cabinet"], "detection": detector_status(),
                "segmentation": "auto_sam2_or_basic", "target_segmentation":segmentation_status(), "semantic_parts":semantic_status(), "input_preparation":preflight_status(), "automatic_inpainting": False}

    @app.post("/api/images", status_code=201)
    async def upload(file: UploadFile = File(...)):
        content = await file.read(MAX_UPLOAD + 1)
        await file.close()
        if len(content) > MAX_UPLOAD:
            raise HTTPException(413, "图片不能超过 12 MB")

        def decode_and_save():
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(content)) as source:
                        if source.format not in ("JPEG", "PNG", "WEBP"):
                            raise ValueError("仅支持 JPG、PNG 和 WebP 图片")
                        if source.width * source.height > 24_000_000 or min(source.size) < 32:
                            raise ValueError("图片至少 32 × 32 像素，总像素不得超过 2400 万")
                        image = ImageOps.exif_transpose(source).convert("RGBA")
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise ValueError("图片无法解码或像素数超出限制") from exc
            image_id = uuid.uuid4().hex
            directory = store.root / "images" / image_id
            directory.mkdir(parents=True)
            (directory / "original.bin").write_bytes(content)
            image.save(directory / "normalized.png", "PNG")
            preview = image.copy()
            preview.thumbnail((1600, 1600))
            preview.save(directory / "preview.png", "PNG")
            filename = (file.filename or "image").replace("\\", "/").rsplit("/", 1)[-1][:200]
            item = {"id": image_id, "name": filename, "width": image.width, "height": image.height,
                    "sha256": hashlib.sha256(content).hexdigest(), "created_at": now(),
                    "normalized_path": "images/%s/normalized.png" % image_id,
                    "preview_url": "/api/images/%s/preview" % image_id}
            cached = next((existing.get("analysis") for existing in store.images()
                           if existing.get("sha256") == item["sha256"] and existing.get("analysis", {}).get("status") == "completed"
                           and existing["analysis"].get("detector_revision") == DETECTOR_REVISION), None)
            if cached:
                item["analysis"] = cached
            store.put_image(item)
            return item
        try:
            return await run_in_threadpool(decode_and_save)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/images/{image_id}/preview")
    def image_preview(image_id: str):
        item = store.image(image_id)
        if not item:
            raise HTTPException(404, "图片不存在")
        return FileResponse(store.root / "images" / item["id"] / "preview.png", media_type="image/png")

    @app.get('/api/images/{image_id}/texture/{slot}')
    def preview_texture(image_id:str,slot:str):
        if slot not in {'base_color_image','normal_image','roughness_image'}:raise HTTPException(404,'贴图通道不存在')
        item=store.image(image_id)
        if not item:raise HTTPException(404,'图片不存在')
        output=io.BytesIO();texture_image(store.root/'images'/item['id']/'normalized.png',slot).save(output,format='PNG')
        return Response(output.getvalue(),media_type='image/png')

    @app.get("/api/images/{image_id}")
    def get_image(image_id: str):
        item = store.image(image_id)
        if not item:
            raise HTTPException(404, "图片不存在")
        if item.get("analysis", {}).get("status") == "completed" and item["analysis"].get("detector_revision") != DETECTOR_REVISION:
            item.pop("analysis")
        return item

    @app.post("/api/images/{image_id}/analysis", status_code=202)
    def analyze(image_id: str):
        image = store.image(image_id)
        if not image:
            raise HTTPException(404, "图片不存在")
        if not detector_status()["available"]:
            raise HTTPException(409, "本地识别模型尚未准备好，请先安装检测模型与运行环境")
        scheduled = [False]
        def enqueue(item):
            current = item.get("analysis", {})
            fresh = current.get("status") == "completed" and current.get("detector_revision") == DETECTOR_REVISION
            if current.get("status") not in ("queued", "running") and not fresh:
                item["analysis"] = {"status": "queued", "objects": []}
                scheduled[0] = True
        image = store.update_image(image_id, enqueue)
        if scheduled[0]:
            executor.submit(analyze_image, store, image_id)
        return image

    @app.get("/api/jobs")
    def jobs():
        return store.jobs()

    @app.post("/api/jobs", status_code=202)
    def create_job(body: JobRequest, idempotency_key: str = Header(default="", max_length=200)):
        if not store.image(body.image_id):
            raise HTTPException(404, "请先上传商品图片")
        if any(not store.image(identity) for identity in body.reference_image_ids):raise HTTPException(404,'参考图片不存在')
        if body.route == "meshy" and not os.getenv("MESHY_API_KEY"):
            raise HTTPException(409, "尚未配置 Meshy API 密钥，可选择本地自动生成或对话看图建模")
        local_status = local3d_status() if body.route == "local" else {}
        selected_local = local_status.get("engines", {}).get(body.local_engine, local_status if body.local_engine == "triposr" else {})
        if body.route == "local" and not selected_local.get("available"):
            raise HTTPException(409, "本地图生 3D 尚未就绪，请先安装本地模型并完成运行环境检查")
        if body.route=='local' and body.local_remove_background and body.local_segmentation=='sam2' and not segmentation_status()['available']:
            raise HTTPException(409,'SAM 2 精细分割尚未准备好，请完成安装与实际运行验证')
        request = body.model_dump()
        digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        item = {"id": uuid.uuid4().hex, "name": body.name, "created_at": now(), "updated_at": now(),
                "status": "queued", "stage": "queued", "request": request, "events": [], "review_status": "pending",
                "reconstruction_strategy":{"mode":"single_primary_view","primary_image_id":body.image_id,"reference_image_ids":body.reference_image_ids,"references_used_for_geometry":False},
                "provider_task_id": None, "submission_started": False, "error": None}
        try:
            item, created = store.create_job(item, idempotency_key, digest)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if created:
            executor.submit(run_job, store, item["id"])
        return item

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return find_job(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        find_job(job_id)
        def mutate(item):
            if item["status"] not in ("queued", "running", "awaiting_input", "awaiting_assistant"):
                raise HTTPException(409, "当前状态不能取消")
            item.update(status="cancelled", stage="cancelled")
            item["events"].append({"at": now(), "stage": "cancelled", "message": "已停止本地处理；已提交的云端任务可能仍会计费"})
        return store.update(job_id, mutate)

    @app.post("/api/jobs/{job_id}/resume")
    def resume(job_id: str):
        find_job(job_id)
        def mutate(item):
            if item["status"] != "awaiting_input" or not item.get("provider_task_id"):
                raise HTTPException(409, "没有可安全恢复查询的云端任务 ID，请核对供应商后台")
            item.update(status="queued", error=None)
        item = store.update(job_id, mutate, allow_cancelled=True)
        executor.submit(run_job, store, job_id)
        return item

    @app.post("/api/jobs/{job_id}/review")
    def review(job_id: str, body: ReviewRequest):
        find_job(job_id)
        def mutate(item):
            if item["status"] != "awaiting_review":
                raise HTTPException(409, "只有待审核的模型可以提交审核")
            item["status"] = "completed" if body.decision == "accept" else "rejected"
            item["review_status"] = "accepted" if body.decision == "accept" else "rejected"
            item["review"] = {"decision": body.decision, "note": body.note, "at": now()}
            item["report"]["review_status"] = item["review_status"]
            item["report"]["review"] = item["review"]
        item = store.update(job_id, mutate, allow_cancelled=True)
        directory = store.root / "jobs" / job_id
        write_json(directory / "quality_report.json", item["report"])
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        metadata["review_status"] = item["review_status"]
        write_json(directory / "metadata.json", metadata)
        return item

    @app.get("/api/jobs/{job_id}/files/{filename}")
    def artifact(job_id: str, filename: str):
        item = find_job(job_id)
        if filename not in {"model.glb", "prepared.png", "mask.png", "quality_report.json", "metadata.json", "preview.png", "source.blend", "modeling_notes.json", "foreground.png", "model_input.png", "local_summary.json", "segmented.png", "segmentation_mask.png", "segmentation_overlay.png", "segmentation_preview.png", "segmentation_summary.json", "cleaned.png", "cleaned_preview.png", "cleanup_mask.png", "input_overlay.png", "input_quality.json", "foreground_before_cleanup.png", "geometry_quality.json", "attempts.json"}:
            raise HTTPException(404, "文件不存在")
        if filename in {"model.glb", "quality_report.json", "metadata.json"} and not item.get("model_url"):
            raise HTTPException(409, "模型尚未完成检查")
        path = store.root / "jobs" / item["id"] / filename
        if not path.is_file():
            raise HTTPException(404, "文件尚未生成")
        mime = "model/gltf-binary" if filename.endswith(".glb") else None
        return FileResponse(path, media_type=mime, filename=filename if not filename.endswith(".png") else None)

    @app.get('/api/jobs/{job_id}/attempts/{index}/{filename}')
    def diagnostic_attempt(job_id:str,index:int,filename:str):
        item=find_job(job_id)
        if filename not in {'model.glb','geometry_quality.json','local_summary.json'}:raise HTTPException(404,'文件不存在')
        attempt=next((value for value in item.get('output_attempts',[]) if value['index']==index),None)
        if not attempt or attempt['engine'] not in {'triposr','hunyuan-mini'}:raise HTTPException(404,'尝试不存在')
        path=store.root/'jobs'/item['id']/'attempts'/('%02d_%s'%(index,attempt['engine']))/filename
        if not path.is_file():raise HTTPException(404,'诊断文件尚未生成')
        return FileResponse(path,media_type='model/gltf-binary' if filename=='model.glb' else None,
                            filename='diagnostic_%d_%s'%(index,filename))

    @app.get('/api/jobs/{job_id}/asset')
    def get_asset(job_id:str,version:str=None):
        job=find_job(job_id)
        try:return asset_catalog(store,job,version)
        except ValueError as exc:raise HTTPException(409,str(exc))

    @app.post('/api/jobs/{job_id}/asset/completion-plan')
    async def complete_part_plan(job_id:str,body:AssetEditRequest):
        job=find_job(job_id)
        try:return await run_in_threadpool(plan_completion,store,job,body)
        except ValueError as exc:raise HTTPException(409,str(exc))
        except subprocess.TimeoutExpired:raise HTTPException(422,'范围诊断超时，原模型保留')

    @app.post('/api/jobs/{job_id}/asset/semantic-scans')
    async def start_semantic_scan(job_id:str,body:SemanticScanRequest):
        job=find_job(job_id)
        try:return await run_in_threadpool(start_scan,store,job,body,executor)
        except ValueError as exc:raise HTTPException(409,str(exc))

    @app.get('/api/jobs/{job_id}/asset/semantic-scans/{identity}')
    def get_semantic_scan(job_id:str,identity:str):
        job=find_job(job_id)
        try:return scan_result(store,job,identity)
        except ValueError as exc:raise HTTPException(404,str(exc))

    @app.get('/api/jobs/{job_id}/asset/semantic-scans/{identity}/{filename}')
    def semantic_scan_file(job_id:str,identity:str,filename:str):
        job=find_job(job_id)
        try:folder=scan_folder(store,job,identity)
        except ValueError as exc:raise HTTPException(404,str(exc))
        if filename!='style.glb' or not (folder/'ready.json').is_file() or json.loads((folder/'status.json').read_text(encoding='utf-8')).get('status')!='ready':raise HTTPException(404,'识别预览尚未完成或未通过检查')
        return FileResponse(folder/filename,media_type='model/gltf-binary')

    @app.post('/api/jobs/{job_id}/asset/completion-preview')
    async def complete_part_preview(job_id:str,body:AssetEditRequest):
        job=find_job(job_id)
        try:return await run_in_threadpool(preview_completion,store,job,body)
        except ValueError as exc:raise HTTPException(409,str(exc))
        except subprocess.TimeoutExpired:raise HTTPException(422,'部件预览超时，原模型保留；可缩小到单个部件后重试')

    @app.post('/api/jobs/{job_id}/asset/part-optimizations')
    async def auto_optimize_part(job_id:str,body:PartOptimizationRequest):
        try:return await run_in_threadpool(start_optimization,store,find_job(job_id),body,executor)
        except ValueError as exc:raise HTTPException(409,str(exc))

    @app.post('/api/jobs/{job_id}/asset/part-surface-repairs')
    async def preserve_part_surface(job_id:str,body:PartSurfaceRepairRequest):
        try:return await run_in_threadpool(start_surface_repair,store,find_job(job_id),body,executor)
        except ValueError as exc:raise HTTPException(409,str(exc))

    @app.post('/api/jobs/{job_id}/asset/part-reference-scans')
    async def start_part_reference(job_id:str,body:PartReferenceRequest):
        job=find_job(job_id)
        try:return await run_in_threadpool(start_reference,store,job,body,executor)
        except ValueError as exc:raise HTTPException(409,str(exc))

    @app.get('/api/jobs/{job_id}/asset/part-reference-scans/{identity}')
    def get_part_reference(job_id:str,identity:str):
        try:return part_task_result(store,find_job(job_id),identity,True)
        except ValueError as exc:raise HTTPException(404,str(exc))

    @app.post('/api/jobs/{job_id}/asset/part-reference-scans/{identity}/cancel')
    def cancel_part_reference(job_id:str,identity:str):
        try:return cancel_part_task(store,find_job(job_id),identity,True)
        except ValueError as exc:raise HTTPException(404,str(exc))

    @app.get('/api/jobs/{job_id}/asset/part-reference-scans/{identity}/{filename}')
    def part_reference_file(job_id:str,identity:str,filename:str):
        import re
        try:folder=part_task_folder(store,find_job(job_id),identity,True)
        except ValueError as exc:raise HTTPException(404,str(exc))
        if not re.fullmatch(r'[a-f0-9]{32}(_preview)?\.png',filename)or json.loads((folder/'status.json').read_text(encoding='utf-8')).get('status')!='ready'or not(folder/filename).is_file():raise HTTPException(404,'参考图不存在或未完成')
        return FileResponse(folder/filename,media_type='image/png')

    @app.post('/api/jobs/{job_id}/asset/part-regenerations')
    async def regenerate_part(job_id:str,body:PartRegenerationRequest):
        try:return await run_in_threadpool(start_regeneration,store,find_job(job_id),body,executor)
        except ValueError as exc:raise HTTPException(409,str(exc))

    @app.get('/api/jobs/{job_id}/asset/part-regenerations/{identity}')
    def get_part_regeneration(job_id:str,identity:str):
        try:return part_task_result(store,find_job(job_id),identity)
        except ValueError as exc:raise HTTPException(404,str(exc))

    @app.post('/api/jobs/{job_id}/asset/part-regenerations/{identity}/cancel')
    def cancel_regenerated_part(job_id:str,identity:str):
        try:return cancel_part_task(store,find_job(job_id),identity)
        except ValueError as exc:raise HTTPException(404,str(exc))

    @app.get('/api/jobs/{job_id}/asset/part-regenerations/{identity}/candidates/{seed}/{filename}')
    def part_seed_file(job_id:str,identity:str,seed:int,filename:str):
        try:folder=part_task_folder(store,find_job(job_id),identity)
        except ValueError as exc:raise HTTPException(404,str(exc))
        state=json.loads((folder/'status.json').read_text(encoding='utf-8'))
        if seed not in(42,77,123)or state.get('status')not in('ready','failed'):raise HTTPException(404,'候选尚未完成')
        child=folder/'candidates'/f'seed_{seed}'
        if filename=='comparison.png':path=child/filename;mime='image/png'
        elif filename in('part.glb','diagnostic.glb')and(child/'checks.json').is_file():path=child/'preview'/filename;mime='model/gltf-binary'
        else:raise HTTPException(404,'候选文件不存在')
        if not path.is_file():raise HTTPException(404,'候选文件不存在')
        return FileResponse(path,media_type=mime)

    @app.get('/api/jobs/{job_id}/asset/part-regenerations/{identity}/views/{index}/{filename}')
    def part_extra_view_file(job_id:str,identity:str,index:int,filename:str):
        try:folder=part_task_folder(store,find_job(job_id),identity)
        except ValueError as exc:raise HTTPException(404,str(exc))
        state=json.loads((folder/'status.json').read_text(encoding='utf-8'))
        path=folder/'views'/str(index)/filename
        if index not in range(3)or filename not in('association.png','before.png','after.png')or state.get('status')not in('ready','needs_input','failed')or not path.is_file():raise HTTPException(404,'补充视图记录尚未完成')
        return FileResponse(path,media_type='image/png')

    @app.get('/api/jobs/{job_id}/asset/part-regenerations/{identity}/{filename}')
    def regenerated_part_file(job_id:str,identity:str,filename:str):
        try:folder=part_task_folder(store,find_job(job_id),identity)
        except ValueError as exc:raise HTTPException(404,str(exc))
        state=json.loads((folder/'status.json').read_text(encoding='utf-8'))
        if filename in('association.png','comparison.png','before.png','after.png')and state.get('method')=='photo_guided_auto'and state.get('status')in('ready','needs_input','failed')and(folder/filename).is_file():
            return FileResponse(folder/filename,media_type='image/png')
        if filename=='generated.glb'and state.get('generated_valid'):path=folder/'generated/model.glb'
        elif filename in('part.glb','diagnostic.glb')and state.get('status')=='ready'and(folder/'ready.json').is_file():path=folder/'preview'/filename
        else:raise HTTPException(404,'候选尚未完成或未通过检查')
        return FileResponse(path,media_type='model/gltf-binary',filename=filename)

    @app.get('/api/jobs/{job_id}/asset/completion-previews/{preview_id}/{filename}')
    def completion_preview_file(job_id:str,preview_id:str,filename:str):
        import re
        job=find_job(job_id)
        if not re.fullmatch(r'[a-f0-9]{32}',preview_id) or filename!='diagnostic.glb':raise HTTPException(404,'预览不存在')
        folder=store.root/'jobs'/job['id']/'completion_previews'/preview_id
        if not (folder/'ready.json').is_file():raise HTTPException(404,'预览未完成')
        return FileResponse(folder/filename,media_type='model/gltf-binary')

    @app.post('/api/jobs/{job_id}/asset/part-proposal')
    async def part_proposal(job_id:str,body:PartPromptRequest):
        job=find_job(job_id)
        try:return await run_in_threadpool(propose_part,store,job,body)
        except ValueError as exc:raise HTTPException(409,str(exc))
        except subprocess.TimeoutExpired:raise HTTPException(422,'辅助分割超时，原模型和原选区保留')

    @app.post('/api/jobs/{job_id}/asset/export-parts')
    async def export_selected_parts(job_id:str,body:PartExportRequest):
        job=find_job(job_id)
        def work():
            source=source_for(store,job,body.version)
            revision=(ROOT/'scripts/part_tools.py').read_bytes()+(ROOT/'scripts/edit_asset.py').read_bytes()
            digest=hashlib.sha256(source.read_bytes()+revision+json.dumps(sorted(set(body.part_ids))).encode()).hexdigest()
            folder=store.root/'jobs'/job_id/'part_exports'/digest;folder.mkdir(parents=True,exist_ok=True)
            with edit_locks.setdefault('export-'+job_id,threading.Lock()):
                if not (folder/'validated.json').exists():
                    write_json(folder/'request.json',{'operation':'export_parts','part_ids':body.part_ids})
                    from .local3d import local_python
                    interpreter=local_python('hunyuan-mini') or local_python('triposr')
                    if not interpreter:raise ValueError('本地导出环境未准备好')
                    with (folder/'worker.log').open('wb') as log:
                        r=subprocess.run([interpreter,'-X','utf8',str(ROOT/'scripts/edit_asset.py'),'--input',str(source),'--request',str(folder/'request.json'),'--output',str(folder)],stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if r.returncode:raise ValueError('部件导出失败，请检查选择；原模型保留')
                    from .geometry import validate_glb
                    write_json(folder/'validated.json',validate_glb(folder/'model.glb'))
            return folder/'model.glb'
        try:path=await run_in_threadpool(work)
        except ValueError as exc:raise HTTPException(409,str(exc))
        except subprocess.TimeoutExpired:raise HTTPException(422,'部件导出超时')
        return FileResponse(path,media_type='model/gltf-binary',filename='selected_parts.glb')

    def reconstruction_key(request):
        keys=('image_id','target','strokes','local_remove_background','local_segmentation','object_category','reference_image_ids')
        def canonical(value):
            if isinstance(value,bool):return value
            if isinstance(value,(int,float)):return float(value)
            if isinstance(value,dict):return {k:canonical(v) for k,v in value.items()}
            if isinstance(value,list):return [canonical(v) for v in value]
            return value
        return json.dumps(canonical({k:request.get(k) for k in keys}),sort_keys=True)

    @app.get('/api/jobs/{job_id}/reconstruction-comparison')
    def reconstruction_comparison(job_id:str):
        source=find_job(job_id);key=reconstruction_key(source['request']);items=[]
        for job in store.jobs():
            if job.get('test_clone_of') and job['id']!=job_id:continue
            if job['request']['route']!='local' or reconstruction_key(job['request'])!=key:continue
            items.append({k:job.get(k) for k in ('id','name','status','stage','model_url','actual_engine','metrics','review_status','output_quality','error') } | {'requested_engine':job['request']['local_engine'],'quality':job['request'].get('local_quality','balanced')})
        return {'source_job':job_id,'reference_url':f'/api/images/{source["request"]["image_id"]}/preview','candidates':items,'similarity_measured':False}

    @app.post('/api/jobs/{job_id}/reconstruction-comparison')
    def create_alternative(job_id:str,body:AlternativeRequest):
        source=find_job(job_id);values={**source['request'],'route':'local','local_engine':body.engine,'local_quality':body.quality,'local_auto_retry':False,'allow_external':False,'name':'本地生成对照 · '+source['name'][:55]+' · '+body.engine+' · '+body.quality}
        request=JobRequest(**values)
        # Reuse exact input + engine, even when the button is clicked repeatedly.
        for job in store.jobs():
            if job.get('test_clone_of'):continue
            if job['request']['route']=='local' and reconstruction_key(job['request'])==reconstruction_key(values) and job['request'].get('local_engine')==body.engine and job['request'].get('local_quality','balanced')==body.quality and job['status']!='cancelled' and (not job.get('actual_engine') or job['actual_engine']==body.engine):return job
        key='engine-comparison-'+hashlib.sha256((reconstruction_key(values)+body.engine+body.quality).encode()).hexdigest()
        return create_job(request,key)

    @app.post('/api/jobs/{job_id}/reference-views')
    def reference_views(job_id:str,body:ReferenceViews):
        job=find_job(job_id)
        if job['request']['image_id'] in body.image_ids:raise HTTPException(422,'主图已保留，无需重复添加')
        if any(not store.image(i) for i in body.image_ids):raise HTTPException(404,'参考图片不存在')
        with edit_locks.setdefault(job_id,threading.Lock()):
            job=store.update(job_id,lambda item:item.update(reference_image_ids=body.image_ids))
        return asset_catalog(store,job)

    @app.post('/api/jobs/{job_id}/assets/{version}/annotation')
    def annotate_asset(job_id:str,version:str,body:VersionAnnotation):
        find_job(job_id)
        with edit_locks.setdefault(job_id,threading.Lock()):
            def change(item):
                entry=next((v for v in item.get('asset_versions',[]) if v['id']==version),None)
                if not entry:raise HTTPException(404,'编辑版本不存在')
                entry.update(note=body.note,archived=body.archived)
            job=store.update(job_id,change)
            path=store.root/'jobs'/job_id/'assets'/version/'manifest.json'
            value=json.loads(path.read_text(encoding='utf-8'));value.update(note=body.note,archived=body.archived);write_json(path,value)
        return asset_catalog(store,job,version)

    @app.post('/api/jobs/{job_id}/asset/compact-storage')
    def compact_storage(job_id:str):
        job=find_job(job_id);results=[]
        with edit_locks.setdefault(job_id,threading.Lock()):
            job=find_job(job_id)
            for version in ['original']+[v['id'] for v in job.get('asset_versions',[])]:
                path=source_for(store,job,version);results.append({'version':version,**deduplicate_model(store,job_id,path),'bytes':path.stat().st_size})
        logical=sum(r['bytes'] for r in results);unique={r['sha256']:r['bytes'] for r in results}
        return {'versions':results,'logical_bytes':logical,'unique_content_bytes':sum(unique.values()),'duplicate_content_bytes':logical-sum(unique.values()),'note':'Identical bytes share storage on hardlink capable disks; history is retained.'}

    @app.get('/api/jobs/{job_id}/asset/compare')
    def compare_assets(job_id:str,left:str='original',right:str=None):
        job=find_job(job_id)
        try:
            a=asset_catalog(store,job,left);b=asset_catalog(store,job,right)
        except ValueError as exc:raise HTTPException(409,str(exc))
        aa={p['id']:p for p in a['parts']};bb={p['id']:p for p in b['parts']}
        return {'left':a,'right':b,'delta':{key:b['metrics'][key]-a['metrics'][key] for key in ('parts','triangles','bytes')},
                'added_parts':sorted(bb.keys()-aa.keys()),'removed_parts':sorted(aa.keys()-bb.keys()),
                'changed_parts':[key for key in aa.keys()&bb.keys() if aa[key]!=bb[key]],'appearance_similarity':'not_measured'}

    @app.get('/api/jobs/{job_id}/asset/quality')
    async def asset_quality(job_id:str,version:str=None):
        job=find_job(job_id)
        try:return await run_in_threadpool(inspect_quality,store,job,version)
        except ValueError as exc:raise HTTPException(409,str(exc))
        except subprocess.TimeoutExpired:raise HTTPException(422,'检查超时，原模型保留')

    @app.post('/api/jobs/{job_id}/asset/versions',status_code=201)
    async def create_asset_version(job_id:str,body:AssetEditRequest):
        find_job(job_id)
        def work():
            with edit_locks.setdefault(job_id,threading.Lock()):return edit_asset(store,job_id,body)
        try:return await run_in_threadpool(work)
        except ValueError as exc:raise HTTPException(409,str(exc))
        except subprocess.TimeoutExpired:raise HTTPException(422,'编辑超时，原版本保留')

    @app.get('/api/jobs/{job_id}/assets/{version}/{filename}')
    def asset_file(job_id:str,version:str,filename:str):
        job=find_job(job_id)
        if filename not in {'model.glb','manifest.json'} or not any(item['id']==version for item in job.get('asset_versions',[])):
            raise HTTPException(404,'编辑版本不存在')
        path=store.root/'jobs'/job['id']/'assets'/version/filename
        if not path.is_file():raise HTTPException(404,'文件不存在')
        return FileResponse(path,media_type='model/gltf-binary' if filename=='model.glb' else None,
                            filename=('edited_'+version[:8]+'.glb') if filename=='model.glb' else filename)

    @app.post('/api/jobs/{job_id}/assets/{version}/review')
    def review_asset_version(job_id:str,version:str,body:ReviewRequest):
        find_job(job_id)
        with edit_locks.setdefault(job_id,threading.Lock()):
            def review_edit(item):
                entry=next((entry for entry in item.get('asset_versions',[]) if entry['id']==version),None)
                if not entry:raise HTTPException(404,'编辑版本不存在')
                if entry.get('review_status')!='unreviewed':raise HTTPException(409,'该编辑版本已审核，请创建新版本后再修改')
                entry['review_status']='accepted' if body.decision=='accept' else 'rejected'
                entry['review']={'decision':body.decision,'note':body.note,'at':now()}
            job=store.update(job_id,review_edit)
            entry=next(entry for entry in job['asset_versions'] if entry['id']==version)
            manifest_path=store.root/'jobs'/job_id/'assets'/version/'manifest.json'
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'));manifest.update(review_status=entry['review_status'],review=entry['review']);write_json(manifest_path,manifest)
            return asset_catalog(store,job,version)

    @app.get("/api/jobs/{job_id}/download")
    def download(job_id: str):
        item = find_job(job_id)
        if not item.get("model_url"):
            raise HTTPException(409, "模型尚未生成")
        output = io.BytesIO()
        directory = store.root / "jobs" / item["id"]
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
            for filename in ["model.glb", "metadata.json", "quality_report.json", "prepared.png"]:
                package.write(directory / filename, filename)
            for filename in ["preview.png", "modeling_notes.json", "foreground.png", "model_input.png", "local_summary.json", "segmented.png", "segmentation_mask.png", "segmentation_overlay.png", "segmentation_summary.json", "cleaned.png", "cleaned_preview.png", "cleanup_mask.png", "input_overlay.png", "input_quality.json", "foreground_before_cleanup.png", "geometry_quality.json", "attempts.json"]:
                if (directory / filename).is_file():
                    package.write(directory / filename, filename)
            package.writestr("README.txt", "FORM 商品资产\n审核状态：%s\n未审核资产属于草稿。尺寸依据、推测内容和检查限制请查看 quality_report.json。\n" % item["review_status"])
        return Response(output.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="asset_%s.zip"' % item["id"][:8]})

    sample_definitions = [
        ("blue_cabinet", "蓝色玻璃边柜", "01_blue_glass_cabinet", "玻璃 / 金属"),
        ("cork_bench", "天然软木长凳", "03_cork_bench", "软木 / 几何结构"),
        ("silver_table", "银色圆形边几", "04_silver_round_table", "金属 / 反射材质"),
        ("floral_chair", "花卉布艺扶手椅", "06_floral_armchair", "软包 / 织物纹理"),
    ]
    sample_root = ROOT / "library" / "models"
    sample_previews = ROOT / "library" / "previews"

    @app.get("/api/samples")
    def samples():
        return [{"id": key, "name": name, "material": material, "model_url": "/api/samples/%s/model" % key,
                 "preview_url": "/api/samples/%s/preview" % key, "source": "existing_reference_asset"}
                for key, name, slug, material in sample_definitions if (sample_root / ("furniture6__" + slug + ".glb")).is_file() and (sample_previews / ("furniture6__" + slug + ".png")).is_file()]

    @app.get("/api/samples/{sample_id}/{kind}")
    def sample_file(sample_id: str, kind: str):
        found = next((entry for entry in sample_definitions if entry[0] == sample_id), None)
        if not found or kind not in ("model", "preview"):
            raise HTTPException(404, "示例不存在")
        path = sample_root / ("furniture6__" + found[2] + ".glb") if kind == "model" else sample_previews / ("furniture6__" + found[2] + ".png")
        if not path.is_file():
            raise HTTPException(404, "示例文件不可用")
        return FileResponse(path, media_type="model/gltf-binary" if kind == "model" else "image/png")

    static = ROOT / "apps" / "web" / "dist"
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(static / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def index(path: str):
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "接口不存在")
        if not (static / "index.html").is_file():
            return {"message": "API 已启动。先执行 npm run build，或通过 npm run dev 启动前端。", "api_docs": "/docs"}
        return FileResponse(static / "index.html")

    return app


app = create_app()
