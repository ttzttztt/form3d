"""Attach an actual model authored in the current conversation to its task."""
import json
from pathlib import Path
import shutil

from .geometry import inspect_glb, validate_glb
from .pipeline import write_json


def attach_asset(store, job_id, model, notes, preview=None, source=None):
    job = store.job(job_id)
    if not job or job["request"]["route"] != "assistant" or job["status"] != "awaiting_assistant":
        raise ValueError("只能把看图建模结果关联到待处理的看图建模任务")
    model = Path(model).resolve()
    metrics = inspect_glb(model)
    validation = validate_glb(model)
    directory = store.root / "jobs" / job_id
    temporary = directory / "model.importing"
    shutil.copyfile(model, temporary)
    temporary.replace(directory / "model.glb")
    for name, origin in [("preview.png", preview), ("source.blend", source)]:
        if origin and Path(origin).is_file():
            shutil.copyfile(origin, directory / name)
    report = {
        "schema_version": "1.1", "job_id": job_id, "asset_version": job_id, "route": "assistant",
        "units": "meter", "scale_status": "nominal_dimensions_not_verified", "ar_true_scale_ready": False,
        "checks": {"glb_structure": "pass", "full_gltf_validator": validation["status"], "viewer_load": "needs_review",
                   "appearance": "needs_review", "dimensions": "unverified"},
        "gltf_validation": validation, "metrics": metrics,
        "evidence": {"image_id": job["request"]["image_id"], "preparation": job.get("preparation"),
                     "geometry_source": "assistant_authored_blender_from_visual_reference", "hidden_surfaces": "inferred"},
        "warnings": ["根据当前上传图片进行对话协助建模，尚未校准实物尺寸", "背面、内部厚度和不可见细节包含推测"],
        "modeling_notes": notes, "review_status": "pending",
    }
    metadata = {"job_id": job_id, "name": job["name"], "route": "assistant", "units": "meter",
                "scale_status": report["scale_status"], "geometry_source": report["evidence"]["geometry_source"],
                "coordinate_system": "gltf_y_up_right_handed", "metrics": metrics, "review_status": "pending"}
    write_json(directory / "metadata.json", metadata)
    write_json(directory / "quality_report.json", report)
    write_json(directory / "modeling_notes.json", notes)
    return store.event(job_id, "review", "已根据图片完成独立建模，请旋转检查与下载", status="awaiting_review",
                       model_url="/api/jobs/%s/files/model.glb" % job_id,
                       preview_url="/api/jobs/%s/files/preview.png" % job_id if preview else None,
                       report=report, metrics=metrics, review_status="pending")
