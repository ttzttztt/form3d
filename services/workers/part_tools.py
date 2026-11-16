"""Attribute-preserving UV unwrap, world-space part translation and subset export."""

import copy
import numpy as np
from services.api.glb_document import selected_primitives, parts_catalog
from edit_asset import accessor_array, node_world_matrices

AUTO_PROXY_FACE_LIMIT = 60000


def reindex(doc, binary, p, mapping, faces):
    from asset_operations import append_array

    for key, index in list(p["attributes"].items()):
        definition = doc["accessors"][index]
        values = accessor_array(doc, binary, index)[mapping]
        if definition.get("normalized") and np.issubdtype(values.dtype, np.integer):
            limit = np.iinfo(values.dtype)
            values = np.maximum(values.astype(float) / limit.max, -1)
        p["attributes"][key] = append_array(doc, binary, values, definition["type"])
    p["indices"] = append_array(doc, binary, np.asarray(faces, dtype="<u4").ravel(), "SCALAR", 5125, 34963)


def box_unwrap(v, f):
    # Six normal-directed charts avoid a single projection's collapsed sides.
    used = np.unique(f)
    t = v[f]
    normal = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    axis = np.argmax(abs(normal), axis=1)
    chart = axis * 2 + (normal[np.arange(len(f)), axis] < 0)
    pairs = np.c_[np.repeat(chart, 3), f.ravel()]
    unique, inverse = np.unique(pairs, axis=0, return_inverse=True)
    mapping = unique[:, 1]
    newfaces = inverse.reshape(-1, 3)
    a = unique[:, 0] // 2
    u = (a + 1) % 3
    vv = (a + 2) % 3
    points = v[mapping]
    low = v[used].min(0)
    scale = max(float(np.ptp(v[used], axis=0).max()), 1e-9)
    row = np.arange(len(mapping))
    coords = np.c_[(points[row, u] - low[u]) / scale, (points[row, vv] - low[vv]) / scale]
    coords[unique[:, 0] % 2 == 1, 0] = 1 - coords[unique[:, 0] % 2 == 1, 0]
    uv = coords * 0.30 + np.c_[(unique[:, 0] % 3) / 3 + 0.015, (unique[:, 0] // 3) / 2 + 0.1]
    return mapping, newfaces, uv


def unwrap_uv(doc, binary, request):
    from furniture_parts import primitive_data
    from asset_operations import append_array

    results = []
    for part, p in selected_primitives(doc, request.get("part_ids", [])):
        v, f, _, _, _, _ = primitive_data(doc, binary, part, p)
        if len(f) > 750000:
            raise ValueError("展开超过 75 万面，请先减面或只选择一个部件")
        used = np.unique(f)
        remap = np.full(len(v), -1, dtype=np.int64)
        remap[used] = np.arange(len(used))
        faces = remap[f]
        requested = request.get("uv_unwrap_mode", "auto")
        mode = ("proxy" if len(f) > AUTO_PROXY_FACE_LIMIT else "atlas") if requested == "auto" else requested
        extra = {}
        if mode == "proxy":
            from proxy_uv import proxy_unwrap

            try:
                mapping, newfaces, uv, extra = proxy_unwrap(v[used], faces)
                mapping = used[mapping]
                if requested == "auto":
                    from uv_quality import uv_diagnostics, prefer_proxy

                    box_mapping, box_faces, box_uv = box_unwrap(v, f)
                    world = node_world_matrices(doc)[part["node"]]

                    def diagnose(m, fs, tex):
                        return uv_diagnostics((np.c_[v[m], np.ones(len(m))] @ world.T)[:, :3], fs, tex)

                    baseline = diagnose(box_mapping, box_faces, box_uv)
                    candidate = diagnose(mapping, newfaces, uv)
                    accepted = prefer_proxy(baseline, candidate)
                    extra["auto_quality_comparison"] = {
                        "box": baseline,
                        "proxy": candidate,
                        "proxy_selected": accepted,
                        "policy": "seams reduce >5%; mean anisotropy <=110% of box; area anisotropy>4 <=0.5%; collapsed area <=0.1%. Heuristics, not appearance guarantees.",
                    }
                    if not accepted:
                        comparison = extra.pop("auto_quality_comparison")
                        mode = "box"
                        extra = {
                            "proxy_attempt": extra,
                            "auto_quality_comparison": comparison,
                            "fallback_reason": "代理 UV 未通过接缝与拉伸对照，保留快速分区",
                        }
                        mapping, newfaces, uv = box_mapping, box_faces, box_uv
            except (ValueError, ImportError, RuntimeError) as exc:
                if requested != "auto":
                    raise ValueError(str(exc))
                mode = "box"
                extra = {"fallback_reason": str(exc)}
        if mode == "cylinder":
            from cylindrical_uv import cylindrical_unwrap

            mapping, newfaces, uv, extra = cylindrical_unwrap(v[used], faces, request.get("axis", "y"))
            mapping = used[mapping]
        if mode == "atlas":
            try:
                import xatlas
            except ImportError:
                raise ValueError("精细 UV 展开需要安装 xatlas，可先选择快速分区展开")
            if len(f) > 60000:
                raise ValueError("精细展开限 6 万面，请先减面、选择更小部件，或使用快速分区展开")
            mapping, newfaces, uv = xatlas.parametrize(v[used].astype(np.float32), faces.astype(np.uint32))
            mapping = used[np.asarray(mapping, dtype=int)]
        elif mode == "box":
            mapping, newfaces, uv = box_unwrap(v, f)
        if not np.isfinite(uv).all() or len(newfaces) != len(f):
            raise ValueError("UV 展开返回无效结果，原版本保留")
        reindex(doc, binary, p, mapping, newfaces)
        p["attributes"]["TEXCOORD_0"] = append_array(doc, binary, uv, "VEC2")
        p["attributes"].pop("TANGENT", None)
        extra.pop("algorithm", None)
        results.append(
            {
                "part_id": part["id"],
                "triangles": len(f),
                "vertices_before": len(used),
                "vertices_after": len(mapping),
                "algorithm": {
                    "atlas": "xatlas",
                    "box": "six_normal_charts",
                    "proxy": "proxy_xatlas_transfer",
                    "cylinder": "continuous_cylinder_and_caps",
                }[mode],
                "positions_preserved": True,
                "seams": "six chart boundaries; inspect pattern continuity"
                if mode == "box"
                else "chart boundaries, inspect texture continuity",
                **extra,
            }
        )
    return {
        "operation": "unwrap_uv",
        "parts": results,
        "note": "UV chart seams may duplicate vertices. Original world triangles retained; existing textures are remapped, inspect the new version.",
    }


def reconstructed_scope(doc, part_ids):

    parts = parts_catalog(doc)
    chosen = set(part_ids)
    if not chosen or not chosen.issubset({p["id"] for p in parts}):
        raise ValueError("所选部件已变化，请重新选择")
    groups = {
        p.get("logical_group_id")
        for p in parts
        if p["id"] in chosen and p.get("group_kind") == "reconstructed_logical_part"
    } - {None}
    return [p["id"] for p in parts if p["id"] in chosen or p.get("logical_group_id") in groups]


def translate_parts(doc, binary, request):
    from furniture_parts import primitive_data

    # A missing-interface patch is never an independently movable component.
    identities = reconstructed_scope(doc, request["part_ids"])
    if not identities:
        raise ValueError("所选部件已变化，请重新选择")
    targets = selected_primitives(doc, identities)
    worlds = node_world_matrices(doc)
    by_node = {}
    results = []
    for part, p in targets:
        primitive_data(doc, binary, part, p)  # Reject animated/non-triangle geometry.
        by_node.setdefault(part["node"], []).append((part, p))
        results.append(part["id"])
    if not doc.get("scenes"):
        children = {c for n in doc["nodes"] for c in n.get("children", [])}
        doc["scenes"] = [{"nodes": [i for i in range(len(doc["nodes"])) if i not in children]}]
        doc["scene"] = 0
    roots = doc["scenes"][doc.get("scene", 0)].setdefault("nodes", [])
    for node_index, selected in by_node.items():
        node = doc["nodes"][node_index]
        mesh = doc["meshes"][node["mesh"]]
        numbers = {part["primitive"] for part, _ in selected}
        ids = node.get("extras", {}).get("form_part_ids", {})
        remaining = [(i, p) for i, p in enumerate(mesh["primitives"]) if i not in numbers]
        moved_mesh = copy.deepcopy(mesh)
        moved_mesh["primitives"] = [p for _, p in selected]
        mesh_index = len(doc["meshes"])
        doc["meshes"].append(moved_mesh)
        transform = worlds[node_index].copy()
        transform[:3, 3] += np.asarray(request["translation"], dtype=float)
        moved_node = {
            "name": "Moved static parts",
            "mesh": mesh_index,
            "matrix": transform.ravel(order="F").tolist(),
            "extras": {"form_part_ids": {str(i): part["id"] for i, (part, _) in enumerate(selected)}},
        }
        roots.append(len(doc["nodes"]))
        doc["nodes"].append(moved_node)
        if remaining:
            mesh["primitives"] = [p for _, p in remaining]
            node.setdefault("extras", {})["form_part_ids"] = {
                str(j): ids.get(str(i), f"node_{node_index}_primitive_{i}") for j, (i, _) in enumerate(remaining)
            }
        else:
            node.pop("mesh")
            node.setdefault("extras", {})["form_part_ids"] = {}
    return {
        "operation": "translate_parts",
        "part_ids": results,
        "world_translation": request["translation"],
        "local_vertex_attributes_preserved": True,
        "method": "independent static node transforms; no float32 vertex displacement",
        "units": "model units; real dimensions unverified",
    }


def export_parts(doc, binary, request):
    if doc.get("skins") or doc.get("animations"):
        raise ValueError("部件导出只支持静态模型")
    allowed = {
        "KHR_texture_transform",
        "KHR_materials_ior",
        "KHR_materials_specular",
        "KHR_materials_unlit",
        "KHR_materials_transmission",
        "KHR_materials_volume",
        "KHR_materials_sheen",
        "KHR_materials_clearcoat",
        "KHR_materials_emissive_strength",
        "KHR_materials_anisotropy",
        "KHR_materials_iridescence",
    }
    if set(doc.get("extensionsUsed", [])) - allowed:
        raise ValueError("该模型含暂不支持安全裁剪的扩展，请保留完整模型导出")
    from furniture_parts import primitive_data

    identities = reconstructed_scope(doc, request["part_ids"])
    if not identities:
        raise ValueError("所选部件已变化，请重新选择")
    targets = selected_primitives(doc, identities)
    keep = {}
    for part, p in targets:
        _, f, _, _, _, _ = primitive_data(doc, binary, part, p)
        used = np.unique(f)
        lookup = np.full(int(f.max()) + 1, -1, dtype=np.int64)
        lookup[used] = np.arange(len(used))
        reindex(doc, binary, p, used, lookup[f])
        keep.setdefault(part["node"], []).append((part, p))
    for i, node in enumerate(doc.get("nodes", [])):
        if "mesh" not in node:
            continue
        if i not in keep:
            node.pop("mesh")
            continue
        mesh = copy.deepcopy(doc["meshes"][node["mesh"]])
        mesh["primitives"] = [p for _, p in keep[i]]
        doc["meshes"].append(mesh)
        node["mesh"] = len(doc["meshes"]) - 1
        node.setdefault("extras", {})["form_part_ids"] = {str(k): part["id"] for k, (part, _) in enumerate(keep[i])}
    used_meshes = sorted({n["mesh"] for n in doc["nodes"] if "mesh" in n})
    remap = {old: new for new, old in enumerate(used_meshes)}
    doc["meshes"] = [doc["meshes"][i] for i in used_meshes]
    for n in doc["nodes"]:
        if "mesh" in n:
            n["mesh"] = remap[n["mesh"]]
    # Keep material/texture indices, including extension maps, unchanged. Prune
    # geometry and repack only reachable accessor/image views even for PBR extensions.
    primitives = [p for m in doc["meshes"] for p in m["primitives"]]
    used_accessors = sorted({a for p in primitives for a in [*p["attributes"].values(), p["indices"]]})
    remap = {old: new for new, old in enumerate(used_accessors)}
    doc["accessors"] = [doc["accessors"][i] for i in used_accessors]
    for p in primitives:
        p["attributes"] = {k: remap[v] for k, v in p["attributes"].items()}
        p["indices"] = remap[p["indices"]]
    used_views = sorted(
        {a["bufferView"] for a in doc["accessors"]}
        | {i["bufferView"] for i in doc.get("images", []) if "bufferView" in i}
    )
    remap = {old: new for new, old in enumerate(used_views)}
    views = []
    packed = bytearray()
    for i in used_views:
        view = copy.deepcopy(doc["bufferViews"][i])
        start = view.get("byteOffset", 0)
        data = binary[start : start + view["byteLength"]]
        packed.extend(b"\0" * (-len(packed) % 4))
        view["byteOffset"] = len(packed)
        views.append(view)
        packed.extend(data)
    doc["bufferViews"] = views
    for a in doc["accessors"]:
        a["bufferView"] = remap[a["bufferView"]]
    for image in doc.get("images", []):
        if "bufferView" in image:
            image["bufferView"] = remap[image["bufferView"]]
    binary.clear()
    binary.extend(packed)
    return {"operation": "export_parts", "part_ids": [p["id"] for p, _ in targets], "world_transforms_preserved": True}
