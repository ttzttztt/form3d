"""Measure paired opposing mesh surfaces, with explicit geometric evidence.

These measurements constrain a generated candidate to an old reconstruction.
They are not measurements of the physical product or semantic proof.
"""

import numpy as np
from scipy.spatial import cKDTree


def paired_thickness(source, visible):
    from part_registration import basis, surface_samples

    points, normals = surface_samples(source, 16000)
    front, front_normals = surface_samples(visible, 5000)
    center, axes, spans = basis(front)
    normal = front_normals.mean(0)
    if np.linalg.norm(normal) < 0.5:
        return None
    normal /= np.linalg.norm(normal)
    if axes[:, 2] @ normal < 0:
        axes[:, 2] *= -1
    xyz = (points - center) @ axes
    observed = (front - center) @ axes
    lo, hi = np.quantile(observed[:, :2], [0.1, 0.9], axis=0)
    core = np.all((xyz[:, :2] >= lo) & (xyz[:, :2] <= hi), axis=1)
    opposite = core & (normals @ normal < -0.72)
    if opposite.sum() < 100:
        return None
    front_core = observed[np.all((observed[:, :2] >= lo) & (observed[:, :2] <= hi), axis=1)]
    distance, near = cKDTree(xyz[opposite, :2]).query(front_core[:, :2])
    gap = front_core[:, 2] - xyz[opposite, 2][near]
    matched = distance < min(spans[:2]) * 0.055
    valid = matched & (gap > min(spans[:2]) * 0.025) & (gap < min(spans[:2]) * 0.65)
    coverage = float(valid.mean())
    if valid.sum() < 300 or coverage < 0.55:
        return None
    median = float(np.median(gap[valid]))
    q25, q75 = np.quantile(gap[valid], [0.25, 0.75])
    if (q75 - q25) / median > 0.40:
        return None
    cells = np.clip(((front_core[valid, :2] - lo) / (hi - lo) * 5).astype(int), 0, 4)
    occupied = len(np.unique(cells[:, 0] * 5 + cells[:, 1])) / 25
    if occupied < 0.64:
        return None
    return {
        "method": "paired_opposing_source_surfaces",
        "core_thickness_source_units": median,
        "paired_visible_sample_fraction": coverage,
        "occupied_core_grid_fraction": occupied,
        "opposing_samples": int(opposite.sum()),
        "paired_samples": int(valid.sum()),
        "gap_interquartile_range_source_units": float(q75 - q25),
        "not_real_dimension_measurement": True,
        "semantic_boundary_verified": False,
    }
