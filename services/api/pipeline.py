import json
import logging

from PIL import Image, ImageDraw

from .geometry import build_template, inspect_glb, validate_glb
from .models import JobRequest
from .local3d import generate_local
from .parts_first import run_parts_first
from .provider import Cancelled, RemotePending, SubmissionUnknown, generate_meshy
from .preflight import InputNeedsAttention
from .output_quality import OutputNeedsAttention

log = logging.getLogger(__name__)


def prepare_image(source, destination, request):
    with Image.open(source) as image:
        rgba = image.convert("RGBA")
    w, h = rgba.size
    t = request.target
    bounds = (round(t.x * w), round(t.y * h), round((t.x + t.width) * w), round((t.y + t.height) * h))
    if bounds[2] - bounds[0] < 16 or bounds[3] - bounds[1] < 16:
        raise ValueError("目标选区至少需要 16 × 16 像素")
    mask = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(mask)
    for stroke in request.strokes:
        radius = max(1, round(stroke.radius * min(w, h)))
        points = [(round(p.x * w), round(p.y * h)) for p in stroke.points]
        if len(points) > 1:
            draw.line(points, fill=0, width=radius * 2, joint="curve")
        for x, y in points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=0)
    from PIL import ImageChops

    alpha = ImageChops.multiply(rgba.getchannel("A"), mask)
    rgba.putalpha(alpha)
    cropped = rgba.crop(bounds)
    if not cropped.getchannel("A").getbbox():
        raise ValueError("选区已被全部擦除，请重置背景擦除后再试")
    cropped.save(destination, "PNG")
    mask.crop(bounds).save(destination.parent / "mask.png", "PNG")
    return {
        "crop_pixels": list(bounds),
        "input_size": [w, h],
        "output_size": list(cropped.size),
        "background_method": "manual_erase" if request.strokes else "crop_only",
        "inpainting": False,
    }


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_job(store, job_id):
    job = store.job(job_id)
    if not job or job["status"] == "cancelled":
        return
    request = JobRequest.model_validate(job["request"])
    directory = store.root / "jobs" / job_id
    directory.mkdir(parents=True, exist_ok=True)

    def check_cancelled():
        if store.job(job_id)["status"] == "cancelled":
            raise Cancelled()

    try:
        store.event(job_id, "prepare", "准备目标图片与人工擦除掩码", status="running", error=None)
        image = store.image(request.image_id)
        preparation = prepare_image(store.root / image["normalized_path"], directory / "prepared.png", request)
        check_cancelled()
        if request.route == "assistant":
            store.event(
                job_id,
                "awaiting_assistant",
                "图片已准备好，请在当前对话中让我处理待建模任务；完成后模型会显示在这里",
                status="awaiting_assistant",
                prepared_url="/api/jobs/%s/files/prepared.png" % job_id,
                preparation=preparation,
            )
            return
        if request.route == "parts_first":
            store.event(
                job_id,
                "generate",
                "开始部件优先生成：识别部件 → 按部件生成 → 审计 → 装配",
                prepared_url="/api/jobs/%s/files/prepared.png" % job_id,
                preparation=preparation,
            )
            run_parts_first(store, job_id, directory, request, image, check_cancelled)
            return
        store.event(
            job_id,
            "generate",
            {"template": "按结构与参数构建家具", "local": "准备本地图生 3D 推理", "meshy": "等待云端图生 3D 结果"}[
                request.route
            ],
            prepared_url="/api/jobs/%s/files/prepared.png" % job_id,
            preparation=preparation,
        )
        model = directory / "model.glb"
        local_summary = None
        if request.route == "template":
            metrics = build_template(request, model)
        elif request.route == "local":
            local_summary = generate_local(
                store,
                job_id,
                directory / "prepared.png",
                directory,
                check_cancelled,
                remove_background=request.local_remove_background,
                engine=request.local_engine,
                segmentation=request.local_segmentation,
            )
            metrics = {}
        else:
            generate_meshy(store, job_id, directory / "prepared.png", model)
            metrics = {}
        check_cancelled()
        store.event(job_id, "validate", "检查 GLB 结构、部件和文件资源")
        metrics.update(inspect_glb(model))
        validation = validate_glb(model)
        check_cancelled()
        template = request.route == "template"
        local = request.route == "local"
        shape_only = local and (local_summary or {}).get("actual_engine", request.local_engine) == "hunyuan-mini"
        scale = (
            "normalized_unverified"
            if local
            else "user_confirmed_parameters"
            if template and request.dimensions.confirmed
            else "proportional_preview"
        )
        report = {
            "schema_version": "1.0",
            "job_id": job_id,
            "asset_version": job_id,
            "route": request.route,
            "units": "meter" if template else "normalized" if local else "provider_unverified",
            "scale_status": scale,
            "ar_true_scale_ready": False,
            "checks": {
                "glb_structure": "pass",
                "full_gltf_validator": validation["status"],
                "viewer_load": "needs_review",
                "appearance": "needs_review",
                "dimensions": "parameter_constraints_only" if template else "unverified",
            },
            "gltf_validation": validation,
            "evidence": {
                "image_id": request.image_id,
                "preparation": preparation,
                "geometry_source": "user_selected_template_and_parameters"
                if template
                else "hunyuan3d_2mini_image_to_shape"
                if shape_only
                else "triposr_image_to_3d"
                if local
                else "meshy_image_to_3d",
                "hidden_surfaces": "template_assumption" if template else "ai_inferred",
                "texture_source": "user_selected_approximate_color"
                if template
                else "none_neutral_material"
                if shape_only
                else "predicted_vertex_colors"
                if local
                else "provider_generated",
            },
            "warnings": (
                ["模板依据人工选择与参数构建，尚未从图片自动恢复结构", "默认不提供照片纹理与内部装配精度"]
                if template
                else [
                    "Hunyuan3D-2mini 目前仅生成几何，不含纹理；灰色仅用于检查形状",
                    "本地实验方案，生成完成不表示商品外观验收合格",
                    "背面和遮挡结构包含推测，实物尺寸未校准",
                ]
                if shape_only
                else [
                    "TripoSR 根据当前图片自动推理形状与颜色，不可见表面包含推测",
                    "输出为比例预览，尚未校准实物尺寸",
                    "细杆、孔洞、镜面与精确商品文字可能失真",
                ]
                if local
                else ["生成的不可见表面为 AI 推测", "云端输出尚未校准尺寸，填写的尺寸未用于拉伸模型"]
            ),
            "metrics": metrics,
            "review_status": "pending",
        }
        if local_summary:
            report["local_inference"] = local_summary
            if local_summary.get("geometry_quality"):
                report["evidence"]["output_geometry"] = local_summary["geometry_quality"]
                report["warnings"].extend(local_summary["geometry_quality"].get("warnings", []))
                report["checks"]["output_geometry"] = local_summary["geometry_quality"]["status"]
            if local_summary.get("watertight") is False:
                report["warnings"].append("生成网格并非完全封闭；作为打印或实体网格使用前需要另行检查和修复")
            report["evidence"].update(
                model_input_url="/api/jobs/%s/files/model_input.png" % job_id,
                foreground_url="/api/jobs/%s/files/foreground.png" % job_id,
                background_method=local_summary["background_method"],
            )
            if local_summary.get("segmentation"):
                report["evidence"]["target_segmentation"] = local_summary["segmentation"]
            if local_summary.get("input_preparation"):
                report["evidence"]["input_preparation"] = local_summary["input_preparation"]
                report["warnings"].extend(local_summary["input_preparation"].get("warnings", []))
        metadata = {
            "name": request.name,
            "job_id": job_id,
            "route": request.route,
            "dimensions_requested": request.dimensions.model_dump(),
            "scale_status": scale,
            "coordinate_system": "gltf_y_up_right_handed",
            "metrics": metrics,
            "review_status": "pending",
        }
        strategy = {
            "mode": "single_primary_view",
            "primary_image_id": request.image_id,
            "reference_image_ids": request.reference_image_ids,
            "references_used_for_geometry": False,
        }
        report["evidence"]["reconstruction_strategy"] = strategy
        metadata["reconstruction_strategy"] = strategy
        if request.reference_image_ids:
            report["warnings"].append("补充视图仅供验收对照，本次几何未融合这些图片")
        write_json(directory / "quality_report.json", report)
        write_json(directory / "metadata.json", metadata)
        store.event(
            job_id,
            "review",
            "模型已生成，请旋转查看并审核",
            status="awaiting_review",
            metrics=metrics,
            report=report,
            model_url="/api/jobs/%s/files/model.glb" % job_id,
            prepared_url="/api/jobs/%s/files/prepared.png" % job_id,
            model_input_url="/api/jobs/%s/files/model_input.png" % job_id if local else None,
            foreground_url="/api/jobs/%s/files/foreground.png" % job_id if local else None,
            review_status="pending",
        )
    except Cancelled:
        pass
    except InputNeedsAttention as exc:
        store.event(
            job_id, "input_blocked", str(exc), status="awaiting_input", attention_kind="local_input", error=str(exc)
        )
    except OutputNeedsAttention as exc:
        store.event(
            job_id, "output_blocked", str(exc), status="awaiting_input", attention_kind="local_output", error=str(exc)
        )
    except (SubmissionUnknown, RemotePending) as exc:
        store.event(job_id, "attention", str(exc), status="awaiting_input", error=str(exc))
    except Exception as exc:
        log.error("Pipeline failed: %s (%s)", job_id, type(exc).__name__)
        # Do not expose provider credentials, signed URLs or raw remote responses.
        safe = str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else "处理暂时失败，请查看本地服务日志"
        store.event(job_id, "failed", safe[:500], status="failed", error=safe[:500])
