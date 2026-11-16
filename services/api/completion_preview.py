"""Immutable cut previews, bound to source bytes and the geometry request."""

import hashlib, json, os, subprocess, uuid, threading
from pathlib import Path
from .asset_editor import source_for, ROOT
from .local3d import local_python
from .geometry import validate_glb

RECONSTRUCTION_LOCK = threading.Lock()


def geometry_key(request):
    fields = (
        "base_version",
        "operation",
        "part_ids",
        "face_selection",
        "completion_profile",
        "completion_shape",
        "completion_bounds",
        "detail_level",
        "name",
    )
    data = request.model_dump()
    return hashlib.sha256(
        json.dumps(
            {key: data[key] for key in fields}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def preview_completion(store, job, request):
    if request.operation not in ("complete_part", "reconstruct_parts"):
        raise ValueError("请选择完整部件重建操作")
    if request.completion_preview_id:
        raise ValueError("请提交新的切分范围，不要复用预览编号")
    if job.get("current_asset_version", "original") != request.base_version:
        raise ValueError("编辑版本已变化，请刷新后重试")
    source = source_for(store, job, request.base_version)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    interpreter = local_python("hunyuan-mini") or local_python("triposr")
    if not interpreter:
        raise ValueError("本地几何环境尚未准备好")
    directory = store.root / "jobs" / job["id"] / "completion_previews" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps(request.model_dump(), ensure_ascii=False), encoding="utf-8")
    reconstruct = request.operation == "reconstruct_parts"
    if reconstruct and not RECONSTRUCTION_LOCK.acquire(blocking=False):
        raise ValueError("已有独立部件预览正在计算，请稍后重试")
    try:
        with (directory / "worker.log").open("wb") as log:
            result = subprocess.run(
                [
                    interpreter,
                    "-X",
                    "utf8",
                    str(ROOT / "services/workers/preview_complete_part.py"),
                    "--input",
                    str(source),
                    "--request",
                    str(directory / "request.json"),
                    "--output",
                    str(directory),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=360 if reconstruct else 180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    finally:
        if reconstruct:
            RECONSTRUCTION_LOCK.release()
    if result.returncode:
        errors = [
            line.split("ValueError: ", 1)[1]
            for line in (directory / "worker.log").read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("ValueError: ")
        ]
        raise ValueError(errors[-1][:200] if errors else "切分预览未完成，原版本保留")
    if (
        store.job(job["id"]).get("current_asset_version", "original") != request.base_version
        or hashlib.sha256(source.read_bytes()).hexdigest() != digest
    ):
        raise ValueError("预览期间源版本已变化，请重新预览")
    validate_glb(directory / "model.glb")
    validate_glb(directory / "diagnostic.glb")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    record = {
        "request_key": geometry_key(request),
        "source_sha256": digest,
        "model_sha256": manifest["model_sha256"],
        "base_version": request.base_version,
    }
    (directory / "ready.json").write_text(json.dumps(record), encoding="utf-8")
    return {
        "preview_id": directory.name,
        "version": request.base_version,
        "preview_url": f"/api/jobs/{job['id']}/asset/completion-previews/{directory.name}/diagnostic.glb",
        "operation": manifest["operation"],
        "appearance_review": "unreviewed",
        "published": False,
    }


def verified_preview(store, job, request, source):
    directory = store.root / "jobs" / job["id"] / "completion_previews" / request.completion_preview_id
    if not (directory / "ready.json").is_file():
        raise ValueError("预览不存在或尚未完成，请重新预览")
    record = json.loads((directory / "ready.json").read_text(encoding="utf-8"))
    if (
        record["request_key"] != geometry_key(request)
        or record["source_sha256"] != hashlib.sha256(source.read_bytes()).hexdigest()
    ):
        raise ValueError("范围、选区或源模型已变化，请重新预览后保存")
    if hashlib.sha256((directory / "model.glb").read_bytes()).hexdigest() != record["model_sha256"]:
        raise ValueError("预览文件校验失败，请重新预览")
    return directory
