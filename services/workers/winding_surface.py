"""Reconstruct a closed candidate from an oriented, incomplete surface.

The winding is evidence from observed triangles, not knowledge of hidden shape.
All generated triangles are reconstructed, including the outer surface.
"""

import sys
from pathlib import Path
import numpy as np
import trimesh


def winding_surface(source, resolution=160, level=0.5, field_smoothing=0, direction=1, observed_distance=False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".tools/geometry_extra"))
    try:
        import igl
    except ImportError as exc:
        raise ValueError("本地实体重建依赖尚未安装，请安装 requirements-geometry.txt") from exc
    from skimage.measure import marching_cubes

    points = source.triangles_center
    weights = source.area_faces
    center = np.average(points, axis=0, weights=weights)
    covariance = ((points - center) * weights[:, None]).T @ (points - center) / weights.sum()
    _, basis = np.linalg.eigh(covariance)
    basis = basis[:, ::-1]
    if np.linalg.det(basis) < 0:
        basis[:, -1] *= -1
    vertices = np.ascontiguousarray((source.vertices - center) @ basis, dtype=np.float64)
    diagonal = float(np.linalg.norm(source.extents))
    step = float(np.ptp(vertices, axis=0).max() / resolution)
    low = vertices.min(0) - step * 4
    high = vertices.max(0) + step * 4
    shape = np.ceil((high - low) / step).astype(int) + 1
    total = int(np.prod(shape))
    field = np.empty(total, dtype=np.float32)
    stride = int(shape[1] * shape[2])
    tail = int(shape[2])
    faces = np.ascontiguousarray(source.faces, dtype=np.int64)
    # An open part's divergence volume changes under translation. It cannot
    # determine orientation; retain the source asset's triangle orientation.
    for start in range(0, total, 180000):
        flat = np.arange(start, min(start + 180000, total))
        q = np.ascontiguousarray(low + np.c_[flat // stride, (flat // tail) % shape[1], flat % shape[2]] * step)
        winding = direction * igl.fast_winding_number(vertices, faces, q)
        if observed_distance:
            signed, *_ = igl.signed_distance(q, vertices, faces, igl.SIGNED_DISTANCE_TYPE_PSEUDONORMAL)
            signed = direction * signed
            mix = np.clip((np.abs(signed) / step - 1) / 2, 0, 1)
            # Near an observed triangle use its actual distance. Far from all
            # observations use continuous winding to estimate missing surfaces.
            field[start : start + len(flat)] = level - ((1 - mix) * signed / step + mix * (level - winding))
        else:
            field[start : start + len(flat)] = winding
    field = field.reshape(tuple(shape))
    if field_smoothing:
        from scipy.ndimage import gaussian_filter

        field = gaussian_filter(field, sigma=field_smoothing)
    boundary = np.r_[
        field[0].ravel(),
        field[-1].ravel(),
        field[:, 0].ravel(),
        field[:, -1].ravel(),
        field[:, :, 0].ravel(),
        field[:, :, -1].ravel(),
    ]
    if boundary.max() >= level:
        raise ValueError("推测实体触及重建范围，不能保证闭合")
    v, f, _, _ = marching_cubes(field, level=level, spacing=(step,) * 3, allow_degenerate=False)
    v = (v + low) @ basis.T + center
    mesh = trimesh.Trimesh(v, f, process=False)
    if mesh.volume < 0:
        mesh.faces = mesh.faces[:, ::-1]
    return mesh, {
        "method": "observed_distance_guided_winding_isosurface"
        if observed_distance
        else "fast_generalized_winding_isosurface",
        "field_smoothing_grid_sigma": field_smoothing,
        "resolution": resolution,
        "level": level,
        "grid_shape": shape.tolist(),
        "grid_step_source_units": step,
        "grid_step_diagonal_ratio": step / diagonal,
        "all_output_surfaces_reconstructed": True,
        "real_hidden_geometry_recovered": False,
    }
