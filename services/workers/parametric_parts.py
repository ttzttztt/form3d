"""Parametric hard parts: clean boxes and cylinders instead of AI-sampled meshes.

Two ways to get the parameters:

* fit_primitive(vertices, faces): fit an oriented box or (elliptic) cylinder to an AI-generated
  part mesh, in that mesh's own frame, and report how far the fit deviates. The caller only
  replaces the AI part when the deviation is small.
* layout_from_masks(...): estimate proportional boxes/cylinders directly from 2D part masks and
  category depth priors, for furniture whose planned parts are all hard parts. Depth and hidden
  extents are assumptions and are reported as such.

Meshes are closed, consistently wound and carry per-face normals and UVs measured in model
units (so a texture has the same density on every part).
"""

import numpy as np

# Kinds that are replaced by / built as parametric primitives, per furniture category.
HARD_KINDS = {
    "table": {"tabletop", "leg", "frame", "panel", "shelf", "drawer"},
    "cabinet": {"door", "drawer", "shelf", "panel", "frame", "body", "leg"},
    "chair": {"leg"},
    "sofa": {"leg"},
}

# Furniture depth as a fraction of its width when only a front/3-quarter photo is available.
DEPTH_PRIOR = {"table": 0.6, "cabinet": 0.45, "chair": 0.9, "sofa": 0.45}
PANEL_THICKNESS = 0.02  # model units (the furniture width is 1)
TOP_THICKNESS = 0.035
ROUND_FILL = 0.86  # area(hull) / area(bounding rectangle): pi/4 ~ 0.785 for an ellipse, 1 for a rectangle

# Deviation gate for replacing an AI part with a fitted primitive.
MAX_MEAN_DEVIATION = 0.02  # fraction of the part's diagonal
MAX_P95_DEVIATION = 0.05
VOLUME_RATIO = (0.7, 1.45)


def is_hard(category, kind):
    return kind in HARD_KINDS.get(category, set())


# --------------------------------------------------------------------------- mesh builders


def box_mesh(extents, transform=None):
    """Closed box centred at the origin; 24 vertices so every face has its own normal and UV chart."""
    ex = np.asarray(extents, float) / 2
    # (normal axis, sign, u axis, v axis)
    faces_spec = [(0, 1, 2, 1), (0, -1, 2, 1), (1, 1, 0, 2), (1, -1, 0, 2), (2, 1, 0, 1), (2, -1, 0, 1)]
    vertices, normals, uvs, faces = [], [], [], []
    for axis, sign, u, v in faces_spec:
        corners = []
        for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            point = np.zeros(3)
            point[axis] = sign * ex[axis]
            point[u] = du * ex[u]
            point[v] = dv * ex[v]
            corners.append(point)
        normal = np.zeros(3)
        normal[axis] = sign
        start = len(vertices)
        for point in corners:
            vertices.append(point)
            normals.append(normal)
            uvs.append([point[u] + ex[u], point[v] + ex[v]])
        quad = [start, start + 1, start + 2, start + 3]
        tri = [[quad[0], quad[1], quad[2]], [quad[0], quad[2], quad[3]]]
        # Wind counter-clockwise when seen from outside.
        test = np.cross(corners[1] - corners[0], corners[2] - corners[0])
        if np.dot(test, normal) < 0:
            tri = [[a, c, b] for a, b, c in tri]
        faces.extend(tri)
    return _transformed(np.array(vertices), np.array(normals), np.array(uvs), np.array(faces), transform)


def cylinder_mesh(radius_x, radius_z, height, transform=None, segments=48):
    """Closed (elliptic) cylinder along +Y, centred at the origin."""
    angles = np.linspace(0, 2 * np.pi, segments + 1)
    half = height / 2
    vertices, normals, uvs, faces = [], [], [], []
    perimeter = np.pi * (3 * (radius_x + radius_z) - np.sqrt((3 * radius_x + radius_z) * (radius_x + 3 * radius_z)))
    for index, angle in enumerate(angles):  # side, with a duplicated seam column
        c, s = np.cos(angle), np.sin(angle)
        normal = np.array([c / max(radius_x, 1e-12), 0, s / max(radius_z, 1e-12)])
        normal /= np.linalg.norm(normal)
        u = perimeter * index / segments
        for y in (-half, half):
            vertices.append([radius_x * c, y, radius_z * s])
            normals.append(normal)
            uvs.append([u, y + half])
    for index in range(segments):
        a, b, c2, d = 2 * index, 2 * index + 1, 2 * index + 2, 2 * index + 3
        faces.extend([[a, b, d], [a, d, c2]])
    for y, sign in ((half, 1), (-half, -1)):  # caps
        centre = len(vertices)
        vertices.append([0, y, 0])
        normals.append([0, sign, 0])
        uvs.append([radius_x, radius_z])
        ring = []
        for angle in angles[:-1]:
            ring.append(len(vertices))
            point = [radius_x * np.cos(angle), y, radius_z * np.sin(angle)]
            vertices.append(point)
            normals.append([0, sign, 0])
            uvs.append([point[0] + radius_x, point[2] + radius_z])
        for index in range(segments):
            a, b = ring[index], ring[(index + 1) % segments]
            faces.append([centre, b, a] if sign > 0 else [centre, a, b])
    return _transformed(np.array(vertices), np.array(normals), np.array(uvs), np.array(faces), transform)


def _transformed(vertices, normals, uvs, faces, transform):
    if transform is not None:
        transform = np.asarray(transform, float)
        vertices = vertices @ transform[:3, :3].T + transform[:3, 3]
        normals = normals @ np.linalg.inv(transform[:3, :3])
        normals /= np.linalg.norm(normals, axis=1, keepdims=True)
        if np.linalg.det(transform[:3, :3]) < 0:
            faces = faces[:, ::-1]
    return {
        "vertices": vertices.astype(np.float32),
        "normals": normals.astype(np.float32),
        "uvs": uvs.astype(np.float32),
        "faces": faces.astype(np.uint32),
    }


def translation(x, y, z):
    matrix = np.eye(4)
    matrix[:3, 3] = [x, y, z]
    return matrix


# --------------------------------------------------------------------------- fitting to AI parts


def _fill_ratio(points_2d):
    """Convex hull area over bounding rectangle area of 2D points."""
    from scipy.spatial import ConvexHull

    span = points_2d.max(0) - points_2d.min(0)
    if span.min() <= 1e-12:
        return 1.0
    try:
        return float(ConvexHull(points_2d).volume / (span[0] * span[1]))
    except Exception:  # degenerate hull: treat as rectangular
        return 1.0


def fit_primitive(vertices, faces, kind):
    """Fit a box or cylinder to a part mesh. Returns (mesh_dict, report)."""
    import trimesh

    mesh = trimesh.Trimesh(np.asarray(vertices, float), np.asarray(faces), process=False)
    to_origin, extents = trimesh.bounds.oriented_bounds(mesh)
    to_world = np.linalg.inv(to_origin)
    local = trimesh.transform_points(mesh.vertices, to_origin)
    order = np.argsort(extents)
    # A leg is round across its two short axes; a slab (top/shelf/door) across its two long axes.
    axis = order[-1] if kind == "leg" else order[0]
    across = [i for i in range(3) if i != axis]
    fill = _fill_ratio(local[:, across])
    shape = "cylinder" if fill < ROUND_FILL else "box"
    if shape == "box":
        built = box_mesh(extents, to_world)
    else:
        # Rotate so the cylinder's +Y axis lies on `axis`, its X/Z radii on the other two.
        basis = np.zeros((4, 4))
        basis[3, 3] = 1
        basis[across[0], 0] = 1
        basis[axis, 1] = 1
        basis[across[1], 2] = 1
        if np.linalg.det(basis[:3, :3]) < 0:
            basis[across[1], 2] = -1
        built = cylinder_mesh(extents[across[0]] / 2, extents[across[1]] / 2, extents[axis], to_world @ basis)
    report = {"shape": shape, "extents": [float(v) for v in extents], "cross_section_fill": fill}
    report.update(deviation(mesh, built))
    report["accepted"] = bool(
        report["mean_deviation"] <= MAX_MEAN_DEVIATION
        and report["p95_deviation"] <= MAX_P95_DEVIATION
        and (report["volume_ratio"] is None or VOLUME_RATIO[0] <= report["volume_ratio"] <= VOLUME_RATIO[1])
    )
    return built, report


def deviation(original, built, samples=3000):
    """Distances from the original surface to the fitted surface, relative to the part diagonal."""
    import trimesh

    fitted = trimesh.Trimesh(built["vertices"], built["faces"], process=False)
    diagonal = float(np.linalg.norm(original.extents)) or 1.0
    points, _ = trimesh.sample.sample_surface(original, samples, seed=0)
    _, distance, _ = trimesh.proximity.closest_point(fitted, points)
    volume_ratio = float(fitted.volume / original.volume) if original.is_volume and original.volume > 0 else None
    return {
        "mean_deviation": float(distance.mean() / diagonal),
        "p95_deviation": float(np.percentile(distance, 95) / diagonal),
        "volume_ratio": volume_ratio,
    }


# --------------------------------------------------------------------------- layout from masks


def mask_box(mask):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("empty part mask")
    return {
        "u0": float(xs.min()),
        "u1": float(xs.max() + 1),
        "v0": float(ys.min()),
        "v1": float(ys.max() + 1),
        "fill": float(len(xs) / ((xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1))),
    }


def layout_from_masks(category, parts, whole):
    """Proportional primitives from 2D masks.

    parts: [{"id", "kind", "mask": bool array}] in one image frame; whole: whole-furniture mask.
    Returns ({part_id: mesh_dict}, [assumption strings], {part_id: params}).
    The model is scaled so the furniture width is 1; Y is up, +Z faces the camera.
    """
    frame = mask_box(whole)
    width_px = frame["u1"] - frame["u0"]
    scale = 1.0 / width_px
    centre_u = (frame["u0"] + frame["u1"]) / 2
    boxes = {p["id"]: mask_box(p["mask"]) for p in parts}
    legs = [p for p in parts if p["kind"] == "leg"]
    ground = max((boxes[p["id"]]["v1"] for p in legs), default=frame["v1"])
    tops = [p for p in parts if p["kind"] == "tabletop"]
    round_top = bool(tops) and boxes[tops[0]["id"]]["fill"] < ROUND_FILL
    depth = 1.0 if (category == "table" and round_top) else DEPTH_PRIOR.get(category, 0.6)
    assumptions = [
        f"深度按品类先验取宽度的 {depth:.2f} 倍（单张照片无法测量）",
        "尺寸为比例模型：家具宽度归一为 1，未校准实物尺寸",
    ]

    def x(u):
        return (u - centre_u) * scale

    def y(v):
        return (ground - v) * scale

    meshes, params = {}, {}
    under_top = None
    for part in tops:
        b = boxes[part["id"]]
        thickness = min(TOP_THICKNESS, max(PANEL_THICKNESS, 0.5 * (b["v1"] - b["v0"]) * scale))
        under_top = y(b["v1"])
        cx, w = (x(b["u0"]) + x(b["u1"])) / 2, (b["u1"] - b["u0"]) * scale
        centre = translation(cx, under_top + thickness / 2, 0)
        if b["fill"] < ROUND_FILL:
            meshes[part["id"]] = cylinder_mesh(w / 2, depth / 2, thickness, centre)
            params[part["id"]] = {"shape": "cylinder", "diameter": w, "thickness": thickness}
        else:
            meshes[part["id"]] = box_mesh([w, thickness, depth], centre)
            params[part["id"]] = {"shape": "box", "size": [w, thickness, depth]}
    if tops:
        assumptions.append("桌面厚度按先验估计；桌面下沿取原图中桌面前缘")

    front_feet = [boxes[p["id"]]["v1"] for p in legs]
    spread = (max(front_feet) - min(front_feet)) if front_feet else 0
    for part in legs:
        b = boxes[part["id"]]
        w = max((b["u1"] - b["u0"]) * scale, 0.01)
        top = under_top if under_top is not None else y(b["v0"])
        # Ground-plane cue: a foot higher in the image stands further back.
        back = 0.0 if spread < 0.03 * (frame["v1"] - frame["v0"]) else (ground - b["v1"]) / spread
        z = (depth / 2 - w / 2) * (1 - 2 * back)
        meshes[part["id"]] = box_mesh([w, top, w], translation((x(b["u0"]) + x(b["u1"])) / 2, top / 2, z))
        params[part["id"]] = {"shape": "box", "size": [w, top, w], "depth_position": z}
    if legs:
        assumptions.append("支腿前后位置按脚底在图中的高低推断；照片中看不到的支腿不会生成")

    for part in parts:
        if part["id"] in meshes:
            continue
        b = boxes[part["id"]]
        w, h = (b["u1"] - b["u0"]) * scale, (b["v1"] - b["v0"]) * scale
        cx, cy = (x(b["u0"]) + x(b["u1"])) / 2, (y(b["v0"]) + y(b["v1"])) / 2
        if part["kind"] == "shelf":
            size, z = [w, PANEL_THICKNESS, depth * 0.95], 0.0
        elif part["kind"] in ("body", "frame") and category == "cabinet":
            size, z = [w, h, depth], 0.0
        else:  # door / drawer front / panel / table apron: a thin board on the front face
            size, z = [w, h, PANEL_THICKNESS], depth / 2 - PANEL_THICKNESS / 2
        meshes[part["id"]] = box_mesh(size, translation(cx, cy, z))
        params[part["id"]] = {"shape": "box", "size": size}
    if any(p["kind"] in ("door", "drawer", "panel") for p in parts):
        assumptions.append("柜门、抽屉面板按原图矩形放在正面，厚度按先验")
    return meshes, assumptions, params
