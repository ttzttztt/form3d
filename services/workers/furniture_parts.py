"""Full-surface editing proposals, logical merge and face reassignment.

These labels are reviewable editing regions, never manufacturing/semantic truth.
All partition operations retain original triangles, attributes and node transforms.
"""

import copy
import uuid
import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree
from services.api.glb_document import parts_catalog, selected_primitives


def primitive_data(doc, binary, part, p):
    from edit_asset import accessor_array, node_world_matrices

    if p.get("mode", 4) != 4 or p.get("targets") or doc.get("skins") or doc.get("animations"):
        raise ValueError("完整分组只支持静态三角网格")
    v = accessor_array(doc, binary, p["attributes"]["POSITION"])
    f = accessor_array(doc, binary, p["indices"]).reshape(-1, 3) if "indices" in p else np.arange(len(v)).reshape(-1, 3)
    if not len(f):
        raise ValueError("部件没有三角面")
    world = (np.c_[v, np.ones(len(v))] @ node_world_matrices(doc)[part["node"]].T)[:, :3]
    triangles = world[f]
    centers = triangles.mean(1)
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    area = np.linalg.norm(cross, axis=1) / 2
    normals = cross / np.maximum(2 * area[:, None], 1e-15)
    return v, f, world, centers, normals, area


def face_graph(v, f, centers):
    scale = max(float(np.ptp(v[f.ravel()], axis=0).max()), 1e-12)
    _, inverse = np.unique(np.round(v / scale, 7), axis=0, return_inverse=True)
    w = inverse[f]
    edges = np.concatenate((w[:, [0, 1]], w[:, [1, 2]], w[:, [2, 0]]))
    edges.sort(axis=1)
    owners = np.tile(np.arange(len(f)), 3)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    e = edges[order]
    o = owners[order]
    matches = np.all(e[1:] == e[:-1], axis=1)
    a = o[:-1][matches]
    b = o[1:][matches]
    weights = np.maximum(np.linalg.norm(centers[a] - centers[b], axis=1), scale * 1e-8)
    return sparse.csr_matrix((np.r_[weights, weights], (np.r_[a, b], np.r_[b, a])), shape=(len(f), len(f)))


def table_cut(centers, normals, area):
    # Some generated tables are tilted in their own Y-up coordinate frame.
    # Classify along the observed top normal, without rotating any geometry.
    upper = (centers[:, 1] > np.quantile(centers[:, 1], 0.55)) & (normals[:, 1] > 0.6)
    axis = np.array([0.0, 1.0, 0.0])
    tilt = 0.0
    confidence = 0.0
    if area[upper].sum() > 0:
        observed = (normals[upper] * area[upper, None]).sum(0)
        observed /= max(np.linalg.norm(observed), 1e-15)
        tilt = float(np.rad2deg(np.arccos(np.clip(observed[1], -1, 1))))
        confidence = float(area[upper & (normals @ observed > 0.88)].sum() / area[upper].sum())
        if 4 < tilt < 30 and confidence > 0.7:
            axis = observed
            right = np.cross(axis, [0.0, 0.0, 1.0])
            right /= np.linalg.norm(right)
            forward = np.cross(right, axis)
            basis = np.stack((right, axis, forward), axis=1)
            centers = centers @ basis
            normals = normals @ basis
    low = centers.min(0)
    high = centers.max(0)
    height = high[1] - low[1]
    if height < 1e-9:
        raise ValueError("模型高度不足以区分桌面和底座")
    bins = 160
    ybin = np.clip(((centers[:, 1] - low[1]) / height * (bins - 1)).astype(int), 0, bins - 1)
    horizontal = (np.abs(normals[:, 1]) > 0.88) & (centers[:, 1] > low[1] + height * 0.58)
    hist = np.bincount(ybin[horizontal], weights=area[horizontal], minlength=bins)
    topbin = int(np.argmax(hist))
    top = low[1] + height * topbin / (bins - 1)
    if not hist[topbin] or topbin < bins * 0.58:
        raise ValueError("未找到可靠的桌面结构，请改用手工分组")
    # Scan below the dominant top. A sustained footprint contraction marks the neck.
    widths = np.zeros(bins)
    for i in range(bins):
        points = centers[ybin == i]
        if len(points) >= 3:
            widths[i] = np.ptp(points[:, [0, 2]], axis=0).prod()
    reference = max(widths[max(0, topbin - 3) : min(bins, topbin + 3)].max(), 1e-15)
    cut = None
    for i in range(topbin - 2, max(int(topbin - bins * 0.22), 1), -1):
        if max(widths[max(0, i - 1) : i + 1]) < reference * 0.48:
            cut = low[1] + height * (i + 1) / (bins - 1)
            break
    # Broad downward-facing underside, when observed, gives a second piece of evidence.
    underside = (normals[:, 1] < -0.82) & (centers[:, 1] < top - height * 0.005) & (centers[:, 1] > top - height * 0.19)
    underhist = np.bincount(ybin[underside], weights=area[underside], minlength=bins)
    if underhist.max() > hist[topbin] * 0.12:
        under = low[1] + height * int(np.argmax(underhist)) / (bins - 1) - height * 0.004
        # The largest flat underside can sit above a protruding rim. Keep the
        # lower neck boundary when available, or that rim is assigned to the base.
        if cut is None:
            cut = under
        elif abs(under - cut) < height * 0.09:
            cut = min(cut, under)
    if cut is None:
        raise ValueError("桌面与底座连接处不清晰，未自动创建分组")
    labels = (centers[:, 1] >= cut).astype(int)
    if min(np.bincount(labels, minlength=2)) < max(12, len(labels) * 0.005):
        raise ValueError("桌面候选过小，未发布自动分组")
    return (
        labels,
        ["底座（候选）", "桌面（候选）"],
        {
            "method": "upper_horizontal_slab_and_neck",
            "cut_y": float(cut),
            "top_y": float(top),
            "classification_up_axis": axis.tolist(),
            "observed_tilt_degrees": tilt,
            "top_normal_confidence": confidence,
            "coordinate_note": "cut_y and top_y are measured along classification_up_axis",
            "includes": "all faces in each full height region, including rim and underside",
            "boundary": "whole triangle centroid assignment, not a physical cut",
        },
    )


def leg_regions(v, f, centers):
    graph = face_graph(v, f, centers)
    low = centers.min(0)
    high = centers.max(0)
    height = high[1] - low[1]
    seedmask = centers[:, 1] < low[1] + height * 0.36
    indices = np.flatnonzero(seedmask)
    _, cc = connected_components(graph[indices][:, indices], directed=False)
    unique, counts = np.unique(cc, return_counts=True)
    keep = unique[counts >= max(24, len(f) * 0.015)]
    if not 2 <= len(keep) <= 8:
        raise ValueError("底部没有分离出稳定支撑，不能可靠地细分桌腿")
    seedfaces = indices[np.isin(cc, keep)]
    seedlabels = np.full(len(f), -1, dtype=int)
    for label, key in enumerate(keep):
        seedlabels[indices[cc == key]] = label
    _, _, sources = dijkstra(graph, indices=seedfaces, directed=False, min_only=True, return_predecessors=True)
    labels = np.full(len(f), -1, dtype=int)
    valid = sources >= 0
    labels[valid] = seedlabels[sources[valid]]
    if np.any(labels < 0):
        labels[labels < 0] = seedlabels[seedfaces[cKDTree(centers[seedfaces]).query(centers[labels < 0])[1]]]
    center = (low + high) / 2
    span = max(np.ptp(centers[:, [0, 2]], axis=0).max(), 1e-9)
    joint = (centers[:, 1] > low[1] + height * 0.65) & (
        np.linalg.norm(centers[:, [0, 2]] - center[[0, 2]], axis=1) < span * 0.14
    )
    names = [f"支撑 {i + 1}（候选）" for i in range(len(keep))]
    if joint.sum() > 12:
        labels[joint] = len(names)
        names.append("公共连接处（候选）")
    return (
        labels,
        names,
        {
            "method": "separated_lower_seeds_geodesic_regions",
            "supports": len(keep),
            "note": "A fused junction is kept separate; not a claim about real disassembly.",
        },
    )


def propose(v, f, centers, normals, area, category, detail):
    if detail == "fine":
        return leg_regions(v, f, centers)
    graph = face_graph(v, f, centers)
    _, cc = connected_components(graph, directed=False)
    ids, counts = np.unique(cc, return_counts=True)
    large = ids[counts >= max(32, len(f) * 0.008)]
    if 2 <= len(large) <= 24:
        labels = np.full(len(f), -1, dtype=int)
        for i, key in enumerate(large):
            labels[cc == key] = i
        missing = labels < 0
        if missing.any():
            known = np.flatnonzero(~missing)
            labels[missing] = labels[known[cKDTree(centers[known]).query(centers[missing])[1]]]
        return (
            labels,
            [f"独立区域 {i + 1}（候选）" for i in range(len(large))],
            {"method": "connected_regions_all_sides", "small_fragments": "assigned to nearest region, never dropped"},
        )
    if category == "table":
        return table_cut(centers, normals, area)
    low = centers.min(0)
    high = centers.max(0)
    extent = high - low
    normalized = (centers - low) / np.maximum(extent, 1e-12)
    if category in {"chair", "sofa"}:
        # Complete spatial editing regions, not a claim that cushions were recognized.
        horizontal = (np.abs(normals[:, 1]) > 0.87) & (normalized[:, 1] > 0.15) & (normalized[:, 1] < 0.73)
        hist = np.histogram(normalized[horizontal, 1], bins=100, range=(0, 1), weights=area[horizontal])[0]
        if hist.max() <= 0:
            raise ValueError("未找到可检查的坐面高度，未自动分组")
        seat = (np.argmax(hist) + 0.5) / 100
        labels = np.zeros(len(f), dtype=int)
        labels[normalized[:, 1] > max(0.1, seat - 0.17)] = 1
        upper = normalized[:, 1] > seat + 0.09
        labels[upper] = 2
        if category == "sofa":
            labels[upper & (normalized[:, 0] < 0.2)] = 3
            labels[upper & (normalized[:, 0] > 0.8)] = 4
            names = [
                "下部结构（候选）",
                "座部区域（候选）",
                "上部中间区域（候选）",
                "左侧上部（候选）",
                "右侧上部（候选）",
            ]
        else:
            names = ["下部支撑（候选）", "坐面区域（候选）", "上部靠背区域（候选）"]
        return (
            labels,
            names,
            {
                "method": "seat_height_complete_spatial_regions",
                "seat_height_normalized": float(seat),
                "semantic_classification": False,
                "review": "Cushions, arms and back boundaries need user inspection.",
            },
        )
    if category in {"cabinet", "lamp"}:
        labels = np.digitize(normalized[:, 1], [0.22, 0.72] if category == "lamp" else [0.18, 0.65])
        return (
            labels,
            ["下部区域（候选）", "中部区域（候选）", "上部区域（候选）"],
            {
                "method": "complete_height_regions",
                "semantic_classification": False,
                "review": "Spatial editing candidates; no automatic cabinet-door or shade recognition.",
            },
        )
    raise ValueError("当前品类没有可靠的完整分组策略，请选择品类或手动拆分")


def replace_primitives(doc, replacements):
    for node_index, mapping in replacements.items():
        node = doc["nodes"][node_index]
        mesh = doc["meshes"][node["mesh"]]
        old_ids = node.get("extras", {}).get("form_part_ids", {})
        primitives = []
        ids = {}
        for i, old in enumerate(mesh["primitives"]):
            for primitive, identity in mapping.get(i, [(old, old_ids.get(str(i), f"node_{node_index}_primitive_{i}"))]):
                ids[str(len(primitives))] = identity
                primitives.append(primitive)
        mesh["primitives"] = primitives
        node.setdefault("extras", {})["form_part_ids"] = ids


def auto_parts(doc, binary, request):
    from asset_operations import append_array

    targets = selected_primitives(doc, request.get("part_ids", []))
    replacements = {}
    evidence = []
    category = request.get("category", "auto")
    category = request.get("_object_category", "other") if category == "auto" else category
    if len(targets) > 1 and request.get("detail_level") != "fine":
        for ordinal, (part, p) in enumerate(targets, 1):
            p.setdefault("extras", {}).update(
                form_logical_group_id="group_" + uuid.uuid4().hex,
                form_proposal_status="review_required",
                form_part_name=part["name"]
                if not part["name"].startswith("geometry")
                else f"已有结构 {ordinal}（候选）",
            )
        return {
            "operation": "auto_parts",
            "method": "existing_primitives_preserved",
            "groups": len(targets),
            "positions_preserved": True,
            "semantic_classification": False,
        }
    for part, p in targets:
        v, f, world, c, n, area = primitive_data(doc, binary, part, p)
        labels, names, details = propose(v, f, c, n, area, category, request.get("detail_level", "coarse"))
        unique, counts = np.unique(labels, return_counts=True)
        if len(unique) < 2:
            raise ValueError("没有生成多个有效部件，原版本保留")
        created = []
        for label, count in zip(unique, counts):
            new = copy.deepcopy(p)
            new["indices"] = append_array(doc, binary, f[labels == label].astype("<u4").ravel(), "SCALAR", 5125, 34963)
            extras = new.setdefault("extras", {})
            extras.update(
                form_part_name=names[int(label)],
                form_group_kind="complete_region_proposal",
                form_source_part=part["id"],
                form_proposal_status="review_required",
                form_logical_group_id="group_" + uuid.uuid4().hex,
            )
            extras.pop("form_selection_role", None)
            created.append((new, "part_" + uuid.uuid4().hex))
        replacements.setdefault(part["node"], {})[part["primitive"]] = created
        evidence.append(
            {
                "source_part": part["id"],
                "counts": counts.tolist(),
                "names": [names[int(i)] for i in unique],
                "triangles_preserved": len(f),
                **details,
            }
        )
    replace_primitives(doc, replacements)
    return {
        "operation": "auto_parts",
        "category": category,
        "regions": evidence,
        "semantic_classification": False,
        "review_status": "review_required",
        "note": "Complete mesh surface partitions, including hidden sides. Not watertight physical cuts.",
    }


def merge_parts(doc, request):
    targets = selected_primitives(doc, request["part_ids"])
    identity = "group_" + uuid.uuid4().hex
    for part, p in targets:
        p.setdefault("extras", {}).update(
            form_logical_group_id=identity,
            form_part_name=request.get("name") or "合并部件",
            form_proposal_status="manually_adjusted",
        )
    return {
        "operation": "merge_parts",
        "group_id": identity,
        "members": [part["id"] for part, _ in targets],
        "materials_preserved": True,
        "transforms_preserved": True,
    }


def assign_faces(doc, binary, request):
    from asset_operations import append_array

    target = request.get("target_part_id")
    lookup = {p["id"]: p for p in parts_catalog(doc)}
    if target and target not in lookup:
        raise ValueError("接收部件已变化，请刷新后重试")
    if target:
        part = lookup[target]
        p = doc["meshes"][doc["nodes"][part["node"]]["mesh"]]["primitives"][part["primitive"]]
        group = p.get("extras", {}).get("form_logical_group_id") or "group_" + uuid.uuid4().hex
        name = part["name"]
        for _, member in selected_primitives(
            doc,
            [
                k
                for k, v in lookup.items()
                if k == target or (v.get("logical_group_id") and v["logical_group_id"] == group)
            ],
        ):
            member.setdefault("extras", {})["form_logical_group_id"] = group
    else:
        group = "group_" + uuid.uuid4().hex
        name = request.get("name") or "拆出的部件"
    selections = {s["part_id"]: s["faces"] for s in request["face_selection"]}
    replacements = {}
    moved = 0
    for part, p in selected_primitives(doc, list(selections)):
        if target and (part["id"] == target or part.get("logical_group_id") == group):
            continue
        _, f, _, _, _, _ = primitive_data(doc, binary, part, p)
        selected = np.unique(selections[part["id"]])
        if len(selected) == 0 or selected.min() < 0 or selected.max() >= len(f):
            raise ValueError("选区编号失效，请重新选择")
        mask = np.zeros(len(f), dtype=bool)
        mask[selected] = True
        created = []
        if (~mask).any():
            remainder = copy.deepcopy(p)
            remainder["indices"] = append_array(doc, binary, f[~mask].astype("<u4").ravel(), "SCALAR", 5125, 34963)
            remainder.setdefault("extras", {}).pop("form_selection_role", None)
            created.append((remainder, part["id"]))
        new = copy.deepcopy(p)
        new["indices"] = append_array(doc, binary, f[mask].astype("<u4").ravel(), "SCALAR", 5125, 34963)
        new.setdefault("extras", {}).update(
            form_logical_group_id=group,
            form_part_name=name,
            form_group_kind="manual_assignment",
            form_source_part=part["id"],
            form_selection_role="selected",
            form_proposal_status="manually_adjusted",
        )
        created.append((new, "part_" + uuid.uuid4().hex if (~mask).any() else part["id"]))
        replacements.setdefault(part["node"], {})[part["primitive"]] = created
        moved += int(mask.sum())
    if not moved:
        raise ValueError("选区已经属于接收部件，无需移动")
    replace_primitives(doc, replacements)
    return {
        "operation": "assign_faces",
        "target_group_id": group,
        "moved_triangles": moved,
        "materials_preserved": True,
        "triangles_preserved": True,
    }
