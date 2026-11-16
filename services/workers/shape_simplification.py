# -*- coding: utf-8 -*-
"""Measured QEM simplification. Rejected attempts never replace their source."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / ".tools/geometry_extra")]
import cv2
import numpy as np
import trimesh
from solid_partition import prepare_mesh
from reconstruct_parts import intersections
from part_registration import surface_samples

LIMITS = {
    "surface_p99_diagonal_ratio": 0.0025,
    "surface_max_diagonal_ratio": 0.008,
    "bounds_delta_diagonal_ratio": 0.003,
    "volume_relative_error": 0.015,
    "minimum_projection_iou": 0.985,
}


def component_count(mesh):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    edges = mesh.face_adjacency
    graph = coo_matrix(
        (np.ones(len(edges), dtype=np.uint8), (edges[:, 0], edges[:, 1])), shape=(len(mesh.faces), len(mesh.faces))
    ).tocsr()
    return int(connected_components(graph, directed=False, return_labels=False))


def surface_error(source, result, count=5000):
    import igl

    diagonal = max(float(np.linalg.norm(source.extents)), 1e-12)
    rows = []
    for original, target in ((source, result), (result, source)):
        points = surface_samples(original, count)[0]
        distance, *_ = igl.signed_distance(
            np.ascontiguousarray(points),
            np.ascontiguousarray(target.vertices),
            np.ascontiguousarray(target.faces, dtype=np.int64),
            igl.SIGNED_DISTANCE_TYPE_UNSIGNED,
        )
        distance = np.abs(distance) / diagonal
        rows.append(
            {
                "p95": float(np.quantile(distance, 0.95)),
                "p99": float(np.quantile(distance, 0.99)),
                "maximum": float(distance.max()),
            }
        )
    return {
        "source_to_result": rows[0],
        "result_to_source": rows[1],
        "samples_per_direction": count,
        "sampling": "deterministic_area_weighted_surface_points",
        "not_hausdorff_or_product_accuracy": True,
    }


def silhouette_masks(mesh, bounds, size=192):
    center = bounds.mean(0)
    scale = (size - 12) / max(float(np.linalg.norm(bounds[1] - bounds[0])), 1e-12)
    vertices = (mesh.vertices - center) * scale
    masks = []
    for a, b in ((0, 1), (0, 2), (1, 2)):
        points = np.rint(vertices[:, [a, b]] + size / 2).astype(np.int32)
        mask = np.zeros((size, size), np.uint8)
        for triangle in points[mesh.faces]:
            cv2.fillConvexPoly(mask, triangle, 1)
        masks.append(mask > 0)
    return masks


def validate_simplification(source, result, source_masks=None):
    diagonal = max(float(np.linalg.norm(source.extents)), 1e-12)
    deviation = surface_error(source, result)
    bounds = float(np.max(abs(source.bounds - result.bounds)) / diagonal)
    closed = bool(source.is_watertight)
    volume = float(abs(result.volume - source.volume) / max(abs(source.volume), 1e-12)) if closed else None
    components_before = component_count(source)
    components_after = component_count(result)
    self_intersections = int(intersections(result))
    source_masks = source_masks if source_masks is not None else silhouette_masks(source, source.bounds)
    result_masks = silhouette_masks(result, source.bounds)
    ious = [float((a & b).sum() / max((a | b).sum(), 1)) for a, b in zip(source_masks, result_masks)]
    failures = []
    if any(
        d["p99"] > LIMITS["surface_p99_diagonal_ratio"] or d["maximum"] > LIMITS["surface_max_diagonal_ratio"]
        for d in (deviation["source_to_result"], deviation["result_to_source"])
    ):
        failures.append("双向采样表面偏差超限")
    if bounds > LIMITS["bounds_delta_diagonal_ratio"]:
        failures.append("外包范围变化超限")
    if min(ious) < LIMITS["minimum_projection_iou"]:
        failures.append("侧向轮廓变化超限")
    if closed and (
        not result.is_watertight
        or not result.is_winding_consistent
        or result.volume <= 0
        or volume > LIMITS["volume_relative_error"]
    ):
        failures.append("闭合体或体积变化检查未通过")
    if components_after != components_before:
        failures.append("连通片数量变化")
    if self_intersections:
        failures.append("减面出现自交")
    return {
        "passed": not failures,
        "failures": failures,
        "surface_error": deviation,
        "bounds_delta_diagonal_ratio": bounds,
        "volume_relative_error": volume,
        "source_closed": closed,
        "result_closed": bool(result.is_watertight),
        "components_before": components_before,
        "components_after": components_after,
        "self_intersection_faces": self_intersections,
        "orthographic_projection_ious": ious,
        "limits": LIMITS,
        "physical_appearance_verified": False,
    }


def simplify_shape(source, target_faces=100000):
    """Pure untextured shape path, before registration/UV/material assignment."""
    import pymeshlab

    source, _ = prepare_mesh(source)
    evidence = {
        "requested_faces": int(target_faces),
        "faces_before": len(source.faces),
        "accepted": False,
        "attempts": [],
    }
    if len(source.faces) <= target_faces:
        evidence.update(status="within_budget", faces_after=len(source.faces))
        return source, evidence
    source_masks = silhouette_masks(source, source.bounds)
    # Retry with a less aggressive budget only after a measured rejection.
    budgets = sorted(
        set([int(target_faces), min(len(source.faces) - 1, max(int(target_faces * 2), int(len(source.faces) * 0.4)))])
    )
    for budget in budgets:
        ms = pymeshlab.MeshSet()
        ms.add_mesh(pymeshlab.Mesh(source.vertices, source.faces.astype(np.int32)))
        ms.meshing_decimation_quadric_edge_collapse(
            targetfacenum=budget,
            preserveboundary=True,
            preservenormal=True,
            preservetopology=True,
            optimalplacement=True,
            qualitythr=0.5,
        )
        current = ms.current_mesh()
        candidate, _ = prepare_mesh(trimesh.Trimesh(current.vertex_matrix(), current.face_matrix(), process=False))
        checks = validate_simplification(source, candidate, source_masks)
        attempt = {"budget": budget, "faces": len(candidate.faces), "checks": checks}
        if 0 < checks["self_intersection_faces"] <= 16 and checks["source_closed"]:
            from storage_contacts import clean_storage_contacts

            try:
                cleaned, cleanup = clean_storage_contacts(candidate)
                rechecked = validate_simplification(source, cleaned, source_masks)
                attempt["bounded_storage_cleanup"] = {"action": cleanup, "checks": rechecked}
                if rechecked["passed"]:
                    candidate, checks = cleaned, rechecked
            except ValueError as exc:
                attempt["bounded_storage_cleanup"] = {"rejected": str(exc)}
        evidence["attempts"].append(attempt)
        if checks["passed"] and len(candidate.faces) < len(source.faces):
            evidence.update(
                status="simplified",
                accepted=True,
                faces_after=len(candidate.faces),
                target_reached=len(candidate.faces) <= target_faces * 1.02,
            )
            return candidate, evidence
    evidence.update(status="preserved_after_rejection", faces_after=len(source.faces), target_reached=False)
    return source, evidence


if __name__ == "__main__":
    import argparse, json, time

    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--target-faces", type=int, default=100000)
    a = p.parse_args()
    started = time.monotonic()
    source = trimesh.load(a.input, force="mesh", process=False)
    result, evidence = simplify_shape(source, a.target_faces)
    output = Path(a.output)
    output.mkdir(parents=True, exist_ok=True)
    result.export(output / "model.glb")
    evidence["elapsed_seconds"] = time.monotonic() - started
    (output / "simplification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False), flush=True)
