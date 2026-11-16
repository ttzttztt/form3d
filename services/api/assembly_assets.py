"""Import an audited local assembly candidate without relabeling it as Blender or real scale."""

import json, os, shutil, tempfile
from pathlib import Path
from .assembly_models import AssemblyPlan
from .assembly_inputs import file_hash
from .geometry import inspect_glb, validate_glb
from .glb_document import read_glb, parts_catalog
from .part_regeneration import write_json


def attach_assembly_candidate(
    store, job_id, source_folder, preview=None, route="assistant", pending_status="awaiting_assistant"
):
    """Publish a checked assembly into a job that is still waiting for it.

    route/pending_status: the offline importer uses an assistant job awaiting import;
    the one-click parts_first job attaches while it is still running.
    """
    job = store.job(job_id)
    source = Path(source_folder)
    if not job or job["request"]["route"] != route or job["status"] != pending_status:
        raise ValueError("Requires a fresh pending import task")
    directory = store.root / "jobs" / job_id
    if (directory / "model.glb").exists():
        raise ValueError("Do not replace an existing original model")
    if preview and not Path(preview).is_file():
        raise ValueError("The supplied preview file is missing")
    evidence = json.loads((source / "assembly.json").read_text(encoding="utf-8"))
    plan = AssemblyPlan.model_validate_json((source / "plan.json").read_text(encoding="utf-8"))
    model = source / "model.glb"
    model_sha = file_hash(model)
    if model_sha != evidence["model_sha256"]:
        raise ValueError("Assembly model changed")
    image = store.image(job["request"]["image_id"])
    if (
        plan.primary_image_id != job["request"]["image_id"]
        or not image
        or file_hash(store.root / image["normalized_path"]) != plan.primary_image_sha256
    ):
        raise ValueError("Assembly belongs to another input image")
    if evidence["status"] != "candidate_ready_for_review" or plan.status != "ready_for_review":
        raise ValueError("Assembly checks are not ready for candidate review")
    physical = [p for p in plan.parts if p.geometry_role == "physical_part"]
    if not physical or any(p.model_sha256 != model_sha for p in physical):
        raise ValueError("Part geometry hashes and assembly model differ")
    if set(evidence.get("part_ids", [])) != {p.id for p in physical} or len(evidence.get("part_ids", [])) != len(
        physical
    ):
        raise ValueError("Assembly manifest and physical part identities differ")
    doc, _, _ = read_glb(model)
    catalog = parts_catalog(doc)
    actual = [p["id"] for p in catalog]
    expected = {i for part in physical for i in part.primitive_ids}
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError("GLB identities and assembly plan differ")
    owners = {i: part for part in physical for i in part.primitive_ids}
    if any(p["logical_group_id"] != owners[p["id"]].id or p["semantic_kind"] != owners[p["id"]].kind for p in catalog):
        raise ValueError("GLB semantic ownership and assembly plan differ")
    validation = validate_glb(model)
    if validation["status"] != "pass":
        raise ValueError("Complete glTF validation did not pass")
    metrics = inspect_glb(model)
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".assembly-", suffix=".importing", delete=False) as stream:
        staged = Path(stream.name)
        try:
            with model.open("rb") as original:
                shutil.copyfileobj(original, stream)
        except Exception:
            stream.close()
            staged.unlink(missing_ok=True)
            raise
    try:
        if file_hash(staged) != model_sha:
            raise ValueError("Assembly model changed during import")
        if store.job(job_id)["status"] != pending_status:
            raise ValueError("The import task state changed")
        # Creating a link is atomic and refuses an existing destination, unlike
        # replace(). This also protects against two separate importer processes.
        try:
            os.link(staged, directory / "model.glb")
        except FileExistsError as exc:
            raise ValueError("Do not replace a concurrently imported original model") from exc
    finally:
        staged.unlink(missing_ok=True)
    if preview and Path(preview).is_file():
        shutil.copyfile(preview, directory / "preview.png")
    write_json(directory / "assembly_plan.json", plan.model_dump())
    write_json(directory / "assembly_evidence.json", evidence)
    report = {
        "schema_version": "parts-first-candidate/1",
        "job_id": job_id,
        "asset_version": job_id,
        "route": route,
        "units": "normalized",
        "scale_status": "normalized_unverified",
        "ar_true_scale_ready": False,
        "checks": {
            "glb_structure": "pass",
            "full_gltf_validator": "pass",
            "appearance": "needs_review",
            "dimensions": "unverified",
            "assembly_acceptance": "pending",
        },
        "gltf_validation": validation,
        "metrics": metrics,
        "review_status": "pending",
        "evidence": {
            "image_id": plan.primary_image_id,
            "geometry_source": "local_image_first_native_parts",
            "source_engine": evidence.get("source_engine", "see_source_generation_hash"),
            "hidden_surfaces": "ai_inferred",
            "assembly_manifest_sha256": file_hash(source / "assembly.json"),
            "part_plan_sha256": file_hash(source / "plan.json"),
            "contacts": evidence.get("contacts", []),
            "placement_hypotheses": evidence.get("placement_hypotheses", []),
            "parametric_fit": evidence.get("parametric_fit"),
        },
        "warnings": [
            "本地按部件生成候选，尚未通过外观与实物结构验收",
            "单位为归一化比例；真实尺寸、隐藏表面和材质尺度未验证",
        ]
        + list((evidence.get("parametric_fit") or {}).get("assumptions", [])),
        "modeling_notes": {"mode": "local_native_parts_candidate", "complete_assembly_accepted": False},
    }
    metadata = {
        "job_id": job_id,
        "name": job["name"],
        "route": route,
        "units": "normalized",
        "scale_status": "normalized_unverified",
        "geometry_source": report["evidence"]["geometry_source"],
        "coordinate_system": plan.coordinate_system,
        "metrics": metrics,
        "review_status": "pending",
    }
    write_json(directory / "quality_report.json", report)
    write_json(directory / "metadata.json", metadata)
    if store.job(job_id)["status"] != pending_status:
        raise ValueError("The import task state changed; candidate was not published")
    return store.event(
        job_id,
        "review",
        "本地按部件生成候选已导入，请检查装配与外观",
        status="awaiting_review",
        review_status="pending",
        model_url=f"/api/jobs/{job_id}/files/model.glb",
        preview_url=f"/api/jobs/{job_id}/files/preview.png" if preview else None,
        metrics=metrics,
        report=report,
    )
