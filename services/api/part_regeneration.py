"""Original-photo part regeneration, immutable proposals, explicit exact-byte adoption."""

import hashlib, json, os, re, shutil, subprocess, time, uuid
from pathlib import Path
from .asset_editor import ROOT, source_for
from .glb_document import read_glb, parts_catalog
from .local3d import local_python, engine_status
from .segmentation import segmentation_python, segmentation_status
from .detection import detector_status
from .geometry import validate_glb
from .gpu import GPU_LOCK


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".writing")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    # Windows readers may briefly open without FILE_SHARE_DELETE. Preserve
    # atomic replacement; retry the rename instead of truncating a live file.
    for attempt in range(20):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(min(0.01 * 2**attempt, 0.25))


def scope(source, ids):
    doc, _, _ = read_glb(source)
    parts = parts_catalog(doc)
    chosen = [p for p in parts if p["id"] in ids]
    if len(chosen) != len(set(ids)):
        raise ValueError("所选部件已变化，请刷新后重试")
    groups = {p.get("logical_group_id") or p["id"] for p in chosen}
    if len(groups) != 1:
        raise ValueError("请先点选一个完整部件组")
    group = next(iter(groups))
    all_parts = [p for p in parts if (p.get("logical_group_id") or p["id"]) == group]
    if any(p.get("semantic_kind") == "unknown" for p in all_parts):
        raise ValueError("未确认区域不能整体重生成，请先确认部件归属")
    return sorted(p["id"] for p in all_parts)


def preflight(source, ids, kind, allow_uv=False):
    """Refuse unsupported sources before spending GPU time."""
    ids = scope(source, ids)
    doc, _, _ = read_glb(source)
    parts = [p for p in parts_catalog(doc) if p["id"] in ids]
    if doc.get("animations") or doc.get("skins"):
        raise ValueError("带动画或骨骼的模型暂不支持部件重生成")
    if len({p["node"] for p in parts}) != 1:
        raise ValueError("跨节点部件暂不自动替换")
    if len({p["material_signature"] for p in parts}) != 1:
        raise ValueError("部件含多种材质，请在局部换材质前重生成")
    allowed = {"pillow": {"pillow"}, "cushion": {"seat", "cushion"}, "bolster": {"bolster"}}[kind]
    if any(p.get("semantic_kind") and p["semantic_kind"] not in allowed for p in parts):
        raise ValueError("所选分组与部件类型不符，请选择对应的靠枕、坐垫或圆柱抱枕")
    for part in parts:
        primitive = doc["meshes"][doc["nodes"][part["node"]]["mesh"]]["primitives"][part["primitive"]]
        material = doc.get("materials", [])[primitive["material"]] if "material" in primitive else {}
        allowed = {"POSITION", "NORMAL", "TEXCOORD_0", "TANGENT"} if allow_uv else {"POSITION", "NORMAL"}
        if (
            set(primitive["attributes"]) - allowed
            or primitive.get("extensions")
            or primitive.get("targets")
            or primitive.get("mode", 4) != 4
        ):
            raise ValueError("带贴图、顶点颜色、形变或压缩的部件暂不替换，请在贴材质前重生成")
        if (
            material.get("extensions")
            or any("Texture" in k for k in material)
            or any("Texture" in k for k in material.get("pbrMetallicRoughness", {}))
        ):
            raise ValueError("带贴图或扩展材质的部件暂不替换，请在贴材质前重生成")
    return ids


def submit_task(executor, worker, store, job_id, identity, folder):
    def finished(future):
        try:
            failure = future.exception()
            state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
            if state.get("status") not in ("queued", "running"):
                return
            if failure is not None:
                import traceback

                (folder / "unexpected_failure.log").write_text(
                    "".join(traceback.format_exception(type(failure), failure, failure.__traceback__)), encoding="utf-8"
                )
            state.update(
                status="cancelled" if (folder / "cancel_requested").exists() else "failed",
                stage="failed",
                error="处理未完成，原模型保留；诊断记录已保存，请重试",
            )
            write_json(folder / "status.json", state)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Could not finalize part task %s", identity)

    try:
        executor.submit(worker, store, job_id, identity).add_done_callback(finished)
    except Exception as exc:
        state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
        state.update(status="failed", stage="failed", error="处理队列不可用，请稍后重试")
        write_json(folder / "status.json", state)
        raise ValueError(state["error"]) from exc


def check_reference_pixels(path):
    from PIL import Image

    with Image.open(path) as image:
        alpha = image.convert("RGBA").getchannel("A")
        bounds = alpha.point(lambda value: 255 if value > 32 else 0).getbbox()
        if not bounds or min(bounds[2] - bounds[0], bounds[3] - bounds[1]) < 96:
            raise ValueError("部件参考的有效区域不足 96 像素，请换用更清晰的部件图后生成")


def folder_for(store, job, identity, reference=False):
    if not re.fullmatch("[a-f0-9]{32}", identity):
        raise ValueError("部件任务不存在")
    folder = (
        store.root / "jobs" / job["id"] / ("part_reference_scans" if reference else "part_regenerations") / identity
    )
    if not (folder / "status.json").is_file():
        raise ValueError("部件任务不存在")
    return folder


def check_source(store, job_id, state):
    job = store.job(job_id)
    if job.get("current_asset_version", "original") != state["version"]:
        raise ValueError("源版本已变化，原模型保留，请重新选择部件")
    source = source_for(store, job, state["version"])
    if digest(source) != state["source_sha256"]:
        raise ValueError("源模型已变化，请重新生成预览")
    return source


def check_photo_inputs(folder, state):
    if (folder / "cancel_requested").exists():
        raise ValueError("已取消，原模型保留")
    if digest(folder / "context.json") != state["context_sha256"]:
        raise ValueError("自动优化请求已变化，请重新开始")
    context = json.loads((folder / "context.json").read_text(encoding="utf-8"))
    photo = Path(context["photo"])
    if not photo.is_file() or digest(photo) != state["image_sha256"]:
        raise ValueError("参考原图已变化或缺失，请重新分析")
    segmented = Path(context["source_folder"]) / "segmented.png"
    if (digest(segmented) if segmented.is_file() else None) != state.get("segmentation_sha256"):
        raise ValueError("整件分割已变化，请重新分析")
    for view in context.get("views", []):
        path = Path(view["photo"])
        if not path.is_file() or digest(path) != state.get("view_images_sha256", {}).get(view["image_id"]):
            raise ValueError("补充视图已变化或缺失，请重新分析")
    return context


def state_result(store, job, identity, reference=False):
    folder = folder_for(store, job, identity, reference)
    state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    result = {
        k: v for k, v in state.items() if k not in ("source_sha256", "scope", "image_sha256", "references_sha256")
    }
    result["published"] = False
    if not reference and state.get("generated_valid"):
        result["generated_url"] = f"/api/jobs/{job['id']}/asset/part-regenerations/{identity}/generated.glb"
    if state.get("method") == "photo_guided_auto" and (folder / "analysis.json").exists():
        result["automatic_plan"] = json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
        for view in result["automatic_plan"].get("additional_views", []):
            if state["status"] in ("ready", "needs_input", "failed"):
                for name in ("association", "before", "after"):
                    if (folder / "views" / str(view["index"]) / (name + ".png")).exists():
                        view[name + "_url"] = (
                            f"/api/jobs/{job['id']}/asset/part-regenerations/{identity}/views/{view['index']}/{name}.png"
                        )
        for name in ("association", "comparison"):
            if state["status"] in ("ready", "needs_input", "failed") and (folder / (name + ".png")).exists():
                result[name + "_url"] = f"/api/jobs/{job['id']}/asset/part-regenerations/{identity}/{name}.png"
        if (folder / "checks.json").exists():
            result["photo_checks"] = json.loads((folder / "checks.json").read_text(encoding="utf-8"))
        if state["status"] in ("ready", "failed"):
            for candidate in result.get("candidate_results", []):
                child = folder / "candidates" / f"seed_{candidate['seed']}"
                if (child / "comparison.png").exists():
                    candidate["comparison_url"] = (
                        f"/api/jobs/{job['id']}/asset/part-regenerations/{identity}/candidates/{candidate['seed']}/comparison.png"
                    )
                if (child / "preview/diagnostic.glb").exists():
                    candidate["preview_url"] = (
                        f"/api/jobs/{job['id']}/asset/part-regenerations/{identity}/candidates/{candidate['seed']}/diagnostic.glb"
                    )
    if state["status"] == "ready":
        if reference:
            data = json.loads((folder / "references.json").read_text(encoding="utf-8"))
            result["candidates"] = [
                {
                    "id": c["id"],
                    "label": c["label"],
                    "preview_url": f"/api/jobs/{job['id']}/asset/part-reference-scans/{identity}/{c['preview']}",
                    "hidden_regions_completed": c.get("hidden_regions_completed"),
                }
                for c in data["candidates"]
            ]
        else:
            manifest = json.loads((folder / "preview/manifest.json").read_text(encoding="utf-8"))
            result.update(
                preview_url=f"/api/jobs/{job['id']}/asset/part-regenerations/{identity}/diagnostic.glb",
                part_url=f"/api/jobs/{job['id']}/asset/part-regenerations/{identity}/part.glb",
                operation=manifest["operation"],
                appearance_review="unreviewed",
            )
    return result


def start_reference(store, job, body, executor):
    if not (segmentation_status()["available"] and detector_status()["weights_ready"]):
        raise ValueError("本地部件识别环境尚未准备好")
    if job.get("current_asset_version", "original") != body.version:
        raise ValueError("编辑版本已变化，请刷新后重试")
    image_id = body.reference_image_id or job["request"]["image_id"]
    if not store.image(image_id):
        raise ValueError("部件参考图片不存在")
    source = source_for(store, job, body.version)
    ids = preflight(source, body.part_ids, body.kind)
    identity = uuid.uuid4().hex
    folder = store.root / "jobs" / job["id"] / "part_reference_scans" / identity
    folder.mkdir(parents=True)
    image = store.image(image_id)
    state = {
        "id": identity,
        "version": body.version,
        "kind": body.kind,
        "scope": ids,
        "source_sha256": digest(source),
        "image_sha256": digest(store.root / image["normalized_path"]),
        "image_id": image_id,
        "reference_origin": "uploaded" if body.reference_image_id else "original_photo",
        "status": "queued",
        "stage": "queued",
    }
    write_json(folder / "status.json", state)
    write_json(folder / "request.json", body.model_dump())
    submit_task(executor, run_reference, store, job["id"], identity, folder)
    return state_result(store, job, identity, True)


def stop_child(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def run_command(folder, command, timeout, progress=None, cancel_folder=None):
    if ((cancel_folder or folder) / "cancel_requested").exists():
        raise ValueError("已取消，原模型保留")
    with (folder / "worker.log").open("wb") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        started = time.monotonic()
        try:
            while process.poll() is None:
                if ((cancel_folder or folder) / "cancel_requested").exists():
                    raise ValueError("已取消，原模型保留")
                if time.monotonic() - started > timeout:
                    raise ValueError("本地部件处理超时，原模型保留")
                if progress:
                    progress()
                time.sleep(0.35)
            if process.returncode:
                lines = (folder / "worker.log").read_text(encoding="utf-8", errors="replace").splitlines()
                errors = [line.split("ValueError: ", 1)[1] for line in lines if line.startswith("ValueError: ")]
                raise ValueError(errors[-1][:220] if errors else "本地处理未完成，原模型保留；运行日志已保存")
        finally:
            stop_child(process)


def gpu_wait(folder):
    deadline = time.monotonic() + 600
    while not GPU_LOCK.acquire(timeout=0.35):
        if (folder / "cancel_requested").exists():
            raise ValueError("已取消，原模型保留")
        if time.monotonic() > deadline:
            raise ValueError("显卡持续忙碌，请稍后重试")


def run_reference(store, job_id, identity):
    job = store.job(job_id)
    folder = folder_for(store, job, identity, True)
    state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    started = time.monotonic()
    try:
        check_source(store, job_id, state)
        state.update(status="running", stage="waiting_gpu")
        write_json(folder / "status.json", state)
        gpu_wait(folder)
        try:
            if (folder / "cancel_requested").exists():
                raise ValueError("已取消，原模型保留")
            state["stage"] = "extracting_reference"
            write_json(folder / "status.json", state)
            image = store.image(state["image_id"])
            target = (
                job["request"]["target"]
                if state["reference_origin"] == "original_photo"
                else {"x": 0, "y": 0, "width": 1, "height": 1}
            )
            run_command(
                folder,
                [
                    segmentation_python(),
                    "-X",
                    "utf8",
                    str(ROOT / "services/workers/prepare_part_reference.py"),
                    "--input",
                    str(store.root / image["normalized_path"]),
                    "--output",
                    str(folder),
                    "--kind",
                    state["kind"],
                    "--target",
                    *[str(target[k]) for k in ("x", "y", "width", "height")],
                ],
                360,
            )
        finally:
            GPU_LOCK.release()
        check_source(store, job_id, state)
        if (folder / "cancel_requested").exists():
            raise ValueError("已取消，原模型保留")
        if digest(store.root / image["normalized_path"]) != state["image_sha256"]:
            raise ValueError("参考原图已变化，请重新提取")
        manifest = json.loads((folder / "references.json").read_text(encoding="utf-8"))
        for candidate in manifest["candidates"]:
            if not re.fullmatch(r"[a-f0-9]{32}\.png", candidate["file"]):
                raise ValueError("参考候选文件无效")
            candidate["file_sha256"] = digest(folder / candidate["file"])
        write_json(folder / "references.json", manifest)
        state.update(
            status="ready",
            stage="reference_ready",
            references_sha256=digest(folder / "references.json"),
            seconds=round(time.monotonic() - started, 3),
        )
        write_json(folder / "status.json", state)
    except Exception as exc:
        state.update(
            status="cancelled" if (folder / "cancel_requested").exists() else "failed",
            stage="failed",
            error=str(exc) if isinstance(exc, ValueError) else "部件参考提取未完成，原模型保留",
        )
        write_json(folder / "status.json", state)


def start_regeneration(store, job, body, executor):
    if not engine_status("hunyuan-mini")["available"]:
        raise ValueError("本地 Hunyuan3D-2mini 尚未准备好")
    references = folder_for(store, job, body.reference_scan_id, True)
    ref_state = json.loads((references / "status.json").read_text(encoding="utf-8"))
    source = check_source(store, job["id"], ref_state)
    ids = scope(source, body.part_ids)
    if (
        ref_state["status"] != "ready"
        or body.version != ref_state["version"]
        or body.kind != ref_state["kind"]
        or ids != ref_state["scope"]
        or body.reference_image_id != (ref_state["image_id"] if ref_state["reference_origin"] == "uploaded" else "")
    ):
        raise ValueError("部件范围或参考已变化，请重新提取参考")
    preflight(source, ids, body.kind)
    if digest(references / "references.json") != ref_state["references_sha256"]:
        raise ValueError("参考候选清单已变化，请重新提取")
    manifest = json.loads((references / "references.json").read_text(encoding="utf-8"))
    candidate = next((c for c in manifest["candidates"] if c["id"] == body.reference_candidate_id), None)
    if not candidate:
        raise ValueError("参考候选不存在")
    if (
        not re.fullmatch(r"[a-f0-9]{32}\.png", candidate["file"])
        or digest(references / candidate["file"]) != candidate["file_sha256"]
    ):
        raise ValueError("参考图片校验失败，请重新提取")
    check_reference_pixels(references / candidate["file"])
    identity = uuid.uuid4().hex
    folder = store.root / "jobs" / job["id"] / "part_regenerations" / identity
    folder.mkdir(parents=True)
    shutil.copyfile(references / candidate["file"], folder / "reference.png")
    payload = {**body.model_dump(), "part_ids": ids}
    write_json(folder / "request.json", payload)
    state = {
        "id": identity,
        "version": body.version,
        "kind": body.kind,
        "scope": ids,
        "source_sha256": digest(source),
        "reference_sha256": digest(folder / "reference.png"),
        "reference_origin": ref_state["reference_origin"],
        "status": "queued",
        "stage": "queued",
    }
    write_json(folder / "status.json", state)
    submit_task(executor, run_regeneration, store, job["id"], identity, folder)
    return state_result(store, job, identity)


def start_surface_repair(store, job, body, executor):
    if job.get("current_asset_version", "original") != body.version:
        raise ValueError("编辑版本已变化，请刷新后重试")
    if not local_python("hunyuan-mini"):
        raise ValueError("本地几何环境尚未准备好")
    source = source_for(store, job, body.version)
    ids = preflight(source, body.part_ids, "cushion")
    doc, _, _ = read_glb(source)
    if not any(p["id"] in ids and p.get("semantic_kind") == "seat" for p in parts_catalog(doc)):
        raise ValueError("请选择尚未拆开的坐面与座架分组")
    identity = uuid.uuid4().hex
    folder = store.root / "jobs" / job["id"] / "part_regenerations" / identity
    folder.mkdir(parents=True)
    state = {
        "id": identity,
        "version": body.version,
        "kind": "cushion",
        "scope": ids,
        "source_sha256": digest(source),
        "reference_sha256": None,
        "reference_origin": "source_mesh",
        "method": "source_seam",
        "status": "queued",
        "stage": "queued",
    }
    write_json(
        folder / "request.json", {"version": body.version, "part_ids": ids, "kind": "cushion", "method": "source_seam"}
    )
    write_json(folder / "status.json", state)
    submit_task(executor, run_surface_repair, store, job["id"], identity, folder)
    return state_result(store, job, identity)


def finish_preview(store, job_id, folder, state, started):
    if (folder / "cancel_requested").exists():
        raise ValueError("已取消，原模型保留")
    check_source(store, job_id, state)
    for name in ("model.glb", "part.glb", "diagnostic.glb"):
        validate_glb(folder / "preview" / name)
    manifest = json.loads((folder / "preview/manifest.json").read_text(encoding="utf-8"))
    preserved = state.get("method") == "source_seam"
    automatic = state.get("method") == "photo_guided_auto"
    if automatic:
        context = check_photo_inputs(folder, state)
        requested = {view["image_id"] for view in context.get("views", [])}
        if requested:
            plan = json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
            matched = {
                view.get("image_id") for view in plan.get("additional_views", []) if view.get("status") == "matched"
            }
            compared = {
                view.get("image_id")
                for view in manifest["operation"].get("photo_checks", {}).get("views", [])
                if view.get("additional_reference", view.get("independent_photo"))
            }
            if requested != matched or requested != compared:
                raise ValueError("补充视图未完整参与对应和对照检查，原模型保留")
    allowed = (
        ("source_seam", "ai_regeneration", "keep")
        if automatic
        else ("source_seam" if preserved else "ai_regeneration",)
    )
    if manifest.get("source_sha256") != state["source_sha256"] or manifest["operation"].get("method") not in allowed:
        raise ValueError("修复预览的来源校验失败，请重新开始")
    inferred = state.get("generated_valid") if automatic else not preserved
    manifest.update(
        reference_sha256=state["reference_sha256"],
        reference_origin=state["reference_origin"],
        generation_model="Hunyuan3D-2mini" if inferred else None,
        generation_mode="photo_guided_optimization"
        if automatic
        else "source_surface_partition"
        if preserved
        else "shape_only",
        reference_hidden_regions_completed=False if state["reference_origin"] == "original_photo" else None,
    )
    write_json(folder / "preview/manifest.json", manifest)
    if state["reference_sha256"] is not None and digest(folder / "reference.png") != state["reference_sha256"]:
        raise ValueError("参考图片已变化，请重新开始")
    check_source(store, job_id, state)
    if (folder / "cancel_requested").exists():
        raise ValueError("已取消，原模型保留")
    record = {
        "version": state["version"],
        "scope": state["scope"],
        "source_sha256": state["source_sha256"],
        "reference_sha256": state["reference_sha256"],
        **{
            name + "_sha256": digest(folder / "preview" / name)
            for name in ("model.glb", "part.glb", "diagnostic.glb", "manifest.json")
        },
    }
    if automatic:
        record["can_adopt"] = manifest["operation"]["photo_checks"]["can_adopt"]
        record["photo_evidence_sha256"] = {
            name: digest(folder / name)
            for name in (
                "context.json",
                "analysis.json",
                "camera.json",
                "checks.json",
                "association.png",
                "comparison.png",
            )
        }
        for path in (folder / "references").glob("*"):
            if path.suffix in (".png", ".json"):
                record["photo_evidence_sha256"]["references/" + path.name] = digest(path)
        for pattern in (
            "views/**/*.json",
            "views/**/*.png",
            "candidates/*/result.json",
            "candidates/*/checks.json",
            "candidates/*/generation.json",
            "candidates/*/preview/manifest.json",
            "candidate_rankings.json",
        ):
            for path in folder.glob(pattern):
                record["photo_evidence_sha256"][path.relative_to(folder).as_posix()] = digest(path)
    write_json(folder / "ready.json", record)
    state.update(status="ready", stage="ready", seconds=round(time.monotonic() - started, 3))
    write_json(folder / "status.json", state)


def run_surface_repair(store, job_id, identity):
    from .completion_preview import RECONSTRUCTION_LOCK

    folder = folder_for(store, store.job(job_id), identity)
    state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    started = time.monotonic()
    try:
        source = check_source(store, job_id, state)
        payload = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        if (
            payload.get("part_ids") != state["scope"]
            or payload.get("version") != state["version"]
            or payload.get("method") != "source_seam"
            or payload.get("kind") != "cushion"
        ):
            raise ValueError("部件请求已变化，请重新开始")
        if not RECONSTRUCTION_LOCK.acquire(blocking=False):
            raise ValueError("已有部件修复正在计算，请稍后重试")
        try:
            state.update(status="running", stage="preserving_source")
            write_json(folder / "status.json", state)
            run_command(
                folder,
                [
                    local_python("hunyuan-mini"),
                    "-X",
                    "utf8",
                    str(ROOT / "services/workers/replace_generated_part.py"),
                    "--input",
                    str(source),
                    "--request",
                    str(folder / "request.json"),
                    "--output",
                    str(folder / "preview"),
                ],
                360,
            )
        finally:
            RECONSTRUCTION_LOCK.release()
        finish_preview(store, job_id, folder, state, started)
    except Exception as exc:
        state.update(
            status="cancelled" if (folder / "cancel_requested").exists() else "failed",
            stage="failed",
            error=str(exc) if isinstance(exc, ValueError) else "原表面修复未完成，原模型保留",
        )
        write_json(folder / "status.json", state)


def run_regeneration(store, job_id, identity):
    job = store.job(job_id)
    folder = folder_for(store, job, identity)
    state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    started = time.monotonic()
    try:
        source = check_source(store, job_id, state)
        if digest(folder / "reference.png") != state["reference_sha256"]:
            raise ValueError("参考图片已变化，请重新开始")
        payload = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        if (
            payload["part_ids"] != state["scope"]
            or payload["kind"] != state["kind"]
            or payload["version"] != state["version"]
        ):
            raise ValueError("部件请求已变化，请重新开始")
        state.update(status="running", stage="waiting_gpu")
        write_json(folder / "status.json", state)
        gpu_wait(folder)
        try:
            state["stage"] = "generating"
            write_json(folder / "status.json", state)

            def progress():
                path = folder / "generated/local_progress.json"
                if path.exists():
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                    except ValueError:
                        return
                    if data.get("sequence") != state.get("progress_sequence"):
                        state.update(
                            progress_sequence=data.get("sequence"),
                            sampling_step=data.get("sampling_step"),
                            sampling_steps=data.get("sampling_steps"),
                        )
                        write_json(folder / "status.json", state)

            run_command(
                folder,
                [
                    local_python("hunyuan-mini"),
                    "-X",
                    "utf8",
                    str(ROOT / "services/workers/generate_hunyuan3d.py"),
                    "--input",
                    str(folder / "reference.png"),
                    "--output",
                    str(folder / "generated"),
                    "--keep-background",
                    "--steps",
                    "50",
                    "--resolution",
                    "384",
                ],
                1800,
                progress,
            )
        finally:
            GPU_LOCK.release()
        validate_glb(folder / "generated/model.glb")
        state.update(stage="aligning", generated_valid=True)
        write_json(folder / "status.json", state)
        source = check_source(store, job_id, state)
        alignment = folder / "alignment_worker"
        alignment.mkdir()
        run_command(
            alignment,
            [
                local_python("hunyuan-mini"),
                "-X",
                "utf8",
                str(ROOT / "services/workers/replace_generated_part.py"),
                "--input",
                str(source),
                "--candidate",
                str(folder / "generated/model.glb"),
                "--request",
                str(folder / "request.json"),
                "--output",
                str(folder / "preview"),
            ],
            360,
            cancel_folder=folder,
        )
        finish_preview(store, job_id, folder, state, started)
    except Exception as exc:
        state.update(
            status="cancelled" if (folder / "cancel_requested").exists() else "failed",
            stage="failed",
            error=str(exc) if isinstance(exc, ValueError) else "部件重生成未完成，原模型保留",
        )
        write_json(folder / "status.json", state)


def verified_regeneration(store, job, request, source):
    folder = folder_for(store, job, request.regeneration_preview_id)
    state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    if state["status"] != "ready" or not (folder / "ready.json").is_file():
        raise ValueError("替换候选尚未完成或未通过检查")
    ready = json.loads((folder / "ready.json").read_text(encoding="utf-8"))
    if not ready.get("can_adopt", True):
        raise ValueError("当前自动检查未允许替换，请检查对照结果或补充参考")
    if (
        ready["version"] != request.base_version
        or ready["source_sha256"] != digest(source)
        or ready["scope"] != scope(source, request.part_ids)
    ):
        raise ValueError("源模型或部件范围已变化，请重新生成预览")
    if (ready["reference_sha256"] is not None and ready["reference_sha256"] != digest(folder / "reference.png")) or any(
        ready[name + "_sha256"] != digest(folder / "preview" / name)
        for name in ("model.glb", "part.glb", "diagnostic.glb", "manifest.json")
    ):
        raise ValueError("替换预览校验失败，请重新生成")
    if any(
        not (folder / name).is_file() or digest(folder / name) != expected
        for name, expected in ready.get("photo_evidence_sha256", {}).items()
    ):
        raise ValueError("原图对照记录已变化，请重新分析")
    if state.get("method") == "photo_guided_auto":
        check_photo_inputs(folder, state)
    return folder / "preview"


def cancel_task(store, job, identity, reference=False):
    folder = folder_for(store, job, identity, reference)
    state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    if state["status"] in ("queued", "running"):
        (folder / "cancel_requested").touch()
    return {"cancel_requested": state["status"] in ("queued", "running"), "published": False}


def recover_part_regenerations(store):
    for pattern in ("jobs/*/part_reference_scans/*/status.json", "jobs/*/part_regenerations/*/status.json"):
        for path in store.root.glob(pattern):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if state.get("status") in ("queued", "running"):
                state.update(status="failed", stage="failed", error="上次部件任务因服务重启而中断，请重新开始")
                write_json(path, state)
