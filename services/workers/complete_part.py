# -*- coding: utf-8 -*-
"""Source diagnosis and explicit volume-guided, capped part reconstruction."""

import copy, json, uuid
import numpy as np
import trimesh
from services.api.glb_document import parts_catalog, selected_primitives
from furniture_parts import primitive_data
from solid_partition import partition_box, prepare_mesh


def context(doc, binary, request):
    catalog = parts_catalog(doc)
    selections = request.get("face_selection", [])
    profile = request.get("completion_profile", "cushion")
    ids = [s["part_id"] for s in selections] if selections else request.get("part_ids", [])
    if not ids or (len(ids) != 1 and profile == "cushion"):
        raise ValueError("请选择一个原始网格上的局部，或一个已保存的表面部件")
    part = next((p for p in catalog if p["id"] == ids[0]), None)
    if part is None:
        raise ValueError("部件已变化，请刷新后重新选择")
    chosen_parts = [p for p in catalog if p["id"] in ids]
    if len(chosen_parts) != len(set(ids)) or any(
        p["node"] != part["node"] or (len(ids) > 1 and p.get("logical_group_id") != part.get("logical_group_id"))
        for p in chosen_parts
    ):
        raise ValueError("请选择同一个逻辑部件，不能合并不同来源重建")
    from edit_asset import node_world_matrices

    scales = np.linalg.svd(node_world_matrices(doc)[part["node"]][:3, :3], compute_uv=False)
    if min(scales) <= 1e-12 or max(scales) / min(scales) > 1.001:
        raise ValueError("非均匀缩放的网格暂不完整重建，请先应用变换或使用原始生成模型")
    completed = any(p.get("completion_role") for p in chosen_parts)
    root = (
        (part.get("logical_group_id") if completed and profile != "cushion" else None)
        or part.get("source_part_id")
        or part["id"]
    )
    family = [
        p
        for p in catalog
        if p["node"] == part["node"]
        and (
            (p.get("logical_group_id") == root)
            if completed and profile != "cushion"
            else (p["id"] == root or p.get("source_part_id") == root)
        )
    ]
    primitives = []
    meshes = []
    guides = []
    for p, primitive in selected_primitives(doc, [p["id"] for p in family]):
        if primitive.get("extras", {}).get("form_completion_role") and profile == "cushion":
            raise ValueError("这个源网格已有重建部件，请回到重建前版本调整范围")
        if set(primitive["attributes"]) - {"POSITION", "NORMAL"}:
            raise ValueError("完整重建当前支持无贴图、无顶点颜色的静态模型；请保留原版本")
        material = doc.get("materials", [])[primitive["material"]] if "material" in primitive else {}
        if any("Texture" in k for k in material) or any(
            "Texture" in k for k in material.get("pbrMetallicRoughness", {})
        ):
            raise ValueError("带贴图材质暂不重建，以免破坏原贴图")
        _, faces, world, centers, normal, area = primitive_data(doc, binary, p, primitive)
        meshes.append(trimesh.Trimesh(world, faces, process=False))
        primitives.append((p, primitive))
        if p["id"] in ids:
            chosen = np.unique(selections[0]["faces"]) if selections else np.arange(len(faces))
            if (
                len(chosen) < (8 if selections or profile == "cushion" else 1)
                or chosen.min() < 0
                or chosen.max() >= len(faces)
            ):
                raise ValueError("选区不足或面编号失效，请重新选择")
            g = trimesh.Trimesh(world, faces[chosen], process=False)
            g.remove_unreferenced_vertices()
            guides.append(g)
    if len({p.get("material") for _, p in primitives}) != 1:
        raise ValueError("同一源网格已有不同材质，请先回到局部换材质前的版本重建")
    source = trimesh.util.concatenate(meshes)
    source.remove_unreferenced_vertices()
    guide = trimesh.util.concatenate(guides)
    guide.remove_unreferenced_vertices()
    if len(source.faces) > 1600000:
        raise ValueError("源网格超过 160 万面，请先减面")
    if profile == "cushion" and guide.area > source.area * 0.8:
        raise ValueError("选区覆盖了大部分源网格，请先选出坐垫局部表面")
    return part, root, primitives, source, guide


def contour_planes(source, guide):
    from shapely.geometry import MultiPoint

    diagonal = max(float(np.linalg.norm(source.extents)), 1e-9)
    hull = MultiPoint(guide.vertices[:, [0, 2]]).convex_hull
    if hull.area < diagonal * diagonal * 0.0001:
        raise ValueError("选区没有足够的三维深度，请补选坐垫顶面再检查")
    poly = hull.buffer(diagonal * 0.0015).simplify(diagonal * 0.003, preserve_topology=True)
    points = np.array(poly.exterior.coords)[:-1]
    center = points.mean(0)
    points = center + (points - center) * 1.015
    area = np.sum(points[:, 0] * np.roll(points[:, 1], -1) - points[:, 1] * np.roll(points[:, 0], -1))
    points = points if area > 0 else points[::-1]
    planes = []
    for a, b in zip(points, np.roll(points, -1, axis=0)):
        delta = b - a
        n = np.array([-delta[1], 0, delta[0]])
        n /= np.linalg.norm(n)
        planes.append((np.array([a[0], 0, a[1]]), n))
    for ratio in (1.0, 2.0):
        for angle in np.arange(8) * np.pi / 4:
            outward = np.array([np.cos(angle), ratio, np.sin(angle)])
            outward /= np.linalg.norm(outward)
            support = float((guide.vertices @ outward).max()) + diagonal * 0.0003
            planes.append((outward * support, -outward))
    return planes, points


def mesh_stats(mesh):
    edges, counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    closed = bool(mesh.is_watertight)
    return {
        "triangles": len(mesh.faces),
        "boundary_edges": int((counts == 1).sum()),
        "nonmanifold_edges": int((counts > 2).sum()),
        "watertight": closed,
        "winding_consistent": bool(mesh.is_winding_consistent),
        "volume": float(mesh.volume) if closed else None,
        "surface_area": float(mesh.area),
    }


def completion_plan(doc, binary, request):
    part, root, primitives, source, guide = context(doc, binary, request)
    profile = request.get("completion_profile", "cushion")
    low, high = source.bounds
    extent = high - low
    glow, ghigh = guide.bounds
    lower = glow - extent * 0.005
    upper = ghigh + extent * 0.008
    # Recover observed underside only near the seed footprint and seat-height band.
    c = source.triangles_center
    n = source.face_normals
    underside = (
        (n[:, 1] < -0.75)
        & (c[:, 0] > glow[0])
        & (c[:, 0] < ghigh[0])
        & (c[:, 2] > glow[2])
        & (c[:, 2] < ghigh[2])
        & (c[:, 1] > glow[1] - extent[1] * 0.12)
        & (c[:, 1] < glow[1] + extent[1] * 0.03)
    )
    if underside.sum() > 20:
        values = c[underside, 1]
        hist, edges = np.histogram(values, bins=32, weights=source.area_faces[underside])
        peak = (edges[np.argmax(hist)] + edges[np.argmax(hist) + 1]) / 2
        lower[1] = min(lower[1], peak - extent[1] * 0.025)
    normalized = np.clip(
        np.array([(lower - low) / np.maximum(extent, 1e-12), (upper - low) / np.maximum(extent, 1e-12)]), 0, 1
    )
    strategy = {}
    if profile != "cushion" and not request.get("completion_bounds"):
        from structural_completion import structural_bounds

        normalized, strategy = structural_bounds(source, profile, request.get("detail_level", "coarse"))
    elif profile != "cushion":
        strategy = {"method": "explicit_world_axis_bounds", "automatic_region": False, "semantic_recognition": False}
    supplied = request.get("completion_bounds")
    if supplied:
        normalized = np.asarray(supplied, dtype=float)
    if (
        normalized.shape != (2, 3)
        or not np.isfinite(normalized).all()
        or (normalized < 0).any()
        or (normalized > 1).any()
        or np.any(normalized[1] - normalized[0] < 0.005)
    ):
        raise ValueError("每个方向的范围至少保留 0.5%，且起点必须小于终点")
    bounds = low + normalized * extent
    if profile != "cushion" and guide.area > source.area * 0.8:
        mask = np.all((source.triangles_center >= bounds[0]) & (source.triangles_center <= bounds[1]), axis=1)
        if mask.sum() < 2:
            raise ValueError("范围内没有足够的结构面，请调整分界")
        guide = trimesh.Trimesh(source.vertices, source.faces[mask], process=False)
        guide.remove_unreferenced_vertices()
    fraction = float(
        guide.area_faces[
            np.all((guide.triangles_center >= bounds[0]) & (guide.triangles_center <= bounds[1]), axis=1)
        ].sum()
        / max(guide.area, 1e-15)
    )
    clean, removed = prepare_mesh(source)
    gclean, _ = prepare_mesh(guide)
    use_contour = profile == "cushion" and request.get("completion_shape", "contour") == "contour"
    planes, outline = contour_planes(source, guide) if use_contour else ([], np.empty((0, 2)))
    area = guide.area_faces
    directions = {
        name: float(area[guide.face_normals[:, axis] * sign > 0.7].sum() / max(area.sum(), 1e-15))
        for name, axis, sign in [
            ("top", 1, 1),
            ("bottom", 1, -1),
            ("front", 2, 1),
            ("back", 2, -1),
            ("left", 0, -1),
            ("right", 0, 1),
        ]
    }
    underconstrained = (
        profile == "cushion" and np.ptp(guide.vertices[:, 1]) < extent[1] * 0.12 and directions["top"] > 0.65
    )
    warnings = ["选区主要是顶面，无法可靠确定坐垫厚度；请补选侧面或明确底部范围。"] if underconstrained else []
    if profile == "cushion" and not use_contour:
        warnings.append(
            "按调整范围切分会重新纳入框内原表面；排除点只修正表面选区。请缩小前后边界，并检查预览是否带入靠垫或扶手。"
        )
    return {
        "completion_profile": profile,
        "completion_shape": request.get("completion_shape", "contour"),
        "source_part_id": root,
        "guide_part_id": part["id"],
        "source_bounds_world": source.bounds.tolist(),
        "bounds_world": bounds.tolist(),
        "completion_bounds": normalized.tolist(),
        "contour_outline_world_xz": outline.tolist(),
        "contour_planes": len(planes),
        "guide_area_in_bounds_fraction": fraction,
        "source": mesh_stats(clean),
        "guide": mesh_stats(gclean),
        "guide_direction_area_fraction": directions,
        "thickness_underconstrained": bool(underconstrained),
        "warnings": warnings,
        "source_degenerate_index_faces_removed": removed,
        "method": ("seed footprint convex contour + upper support planes" if use_contour else "explicit_box_volume")
        if profile == "cushion"
        else strategy["method"],
        "strategy": strategy,
        "limits": [
            "坐垫可按选区轮廓或显式范围切分；均需检查侧面和底面。",
            "会新增推测接合面，不能恢复真实隐藏结构。",
            "仅支持无贴图、无顶点颜色的静态网格。",
        ],
    }


def complete_part(doc, binary, request):
    from asset_operations import append_array
    from edit_asset import node_world_matrices

    plan = completion_plan(doc, binary, request)
    box = (
        request.get("completion_shape", "contour") == "box"
        and request.get("completion_profile", "cushion") == "cushion"
    )
    if box and not request.get("completion_bounds"):
        raise ValueError("按范围切分需要明确的三维边界，请先检查并调整范围")
    if plan["guide_area_in_bounds_fraction"] < (0.05 if box else 0.75):
        raise ValueError("范围排除了较多已选表面，请先检查并扩大范围")
    part, root, primitives, source, guide = context(doc, binary, request)
    profile = request.get("completion_profile", "cushion")
    planes, _ = contour_planes(source, guide) if profile == "cushion" and not box else ([], None)
    inherited = []
    for old_part, old_p in primitives:
        if old_p.get("extras", {}).get("form_completion_role") == "inferred_interface":
            _, old_f, old_w, _, _, _ = primitive_data(doc, binary, old_part, old_p)
            old = trimesh.Trimesh(old_w, old_f, process=False)
            inherited.append(old)
            b = np.asarray(plan["bounds_world"])
            outside = np.zeros(len(old_f), bool)
            for axis in range(3):
                outside |= np.all(old.triangles[:, :, axis] < b[0, axis] - 1e-8, axis=1) | np.all(
                    old.triangles[:, :, axis] > b[1, axis] + 1e-8, axis=1
                )
            if not outside.all():
                raise ValueError("新范围会切到已有推测面，请缩小范围或回到重建前版本")
    source, seat, seat_caps, body, body_caps, evidence = partition_box(source, plan["bounds_world"], planes)
    inherited_count = 0
    if inherited:
        from structural_completion import inherited_interface_mask

        old_mesh = trimesh.util.concatenate(inherited)
        mask = inherited_interface_mask(body, old_mesh, float(np.linalg.norm(source.extents)))
        inherited_count = int(mask.sum())
        body_caps |= mask
    seat_stats = mesh_stats(seat)
    body_stats = mesh_stats(body)
    if not seat_stats["watertight"] or not seat_stats["winding_consistent"] or seat_stats["volume"] <= 0:
        raise ValueError("坐垫未形成一致闭合体，原模型保留，请调整范围")
    if not body_stats["watertight"] or not body_stats["winding_consistent"] or body_stats["volume"] <= 0:
        raise ValueError("椅身切口未通过闭合检查，原模型保留，请调整范围")
    count = len(seat.split(only_watertight=False))
    body_components = len(body.split(only_watertight=False))
    if profile == "support" and request.get("detail_level") == "fine" and count < 2:
        raise ValueError("当前分界仍是连体支撑，请降低分界或保持整体")
    if count != 1 and not (profile == "support" and 1 < count <= 8):
        raise ValueError("范围包含多个分离实体，请缩小范围避免带入其他结构")
    volume_error = float(abs(seat.volume + body.volume - source.volume) / max(abs(source.volume), 1e-15))
    if volume_error > 1e-5:
        raise ValueError("切分体积校验未通过，原版本保留")
    world_matrix = node_world_matrices(doc)[part["node"]]
    inverse = np.linalg.inv(world_matrix)
    base = primitives[0][1]
    body_group = "group_" + uuid.uuid4().hex
    created = []
    name = request.get("name") or "完整部件候选"
    seat_groups = []
    specifications = [(False, body, body_caps, body_group, "其余结构")]
    components = (
        trimesh.graph.connected_components(seat.face_adjacency, nodes=np.arange(len(seat.faces)))
        if profile == "support" and count > 1
        else [np.arange(len(seat.faces))]
    )
    for ordinal, indices in enumerate(sorted(components, key=lambda a: float(seat.triangles_center[a, 0].mean())), 1):
        group = "group_" + uuid.uuid4().hex
        seat_groups.append(group)
        m = trimesh.Trimesh(seat.vertices, seat.faces[indices], process=False)
        m.remove_unreferenced_vertices()
        specifications.append(
            (True, m, seat_caps[indices], group, name + (f" {ordinal}" if len(components) > 1 else ""))
        )
    for is_seat, mesh, caps, group, label in specifications:
        emitted = []
        local = (np.c_[mesh.vertices, np.ones(len(mesh.vertices))] @ inverse.T)[:, :3].astype(np.float32)
        for inferred in (False, True):
            faces = mesh.faces[caps == inferred]
            if not len(faces):
                continue
            used = np.unique(faces)
            remap = np.full(len(local), -1, dtype=int)
            remap[used] = np.arange(len(used))
            f = remap[faces]
            v = local[used]
            m = trimesh.Trimesh(v, f, process=False)
            if inferred:
                m = trimesh.graph.smooth_shade(m, angle=np.deg2rad(30), facet_minarea=10)
            v = m.vertices
            f = m.faces
            normals = m.vertex_normals.copy()
            length = np.linalg.norm(normals, axis=1)
            normals[length < 1e-10] = [0, 1, 0]
            normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-15)
            p = copy.deepcopy(base)
            p["attributes"] = {
                "POSITION": append_array(doc, binary, v, "VEC3"),
                "NORMAL": append_array(doc, binary, normals, "VEC3"),
            }
            p["indices"] = append_array(doc, binary, f.ravel(), "SCALAR", 5125, 34963)
            p.setdefault("extras", {}).update(
                form_part_name=label,
                form_source_part=root,
                form_logical_group_id=group,
                form_group_kind="volume_completed_part",
                form_selection_role="selected" if is_seat else "remainder",
                form_completion_role="inferred_interface" if inferred else "observed_surface",
                form_proposal_status="reconstruction_review_required",
                form_completion_note="平面推测接合面；非真实隐藏结构" if inferred else "源模型表面，经范围切割",
            )
            created.append((p, "part_" + uuid.uuid4().hex))
            emitted.append(
                trimesh.Trimesh(
                    (np.c_[v.astype(np.float32), np.ones(len(v))] @ world_matrix.T)[:, :3], f, process=False
                )
            )
        checked = trimesh.util.concatenate(emitted)
        checked.merge_vertices(digits_vertex=8)
        if not checked.is_watertight or not checked.is_winding_consistent:
            raise ValueError("GLB 存储精度下切口未保持闭合，原版本保留，请略调范围")
    node = doc["nodes"][part["node"]]
    mesh = doc["meshes"][node["mesh"]]
    family_numbers = {p["primitive"] for p, _ in primitives}
    old_ids = node.get("extras", {}).get("form_part_ids", {})
    new = []
    identities = {}
    for i, p in enumerate(mesh["primitives"]):
        entries = (
            created
            if i == min(family_numbers)
            else []
            if i in family_numbers
            else [(p, old_ids.get(str(i), f"node_{part['node']}_primitive_{i}"))]
        )
        for primitive, identity in entries:
            identities[str(len(new))] = identity
            new.append(primitive)
    mesh["primitives"] = new
    node.setdefault("extras", {})["form_part_ids"] = identities
    return {
        "operation": "complete_part",
        "plan": plan,
        "part_group_id": seat_groups[0],
        "part_group_ids": seat_groups,
        "remainder_group_id": body_group,
        "part": {
            **seat_stats,
            "components": count,
            "inferred_triangles": int(seat_caps.sum()),
            "inferred_area_fraction": float(seat.area_faces[seat_caps].sum() / seat.area),
        },
        "remainder": {
            **body_stats,
            "components": body_components,
            "inferred_triangles": int(body_caps.sum()),
            "inherited_inferred_triangles": inherited_count,
        },
        "volume_partition_relative_error": volume_error,
        "positions_unchanged": False,
        "reconstruction_status": "inferred_interfaces_review_required",
        **evidence,
    }
