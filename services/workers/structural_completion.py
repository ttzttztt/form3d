"""Height-based structural proposals, with no claim of semantic recognition."""

import numpy as np
from furniture_parts import table_cut


def structural_bounds(source, profile, detail="coarse"):
    low, high = source.bounds
    extent = high - low
    c = source.triangles_center
    n = source.face_normals
    area = source.area_faces
    top = (c[:, 1] > low[1] + extent[1] * 0.8) & (n[:, 1] > 0.9)
    table_like = float(area[top].sum() / max(source.area, 1e-15)) > 0.08
    if profile == "support" and detail == "fine":
        from furniture_parts import face_graph
        from scipy.sparse.csgraph import connected_components

        graph = face_graph(source.vertices, source.faces, c)
        candidates = []
        for level in np.linspace(0.08, 0.95, 30):
            cut = low[1] + extent[1] * level
            ids = np.flatnonzero(c[:, 1] < cut)
            if len(ids) < 32:
                continue
            _, labels = connected_components(graph[ids][:, ids], directed=False)
            weights = np.bincount(labels, weights=area[ids])
            count = int((weights > source.area * 0.003).sum())
            if 2 <= count <= 8:
                candidates.append((cut, count))
        if len(candidates) < 2:
            raise ValueError("未找到稳定分开的支脚，连接架保持整体")
        distribution = np.bincount([number for _, number in candidates])
        dominant = int(np.argmax(distribution))
        cut, count = next((height, number) for height, number in reversed(candidates) if number == dominant)
        method = "separated_lower_branches_before_junction"
    elif profile == "slab" or table_like:
        labels, names, evidence = table_cut(c, n, area)
        if abs(np.asarray(evidence["classification_up_axis"])[1]) < 0.999:
            raise ValueError("桌面明显倾斜，当前高度分界不可靠，请改用手动范围")
        cut = float(evidence["cut_y"])
        method = "observed_tabletop_neck"
    else:
        down = (n[:, 1] < -0.7) & (c[:, 1] > low[1] + extent[1] * 0.08) & (c[:, 1] < low[1] + extent[1] * 0.45)
        if down.sum() < 20:
            raise ValueError("未找到稳定的底架连接高度，请手动调整范围")
        values = c[down, 1]
        weights = area[down]
        hist, edges = np.histogram(values, bins=64, weights=weights)
        peak = (edges[np.argmax(hist)] + edges[np.argmax(hist) + 1]) / 2
        near = abs(values - peak) < extent[1] * 0.06
        v = values[near]
        w = weights[near]
        order = np.argsort(v)
        q = np.searchsorted(np.cumsum(w[order]), w.sum() * 0.08)
        cut = float(v[order[min(q, len(v) - 1)]] - extent[1] * 0.012)
        method = "lower_shell_underside_band"
    normalized = (cut - low[1]) / max(extent[1], 1e-12)
    if not 0.02 < normalized < 0.98:
        raise ValueError("连接高度接近边界，未提出自动拆分")
    bounds = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    bounds[1 if profile == "support" else 0, 1] = normalized
    return bounds, {
        "method": method,
        "cut_height_world": cut,
        "automatic_region": True,
        "semantic_recognition": False,
        **(
            {
                "seed_component_count": count,
                "height_candidates": [{"height_world": h, "seed_components": n} for h, n in candidates],
            }
            if profile == "support" and detail == "fine"
            else {}
        ),
    }


def inherited_interface_mask(mesh, interfaces, scale):
    """Match unchanged source triangles; reject rather than guess provenance."""
    if not len(interfaces.faces):
        return np.zeros(len(mesh.faces), bool)
    both = np.concatenate((mesh.vertices, interfaces.vertices))
    _, inverse = np.unique(np.round(both / max(scale, 1e-12), 8), axis=0, return_inverse=True)
    a = np.sort(inverse[: len(mesh.vertices)][mesh.faces], axis=1).astype("<i8")
    b = np.sort(inverse[len(mesh.vertices) :][interfaces.faces], axis=1).astype("<i8")
    kind = np.dtype((np.void, 24))
    aa = np.ascontiguousarray(a).view(kind).ravel()
    bb = np.ascontiguousarray(b).view(kind).ravel()
    mask = np.isin(aa, bb)
    if len(np.unique(aa[mask])) != len(np.unique(bb)):
        raise ValueError("既有推测面的来源未完整保留，请回到前一版本或调整分界")
    return mask
