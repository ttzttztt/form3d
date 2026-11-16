"""UV diagnostics used to choose between projections, never photo fidelity scores."""

import numpy as np


def uv_diagnostics(vertices, faces, uv):
    vertices = np.asarray(vertices, dtype=float)
    uv = np.asarray(uv, dtype=np.float32).astype(float)
    diagonal = max(float(np.linalg.norm(np.ptp(vertices, axis=0))), 1e-9)
    _, welded = np.unique(np.round(vertices / diagonal, 7), axis=0, return_inverse=True)
    a = np.concatenate((faces[:, 0], faces[:, 1], faces[:, 2]))
    b = np.concatenate((faces[:, 1], faces[:, 2], faces[:, 0]))
    swap = welded[a] > welded[b]
    left, right = np.where(swap, b, a), np.where(swap, a, b)
    edges = np.c_[welded[left], welded[right]]
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    sorted_edges = edges[order]
    same = np.all(sorted_edges[1:] == sorted_edges[:-1], axis=1)
    starts = np.r_[0, np.flatnonzero(~same) + 1]
    counts = np.diff(np.r_[starts, len(edges)])
    group = np.repeat(np.arange(len(starts)), counts)
    coords = np.c_[uv[left], uv[right]][order]
    changes = same & np.any(abs(coords[1:] - coords[:-1]) > 1e-5, axis=1)
    seams = np.zeros(len(starts), dtype=bool)
    seams[group[1:][changes]] = True
    lengths = np.linalg.norm(vertices[left[order[starts]]] - vertices[right[order[starts]]], axis=1)
    triangles = vertices[faces]
    edge, other = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    area = np.linalg.norm(np.cross(edge, other), axis=1) / 2
    tex = uv[faces]
    ue, uo = tex[:, 1] - tex[:, 0], tex[:, 2] - tex[:, 0]
    uv_area = abs(ue[:, 0] * uo[:, 1] - ue[:, 1] * uo[:, 0]) / 2
    valid = area > diagonal**2 * 1e-12
    length = np.linalg.norm(edge[valid], axis=1)
    x = np.sum(edge[valid] * other[valid], axis=1) / np.maximum(length, 1e-15)
    y = np.sqrt(np.maximum(np.sum(other[valid] ** 2, axis=1) - x * x, 1e-30))
    jacobian = np.zeros((valid.sum(), 2, 2))
    jacobian[:, :, 0] = ue[valid] / np.maximum(length[:, None], 1e-15)
    jacobian[:, :, 1] = (uo[valid] - jacobian[:, :, 0] * x[:, None]) / y[:, None]
    singular = np.linalg.svd(jacobian, compute_uv=False)
    ratio = singular[:, 0] / np.maximum(singular[:, 1], 1e-15)
    weights = area[valid]
    total = max(float(weights.sum()), 1e-15)
    return {
        "normalized_seam_length": float(lengths[seams].sum() / diagonal),
        "collapsed_geometry_area_fraction": float(area[uv_area < 1e-12].sum() / max(float(area.sum()), 1e-15)),
        "area_fraction_anisotropy_over_4": float(weights[ratio > 4].sum() / total),
        "geometric_mean_anisotropy": float(np.exp(np.sum(weights * np.log(np.clip(ratio, 1, 1000))) / total)),
    }


def prefer_proxy(baseline, candidate):
    """Conservative heuristic: visibly fewer seams, bounded area stretch/collapse."""
    return bool(
        all(np.isfinite(v) for v in [*baseline.values(), *candidate.values()])
        and candidate["normalized_seam_length"] < baseline["normalized_seam_length"] * 0.95
        and candidate["geometric_mean_anisotropy"] <= baseline["geometric_mean_anisotropy"] * 1.1
        and candidate["area_fraction_anisotropy_over_4"] <= 0.005
        and candidate["collapsed_geometry_area_fraction"] <= 0.001
    )
