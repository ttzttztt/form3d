"""One-click parts-first route: photo → part plan → (user confirms) → native part generation → audit → assembly.

Each stage is an isolated worker process (see services/workers/). The orchestrator only
sequences them, streams progress into the job's event log, enforces the GPU lock and
cancellation, and stops with an explanation when a stage's evidence gate does not pass.
Nothing here relabels a failed or ambiguous part as accepted.

When the request asks for plan review (the default), the job pauses in
`awaiting_plan_review` after planning. The user may drop parts or correct their kinds;
`confirm_plan` rebuilds the plan from the edited observations with the same builder the
planner uses, records the edits, and the job resumes from generation. A restarted service
also resumes from a confirmed plan instead of planning again.
"""

import json
import os
import shutil
import time
from pathlib import Path

from .assembly_assets import attach_assembly_candidate
from .assembly_models import AssemblyPlan
from .assembly_planning import plan_from_image_observations
from .gpu import GPU_LOCK
from .local3d import local_python
from .output_quality import OutputNeedsAttention
from .preflight import InputNeedsAttention
from .provider import Cancelled
from .segmentation import segmentation_python
from .subprocesses import last_error, run_worker

ROOT = Path(__file__).resolve().parents[2]
WORKERS = ROOT / "services" / "workers"
CATEGORIES = ("sofa", "chair", "table", "cabinet")
MAX_PARTS = 16

# Part kinds offered when correcting a plan, per furniture category.
KIND_OPTIONS = {
    "sofa": ["seat_cushion", "back_cushion", "bolster", "armrest", "frame", "body", "leg"],
    "chair": ["seat_cushion", "backrest", "armrest", "leg", "frame", "body"],
    "table": ["tabletop", "leg", "frame", "panel", "shelf", "drawer"],
    "cabinet": ["door", "drawer", "shelf", "panel", "frame", "body", "leg"],
}

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

TIMEOUTS = {
    "plan": 900,
    "generate": 3600,
    "audit": 1800,
    "export": 1800,
    "parametric": 600,
    "shape": 1800,
    "regions": 900,
    "segment": 900,
    "complete": 7200,
    "assemble": 900,
}

# Must match services/workers/parametric_parts.HARD_KINDS (kept here so the API process does not
# import worker code): these kinds are built or replaced as parametric boxes/cylinders.
HARD_KINDS = {
    "table": {"tabletop", "leg", "frame", "panel", "shelf", "drawer"},
    "cabinet": {"door", "drawer", "shelf", "panel", "frame", "body", "leg"},
    "chair": {"leg"},
    "sofa": {"leg"},
}
VRAM_PROFILES = ["standard", "reduced", "low", "minimal"]

# A plan without any of these kinds is missing the part that defines the furniture
# (e.g. a "table" of one leg) and must not be built as if it were complete.
REQUIRED_KINDS = {
    "table": ({"tabletop"}, "桌面"),
    "chair": ({"seat_cushion", "backrest", "body"}, "坐面或靠背"),
    "sofa": ({"seat_cushion", "back_cushion", "body", "frame"}, "坐垫、靠垫或沙发主体"),
    "cabinet": ({"door", "drawer", "shelf", "body", "frame", "panel"}, "柜门、抽屉、层板或柜体"),
}  # services/workers/vram_profiles.py


def parts_python():
    configured = os.getenv("PARTS_PYTHON")
    candidate = (
        Path(configured)
        if configured
        else ROOT / ".venv-parts" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    return str(candidate.resolve()) if candidate.is_file() else None


def holo_python():
    configured = os.getenv("HOLO_PYTHON")
    candidate = (
        Path(configured)
        if configured
        else ROOT / ".venv-holo" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    return str(candidate.resolve()) if candidate.is_file() else None


def shape_first_ready():
    """Whole-shape generation + photo split + HoloPart: the default route when installed.

    IMG3D_SHAPE_FIRST=0 switches back to the parametric / PartCrafter routes.
    """
    return (
        os.getenv("IMG3D_SHAPE_FIRST", "1") == "1"
        and bool(local_python("hunyuan-mini"))
        and bool(holo_python())
        and bool(segmentation_python())
        and (ROOT / ".models" / "hunyuan3d-2mini").is_dir()
        and (ROOT / ".models" / "holopart" / "model_index.json").is_file()
    )


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
    planner = ("planner_runtime", "detector_weights", "segmenter_weights", "segmenter_source")
    geometry = ("geometry_runtime", "geometry_extra")
    generator = ("generator_runtime", "generator_weights", "generator_source")
    return {
        # Furniture made only of hard parts needs no generator: plan + parametric build.
        "available": all(checks[name] for name in planner + geometry),
        "generator_available": all(checks[name] for name in generator),
        "shape_first_available": shape_first_ready(),
        "checks": checks,
        "missing": [name for name, ok in checks.items() if not ok],
        "planner": "Grounding DINO Tiny + SAM 2.1 Hiera Tiny",
        "generator": "PartCrafter",
        "categories": list(CATEGORIES),
        "kind_options": KIND_OPTIONS,
        "max_parts": MAX_PARTS,
        "requires_key": False,
        "output": "geometry_only",
        "appearance_accepted": False,
    }


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path, value):
    temporary = Path(path).with_suffix(".writing")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class _Runner:
    """Runs one worker at a time, mirroring progress files into job events."""

    def __init__(self, store, job_id, folder, check_cancelled):
        self.store, self.job_id, self.folder, self.check_cancelled = store, job_id, folder, check_cancelled

    def run(self, name, command, progress_path=None, stage_messages=None):
        log_path = self.folder / f"{name}.log"
        seen = None

        def mirror_progress():
            nonlocal seen
            if progress_path is None:
                return
            value = _read_json(progress_path)
            if not value or (value.get("sequence"), value.get("stage")) == seen:
                return
            seen = (value.get("sequence"), value.get("stage"))
            message = (stage_messages or {}).get(value.get("stage"), value.get("stage"))
            if value.get("total") and value.get("step") is not None:
                message = f"{message} {value['step']}/{value['total']}"
            elif value.get("total") and value.get("part_index") is not None:
                message = f"{message} {value['part_index']}/{value['total']}"
            self.store.event(self.job_id, "parts_" + name, message)

        returncode = run_worker(
            command,
            log_path,
            timeout=TIMEOUTS[name],
            should_stop=self.check_cancelled,
            on_poll=mirror_progress,
            timeout_message=f"部件优先流程在「{name}」阶段超时，已停止；日志见 parts_first/{name}.log",
        )
        if returncode:
            detail = last_error(log_path)
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


def _physical(plan):
    return [p for p in plan.get("parts", []) if p.get("geometry_role", "physical_part") == "physical_part"]


def _plan_problem(plan):
    """None when the plan can be generated, otherwise a user-facing reason."""
    if shape_first_ready():
        return None  # parts come from the photo regions, not from the detector's kinds or counts
    physical = _physical(plan)
    unknown = [p for p in physical if p.get("kind") == "unknown"]
    kinds = {p.get("kind") for p in physical}
    needed = REQUIRED_KINDS.get(plan.get("object_category"))
    if physical and not unknown and needed and not kinds & needed[0]:
        return f"没有识别出{needed[1]}，部件清单不完整；请换一张更清晰的图，或调整框选范围"
    if plan.get("status") == "planned" and physical and len(physical) <= MAX_PARTS:
        return None
    if not physical:
        return "原图中没有识别出可生成的部件"
    if unknown:
        return f"有 {len(unknown)} 个区域的部件类别互相冲突，请为它们选择类别或去掉后再继续"
    hard = HARD_KINDS.get(plan.get("object_category"), set())
    if all(p.get("kind") in hard for p in physical):
        return None  # built parametrically: the PartCrafter part limit does not apply
    if len(physical) > MAX_PARTS:
        return f"识别出 {len(physical)} 个部件，超过 PartCrafter 单次 {MAX_PARTS} 个部件的上限，请去掉一些"
    return "部件清单证据不足"


def plan_summary(plan_folder):
    """Parts as shown to the user; `index` matches the numbers drawn on the overlay image."""
    plan = _read_json(plan_folder / "plan.json") or {}
    original = _read_json(plan_folder / "observations.original.json") or _read_json(plan_folder / "observations.json")
    order = {row["mask_sha256"]: number + 1 for number, row in enumerate((original or {}).get("parts", []))}
    parts = []
    for part in _physical(plan):
        mask = (part.get("observations") or [{}])[0].get("mask_sha256")
        parts.append({"id": part["id"], "name": part["name"], "kind": part["kind"], "index": order.get(mask)})
    parts.sort(key=lambda p: (p["index"] is None, p["index"] or 0))
    return {
        "count": len(parts),
        "parts": parts,
        "category": plan.get("object_category"),
        "kind_options": KIND_OPTIONS.get(plan.get("object_category"), []),
        "problem": _plan_problem(plan),
        "confirmed": (plan_folder / "confirmed.json").is_file(),
    }


def confirm_plan(directory, remove=(), kinds=None):
    """Apply the user's corrections and mark the plan confirmed. Raises ValueError if still not generatable."""
    plan_folder = directory / "parts_first" / "plan"
    if (plan_folder / "confirmed.json").is_file():
        raise ValueError("部件规划已经确认过")
    plan = AssemblyPlan.model_validate_json((plan_folder / "plan.json").read_text(encoding="utf-8"))
    observations = json.loads((plan_folder / "observations.json").read_text(encoding="utf-8"))
    kinds = dict(kinds or {})
    remove = set(remove)
    physical = {p.id: p for p in plan.parts if p.geometry_role == "physical_part"}
    unknown_ids = (remove | set(kinds)) - set(physical)
    if unknown_ids:
        raise ValueError("部件不存在或已变化，请刷新后重试")
    allowed = set(KIND_OPTIONS.get(plan.object_category, []))
    if any(kind not in allowed for kind in kinds.values()):
        raise ValueError("所选部件类别不适用于该家具")
    edits_by_mask = {}
    for part_id, part in physical.items():
        mask = part.observations[0].mask_sha256
        if part_id in remove:
            edits_by_mask[mask] = None
        elif part_id in kinds:
            edits_by_mask[mask] = kinds[part_id]
    rows = []
    for row in observations["parts"]:
        mask = row["mask_sha256"]
        if mask in edits_by_mask and edits_by_mask[mask] is None:
            continue
        if edits_by_mask.get(mask):
            row = {**row, "kind": edits_by_mask[mask], "kind_corrected_by_user": True}
        rows.append(row)
    if not rows:
        raise ValueError("至少需要保留一个部件")
    rebuilt = plan_from_image_observations(
        plan.primary_image_id,
        plan.primary_image_sha256,
        plan.object_category,
        plan.furniture_target.model_dump(),
        rows,
        plan_id=plan.id,
    ).model_dump()
    problem = _plan_problem(rebuilt)
    if problem:
        raise ValueError(problem)
    if not (plan_folder / "plan.original.json").exists():
        shutil.copyfile(plan_folder / "plan.json", plan_folder / "plan.original.json")
        shutil.copyfile(plan_folder / "observations.json", plan_folder / "observations.original.json")
    _write_json(plan_folder / "observations.json", {**observations, "parts": rows})
    _write_json(plan_folder / "plan.json", rebuilt)
    _write_json(
        plan_folder / "confirmed.json",
        {"removed": sorted(remove), "kinds": kinds, "by": "user", "at": time.time()},
    )
    shutil.copyfile(plan_folder / "plan.json", directory / "parts_plan.json")
    return plan_summary(plan_folder)


def run_parts_first(store, job_id, directory, request, image, check_cancelled):
    """Execute (or resume) a parts_first job. Raises the pipeline's standard exceptions."""
    status = parts_first_status()
    if not status["available"]:
        raise ValueError("部件优先生成环境未就绪，缺少：" + "、".join(status["missing"]))
    runner_status = status
    if request.object_category not in CATEGORIES:
        raise ValueError("部件优先生成需要先选择家具类别（沙发、椅子、桌子或柜子）")
    root = directory / "parts_first"
    plan_folder, raw_folder, assembly_folder = root / "plan", root / "raw", root / "assembly"
    runner = _Runner(store, job_id, root, check_cancelled)

    if (plan_folder / "confirmed.json").is_file():
        # Resume after confirmation (or a restart): keep the plan, retry everything after it.
        stamp = int(time.time() * 1000)
        for folder in (raw_folder, assembly_folder, root / "assembly_parametric", root / "parametric"):
            if folder.exists():
                folder.rename(folder.with_name(f"{folder.name}_superseded_{stamp}"))
        store.event(job_id, "parts_resume", "使用已确认的部件规划继续生成")
    else:
        if root.exists():
            # A restart before confirmation: keep the old evidence, plan again.
            root.rename(directory / f"parts_first_interrupted_{int(time.time() * 1000)}")
        root.mkdir(parents=True)
        _plan(store, job_id, request, image, runner, check_cancelled, plan_folder)
        _publish_evidence(root, directory)
        summary = plan_summary(plan_folder)
        if summary["problem"] and not request.parts_plan_review:
            raise InputNeedsAttention("部件规划未通过：" + summary["problem"] + "；识别叠加图已保存")
        if request.parts_plan_review:
            message = (
                f"识别出 {summary['count']} 个部件，请确认或修正后继续"
                if not summary["problem"]
                else "部件规划需要修正：" + summary["problem"]
            )
            store.event(
                job_id,
                "parts_plan_review",
                message,
                status="awaiting_plan_review",
                parts_plan=summary,
                parts_overlay_url=f"/api/jobs/{job_id}/files/parts_overlay.png",
            )
            return None
        _write_json(plan_folder / "confirmed.json", {"by": "automatic", "at": time.time()})
        store.event(
            job_id,
            "parts_planned",
            f"识别出 {summary['count']} 个部件",
            parts_plan=summary,
            parts_overlay_url=f"/api/jobs/{job_id}/files/parts_overlay.png",
        )
    if shape_first_ready():
        return _build_shape_first(store, job_id, runner, check_cancelled, root, image)
    plan = _read_json(plan_folder / "plan.json") or {}
    kinds = [p["kind"] for p in _physical(plan)]
    hard = HARD_KINDS.get(plan.get("object_category"), set())
    if request.parts_parametric and kinds and all(kind in hard for kind in kinds):
        return _build_parametric(store, job_id, directory, runner, root)
    if not runner_status.get("generator_available", True):
        soft = sorted({kind for kind in kinds if kind not in hard})
        raise ValueError(
            "该家具含软包或非规则部件（"
            + "、".join(soft)
            + "），需要 PartCrafter 环境："
            + "、".join(status["missing"])
        )
    return _generate_and_assemble(store, job_id, directory, runner, check_cancelled, root, request.parts_parametric)


def _build_shape_first(store, job_id, runner, check_cancelled, root, image):
    """Generate the whole shape, split it by the photo's regions, complete each part as a solid.

    Category-independent: no furniture rules decide the parts. Hidden geometry is generated and
    marked as inferred; parts whose completion strays from the observed surface are thickened
    surfaces flagged for review (assemble_shape_parts.py).
    """
    folder, plan = root / "shape_first", root / "plan"
    if folder.exists():
        folder.rename(folder.with_name(f"shape_first_superseded_{int(time.time() * 1000)}"))
    folder.mkdir(parents=True)
    hunyuan = local_python("hunyuan-mini")
    store.event(job_id, "parts_shape", "整体生成：Hunyuan3D-2mini 从原图生成完整形状")
    _with_gpu(
        check_cancelled,
        lambda: runner.run(
            "shape",
            [
                hunyuan,
                "-X",
                "utf8",
                "-u",
                WORKERS / "generate_hunyuan3d.py",
                "--input",
                plan / "generation_input.png",
                "--output",
                folder / "shape",
                "--steps",
                "30",
                "--resolution",
                "256",
                "--keep-background",
            ],
            progress_path=folder / "shape" / "local_progress.json",
        ),
    )
    store.event(job_id, "parts_regions", "在原图中按区域分割部件（SAM 2，不依赖品类规则）")
    _with_gpu(
        check_cancelled,
        lambda: runner.run(
            "regions",
            [
                segmentation_python(),
                "-X",
                "utf8",
                "-u",
                WORKERS / "photo_regions.py",
                "--plan",
                plan,
                "--output",
                folder / "regions",
            ],
        ),
    )
    store.event(job_id, "parts_segment", "把原图分区对齐并投影到整体形状上")
    runner.run(
        "segment",
        [
            hunyuan,
            "-X",
            "utf8",
            "-u",
            WORKERS / "segment_shape_by_photo.py",
            "--mesh",
            folder / "shape" / "model.glb",
            "--plan",
            plan,
            "--regions",
            folder / "regions",
            "--output",
            folder / "segment",
        ],
    )
    store.event(job_id, "parts_complete", "用 HoloPart 把每个部件补全为实体（隐藏部分为生成）")
    _with_gpu(
        check_cancelled,
        lambda: runner.run(
            "complete",
            [
                holo_python(),
                "-X",
                "utf8",
                "-u",
                WORKERS / "complete_parts_holopart.py",
                "--input",
                folder / "segment" / "segmented.glb",
                "--output",
                folder / "complete",
            ],
        ),
    )
    runner.run(
        "assemble",
        [
            hunyuan,
            "-X",
            "utf8",
            "-u",
            WORKERS / "assemble_shape_parts.py",
            "--plan",
            plan,
            "--image",
            store.root / image["normalized_path"],
            "--regions",
            folder / "regions",
            "--segmentation",
            folder / "segment",
            "--completion",
            folder / "complete",
            "--output",
            folder / "assembly",
        ],
    )
    return attach_assembly_candidate(
        store, job_id, folder / "assembly", None, route="parts_first", pending_status="running"
    )


def _build_parametric(store, job_id, directory, runner, root):
    """All planned parts are hard parts: build them from the masks on the CPU, no AI sampling."""
    store.event(job_id, "parts_parametric", "全部为规则部件：按原图掩码拟合参数化构件（不使用显卡）")
    output = root / "parametric"
    runner.run(
        "parametric",
        [
            local_python("hunyuan-mini"),
            "-X",
            "utf8",
            "-u",
            WORKERS / "fit_parametric_parts.py",
            "from-plan",
            "--plan",
            root / "plan",
            "--output",
            output,
        ],
    )
    return attach_assembly_candidate(store, job_id, output, None, route="parts_first", pending_status="running")


def _plan(store, job_id, request, image, runner, check_cancelled, plan_folder):
    store.event(job_id, "parts_plan", "在原图中识别家具部件（检测 + 分割）")
    target = request.target
    command = [
        segmentation_python(),
        "-X",
        "utf8",
        "-u",
        WORKERS / "plan_assembly_from_photo.py",
        "--input",
        store.root / image["normalized_path"],
        "--image-id",
        request.image_id,
        "--category",
        request.object_category,
        "--target",
        target.x,
        target.y,
        target.width,
        target.height,
        "--output",
        plan_folder,
    ]
    _with_gpu(check_cancelled, lambda: runner.run("plan", command))


def _generate_with_vram_fallback(store, job_id, runner, check_cancelled, command, raw_folder):
    """Start with the profile PartCrafter picks for this card; on out-of-memory retry smaller, in a fresh process."""
    requested = "auto"
    seed_args = []  # default seed first; one reseeded retry after a decode failure
    while True:
        try:
            _with_gpu(
                check_cancelled,
                lambda: runner.run(
                    "generate",
                    command + ["--vram-profile", requested] + seed_args,
                    raw_folder / "progress.json",
                    PARTCRAFTER_STAGES,
                ),
            )
        except ValueError:
            facts = _read_json(raw_folder / "generation.json") or {}
            used = (facts.get("vram_profile") or {}).get("name")
            # Measured on a 6 GB card: thin parts (chair legs) sometimes decode to nothing at any
            # profile, and a different seed usually fixes it. Retry once at the same profile.
            if not facts.get("out_of_memory") and "failed to decode" in (facts.get("error") or "") and not seed_args:
                raw_folder.rename(raw_folder.with_name(f"raw_decode_failed_{int(time.time() * 1000)}"))
                seed_args = ["--seed", "43"]
                requested = used if used in VRAM_PROFILES else requested
                store.event(job_id, "parts_decode_retry", "部分部件网格解码失败，换一个随机种子重试一次")
                continue
            if not facts.get("out_of_memory") or used not in VRAM_PROFILES or used == VRAM_PROFILES[-1]:
                if facts.get("out_of_memory"):
                    raise ValueError(
                        "显存不足：最低档位仍无法完成，请在部件确认时减少部件数，或让桌腿、柜门等改用参数化构件"
                    ) from None
                raise
            failed = raw_folder.with_name(f"raw_oom_{used}_{int(time.time() * 1000)}")
            raw_folder.rename(failed)
            requested = VRAM_PROFILES[VRAM_PROFILES.index(used) + 1]
            store.event(job_id, "parts_vram_retry", f"显存不足（档位 {used}），改用更省显存的档位 {requested} 重试")
            continue
        facts = _read_json(raw_folder / "generation.json") or {}
        profile = facts.get("vram_profile") or {}
        peak = facts.get("gpu_peak_reserved_bytes")
        if peak:
            store.event(
                job_id,
                "parts_generated",
                f"部件生成完成：显存峰值 {peak / 1024**3:.1f} GB，档位 {profile.get('name', '手动')}"
                f"（每部件 {facts.get('tokens_per_part')} token）",
                parts_generation={
                    "vram_profile": profile,
                    "gpu_peak_reserved_bytes": peak,
                    "seconds": facts.get("elapsed_seconds"),
                },
            )
        return facts


def _generate_and_assemble(store, job_id, directory, runner, check_cancelled, root, parametric=True):
    plan_folder, raw_folder, assembly_folder = root / "plan", root / "raw", root / "assembly"
    physical = _physical(_read_json(plan_folder / "plan.json") or {})
    command = [
        parts_python(),
        "-X",
        "utf8",
        "-u",
        WORKERS / "generate_partcrafter.py",
        "--input",
        plan_folder / "generation_input.png",
        "--plan",
        plan_folder / "plan.json",
        "--count-source",
        "image_plan",
        "--output",
        raw_folder,
    ]
    _generate_with_vram_fallback(store, job_id, runner, check_cancelled, command, raw_folder)

    store.event(job_id, "parts_audit", "检查每个部件的闭合、自交，并与原图部件对应")
    geometry_python = local_python("hunyuan-mini")
    runner.run(
        "audit",
        [
            geometry_python,
            "-X",
            "utf8",
            "-u",
            WORKERS / "audit_parts_first.py",
            raw_folder,
            "--observations",
            plan_folder,
            "--name",
            "audit",
        ],
    )
    _publish_evidence(root, directory)
    _audit_gate(_read_json(raw_folder / "audit" / "audit.json") or {}, len(physical))

    store.event(job_id, "parts_export", "装配部件，生成 UV 与带部件身份的 GLB")
    runner.run(
        "export",
        [
            geometry_python,
            "-X",
            "utf8",
            "-u",
            WORKERS / "export_planned_assembly.py",
            "--source",
            raw_folder,
            "--observations",
            plan_folder,
            "--audit",
            "audit",
            "--output",
            assembly_folder,
        ],
    )
    check_cancelled()
    final = assembly_folder
    plan = _read_json(plan_folder / "plan.json") or {}
    hard = HARD_KINDS.get(plan.get("object_category"), set())
    if parametric and any(p["kind"] in hard for p in physical):
        store.event(job_id, "parts_parametric", "把桌面、支腿、柜门等规则部件替换为拟合的参数化构件")
        refined = root / "assembly_parametric"
        try:
            runner.run(
                "parametric",
                [
                    geometry_python,
                    "-X",
                    "utf8",
                    "-u",
                    WORKERS / "fit_parametric_parts.py",
                    "refine",
                    "--assembly",
                    assembly_folder,
                    "--output",
                    refined,
                ],
            )
            final = refined
            rows = ((_read_json(refined / "assembly.json") or {}).get("parametric_fit") or {}).get("parts", [])
            kept = [r for r in rows if not r.get("replaced")]
            store.event(
                job_id,
                "parts_parametric_done",
                f"{len(rows) - len(kept)}/{len(rows)} 个规则部件已替换为参数化构件"
                + (f"；{len(kept)} 个与拟合形状偏差较大，保留 AI 结果" if kept else ""),
            )
        except ValueError as exc:
            store.event(job_id, "parts_parametric_skipped", f"参数化替换未完成，保留 AI 部件：{exc}"[:300])
    preview = directory / "parts_fit.png"
    return attach_assembly_candidate(
        store,
        job_id,
        final,
        str(preview) if preview.is_file() else None,
        route="parts_first",
        pending_status="running",
    )


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


def _publish_evidence(root, directory):
    for name, parts in EVIDENCE_FILES.items():
        source = root.joinpath(*parts)
        if source.is_file():
            shutil.copyfile(source, directory / name)


__all__ = [
    "run_parts_first",
    "confirm_plan",
    "plan_summary",
    "parts_first_status",
    "parts_python",
    "Cancelled",
    "CATEGORIES",
    "KIND_OPTIONS",
]
