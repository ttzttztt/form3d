"""Recover supported rim curvature and preserve corroborated dimple candidates."""

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter
from scipy.spatial import cKDTree
from shapely import points as shape_points, distance as shape_distance, covers
from shapely.geometry import Point


def refine_seat_details(xy, top, bottom, polygon, source, known, excluded, photo):
    from soft_part_repair import interpolate
    from photo_part_evidence import project

    centers = source.triangles_center
    normals = source.face_normals
    areas = source.area_faces
    height = float(np.median(top) - bottom)
    d = shape_distance(shape_points(centers[:, [0, 2]]), polygon.boundary)
    roof = interpolate(centers[known][:, [0, 2]], centers[known, 1], centers[:, [0, 2]], k=6)
    drop = roof - centers[:, 1]
    blocked = covers(excluded, shape_points(centers[:, [0, 2]]))
    edge = (
        (~blocked)
        & (normals[:, 1] > 0.15)
        & (normals[:, 1] < 0.8)
        & (drop > height * 0.01)
        & (drop < height * 0.35)
        & (d < height * 0.35)
    )
    radii = d[edge] + drop[edge] + np.sqrt(np.maximum(0, 2 * d[edge] * drop[edge]))
    valid = (radii > height * 0.015) & (radii < height * 0.4)
    radius = None
    if valid.sum() >= 30:
        values = radii[valid]
        weights = areas[edge][valid]
        order = np.argsort(values)
        radius = float(values[order[np.searchsorted(np.cumsum(weights[order]), weights.sum() / 2)]])
        distance = shape_distance(shape_points(xy), polygon.boundary)
        band = distance < radius
        bevel = radius - np.sqrt(np.maximum(0, radius * radius - (radius - np.minimum(distance, radius)) ** 2))
        # Limit the new profile by the already observed roof height.
        base = interpolate(centers[known][:, [0, 2]], centers[known, 1], xy, k=20)
        top[band] = np.minimum(top[band], base[band] - bevel[band])
    # Detect only existing depressions supported by both mesh and photograph.
    lo, hi = polygon.bounds[:2], polygon.bounds[2:]
    axis0 = np.linspace(lo[0], hi[0], 96)
    axis1 = np.linspace(lo[1], hi[1], 96)
    grid = np.stack(np.meshgrid(axis0, axis1, indexing="ij"), axis=-1)
    values = interpolate(centers[known][:, [0, 2]], centers[known, 1], grid.reshape(-1, 2), k=6).reshape(96, 96)
    residual = gaussian_filter(values, 2.5) - values
    peaks = (residual == maximum_filter(residual, size=7)) & (residual > height * 0.025) & (residual < height * 0.25)
    candidates = []
    image = cv2.cvtColor(photo["rgb"], cv2.COLOR_RGB2GRAY)
    mask = photo.get("mask")
    matrix = np.asarray(photo["projection_from_world"])
    for i, j in zip(*np.nonzero(peaks)):
        point = grid[i, j]
        if not polygon.buffer(-height * 0.6).covers(Point(point)) or excluded.covers(Point(point)):
            continue
        nearest = cKDTree(centers[known][:, [0, 2]]).query(point)[0]
        if nearest > height * 0.12:
            continue
        world = np.array([[point[0], values[i, j], point[1]]])
        pixel, _ = project(world, matrix)
        u, v = np.rint(pixel[0]).astype(int)
        radius_px = max(4, round(max(image.shape) * 0.009))
        if not radius_px <= u < image.shape[1] - radius_px or not radius_px <= v < image.shape[0] - radius_px:
            continue
        if mask is not None and not mask[v, u]:
            continue
        patch = image[v - radius_px : v + radius_px + 1, u - radius_px : u + radius_px + 1].astype(float)
        yy, xx = np.ogrid[-radius_px : radius_px + 1, -radius_px : radius_px + 1]
        r2 = xx * xx + yy * yy
        inner = patch[r2 <= (radius_px * 0.25) ** 2].mean()
        outer = patch[(r2 > (radius_px * 0.65) ** 2) & (r2 <= radius_px**2)].mean()
        if outer - inner < 6:
            continue
        candidates.append(
            {
                "world": world[0].tolist(),
                "pixel": [int(u), int(v)],
                "observed_depth_source_units": float(residual[i, j]),
                "photo_dark_contrast": float(outer - inner),
                "action": "preserved_from_observed_height_field",
                "is_verified_button": False,
            }
        )
    candidates = sorted(candidates, key=lambda c: c["observed_depth_source_units"], reverse=True)[:8]
    return top, {
        "rim_radius_source_units": radius,
        "rim_observation_faces": int(valid.sum()),
        "rim_method": "observed_edge_cross_section" if radius is not None else "no_reliable_rim_profile",
        "dimple_candidates": candidates,
        "unobserved_buttons_added": 0,
        "stitching": "not_recovered_without_supported_line_evidence",
        "physical_detail_verified": False,
    }
