"""One-click parts-first route: photo → part plan → native part generation → audit → assembly.

Each stage is an isolated worker process (see services/workers/). The orchestrator only
sequences them, streams progress into the job's event log, enforces the GPU lock and
cancellation, and stops with an explanation when a stage's evidence gate does not pass.
Nothing here relabels a failed or ambiguous part as accepted.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .assembly_assets import attach_assembly_candidate
from .gpu import GPU_LOCK
from .local3d import local_python
from .output_quality import OutputNeedsAttention
from .preflight import InputNeedsAttention
from .provider import Cancelled
from .segmentation import segmentation_python

ROOT = Path(__file__).resolve().parents[2]
WORKERS = ROOT / "services" / "workers"
CATEGORIES = ("sofa", "chair", "table", "cabinet")

# Evidence copied into the job folder so the workbench can show it (see app.artifact).
EVIDENCE_FILES = {
    "parts_overlay.png": ("plan", "observations.png"),
    "parts_plan.json": ("plan", "plan.json"),
    "parts_fit.png": ("raw", "audit", "photo_fitted_geometry.png"),
    "parts_audit.json": ("raw", "audit", "audit.json"),
}

PARTCRAFTER_STAGES = {
    "preparing_image": "准备部件生成输入",
    "loading_weights": "加载 PartCrafter 权重",
    "conditioning_ready_sampling_weights_only": "图像条件已编码，开始采样",
    "sampling": "按部件联合采样",
    "decoding_part": "解码部件网格",
    "exporting_raw_parts": "导出原始部件",
    "raw_candidates_ready": "原始部件已生成",
}

TIMEOUTS = {"plan": 900, "generate": 3600, "audit": 1800, "export": 1800}


def parts_python():
    configured = os.getenv("PARTS_PYTHON")
    candidate = (
        Path(configured)
        if configured
        else ROOT / ".venv-parts" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    return str(candidate.resolve()) if candidate.is_file() else None


def parts_first_status():
    """Report each prerequisite separately so the settings panel can say what is missing."""
    checks = {
        "planner_runtime": bool(segmentation_python()),
        "detector_weights": (ROOT / ".models" / "grounding-dino-tiny").is_dir(),
        "segmenter_weights": (ROOT / ".models" / "sam2.1-hiera-tiny" / "sam2.1_hiera_tiny.pt").is_file(),
        "segmenter_source": (ROOT / ".tools" / "SAM2").is_dir(),
        "generator_runtime": bool(parts_python()),
        "generator_weights": (ROOT / ".models" / "partcrafter" / "provenance.json").is_file(),
        "generator_source": (
            ROOT / ".tools" / "PartCrafter" / "src" / "pipelines" / "pipeline_partcrafter.py"
        ).is_file(),
        "geometry_runtime": bool(local_python("hunyuan-mini")),
        "geometry_extra": (ROOT / ".tools" / "geometry_extra").is_dir(),
    }
    return {
        "available": all(checks.values()),
        "checks": checks,
        "missing": [name for name, ok in checks.items() if not ok],
        "planner": "Grounding DINO Tiny + SAM 2.1 Hiera Tiny",
        "generator": "PartCrafter",
        "categories": list(CATEGORIES),
        "max_parts": 16,
        "requires_key": False,
        "output": "geometry_only",
        "appearance_accepted": False,
    }


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _last_error(log_path):
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        for marker in ("ValueError: ", "RuntimeError: "):
            if marker in line:
                return line.split(marker, 1)[1][:300]
    return None


class _Runner:
    """Runs one worker at a time, mirroring progress files into job events."""

    def __init__(self, store, job_id, folder, check_cancelled):
        self.store, self.job_id, self.folder, self.check_cancelled = store, job_id, folder, check_cancelled

    def run(self, name, command, progress_path=None, stage_messages=None):
        log_path = self.folder / f"{name}.log"
        started = time.monotonic()
        seen = None
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(ROOT),
                env={**os.environ, "PYTHONUTF8": "1"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                while process.poll() is None:
                    self.check_cancelled()
                    if progress_path is not None:
                        value = _read_json(progress_path)
                        if value and (value.get("sequence"), value.get("stage")) != seen:
                            seen = (value.get("sequence"), value.get("stage"))
                            message = (stage_messages or {}).get(value.get("stage"), value.get("stage"))
                            if value.get("total") and value.get("step") is not None:
                                message = f"{message} {value['step']}/{value['total']}"
                            elif value.get("total") and value.get("part_index") is not None:
                                message = f"{message} {value['part_index']}/{value['total']}"
                            self.store.event(self.job_id, "parts_" + name, message)
                    if time.monotonic() - started > TIMEOUTS[name]:
                        raise ValueError(f"部件优先流程在「{name}」阶段超时，已停止；日志见 parts_first/{name}.log")
                    time.sleep(0.25)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        self.check_cancelled()
        if process.returncode:
            detail = _last_error(log_path)
            raise ValueError(
                f"部件优先流程「{name}」阶段失败：{detail}"
                if detail
                else f"部件优先流程「{name}」阶段失败，日志见 parts_first/{name}.log"
            )


def _with_gpu(check_cancelled, action):
    while not GPU_LOCK.acquire(timeout=0.25):
        check_cancelled()
    try:
        return action()
    finally:
        GPU_LOCK.release()


def _plan_gate(plan_folder):
    plan = _read_json(plan_folder / "plan.json") or {}
    physical = [p for p in plan.get("parts", []) if p.get("geometry_role", "physical_part") == "physical_part"]
    if plan.get("status") == "planned" and physical:
        return plan, physical
    unknown = [p for p in physical if p.get("kind") == "unknown"]
    if not physical:
        reason = "原图中没有识别出可生成的部件"
    elif unknown:
        reason = f"有 {len(unknown)} 个区域的部件类别互相冲突，需要换一张更清晰的图或改用整体生成"
    elif len(physical) > 16:
        reason = f"识别出 {len(physical)} 个部件，超过 PartCrafter 单次 16 个部件的上限"
    else:
        reason = "部件清单证据不足"
    raise InputNeedsAttention("部件规划未通过：" + reason + "；识别叠加图已保存")


def _audit_gate(audit, slot_count):
    reasons = []
    if audit.get("geometry_gate") != "passed":
        failed = [s for s in audit.get("slots", []) if s.get("geometry_gate") != "passed"]
        reasons.append(f"{len(failed)} 个部件网格未通过闭合/自交检查")
    matches = audit.get("photo_evidence", {}).get("matches", [])
    linked = [m for m in matches if m.get("link_status") == "photo_linked_hypothesis"]
    if len(linked) != slot_count:
        reasons.append(f"只有 {len(linked)}/{slot_count} 个生成部件能可靠对应到原图部件")
    if reasons:
        raise OutputNeedsAttention("部件生成结果未通过审计：" + "；".join(reasons) + "。原始部件和审计记录已保存")


def run_parts_first(store, job_id, directory, request, image, check_cancelled):
    """Execute the pipeline for a queued parts_first job. Raises the pipeline's standard exceptions."""
    status = parts_first_status()
    if not status["available"]:
        raise ValueError("部件优先生成环境未就绪，缺少：" + "、".join(status["missing"]))
    if request.object_category not in CATEGORIES:
        raise ValueError("部件优先生成需要先选择家具类别（沙发、椅子、桌子或柜子）")
    root = directory / "parts_first"
    if root.exists():
        # A restart after a crash: keep the old evidence, start a fresh attempt.
        root.rename(directory / f"parts_first_interrupted_{int(time.time())}")
    root.mkdir(parents=True)
    plan_folder, raw_folder, assembly_folder = root / "plan", root / "raw", root / "assembly"
    runner = _Runner(store, job_id, root, check_cancelled)
    source = store.root / image["normalized_path"]
    target = request.target

    store.event(job_id, "parts_plan", "在原图中识别家具部件（检测 + 分割）")
    _with_gpu(
        check_cancelled,
        lambda: runner.run(
            "plan",
            [
                segmentation_python(),
                "-X",
                "utf8",
                "-u",
                str(WORKERS / "plan_assembly_from_photo.py"),
                "--input",
                str(source),
                "--image-id",
                request.image_id,
                "--category",
                request.object_category,
                "--target",
                str(target.x),
                str(target.y),
                str(target.width),
                str(target.height),
                "--output",
                str(plan_folder),
            ],
        ),
    )
    _publish_evidence(store, job_id, root, directory)
    plan, physical = _plan_gate(plan_folder)
    kinds = "、".join(sorted({p["name"].rsplit(" ", 1)[0] for p in physical}))
    store.event(
        job_id,
        "parts_planned",
        f"识别出 {len(physical)} 个部件：{kinds}",
        parts_plan={
            "count": len(physical),
            "parts": [{"id": p["id"], "name": p["name"], "kind": p["kind"]} for p in physical],
        },
        parts_overlay_url=f"/api/jobs/{job_id}/files/parts_overlay.png",
    )

    _with_gpu(
        check_cancelled,
        lambda: runner.run(
            "generate",
            [
                parts_python(),
                "-X",
                "utf8",
                "-u",
                str(WORKERS / "generate_partcrafter.py"),
                "--input",
                str(plan_folder / "generation_input.png"),
                "--plan",
                str(plan_folder / "plan.json"),
                "--count-source",
                "image_plan",
                "--output",
                str(raw_folder),
            ],
            progress_path=raw_folder / "progress.json",
            stage_messages=PARTCRAFTER_STAGES,
        ),
    )

    store.event(job_id, "parts_audit", "检查每个部件的闭合、自交，并与原图部件对应")
    runner.run(
        "audit",
        [
            local_python("hunyuan-mini"),
            "-X",
            "utf8",
            "-u",
            str(WORKERS / "audit_parts_first.py"),
            str(raw_folder),
            "--observations",
            str(plan_folder),
            "--name",
            "audit",
        ],
    )
    _publish_evidence(store, job_id, root, directory)
    audit = _read_json(raw_folder / "audit" / "audit.json") or {}
    _audit_gate(audit, len(physical))

    store.event(job_id, "parts_export", "装配部件，生成 UV 与带部件身份的 GLB")
    runner.run(
        "export",
        [
            local_python("hunyuan-mini"),
            "-X",
            "utf8",
            "-u",
            str(WORKERS / "export_planned_assembly.py"),
            "--source",
            str(raw_folder),
            "--observations",
            str(plan_folder),
            "--audit",
            "audit",
            "--output",
            str(assembly_folder),
        ],
    )
    check_cancelled()
    preview = directory / "parts_fit.png"
    return attach_assembly_candidate(
        store,
        job_id,
        assembly_folder,
        str(preview) if preview.is_file() else None,
        route="parts_first",
        pending_status="running",
    )


def _publish_evidence(store, job_id, root, directory):
    for name, parts in EVIDENCE_FILES.items():
        source = root.joinpath(*parts)
        if source.is_file():
            shutil.copyfile(source, directory / name)


__all__ = ["run_parts_first", "parts_first_status", "parts_python", "Cancelled", "CATEGORIES"]
