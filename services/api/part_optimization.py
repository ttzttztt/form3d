"""Automatic photo-bound part optimization, always previewed before adoption."""

import json, re, shutil, time, uuid
from .asset_editor import ROOT, source_for
from .glb_document import read_glb, parts_catalog
from .local3d import local_python, engine_status
from .segmentation import segmentation_python, segmentation_status, image_background_kind
from .gpu import GPU_LOCK
from .part_regeneration import (
    digest,
    write_json,
    scope,
    preflight,
    submit_task,
    folder_for,
    state_result,
    check_source,
    check_photo_inputs,
    run_command,
    gpu_wait,
    finish_preview,
)


def photo_content_digest(path):
    import hashlib
    from PIL import Image

    with Image.open(path) as source:
        rgba = source.convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        white.alpha_composite(rgba)
        return hashlib.sha256(str(rgba.size).encode() + white.convert("RGB").tobytes()).hexdigest()


def original_job(store, job):
    seen = set()
    while job.get("test_clone_of") and job["id"] not in seen:
        seen.add(job["id"])
        parent = store.job(job["test_clone_of"])
        if (
            not parent
            or parent["request"]["image_id"] != job["request"]["image_id"]
            or parent["request"]["target"] != job["request"]["target"]
        ):
            break
        job = parent
    return job


def start_optimization(store, job, body, executor):
    if job.get("current_asset_version", "original") != body.version:
        raise ValueError("编辑版本已变化，请刷新后重试")
    source = source_for(store, job, body.version)
    ids = scope(source, body.part_ids)
    parts = [p for p in parts_catalog(read_glb(source)[0]) if p["id"] in ids]
    kinds = {p.get("semantic_kind") for p in parts}
    if len(kinds) != 1 or next(iter(kinds)) not in ("pillow", "seat", "cushion", "bolster"):
        raise ValueError("请选择已识别的靠枕、坐垫或圆柱抱枕")
    kind = "cushion" if next(iter(kinds)) in ("seat", "cushion") else next(iter(kinds))
    preflight(source, ids, kind, allow_uv=True)
    if not local_python("hunyuan-mini") or not segmentation_status()["available"]:
        raise ValueError("本地几何或分割环境尚未准备好")
    image = store.image(job["request"]["image_id"])
    photo = store.root / image["normalized_path"]
    views = []
    seen_photos = {photo_content_digest(photo)}
    for view in getattr(body, "reference_views", []):
        if view.image_id == job["request"]["image_id"]:
            raise ValueError("补充视图不能重复主图")
        info = store.image(view.image_id)
        if not info:
            raise ValueError("补充图片不存在，请重新上传")
        path = store.root / info["normalized_path"]
        content = photo_content_digest(path)
        if content in seen_photos:
            raise ValueError("补充视图与主图或已有视图内容重复，不能作为独立角度")
        seen_photos.add(content)
        views.append(
            {
                "image_id": view.image_id,
                "role": view.role,
                "target": view.target.model_dump(),
                "photo": str(store.root / info["normalized_path"]),
            }
        )
    identity = uuid.uuid4().hex
    folder = store.root / "jobs" / job["id"] / "part_regenerations" / identity
    folder.mkdir(parents=True)
    root = original_job(store, job)
    context = {
        "source": str(source),
        "part_ids": ids,
        "kind": kind,
        "seat_with_frame": next(iter(kinds)) == "seat",
        "photo": str(photo),
        "source_folder": str(store.root / "jobs" / root["id"]),
        "original_request": root["request"],
        "views": views,
        "candidate_count": getattr(body, "candidate_count", 3),
        "target_faces": getattr(body, "target_faces", 100000),
    }
    write_json(folder / "context.json", context)
    segmented = store.root / "jobs" / root["id"] / "segmented.png"
    state = {
        "id": identity,
        "version": body.version,
        "scope": ids,
        "kind": kind,
        "method": "photo_guided_auto",
        "source_sha256": digest(source),
        "image_sha256": digest(photo),
        "segmentation_sha256": digest(segmented) if segmented.is_file() else None,
        "context_sha256": digest(folder / "context.json"),
        "reference_sha256": None,
        "reference_origin": "original_photo",
        "status": "queued",
        "stage": "queued",
    }
    state["view_images_sha256"] = {
        view["image_id"]: digest(__import__("pathlib").Path(view["photo"])) for view in views
    }
    write_json(folder / "status.json", state)
    submit_task(executor, run_optimization, store, job["id"], identity, folder)
    return state_result(store, job, identity)


def copy_reference_cache(store, job, state, destination):
    # Image proposals are independent of the 3D scope. Reuse only the same
    # original image bytes, target crop and kind, never a cached 3D association.
    for candidate_job in store.jobs():
        if (
            candidate_job["request"]["image_id"] != job["request"]["image_id"]
            or candidate_job["request"]["target"] != job["request"]["target"]
        ):
            continue
        for path in (store.root / "jobs" / candidate_job["id"] / "part_reference_scans").glob("*/status.json"):
            try:
                status = json.loads(path.read_text(encoding="utf-8"))
                if (
                    status.get("status") != "ready"
                    or status.get("kind") != state["kind"]
                    or status.get("reference_origin") != "original_photo"
                    or status.get("image_sha256") != state["image_sha256"]
                ):
                    continue
                source = path.parent
                manifest_path = source / "references.json"
                if digest(manifest_path) != status.get("references_sha256"):
                    continue
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if "product_crop_pixels" not in manifest:
                    continue
                names = {"references.json"}
                for c in manifest["candidates"]:
                    for key in ("file", "mask_file", "preview"):
                        name = c[key]
                        if not re.fullmatch(r"[a-f0-9]{32}(_mask|_preview)?\.png", name):
                            raise ValueError("参考缓存文件无效")
                        if key == "file":
                            names.add(name)
                    if digest(source / c["file"]) != c["file_sha256"]:
                        raise ValueError("参考缓存校验失败")
                whole = manifest.get("whole_product_mask")
                if whole:
                    if whole.get("file") != "whole_product_mask.png" or digest(source / whole["file"]) != whole.get(
                        "sha256"
                    ):
                        raise ValueError("整件轮廓缓存校验失败")
                    names.add(whole["file"])
                destination.mkdir(exist_ok=True)
                for name in names:
                    shutil.copyfile(source / name, destination / name)
                # Recreate unsigned masks/previews from the verified cutout,
                # and the product image from the bound original photo bytes.
                from PIL import Image

                image = store.image(job["request"]["image_id"])
                original = Image.open(store.root / image["normalized_path"]).convert("RGBA")
                white = Image.new("RGBA", original.size, "white")
                white.alpha_composite(original)
                product = white.convert("RGB").crop(manifest["product_crop_pixels"])
                product.save(destination / "product.png")
                for c in manifest["candidates"]:
                    rgba = Image.open(destination / c["file"]).convert("RGBA")
                    crop = c["source_crop_in_product_pixels"]
                    if rgba.size != (crop[2] - crop[0], crop[3] - crop[1]):
                        raise ValueError("参考坐标与尺寸不一致")
                    mask = Image.new("L", product.size)
                    mask.paste(rgba.getchannel("A"), tuple(crop[:2]))
                    mask.save(destination / c["mask_file"])
                    preview = Image.new("RGBA", rgba.size, "white")
                    preview.alpha_composite(rgba)
                    preview.convert("RGB").save(destination / c["preview"])
                return {"job": candidate_job["id"], "scan_id": source.name, "reused_2d_proposals_only": True}
            except (ValueError, KeyError, OSError):
                continue
    return None


def copy_generation_cache(store, job, state, destination, seed=42):
    """Reuse only exact-reference raw shapes; never reuse pose or adoption."""
    worker_sha = digest(ROOT / "services/workers/generate_hunyuan3d.py")
    for candidate_job in store.jobs():
        if candidate_job["request"]["image_id"] != job["request"]["image_id"]:
            continue
        root = store.root / "jobs" / candidate_job["id"]
        paths = (
            list((root / "part_regenerations").glob("*/generated/local_summary.json"))
            + list((root / "part_regenerations").glob("*/candidates/*/generated/local_summary.json"))
            + list((root / "upgrade_inferences").glob("*/local_summary.json"))
        )
        for path in paths:
            if path.parent == destination:
                continue
            try:
                summary = json.loads(path.read_text(encoding="utf-8"))
                marker = (
                    path.parent / "execution.json"
                    if (path.parent / "execution.json").exists()
                    else path.parent.parent / "generation.json"
                    if (path.parent.parent / "generation.json").exists()
                    else path.parent.parent / "status.json"
                )
                status = json.loads(marker.read_text(encoding="utf-8"))
                if (
                    not (status.get("generated_valid") or status.get("status") == "completed")
                    or summary.get("input_sha256") != state["reference_sha256"]
                    or summary.get("worker_revision") != worker_sha
                ):
                    continue
                if (
                    summary.get("model") != "Hunyuan3D-2mini"
                    or summary.get("mode") != "shape_only"
                    or summary.get("steps") != 50
                    or summary.get("resolution") != 384
                    or summary.get("seed") != seed
                ):
                    continue
                if (
                    digest(path.parent / "model.glb") != summary["model_sha256"]
                    or digest(path.parent / "foreground.png") != summary["foreground_sha256"]
                ):
                    continue
                destination.mkdir(exist_ok=True)
                for name in ("model.glb", "foreground.png", "local_summary.json"):
                    shutil.copyfile(path.parent / name, destination / name)
                return {
                    "job": candidate_job["id"],
                    "task": path.parent.parent.name,
                    "seed": seed,
                    "raw_geometry_only": True,
                    "pose_and_checks_recomputed": True,
                }
            except (ValueError, KeyError, OSError):
                continue
    return None


def run_optimization(store, job_id, identity):
    job = store.job(job_id)
    folder = folder_for(store, job, identity)
    state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    started = time.monotonic()

    def stage(name):
        check_source(store, job_id, state)
        context = check_photo_inputs(folder, state)
        state.update(status="running", stage=name)
        write_json(folder / "status.json", state)
        return context

    def command(name, args, timeout, progress=None):
        try:
            run_command(folder, args, timeout, progress)
        finally:
            if (folder / "worker.log").is_file():
                shutil.copyfile(folder / "worker.log", folder / (name + "_worker.log"))

    try:
        context = stage("extracting_reference")
        references = folder / "references"
        reused = copy_reference_cache(store, job, state, references)
        if reused:
            state["reference_cache"] = reused
            write_json(folder / "status.json", state)
        else:
            references.mkdir(exist_ok=True)
            stage("waiting_gpu")
            gpu_wait(folder)
            try:
                stage("extracting_reference")
                target = job["request"]["target"]
                command(
                    "extract",
                    [
                        segmentation_python(),
                        "-X",
                        "utf8",
                        str(ROOT / "services/workers/prepare_part_reference.py"),
                        "--input",
                        context["photo"],
                        "--output",
                        str(references),
                        "--kind",
                        state["kind"],
                        "--detect-parts",
                        "--target",
                        *[str(target[k]) for k in ("x", "y", "width", "height")],
                    ],
                    360,
                )
            finally:
                GPU_LOCK.release()
        for index, view in enumerate(context.get("views", [])):
            location = folder / "views" / str(index)
            view_refs = location / "references"
            location.mkdir(parents=True, exist_ok=True)
            view_job = {**job, "request": {**job["request"], "image_id": view["image_id"], "target": view["target"]}}
            reused_view = copy_reference_cache(
                store, view_job, {**state, "image_sha256": state["view_images_sha256"][view["image_id"]]}, view_refs
            )
            if reused_view:
                continue
            view_refs.mkdir(exist_ok=True)
            stage("waiting_gpu")
            gpu_wait(folder)
            try:
                stage("extracting_additional_view")
                target = view["target"]
                flags = ["--whole-product-mask"] if image_background_kind(view["photo"]) == "scene" else []
                command(
                    f"view_{index}_extract",
                    [
                        segmentation_python(),
                        "-X",
                        "utf8",
                        str(ROOT / "services/workers/prepare_part_reference.py"),
                        "--input",
                        view["photo"],
                        "--output",
                        str(view_refs),
                        "--kind",
                        state["kind"],
                        "--detect-parts",
                        *flags,
                        "--target",
                        *[str(target[k]) for k in ("x", "y", "width", "height")],
                    ],
                    360,
                )
            except ValueError as exc:
                if (folder / "cancel_requested").exists():
                    raise
                state.update(status="needs_input", stage="needs_input", error="补充视图未得到可对应的部件：" + str(exc))
                write_json(folder / "status.json", state)
                return
            finally:
                GPU_LOCK.release()
        worker = [
            local_python("hunyuan-mini"),
            "-X",
            "utf8",
            str(ROOT / "services/workers/auto_part_optimization.py"),
            "--folder",
            str(folder),
        ]
        stage("matching_reference")
        command("analyze", worker + ["--stage", "analyze"], 360)
        plan = json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
        refinements = ([folder] if plan.get("needs_guided_reference") else []) + [
            folder / "views" / str(v["index"])
            for v in plan.get("additional_views", [])
            if v.get("needs_guided_reference")
        ]
        for index, location in enumerate(refinements):
            stage("waiting_gpu")
            gpu_wait(folder)
            try:
                stage("refining_reference")
                command(
                    "refine_" + str(index),
                    [
                        segmentation_python(),
                        "-X",
                        "utf8",
                        str(ROOT / "services/workers/refine_photo_part.py"),
                        "--output",
                        str(location / "references"),
                        "--hint",
                        str(location / "hint.png"),
                        "--other",
                        str(location / "other.png"),
                    ],
                    180,
                )
            finally:
                GPU_LOCK.release()
            (location / "guided_done").touch()
        if refinements:
            stage("matching_reference")
            command("analyze_guided", worker + ["--stage", "analyze"], 360)
            plan = json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
        state["strategy"] = plan["route"]
        write_json(folder / "status.json", state)
        if plan["route"] == "needs_input":
            state.update(status="needs_input", stage="needs_input", error=plan["reason"])
            write_json(folder / "status.json", state)
            return
        if plan["route"] == "ai_regeneration":
            if not engine_status("hunyuan-mini")["available"]:
                raise ValueError("当前部件需要重新生成，本地模型尚未准备好")
            refs = json.loads((references / "references.json").read_text(encoding="utf-8"))
            ref = next(c for c in refs["candidates"] if c["id"] == plan["photo_association"]["candidate_id"])
            from .part_regeneration import check_reference_pixels

            check_reference_pixels(references / ref["file"])
            shutil.copyfile(references / ref["file"], folder / "reference.png")
            state["reference_sha256"] = digest(folder / "reference.png")
            from .part_candidates import run_candidates

            run_candidates(store, job, folder, state, context, stage)
        else:
            from .part_candidates import wait_cpu
            from .completion_preview import RECONSTRUCTION_LOCK

            stage("waiting_cpu")
            wait_cpu(folder)
            try:
                stage("optimizing_shape")
                command("optimize", worker + ["--stage", "optimize"], 600)
            finally:
                RECONSTRUCTION_LOCK.release()
        stage("checking_comparison")
        finish_preview(store, job_id, folder, state, started)
    except Exception as exc:
        state.update(
            status="cancelled" if (folder / "cancel_requested").exists() else "failed",
            stage="failed",
            error=str(exc) if isinstance(exc, ValueError) else "自动优化未完成，原模型保留",
        )
        write_json(folder / "status.json", state)
