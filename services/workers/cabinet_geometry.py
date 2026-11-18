"""Cabinet geometry from one photo, without AI sampling.

1. Perspective: line segments on the furniture vote for the front face's horizontal vanishing
   point. Product photos keep verticals parallel (two-point perspective), so the horizon passes
   through that point and the camera has no pitch about it.
2. Front face and side face: the silhouette's lower boundary splits into a front edge (a line
   through the vanishing point) and, where visible, a side edge. The fold between them is the
   front/side corner.
3. Proportions: with a pinhole camera, width and height are measured on the front plane and
   depth on the side plane. Without a visible side, the depth stays a category prior.
4. Layout: the front face is rectified and cut recursively along seams that span a whole block
   (XY-cut). Thin strips become boards (rails, stiles, shelf edges); cluttered cells are open
   compartments; plain cells are drawer fronts or doors.

Everything returned is a hypothesis with its evidence; nothing here claims verified structure.
"""

import math

import cv2
import numpy as np

DEFAULT_FOCAL = 1.4  # x max(image side): about a 50 mm lens on full frame
BOARD = 0.03  # strips thinner than 3 % of the front width are boards, not cells
OPEN_DENSITY = 0.07  # edge density above which a cell is an open compartment
GAP = 0.015  # strips thinner than this (fraction of width) are seams between fronts, not boards
SEAM_GRADIENT = 24.0  # Sobel response (0..255 image, 3x3) that counts as a seam pixel
OPEN_STD = 50.0  # luminance spread of an open, filled compartment (books, decor, shadows)
DOOR_RATIO = 1.0  # a plain front taller than wide is a door; drawers are wider than tall
MIN_REPROJECTION_IOU = 0.85  # model silhouette vs photo silhouette; below this the analysis is not used
DARK = 0.6  # strips darker than this fraction of the front's median are shadow seams


# ---------------------------------------------------------------- line evidence
def line_segments(gray, mask, min_length):
    try:
        found = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    except cv2.error:
        found = None
    if found is None:
        edges = cv2.Canny(gray, 50, 150)
        found = cv2.HoughLinesP(edges, 1, np.pi / 360, 40, minLineLength=min_length, maxLineGap=4)
    if found is None:
        return np.zeros((0, 4))
    segs = found.reshape(-1, 4).astype(float)
    length = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    inside = cv2.dilate(mask.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    mx = np.clip(((segs[:, 0] + segs[:, 2]) / 2).astype(int), 0, mask.shape[1] - 1)
    my = np.clip(((segs[:, 1] + segs[:, 3]) / 2).astype(int), 0, mask.shape[0] - 1)
    return segs[(length >= min_length) & inside[my, mx]]


def _homogeneous_lines(segs):
    ones = np.ones((len(segs), 1))
    return np.cross(np.hstack([segs[:, :2], ones]), np.hstack([segs[:, 2:], ones]))


def _consistent(segs, vp, tol_deg):
    """Segments whose direction points at the (homogeneous) vanishing point."""
    mid = (segs[:, :2] + segs[:, 2:]) / 2
    direction = segs[:, 2:] - segs[:, :2]
    if abs(vp[2]) < 1e-9 * np.linalg.norm(vp[:2]):
        towards = np.tile(vp[:2], (len(segs), 1))
    else:
        towards = vp[:2] / vp[2] - mid
    cos = np.abs(np.sum(direction * towards, 1)) / (
        np.linalg.norm(direction, axis=1) * np.linalg.norm(towards, axis=1) + 1e-9
    )
    return cos > math.cos(math.radians(tol_deg))


def vanishing_point(segs, seed=0, iterations=1500, tol_deg=1.0):
    """RANSAC over segment pairs; returns (homogeneous point, inlier mask) or (None, None)."""
    if len(segs) < 2:
        return None, None
    rng = np.random.default_rng(seed)
    lines = _homogeneous_lines(segs)
    length = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    best, best_score = None, 0.0
    for _ in range(iterations):
        i, j = rng.choice(len(segs), 2, replace=False, p=length / length.sum())
        vp = np.cross(lines[i], lines[j])
        if not np.any(vp):
            continue
        score = length[_consistent(segs, vp, tol_deg)].sum()
        if score > best_score:
            best, best_score = vp, score
    if best is None:
        return None, None
    inliers = _consistent(segs, best, tol_deg)
    # Least squares refinement: the point closest to all inlier lines (weighted by length).
    normed = lines[inliers] / np.linalg.norm(lines[inliers][:, :2], axis=1, keepdims=True)
    _, _, vt = np.linalg.svd(normed * length[inliers][:, None])
    return vt[-1], inliers


# ---------------------------------------------------------------- silhouette
def boundary_profiles(mask):
    cols = np.flatnonzero(mask.any(0))
    top = np.array([np.argmax(mask[:, x]) for x in cols], float)
    bottom = np.array([mask.shape[0] - 1 - np.argmax(mask[::-1, x]) for x in cols], float)
    return cols.astype(float), top, bottom


def _line_y(line, x):
    return -(line[0] * x + line[2]) / line[1]


def fit_through_vp(vp, xs, ys, tol):
    """Line through the vanishing point that fits the most profile points; returns (line, inliers)."""
    best, best_inliers = None, None
    for k in range(0, len(xs), max(1, len(xs) // 200)):
        line = np.cross(vp, [xs[k], ys[k], 1.0])
        if abs(line[1]) < 1e-12:
            continue
        inliers = np.abs(_line_y(line, xs) - ys) < tol
        if best is None or inliers.sum() > best_inliers.sum():
            best, best_inliers = line, inliers
    return best, best_inliers


def longest_run(flags, xs, gap):
    """Index range of the longest run of True flags allowing gaps up to `gap` pixels."""
    idx = np.flatnonzero(flags)
    if not len(idx):
        return None
    runs, start = [], idx[0]
    for a, b in zip(idx[:-1], idx[1:]):
        if xs[b] - xs[a] > gap:
            runs.append((start, a))
            start = b
    runs.append((start, idx[-1]))
    return max(runs, key=lambda r: xs[r[1]] - xs[r[0]])


# ---------------------------------------------------------------- camera
class Camera:
    """Pinhole camera, y down, z forward. Two-point perspective: no pitch, horizon at cy."""

    def __init__(self, focal, cx, cy):
        self.f, self.cx, self.cy = float(focal), float(cx), float(cy)

    def ray(self, u, v):
        r = np.array([(u - self.cx) / self.f, (v - self.cy) / self.f, 1.0])
        return r / np.linalg.norm(r)

    def project(self, points):
        p = np.asarray(points, float).reshape(-1, 3)
        return np.c_[self.f * p[:, 0] / p[:, 2] + self.cx, self.f * p[:, 1] / p[:, 2] + self.cy]

    def direction(self, vp):
        if abs(vp[2]) < 1e-9 * np.linalg.norm(vp[:2]):
            d = np.array([vp[0], vp[1], 0.0])
        else:
            d = np.array([vp[0] / vp[2] - self.cx, vp[1] / vp[2] - self.cy, self.f])
        d[1] = 0.0  # horizontal by construction of the two-point model
        d /= np.linalg.norm(d)
        return d if d[0] > 0 else -d


def on_plane(camera, u, v, normal, point):
    r = camera.ray(u, v)
    return r * (normal @ point) / (normal @ r)


# ---------------------------------------------------------------- main estimate
def estimate(image, mask, depth_prior=0.45, seed=0):
    """Front quad, side, camera and metric proportions. Raises ValueError when unsupported."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    h_img, w_img = mask.shape
    cols, top, bottom = boundary_profiles(mask)
    if len(cols) < 20:
        raise ValueError("furniture mask too small")
    span = cols[-1] - cols[0]
    # Legs and feet would bend the lower silhouette; a wide horizontal opening keeps the carcass.
    k = max(3, int(0.08 * span)) | 1
    body = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((1, k), np.uint8)) > 0
    body = cv2.morphologyEx(body.astype(np.uint8), cv2.MORPH_OPEN, np.ones((k, 1), np.uint8)) > 0
    if body.sum() > 0.5 * mask.sum():
        cols, top, bottom = boundary_profiles(body)
        span = cols[-1] - cols[0]
    segs = line_segments(gray, mask, max(12, 0.03 * span))
    angle = np.degrees(np.arctan2(segs[:, 3] - segs[:, 1], segs[:, 2] - segs[:, 0])) % 180
    horizontal = segs[(angle < 40) | (angle > 140)]
    vertical = segs[np.abs(angle - 90) < 8]
    vp, inliers = vanishing_point(horizontal, seed)
    if vp is None:
        vp = np.array([1.0, 0.0, 0.0])  # frontal: horizontal lines stay horizontal
        inliers = np.zeros(len(horizontal), bool)
    finite = abs(vp[2]) > 1e-9 * np.linalg.norm(vp[:2]) and abs(vp[0] / vp[2] - w_img / 2) < 50 * w_img
    if not finite:
        vp = np.array([vp[0], vp[1], 0.0])
    tol = max(2.0, 0.006 * h_img)
    bottom_line, bottom_in = fit_through_vp(vp, cols, bottom, tol)
    run = longest_run(bottom_in, cols, 0.03 * span)
    if bottom_line is None or run is None or cols[run[1]] - cols[run[0]] < 0.4 * span:
        raise ValueError("front bottom edge not found")
    xl, xr = cols[run[0]], cols[run[1]]
    # Refine without the vanishing-point constraint: a slightly-off point would tilt the corners.
    trim = (cols >= xl + 0.05 * (xr - xl)) & (cols <= xr - 0.05 * (xr - xl)) & bottom_in
    slope, intercept = np.polyfit(cols[trim], bottom[trim], 1)
    bottom_line = np.array([slope, -1.0, intercept])
    side, side_line = None, None
    if cols[-1] - xr > 0.02 * span:
        side = "right"
    elif xl - cols[0] > 0.02 * span:
        side = "left"
    if side:
        # The fold is where the front and side bottom edges meet. The inlier run of the front edge
        # usually spills a little into the side, so the side edge is fitted on the strip's middle.
        a, b = (xr, cols[-1]) if side == "right" else (cols[0], xl)
        pick = (cols >= a + 0.15 * (b - a)) & (cols <= b - 0.15 * (b - a))
        crease = xr if side == "right" else xl
        if pick.sum() >= 3:
            slope, intercept = np.polyfit(cols[pick], bottom[pick], 1)
            side_line = np.array([slope, -1.0, intercept])
            meet = np.cross(bottom_line, side_line)
            if abs(meet[2]) > 1e-12 and cols[0] <= meet[0] / meet[2] <= cols[-1]:
                crease = meet[0] / meet[2]
        else:  # side too thin to fit: snap to the strongest vertical segment nearby
            near = vertical[np.abs((vertical[:, 0] + vertical[:, 2]) / 2 - crease) < 0.03 * span]
            if len(near):
                longest = near[np.argmax(np.abs(near[:, 3] - near[:, 1]))]
                crease = (longest[0] + longest[2]) / 2
        xl, xr = (xl, crease) if side == "right" else (crease, xr)

    horizon = vp[1] / vp[2] if finite else h_img / 2
    focal = DEFAULT_FOCAL * max(h_img, w_img)
    if side_line is not None and finite and abs(side_line[0]) > 1e-6:
        # Orthogonal vanishing points on the horizon: (v1 - c)(v2 - c) = -f^2.
        vx2 = (horizon - side_line[2]) / side_line[0]
        product = -(vp[0] / vp[2] - w_img / 2) * (vx2 - w_img / 2)
        if (0.5 * max(h_img, w_img)) ** 2 < product < (5 * max(h_img, w_img)) ** 2:
            focal = math.sqrt(product)
    camera = Camera(focal, w_img / 2, horizon)
    across = camera.direction(vp)
    up = np.array([0.0, -1.0, 0.0])
    normal = np.cross(across, up)  # front-plane normal
    if normal[2] > 0:
        normal = -normal  # points back towards the camera

    # Front top edge: the silhouette top, unless the top surface is visible as a sliver above a
    # supported edge. Choose the candidate whose predicted top-surface back edge matches the silhouette.
    front = (cols >= xl) & (cols <= xr)
    top_line, _ = fit_through_vp(vp, cols[front], top[front], tol)
    candidates = [top_line]
    if inliers is not None and inliers.any():
        consistent = horizontal[inliers]
        mids_x = (consistent[:, 0] + consistent[:, 2]) / 2
        mids_y = (consistent[:, 1] + consistent[:, 3]) / 2
        height_guess = np.median(bottom[front] - top[front])
        band = (mids_y > _line_y(top_line, mids_x)) & (mids_y < _line_y(top_line, mids_x) + 0.12 * height_guess)
        for seg in consistent[band]:
            covered = abs(seg[2] - seg[0]) / (xr - xl)
            if covered > 0.25:
                candidates.append(np.cross(vp, [(seg[0] + seg[2]) / 2, (seg[1] + seg[3]) / 2, 1.0]))

    def corner(line, x):
        return np.array([x, _line_y(line, x)])

    def solve(top_edge):
        bl, br = corner(bottom_line, xl), corner(bottom_line, xr)
        tl, tr = corner(top_edge, xl), corner(top_edge, xr)
        anchor = camera.ray(*bl)  # put the front-bottom-left corner at distance 1 along its ray
        p_bl = anchor
        p_br = on_plane(camera, *br, normal, p_bl)
        p_tl = on_plane(camera, *tl, normal, p_bl)
        p_tr = on_plane(camera, *tr, normal, p_bl)
        width = np.linalg.norm(p_br - p_bl)
        height = (np.linalg.norm(p_tl - p_bl) + np.linalg.norm(p_tr - p_br)) / 2
        depth, measured = depth_prior * width, False
        if side and side_line is not None:
            fold = p_br if side == "right" else p_bl
            far_x = cols[-1] if side == "right" else cols[0]
            far = on_plane(camera, far_x, _line_y(side_line, far_x), across, fold)
            depth, measured = abs((far - fold) @ normal), True
        return {
            "quad_px": [tl.tolist(), tr.tolist(), br.tolist(), bl.tolist()],
            "corners_3d": [p_tl, p_tr, p_br, p_bl],
            "width": width,
            "height": height,
            "depth": depth,
            "depth_measured": measured,
        }

    def top_error(result):
        if not result["depth_measured"]:
            return 0.0
        error = 0.0
        for corner_3d in result["corners_3d"][:2]:
            back = corner_3d - normal * result["depth"]
            u, v = camera.project(back)[0]
            near = np.abs(cols - u) < 3
            if near.any():
                error += abs(np.median(top[near]) - v)
        return error

    solutions = [solve(c) for c in candidates if c is not None]
    best = min(solutions, key=top_error)
    best.update(
        {
            "camera": {"focal": focal, "cx": camera.cx, "cy": camera.cy},
            "vanishing_point": vp.tolist(),
            "vanishing_point_finite": bool(finite),
            "side": side,
            "across": across.tolist(),
            "normal": normal.tolist(),
            "evidence": {
                "horizontal_segments": int(len(horizontal)),
                "segments_on_vanishing_point": int(inliers.sum()) if inliers is not None else 0,
                "top_candidates": len(solutions),
                "focal_from_vanishing_points": focal != DEFAULT_FOCAL * max(h_img, w_img),
            },
        }
    )
    # Legs: the full silhouette hangs below the carcass' front bottom edge in a few narrow places.
    full_cols, _, full_bottom = boundary_profiles(mask)
    edge_y = _line_y(bottom_line, full_cols)
    inside = (full_cols >= xl) & (full_cols <= xr)
    hanging = inside & (full_bottom - edge_y > 0.03 * span)
    best["leg_height"] = 0.0
    if inside.any() and 0.01 < hanging.sum() / inside.sum() < 0.5:
        k = np.flatnonzero(hanging)[np.argmax((full_bottom - edge_y)[hanging])]
        x = full_cols[k]
        foot = on_plane(camera, x, full_bottom[k], normal, best["corners_3d"][3])
        top_of_leg = on_plane(camera, x, edge_y[k], normal, best["corners_3d"][3])
        best["leg_height"] = float(abs(foot[1] - top_of_leg[1]))
    best["corners_3d"] = [c.tolist() for c in best["corners_3d"]]
    return best


# ---------------------------------------------------------------- layout
def rectify(image, geometry, width_px=800):
    aspect = geometry["height"] / geometry["width"]
    size = (width_px, max(8, int(round(width_px * aspect))))
    target = np.float32([[0, 0], [size[0], 0], [size[0], size[1]], [0, size[1]]])
    matrix = cv2.getPerspectiveTransform(np.float32(geometry["quad_px"]), target)
    return cv2.warpPerspective(image, matrix, size, flags=cv2.INTER_AREA), matrix


def _cuts(profile, length, minimum_gap, threshold):
    peaks = []
    order = np.argsort(-profile)
    for i in order:
        if profile[i] < threshold:
            break
        if i < 0.012 * length or i > 0.988 * length:
            continue
        if all(abs(i - p) >= minimum_gap for p in peaks):
            peaks.append(int(i))
    return sorted(peaks)


def layout(rectified):
    """Recursive XY-cut of the rectified front. Coordinates are fractions of the front (0..1).

    Cells: drawer / door (plain fronts), open (cluttered compartment), board_h / board_v (rails,
    shelf edges, stiles, plinth). Dark thin strips are shadow seams and are dropped.
    """
    gray = cv2.GaussianBlur(cv2.cvtColor(rectified, cv2.COLOR_RGB2GRAY), (3, 3), 0)
    gx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    gy = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    # Low threshold on purpose: shelf edges in dark wood are faint but run the full width.
    h_edges = cv2.dilate(((gy > SEAM_GRADIENT) & (gy > 1.5 * gx)).astype(np.uint8), np.ones((5, 1), np.uint8)) > 0
    v_edges = cv2.dilate(((gx > SEAM_GRADIENT) & (gx > 1.5 * gy)).astype(np.uint8), np.ones((1, 5), np.uint8)) > 0
    H, W = gray.shape
    board_px = BOARD * W
    luminance = float(np.median(gray))
    # Closing removes thin dark seams and handle slots, so only real clutter keeps a high spread.
    smooth = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((int(BOARD * gray.shape[1]) | 1,) * 2, np.uint8))
    cells = []

    def clutter(x0, y0, x1, y1):
        mx, my = (x1 - x0) // 8, (y1 - y0) // 8
        inner = smooth[y0 + my : y1 - my, x0 + mx : x1 - mx]
        return float(inner.std()) if inner.size else 0.0

    def split(x0, y0, x1, y1, axis, depth, tried=False):
        w, h = x1 - x0, y1 - y0
        if min(w, h) < board_px:
            cells.append({"box": (x0, y0, x1, y1), "type": "board"})
            return
        if depth >= 1 and clutter(x0, y0, x1, y1) > OPEN_STD:
            cells.append({"box": (x0, y0, x1, y1), "type": "open"})  # do not cut along book spines
            return
        if axis == "h":
            cuts = _cuts(h_edges[y0:y1, x0:x1].mean(1), h, max(3, 0.6 * board_px), 0.8)
        else:
            cuts = _cuts(v_edges[y0:y1, x0:x1].mean(0), w, max(3, 0.6 * board_px), 0.85)
        if not cuts or depth > 6:
            if not tried and depth <= 6:
                return split(x0, y0, x1, y1, "v" if axis == "h" else "h", depth, True)
            cells.append({"box": (x0, y0, x1, y1), "type": "closed"})
            return
        bounds = [0] + cuts + [h if axis == "h" else w]
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b - a >= 2:
                box = (x0, y0 + a, x1, y0 + b) if axis == "h" else (x0 + a, y0, x0 + b, y1)
                split(*box, "v" if axis == "h" else "h", depth + 1)

    split(0, 0, W, H, "h", 0)
    kept = []
    for cell in cells:
        x0, y0, x1, y1 = cell["box"]
        long_side, short_side = max(x1 - x0, y1 - y0), min(x1 - x0, y1 - y0)
        dark = gray[y0:y1, x0:x1].mean() < DARK * luminance
        if cell["type"] == "board" and (short_side < GAP * W or dark):
            continue  # a seam or shadow between two fronts
        if cell["type"] in ("closed", "open") and long_side > 8 * short_side:
            cell["type"] = "board"  # plinth, top rail or stile, not a drawer or compartment
        kept.append(cell)
    # A short band (or thin horizontal strip) directly above a plain front of the same width is
    # that front's handle groove. Never merged into open compartments: there it is a shelf.
    merged = True
    while merged:
        merged = False
        for band in kept:
            bx0, by0, bx1, by1 = band["box"]
            if band["type"] == "board" and (bx1 - bx0) < (by1 - by0):
                continue
            for below in kept:
                x0, y0, x1, y1 = below["box"]
                if below is band or below["type"] != "closed" or abs(y0 - by1) > 2 * GAP * W:
                    continue
                same = abs(x0 - bx0) < GAP * W and abs(x1 - bx1) < GAP * W
                if same and (by1 - by0) < 0.35 * (y1 - y0):
                    below["box"] = (x0, by0, x1, y1)
                    kept.remove(band)
                    merged = True
                    break
            if merged:
                break
    out = []
    for cell in kept:
        x0, y0, x1, y1 = cell["box"]
        kind = cell["type"]
        if kind == "closed":
            kind = "door" if (y1 - y0) / (x1 - x0) >= DOOR_RATIO else "drawer"
        elif kind == "board":
            kind = "board_h" if (x1 - x0) >= (y1 - y0) else "board_v"
        out.append({"kind": kind, "box": [x0 / W, y0 / H, x1 / W, y1 / H], "clutter": clutter(x0, y0, x1, y1)})
    return out


# ---------------------------------------------------------------- 3D parts
PANEL = 0.018  # carcass board thickness in model units (furniture width = 1)
FRONT = 0.02  # door / drawer front thickness
REVEAL = 0.004  # gap around each front
NAMES = {
    "door": "柜门",
    "drawer": "抽屉",
    "shelf": "层板",
    "panel": "隔板",
    "body": "柜体",
    "leg": "柜腿",
    "frame": "底座",
}


def _merge(meshes):
    out, offset = {"vertices": [], "normals": [], "uvs": [], "faces": []}, 0
    for mesh in meshes:
        for key in ("vertices", "normals", "uvs"):
            out[key].append(mesh[key])
        out["faces"].append(mesh["faces"] + offset)
        offset += len(mesh["vertices"])
    return {key: np.concatenate(value) for key, value in out.items()}


def build(geometry, cells):
    """Parts in model units: width 1, Y up from the floor, +Z towards the camera, x centred.

    Returns (parts, assumptions); each part is {"id", "kind", "name", "mesh", "inferred"}.
    """
    from parametric_parts import box_mesh, translation

    H = geometry["height"] / geometry["width"]
    D = geometry["depth"] / geometry["width"]
    base = geometry.get("leg_height", 0.0) / geometry["width"]
    front_z = D / 2
    parts, counts = [], {}

    def add(kind, meshes, inferred, label=None):
        counts[kind] = counts.get(kind, 0) + 1
        name = label or f"{NAMES[kind]} {counts[kind]}"
        parts.append(
            {"id": f"{kind}_{counts[kind]}", "kind": kind, "name": name, "mesh": _merge(meshes), "inferred": inferred}
        )

    def box(size, x, y, z):
        return box_mesh(size, translation(x, y, z))

    def x_of(u):
        return u - 0.5

    def y_of(v):
        return base + (1 - v) * H

    t = PANEL
    add(
        "body",
        [
            box([t, H, D], -0.5 + t / 2, base + H / 2, 0),
            box([t, H, D], 0.5 - t / 2, base + H / 2, 0),
            box([1 - 2 * t, t, D], 0, base + H - t / 2, 0),
            box([1 - 2 * t, t, D], 0, base + t / 2, 0),
            box([1 - 2 * t, H - 2 * t, t], 0, base + H / 2, -D / 2 + t / 2),
        ],
        inferred=False,
        label="柜体（侧板、顶板、底板、背板）",
    )
    inner_depth = D - t
    inner_z = t / 2  # centre of the space in front of the back panel
    edge = 0.03
    for cell in cells:
        u0, v0, u1, v1 = cell["box"]
        if cell["kind"] in ("board_h", "board_v", "open"):  # interior boards stay inside the side panels
            u0, u1 = max(u0, t), min(u1, 1 - t)
        w, h = u1 - u0, (v1 - v0) * H
        cx, cy = x_of((u0 + u1) / 2), y_of((v0 + v1) / 2)
        if cell["kind"] == "board_h":
            if v1 > 1 - edge and h > 1.5 * t:  # plinth / kick board
                add("frame", [box([1 - 2 * t, h, inner_depth], 0, base + h / 2, inner_z)], inferred=False, label="底座")
            elif edge < v0 and v1 < 1 - edge:
                add("shelf", [box([w, max(t, h), inner_depth], cx, cy, inner_z)], inferred=False)
        elif cell["kind"] == "board_v" and edge < u0 and u1 < 1 - edge:
            add("panel", [box([max(t, w), h, inner_depth], cx, cy, inner_z)], inferred=False)
        elif cell["kind"] in ("door", "drawer"):
            fw, fh = w - 2 * REVEAL, h - 2 * REVEAL
            meshes = [box([fw, fh, FRONT], cx, cy, front_z - FRONT / 2)]
            if cell["kind"] == "drawer":  # hidden drawer box behind the front
                bw, bh, bd, bt = fw - 0.03, 0.75 * fh, min(0.85 * inner_depth, 0.55), 0.012
                z0 = front_z - FRONT - bd / 2
                yb = cy - fh / 2 + 0.01
                meshes += [
                    box([bw, bt, bd], cx, yb + bt / 2, z0),
                    box([bt, bh, bd], cx - bw / 2 + bt / 2, yb + bh / 2, z0),
                    box([bt, bh, bd], cx + bw / 2 - bt / 2, yb + bh / 2, z0),
                    box([bw, bh, bt], cx, yb + bh / 2, z0 - bd / 2 + bt / 2),
                ]
            add(cell["kind"], meshes, inferred=cell["kind"] == "drawer")
    # Shelves implied by two open compartments stacked without a detected board between them.
    opens = [c["box"] for c in cells if c["kind"] == "open"]
    boards = [c["box"] for c in cells if c["kind"] == "board_h"]
    for a in opens:
        for b in opens:
            if abs(a[3] - b[1]) < 0.02 and min(a[2], b[2]) - max(a[0], b[0]) > 0.5 * (a[2] - a[0]):
                y = (a[3] + b[1]) / 2
                if not any(bb[1] - 0.02 <= y <= bb[3] + 0.02 for bb in boards):
                    u0, u1 = max(a[0], b[0]), min(a[2], b[2])
                    add(
                        "shelf", [box([u1 - u0, t, inner_depth], x_of((u0 + u1) / 2), y_of(y), inner_z)], inferred=False
                    )
    if base > 0.01:
        leg = 0.04
        for sx in (-1, 1):
            for sz in (-1, 1):
                add(
                    "leg",
                    [box([leg, base, leg], sx * (0.5 - leg / 2 - 0.01), base / 2, sz * (D / 2 - leg / 2 - 0.01))],
                    inferred=sz < 0,
                )
    assumptions = [
        f"高宽比 {H:.2f}、深宽比 {D:.2f} 由透视测得"
        if geometry["depth_measured"]
        else f"高宽比 {H:.2f} 由透视测得；深度按先验取宽度的 {D:.2f} 倍（看不到侧面）",
        "板厚、抽屉箱体与背板按常见做法推断，照片中不可见",
        "尺寸为比例模型：家具宽度归一为 1，未校准实物尺寸",
    ]
    if base > 0.01:
        assumptions.append("后侧两条柜腿按对称推断")
    return parts, assumptions


def to_camera(geometry, points):
    """Model units -> the estimated camera frame (for reprojection checks)."""
    s = geometry["width"]
    D = geometry["depth"] / s
    base = geometry.get("leg_height", 0.0) / s
    bl = np.asarray(geometry["corners_3d"][3])
    across, normal = np.asarray(geometry["across"]), np.asarray(geometry["normal"])
    up = np.array([0.0, -1.0, 0.0])
    p = np.asarray(points, float)
    return bl + s * ((p[:, :1] + 0.5) * across + (p[:, 1:2] - base) * up + (p[:, 2:3] - D / 2) * normal)


def reprojection(geometry, parts, shape, colours=None):
    """Render the parts with the estimated camera: (silhouette, shaded rgb, visible part index per pixel).

    Z-buffered triangles with flat shading by face normal. Hidden structure is rendered too and
    stays behind the visible boards, as in the photo.
    """
    c = geometry["camera"]
    camera = Camera(c["focal"], c["cx"], c["cy"])
    silhouette = np.zeros(shape, np.uint8)
    shaded = np.full(shape + (3,), 255, np.uint8)
    light = np.array([0.3, -0.8, -0.5])
    light /= np.linalg.norm(light)
    triangles = []
    for index, part in enumerate(parts):
        points = to_camera(geometry, part["mesh"]["vertices"])
        pixels = camera.project(points)
        colour = np.array((colours or {}).get(part["kind"], (180, 140, 100)), float)
        for face in part["mesh"]["faces"]:
            a, b, d = points[face]
            normal = np.cross(b - a, d - a)
            normal /= np.linalg.norm(normal) + 1e-12
            if normal @ a > 0:
                continue  # back face
            shade = 0.55 + 0.45 * max(0.0, -normal @ light)
            triangles.append((index, np.int32(np.round(pixels[face])), colour * shade, points[face][:, 2]))
    zbuffer = np.full(shape, np.inf)
    owner = np.full(shape, -1, np.int32)
    for index, tri, colour, depths in triangles:  # per-pixel depth test (z-buffer)
        x0, y0 = np.maximum(tri.min(0), 0)
        x1, y1 = np.minimum(tri.max(0), [shape[1] - 1, shape[0] - 1])
        if x1 < x0 or y1 < y0:
            continue
        ys, xs = np.mgrid[y0 : y1 + 1, x0 : x1 + 1]
        (ax, ay), (bx, by), (cx_, cy_) = tri.astype(float)
        area = (bx - ax) * (cy_ - ay) - (cx_ - ax) * (by - ay)
        if abs(area) < 1e-9:
            continue
        w1 = ((xs - ax) * (cy_ - ay) - (cx_ - ax) * (ys - ay)) / area
        w2 = ((bx - ax) * (ys - ay) - (xs - ax) * (by - ay)) / area
        w0 = 1 - w1 - w2
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        z = 1.0 / (w0 / depths[0] + w1 / depths[1] + w2 / depths[2] + 1e-12)  # perspective-correct depth
        region = zbuffer[y0 : y1 + 1, x0 : x1 + 1]
        nearer = inside & (z < region)
        region[nearer] = z[nearer]
        shaded[y0 : y1 + 1, x0 : x1 + 1][nearer] = colour.astype(np.uint8)
        owner[y0 : y1 + 1, x0 : x1 + 1][nearer] = index
        silhouette[y0 : y1 + 1, x0 : x1 + 1][inside] = 1
    return silhouette > 0, shaded, owner


def filled(mask):
    """Silhouette with interior holes filled (segmenters often drop dark open compartments)."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.zeros(mask.shape, np.uint8)
    cv2.drawContours(out, contours, -1, 1, thickness=-1)
    return out > 0


def part_masks(geometry, parts, shape):
    """Image mask per part: its visible pixels, or its full projection when it is hidden."""
    _, _, owner = reprojection(geometry, parts, shape)
    masks = []
    for index, part in enumerate(parts):
        visible = owner == index
        if visible.sum() >= 20:
            masks.append((visible, "partial"))
        else:
            alone, _, _ = reprojection(geometry, [part], shape)
            masks.append((alone, "hidden_inferred"))
    return masks


def analyse(rgb, mask, depth_prior=0.45):
    """Photo + furniture mask -> (geometry, cells, parts, assumptions, reprojection IoU)."""
    silhouette = filled(mask)
    geometry = estimate(rgb, silhouette, depth_prior)
    rectified, _ = rectify(rgb, geometry)
    cells = layout(rectified)
    parts, assumptions = build(geometry, cells)
    rendered, _, _ = reprojection(geometry, parts, mask.shape)
    iou = float((rendered & silhouette).sum() / max((rendered | silhouette).sum(), 1))
    return geometry, cells, parts, assumptions, iou
