"""Shape-constrained closed soft parts fitted to observed surfaces, never true hidden geometry."""

import numpy as np
import trimesh
from scipy.spatial import cKDTree, ConvexHull, Delaunay


def interpolate(tree, values, queries, k=10):
    d, ids = tree.query(queries, k=min(k, len(values)), workers=6)
    if d.ndim == 1:
        return values[ids]
    weights = 1 / np.maximum(d, 1e-6) ** 2
    return (values[ids] * weights).sum(1) / weights.sum(1)


def weighted_median(values, weights):
    order = np.argsort(values)
    return float(values[order[np.searchsorted(np.cumsum(weights[order]), weights.sum() / 2)]])


def pillow_sheets(source, resolution=128):
    points = source.triangles_center
    normals = source.face_normals
    weights = source.area_faces
    center = np.average(points, axis=0, weights=weights)
    cov = ((points - center) * weights[:, None]).T @ (points - center) / weights.sum()
    eigen, basis = np.linalg.eigh(cov)
    basis = basis[:, ::-1]
    if np.linalg.det(basis) < 0:
        basis[:, -1] *= -1
    cloud = (points - center) @ basis
    n = normals @ basis
    front = n[:, 2] > 0.35
    back = n[:, 2] < -0.35
    if min(weights[front].sum(), weights[back].sum()) < source.area * 0.06:
        raise ValueError("缺少前后两侧的可靠表面，不能自动确定软包厚度")
    diag = float(np.linalg.norm(source.extents))
    uv = (source.vertices - center) @ basis[:, :2]
    hull = ConvexHull(uv)
    boundary = uv[hull.vertices]
    low = uv.min(0)
    high = uv.max(0)
    step = float((high - low).max() / resolution)
    interior = np.stack(
        np.meshgrid(
            np.arange(low[0], high[0] + step / 2, step), np.arange(low[1], high[1] + step / 2, step), indexing="ij"
        ),
        axis=-1,
    ).reshape(-1, 2)
    interior = interior[np.all(interior @ hull.equations[:, :2].T + hull.equations[:, 2] < -step * 0.15, axis=1)]
    ring = []
    for a, b in zip(boundary, np.roll(boundary, -1, axis=0)):
        count = max(1, int(np.ceil(np.linalg.norm(b - a) / step)))
        ring.extend(a + (b - a) * t for t in np.arange(count) / count)
    xy = np.vstack([np.asarray(ring), interior])
    tri = Delaunay(xy)
    faces = tri.simplices.copy()
    positive = np.cross(xy[faces[:, 1]] - xy[faces[:, 0]], xy[faces[:, 2]] - xy[faces[:, 0]]) > 0
    faces[~positive] = faces[~positive][:, ::-1]
    top = interpolate(cKDTree(cloud[front, :2]), cloud[front, 2], xy)
    bottom = interpolate(cKDTree(cloud[back, :2]), cloud[back, 2], xy)
    middle = (top + bottom) / 2
    thickness = np.maximum(top - bottom, diag * 0.002)
    # Taper a soft rim to the actually observed side, keeping a positive thickness.
    distances = -(xy @ hull.equations[:, :2].T + hull.equations[:, 2]).max(1)
    blend = np.clip(distances / max(diag * 0.018, 1e-9), 0, 1)
    nearest = cKDTree(cloud[:, :2]).query(xy, k=min(8, len(cloud)))[1]
    rim = np.median(cloud[nearest, 2], axis=1)
    middle = blend * middle + (1 - blend) * rim
    thickness = blend * thickness + (1 - blend) * diag * 0.002
    top = middle + thickness / 2
    bottom = middle - thickness / 2
    verts = np.vstack([np.c_[xy, top], np.c_[xy, bottom]]) @ basis.T + center
    count = len(xy)
    all_faces = [faces, faces[:, ::-1] + count]
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    keys = np.sort(edges, axis=1)
    _, indices, counts = np.unique(keys, axis=0, return_index=True, return_counts=True)
    boundary_edges = edges[indices[counts == 1]]
    walls = []
    for a, b in boundary_edges:
        walls.extend([[b, a, a + count], [a + count, b + count, b]])
    all_faces.append(np.asarray(walls))
    mesh = trimesh.Trimesh(verts, np.vstack(all_faces), process=False)
    if mesh.volume < 0:
        mesh.faces = mesh.faces[:, ::-1]
    return mesh, {
        "method": "paired_observed_surface_height_fields_with_soft_rim",
        "resolution": resolution,
        "minimum_inferred_rim_thickness_source_units": diag * 0.002,
        "front_observation_area_fraction": float(weights[front].sum() / source.area),
        "back_observation_area_fraction": float(weights[back].sum() / source.area),
        "all_output_surfaces_reconstructed": True,
        "real_hidden_geometry_recovered": False,
    }


def bolster_profile(source, rings=80, sections=80):
    from cylinder_evidence import fit_cylinder
    from scipy.ndimage import gaussian_filter

    diag = float(np.linalg.norm(source.extents))
    points = source.triangles_center
    normals = source.face_normals
    weights = source.area_faces
    fit = fit_cylinder(points, normals, weights, diag)
    if fit is None:
        raise ValueError("没有足够的圆柱曲面证据，未强制套用圆柱形状")
    chosen, evidence = fit
    axis = np.asarray(evidence["axis"])
    center = np.asarray(evidence["axis_point_source_units"])
    radius = evidence["radius_source_units"]
    u = np.cross(axis, np.eye(3)[np.argmin(abs(axis))])
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    relative = points - center
    t = relative @ axis
    xy = relative @ np.c_[u, v]
    r = np.linalg.norm(xy, axis=1)
    angle = np.arctan2(xy[:, 1], xy[:, 0])
    side = chosen & (abs(normals @ axis) < 0.45)
    end = chosen & (abs(normals @ axis) > 0.75)
    lo = (
        weighted_median(t[end & (t < np.median(t[side]))], weights[end & (t < np.median(t[side]))])
        if (end & (t < np.median(t[side]))).sum() > 8
        else float(np.min((source.vertices - center) @ axis))
    )
    hi = (
        weighted_median(t[end & (t > np.median(t[side]))], weights[end & (t > np.median(t[side]))])
        if (end & (t > np.median(t[side]))).sum() > 8
        else float(np.max((source.vertices - center) @ axis))
    )
    if hi - lo < radius * 2.5:
        raise ValueError("抱枕轴向范围不足，未生成圆柱候选")
    tree_points = np.vstack([np.c_[t[side], radius * (angle[side] + offset)] for offset in (-2 * np.pi, 0, 2 * np.pi)])
    values = np.tile(r[side], 3)
    ts = np.linspace(lo, hi, rings)
    angles = np.arange(sections) * 2 * np.pi / sections
    tt, aa = np.meshgrid(ts, angles, indexing="ij")
    rr = interpolate(cKDTree(tree_points), values, np.c_[tt.ravel(), radius * aa.ravel()]).reshape(tt.shape)
    rr = gaussian_filter(rr, sigma=(0.5, 0.5), mode=("nearest", "wrap"))
    rr = np.clip(rr, radius * 0.55, radius * 1.45)
    verts = (
        center + tt[:, :, None] * axis + rr[:, :, None] * (np.cos(aa)[:, :, None] * u + np.sin(aa)[:, :, None] * v)
    ).reshape(-1, 3)
    faces = []
    for i in range(rings - 1):
        for j in range(sections):
            a = i * sections + j
            b = i * sections + (j + 1) % sections
            c = (i + 1) * sections + j
            d = (i + 1) * sections + (j + 1) % sections
            faces.extend([[a, b, c], [b, d, c]])
    verts = np.vstack([verts, center + lo * axis, center + hi * axis])
    a = len(verts) - 2
    b = len(verts) - 1
    for j in range(sections):
        faces.extend(
            [[a, (j + 1) % sections, j], [b, (rings - 1) * sections + j, (rings - 1) * sections + (j + 1) % sections]]
        )
    mesh = trimesh.Trimesh(verts, np.asarray(faces), process=False)
    if mesh.volume < 0:
        mesh.faces = mesh.faces[:, ::-1]
    return mesh, {
        "method": "observed_cylinder_axis_and_angular_radius_profile_with_end_caps",
        "rings": rings,
        "sections": sections,
        "cylinder_fit": evidence,
        "all_output_surfaces_reconstructed": True,
        "real_hidden_geometry_recovered": False,
    }
