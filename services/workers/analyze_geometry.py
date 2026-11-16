# -*- coding: utf-8 -*-
"""Measured output geometry screening. No image/3D ground-truth accuracy claims."""

import argparse
import hashlib
import json
from pathlib import Path
import time

RULES = {
    "version": "1.0",
    "volumetric_thin_ratio": 0.025,
    "vase_flat_cross_ratio": 0.30,
    "vase_std_ratio": 0.35,
    "box_surface_fraction": 0.985,
    "box_volume_fill": 0.96,
}


def analyze(path, category="unknown"):
    import numpy as np
    import trimesh

    started = time.monotonic()
    mesh = trimesh.load(path, force="mesh", process=False)
    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.faces)
    reasons = []
    warnings = []
    if not len(vertices) or not len(faces) or not np.isfinite(vertices).all():
        raise ValueError("Empty mesh or non-finite positions")
    sample = vertices[:: max(1, len(vertices) // 30000)]
    centered = sample - sample.mean(axis=0)
    _, singular, basis = np.linalg.svd(centered, full_matrices=False)
    extents = np.sort(np.ptp(centered @ basis.T, axis=0))
    std = np.sort(singular)
    thin_ratio = float(extents[0] / max(1e-12, extents[-1]))
    cross_ratio = float(extents[0] / max(1e-12, extents[1]))
    std_ratio = float(std[0] / max(1e-12, std[1]))
    aabb = np.maximum(mesh.extents, 1e-12)
    normalized = (vertices - mesh.bounds[0]) / aabb
    on_box = float(np.any((normalized < 0.005) | (normalized > 0.995), axis=1).mean())
    fill = float(abs(mesh.volume) / np.prod(aabb))
    components = mesh.split(only_watertight=False)
    component_sizes = sorted(
        [{"faces": len(part.faces), "area": float(part.area)} for part in components],
        key=lambda item: item["faces"],
        reverse=True,
    )
    volumetric = category in ["vase", "sofa", "chair", "plant", "cabinet", "table"]
    if volumetric and thin_ratio < RULES["volumetric_thin_ratio"]:
        reasons.append(
            {
                "code": "volumetric_object_flattened",
                "message": "该品类模型近似薄片，缺少可辨体积；需要其他视图或生成方案",
            }
        )
    elif category == "vase" and cross_ratio < RULES["vase_flat_cross_ratio"] and std_ratio < RULES["vase_std_ratio"]:
        reasons.append(
            {
                "code": "vase_flat_cross_section",
                "message": "花瓶模型横向厚度偏薄，疑似沿轮廓生成的薄片；单张正面图不足以确认瓶身",
            }
        )
    elif category in ["plant", "sofa", "chair"] and cross_ratio < 0.30 and std_ratio < 0.10:
        reasons.append({"code": "low_rank_volume", "message": "主体近似弯曲剪影片，缺少该品类应有的立体结构"})
    elif thin_ratio < RULES["volumetric_thin_ratio"]:
        warnings.append("模型很薄；当前品类可能允许薄结构，保留候选供检查")
    if (
        category in ["sofa", "chair", "plant"]
        and on_box > RULES["box_surface_fraction"]
        and fill > RULES["box_volume_fill"]
    ):
        reasons.append({"code": "box_degeneracy", "message": "该品类输出近似实心方块，缺少应有结构"})
    if len(components) > 1:
        warnings.append("模型有 %d 个几何连通片；可能包含独立部件或漂浮碎片，未自动删除" % len(components))
    if not mesh.is_watertight:
        warnings.append("网格并非完全封闭，实体用途需要另行检查")
    return {
        "status": "blocked" if reasons else "pass",
        "category": category,
        "reasons": reasons,
        "warnings": warnings,
        "metrics": {
            "vertices": len(vertices),
            "triangles": len(faces),
            "pca_extents": extents.tolist(),
            "thin_ratio": thin_ratio,
            "cross_section_ratio": cross_ratio,
            "std_thickness_ratio": std_ratio,
            "aabb_surface_fraction": on_box,
            "aabb_volume_fill": fill,
            "components": len(components),
            "largest_components": component_sizes[:20],
            "watertight": bool(mesh.is_watertight),
        },
        "rules": RULES,
        "duration_seconds": round(time.monotonic() - started, 3),
        "model_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "worker_revision": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "appearance_accepted": False,
        "score_note": "Heuristic geometry screening; no measured image similarity, hidden-surface correctness or physical accuracy. Openings and semantic parts are not proven.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--category", default="unknown")
    args = parser.parse_args()
    result = analyze(args.input, args.category)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": result["status"],
                "reasons": [r["code"] for r in result["reasons"]],
                "seconds": result["duration_seconds"],
            }
        ),
        flush=True,
    )
