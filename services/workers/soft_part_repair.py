"""Source-guided soft volumes. Reconstructed surfaces remain review candidates."""

import numpy as np
import trimesh
from scipy.spatial import ConvexHull, cKDTree
from shapely.geometry import MultiPoint, Point, Polygon
from shapely.ops import unary_union


def grid_in_hull(points, resolution=96, polygon=None):
    # Tiny marching-cubes contour edges can collapse in glTF float32. Simplify
    # only this estimated contour before inserting uniformly spaced samples.
    polygon = MultiPoint(points).convex_hull if polygon is None else polygon
    if not polygon.is_valid or polygon.geom_type != "Polygon" or polygon.area <= 0 or len(polygon.interiors):
        raise ValueError("部件轮廓不完整或包含孔洞，未自动补成实体")
    polygon = polygon.simplify(np.linalg.norm(np.ptp(points, axis=0)) * 0.001, preserve_topology=True)
    boundary = np.asarray(polygon.exterior.coords)[:-1]
    # Subdivide a conforming polygon triangulation. Dense collinear Delaunay
    # boundary samples can form zero-area faces and corrupt the closed rim.
    xy, faces = trimesh.creation.triangulate_polygon(Polygon(boundary), engine="earcut")
    vertices = np.c_[xy, np.zeros(len(xy))]
    for _ in range(max(1, int(round(np.log2(resolution / 3))))):
        vertices, faces = trimesh.remesh.subdivide(vertices, faces)
    xy = vertices[:, :2]
    delta1 = xy[faces[:, 1]] - xy[faces[:, 0]]
    delta2 = xy[faces[:, 2]] - xy[faces[:, 0]]
    positive = delta1[:, 0] * delta2[:, 1] - delta1[:, 1] * delta2[:, 0] > 0
    faces[~positive] = faces[~positive, ::-1]
    from shapely import points as shape_points, distance as shape_distance

    distance = shape_distance(shape_points(xy), polygon.boundary)
    return xy, faces, distance, polygon


def interpolate(xy, values, query, k=10):
    distance, indices = cKDTree(xy).query(query, k=min(k, len(values)))
    if distance.ndim == 1:
        return values[indices]
    weights = 1 / np.maximum(distance, 1e-7) ** 2
    return (values[indices] * weights).sum(1) / weights.sum(1)


def sheets(xy, faces, top, bottom, axes, center):
    count = len(xy)
    vertices = np.vstack([np.c_[xy, top], np.c_[xy, bottom]]) @ axes.T + center
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    _, index, counts = np.unique(np.sort(edges, axis=1), axis=0, return_index=True, return_counts=True)
    walls = []
    for a, b in edges[index[counts == 1]]:
        walls.extend([[b, a, a + count], [a + count, b + count, b]])
    all_faces = np.vstack([faces, faces[:, ::-1] + count, walls])
    mesh = trimesh.Trimesh(vertices, all_faces, process=False)
    if mesh.volume < 0:
        mesh.faces = mesh.faces[:, ::-1]
    return mesh


def fill_paper_pillow(aligned, target, placement, contour_polygon=None, force=False, pose_surface=None):
    measurement = placement.get("thickness_constraint") or {}
    if measurement.get("method") != "paired_opposing_source_surfaces":
        return aligned, None
    from part_registration import observed_pose_surface, surface_samples, basis

    visible = pose_surface if pose_surface is not None else observed_pose_surface(target, "pillow")[0]
    front, fn = surface_samples(visible, 8000)
    center, axes, spans = basis(front)
    normal = fn.mean(0)
    if axes[:, 2] @ normal < 0:
        axes[:, 2] *= -1
    contour = (aligned.vertices - center) @ axes[:, :2]
    area = (MultiPoint(contour).convex_hull if contour_polygon is None else contour_polygon).area
    gap = measurement["core_thickness_source_units"]
    mass_ratio = float(aligned.volume / max(area * gap, 1e-12))
    if mass_ratio >= 0.25 and not force:
        return aligned, None
    points, normals = surface_samples(target, 24000)
    points = (points - center) @ axes
    front = (front - center) @ axes
    front_median = np.median(front[:, 2])
    front = front[abs(front[:, 2] - front_median) < gap * 0.4]
    back = points[
        (normals @ (normal / np.linalg.norm(normal)) < -0.72) & (abs(points[:, 2] - (front_median - gap)) < gap * 0.4)
    ]
    if len(front) < 300 or len(back) < 100:
        raise ValueError("生成靠枕是薄壳，但旧模型缺少可靠的成对表面，未强行补厚")
    xy, faces, distance, polygon = grid_in_hull(
        contour, resolution=48 if contour_polygon is not None else 96, polygon=contour_polygon
    )
    top = interpolate(front[:, :2], front[:, 2], xy)
    bottom = interpolate(back[:, :2], back[:, 2], xy)
    smoothing = None
    if contour_polygon is not None:
        from scipy.ndimage import gaussian_filter

        low, high = xy.min(0), xy.max(0)
        axes_grid = [np.linspace(low[i], high[i], 96) for i in range(2)]
        grid = np.stack(np.meshgrid(*axes_grid, indexing="ij"), axis=-1).reshape(-1, 2)
        smooth = []
        for points in (front, back):
            field = interpolate(points[:, :2], points[:, 2], grid).reshape(96, 96)
            field = gaussian_filter(field, 1.5)
            smooth.append(interpolate(grid, field.ravel(), xy, k=4))
        smoothing = float(max(np.max(abs(top - smooth[0])), np.max(abs(bottom - smooth[1]))))
        top, bottom = smooth
    middle = (top + bottom) / 2
    thickness = np.clip(top - bottom, gap * 0.5, gap * 1.5)
    taper = np.sin(np.clip(distance / (min(spans[:2]) * 0.10), 0, 1) * np.pi / 2)
    thickness *= 0.015 + 0.985 * taper
    mesh = sheets(xy, faces, middle + thickness / 2, middle - thickness / 2, axes, center)
    return mesh, {
        "method": "paired_observed_height_fields_inside_ai_contour"
        if contour_polygon is None
        else "photo_contour_observed_height_fields",
        "paper_shell_volume_ratio_before": mass_ratio,
        "volume_ratio_after": float(mesh.volume / (area * gap)),
        "front_observation_samples": len(front),
        "back_observation_samples": len(back),
        "all_output_surfaces_reconstructed": True,
        "contour_is_convex_estimate": contour_polygon is None,
        "soft_rim_from_observed_thickness": True,
        "heightfield_smoothing_maximum_change_source_units": smoothing,
        "real_hidden_geometry_recovered": False,
        "not_new_ai_inference": True,
    }


def shell_volume_ratio(mesh):
    from part_registration import basis, surface_samples

    points = surface_samples(mesh, 5000)[0]
    center, axes, spans = basis(points)
    area = MultiPoint((points - center) @ axes[:, :2]).convex_hull.area
    return float(mesh.volume / max(area * spans[2], 1e-12))


def rebuild_occluded_seat(upper, top_height, bottom, occluders, photo_context=None):
    if not occluders:
        return upper, None, None
    polygon = MultiPoint(upper.vertices[:, [0, 2]]).convex_hull
    region = unary_union(occluders).intersection(polygon)
    fraction = float(region.area / polygon.area)
    if fraction < 0.01:
        return upper, None, None
    if fraction > 0.65:
        raise ValueError("相邻靠枕遮挡了大部分坐垫，源表面不足，未自动补出整块坐垫")
    centers, normals, areas = upper.triangles_center, upper.face_normals, upper.area_faces
    blocked = np.array([region.covers(Point(point)) for point in centers[:, [0, 2]]])
    up = normals[:, 1] > 0.65
    height = top_height - bottom
    deep = blocked & (centers[:, 1] < top_height - height * 0.20) & (normals[:, 1] > -0.3)
    if areas[deep].sum() < polygon.area * 0.003:
        return upper, None, None
    known = up & ~blocked & (centers[:, 1] > top_height - height * 0.25)
    if known.sum() < 200 or areas[known].sum() < polygon.area * 0.25:
        raise ValueError("坐垫可用顶面不足，未将残缺区域补成猜测的大平面")
    xy, faces, _, _ = grid_in_hull(upper.vertices[:, [0, 2]])
    top = interpolate(centers[known][:, [0, 2]], centers[known, 1], xy, k=6)
    details = None
    if photo_context is not None:
        from soft_surface_details import refine_seat_details

        top, details = refine_seat_details(xy, top, bottom, polygon, upper, known, region, photo_context)
    if np.any(top <= bottom):
        raise ValueError("坐垫顶底范围冲突，保留原模型")
    # Coordinates of the common sheet builder are (X,Z,Y).
    axes = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])
    mesh = sheets(xy, faces, top, np.full(len(xy), bottom), axes, np.zeros(3))
    # Quantify interpolation on known source points; this is not product accuracy.
    predicted = interpolate(xy, top, centers[known][:, [0, 2]], k=4)
    error = float(np.quantile(abs(predicted - centers[known, 1]), 0.95))
    if error > np.linalg.norm(upper.extents) * 0.01:
        raise ValueError("修复改变了过多未遮挡顶面，未采用")
    return (
        mesh,
        region,
        {
            "method": "source_height_field_with_semantic_neighbour_exclusions",
            "occluded_roof_area_fraction": fraction,
            "known_roof_observation_faces": int(known.sum()),
            "known_roof_height_error_p95_source_units": error,
            "all_seat_surfaces_reconstructed": True,
            "detail_evidence": details,
            "real_hidden_geometry_recovered": False,
        },
    )
