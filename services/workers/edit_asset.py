# -*- coding: utf-8 -*-
"""CPU-only asset grouping/material edit, preserving original triangle data."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.api.glb_document import (
    read_glb,
    write_glb,
    parts_catalog,
    selected_primitives,
    material_edit,
    set_part_ids,
    compact_static,
)


def accessor_array(doc, binary, index):
    import numpy as np

    accessor = doc["accessors"][index]
    if accessor.get("sparse") or "bufferView" not in accessor:
        raise ValueError("稀疏 accessor 暂不支持分组")
    view = doc["bufferViews"][accessor["bufferView"]]
    if view.get("buffer", 0) != 0 or view.get("extensions"):
        raise ValueError("压缩 buffer 暂不支持分组")
    dtype = np.dtype(
        {5126: "<f4", 5125: "<u4", 5123: "<u2", 5121: "u1", 5120: "i1", 5122: "<i2"}[accessor["componentType"]]
    )
    components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride", dtype.itemsize * components)
    return np.ndarray(
        (accessor["count"], components), dtype=dtype, buffer=binary, offset=offset, strides=(stride, dtype.itemsize)
    ).copy()


def node_world_matrices(doc):
    import numpy as np

    matrices = {}

    def visit(index, parent):
        node = doc["nodes"][index]
        if "matrix" in node:
            local = np.array(node["matrix"]).reshape(4, 4, order="F")
        else:
            x, y, z, w = node.get("rotation", [0, 0, 0, 1])
            scale = node.get("scale", [1, 1, 1])
            local = np.eye(4)
            local[:3, :3] = np.array(
                [
                    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
                ]
            ) @ np.diag(scale)
            local[:3, 3] = node.get("translation", [0, 0, 0])
        matrices[index] = parent @ local
        for child in node.get("children", []):
            visit(child, matrices[index])

    scenes = doc.get("scenes", [])
    roots = scenes[doc.get("scene", 0)].get("nodes", []) if scenes else list(range(len(doc["nodes"])))
    for index in roots:
        visit(index, np.eye(4))
    return matrices


def group_geometry(doc, binary, request):
    import numpy as np
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components

    if doc.get("animations") or doc.get("skins"):
        raise ValueError("区域分组暂只支持静态网格")
    for mesh in doc["meshes"]:
        if any(p.get("extensions", {}).get("KHR_draco_mesh_compression") for p in mesh["primitives"]):
            raise ValueError("压缩网格暂不支持分组")
    worlds = node_world_matrices(doc)
    targets = selected_primitives(doc, request.get("part_ids", []))
    prepared = []
    for part, primitive in targets:
        if primitive.get("mode", 4) != 4:
            raise ValueError("只支持三角网格分组")
        vertices = accessor_array(doc, binary, primitive["attributes"]["POSITION"])
        faces = (
            accessor_array(doc, binary, primitive["indices"]).ravel().reshape(-1, 3)
            if "indices" in primitive
            else np.arange(len(vertices)).reshape(-1, 3)
        )
        world = np.c_[vertices, np.ones(len(vertices))] @ worlds[part["node"]].T
        prepared.append((part, primitive, vertices, faces, world[:, :3]))
    bounds = np.array(
        [
            [min(v[f.ravel(), axis].min() for _, _, _, f, v in prepared) for axis in range(3)],
            [max(v[f.ravel(), axis].max() for _, _, _, f, v in prepared) for axis in range(3)],
        ]
    )
    result = []
    replacements = {}
    triangle_total = 0
    new_total = 0
    axis = {"x": 0, "y": 1, "z": 2}[request["axis"]]
    cut = bounds[0, axis] + (bounds[1, axis] - bounds[0, axis]) * request["position"]

    def append_indices(faces):
        binary.extend(b"\0" * (-len(binary) % 4))
        offset = len(binary)
        data = faces.astype("<u4").ravel().tobytes()
        binary.extend(data)
        view = len(doc.setdefault("bufferViews", []))
        doc["bufferViews"].append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": 34963})
        accessor = len(doc.setdefault("accessors", []))
        doc["accessors"].append({"bufferView": view, "componentType": 5125, "count": len(faces) * 3, "type": "SCALAR"})
        return accessor

    for part, primitive, vertices, faces, world in prepared:
        triangle_total += len(faces)
        if request["operation"] == "face_group":
            selected = next((item["faces"] for item in request["face_selection"] if item["part_id"] == part["id"]), [])
            if not selected or max(selected) >= len(faces):
                raise ValueError("选面编号已失效，请重新选择")
            group_ids = np.zeros(len(faces), dtype=int)
            group_ids[selected] = 1
            kind = "manual_faces"
            prefix = "选面"
        elif request["operation"] == "plane_group":
            group_ids = (world[faces].mean(axis=1)[:, axis] >= cut).astype(int)
            kind = "spatial_region"
            prefix = "区域"
        else:
            scale = max(float(np.ptp(vertices, axis=0).max()), 1e-12)
            _, inverse = np.unique(np.round(vertices / scale, 6), axis=0, return_inverse=True)
            welded = inverse[faces]
            edges = np.concatenate((welded[:, [0, 1]], welded[:, [1, 2]], welded[:, [2, 0]]))
            graph = sparse.coo_matrix(
                (np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(int(inverse.max()) + 1,) * 2
            )
            _, labels = connected_components(graph, directed=False)
            group_ids = labels[welded[:, 0]]
            unique, counts = np.unique(group_ids, return_counts=True)
            large = unique[counts >= request["min_faces"]]
            if len(large) > request["max_groups"] - 1:
                raise ValueError("连通片过多，请增大最小三角面数量")
            group_ids = np.where(np.isin(group_ids, large), group_ids, -1)
            kind = "connected_component"
            prefix = "连通片"
        primitives = []
        unique_groups = np.unique(group_ids)
        if len(unique_groups) == 1:
            new_total += len(faces)
            result.append({"source_part": part["id"], "created_groups": 1, "triangles": len(faces)})
            continue
        for ordinal, identity in enumerate(unique_groups, 1):
            subset = faces[group_ids == identity]
            new_total += len(subset)
            new = copy.deepcopy(primitive)
            new["indices"] = append_indices(subset)
            new.setdefault("extras", {}).update(
                form_group_kind=kind,
                form_source_part=part["id"],
                form_part_name=(request.get("name") or part["name"] + " / " + prefix) + f" {ordinal}",
            )
            if request["operation"] == "face_group":
                new["extras"]["form_selection_role"] = "selected" if identity == 1 else "remainder"
                new["extras"]["form_part_name"] = (
                    (request.get("name") or "新部件") if identity == 1 else part["name"] + "（其余部分）"
                )
            else:
                new["extras"].pop("form_selection_role", None)
            primitives.append(new)
        replacements.setdefault(part["node"], {})[part["primitive"]] = primitives
        result.append({"source_part": part["id"], "created_groups": len(primitives), "triangles": len(faces)})
    if all(row["created_groups"] <= 1 for row in result):
        raise ValueError("当前条件没有分出多个区域；连体网格可使用区域分组或调整分界位置")
    for node_index, mapping in replacements.items():
        mesh = doc["meshes"][doc["nodes"][node_index]["mesh"]]
        import uuid

        node = doc["nodes"][node_index]
        old_ids = node.get("extras", {}).get("form_part_ids", {})
        ids = {}
        new_primitives = []
        for index, old in enumerate(mesh["primitives"]):
            for item in mapping.get(index, [old]):
                ids[str(len(new_primitives))] = (
                    ("part_" + uuid.uuid4().hex)
                    if index in mapping
                    else old_ids.get(str(index), f"node_{node_index}_primitive_{index}")
                )
                new_primitives.append(item)
        mesh["primitives"] = new_primitives
        node.setdefault("extras", {})["form_part_ids"] = ids
    assert triangle_total == new_total, "Grouping lost triangles"
    return {
        "operation": request["operation"],
        "groups": result,
        "triangles_preserved": triangle_total,
        "note": "Geometric grouping only; no semantic labels, no triangle cutting, no watertight physical part reconstruction.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    source = Path(args.input)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    doc, binary, extra = read_glb(source)
    set_part_ids(doc)
    original_positions = {
        index: accessor_array(doc, binary, index).tobytes()
        for index in {p["attributes"]["POSITION"] for mesh in doc["meshes"] for p in mesh["primitives"]}
    }
    from asset_operations import apply_operation

    evidence = apply_operation(doc, binary, request)
    unchanged = request["operation"] not in {
        "decimate",
        "optimize_mesh",
        "repair_geometry",
        "translate_parts",
        "complete_part",
        "reconstruct_parts",
    } or (request["operation"] == "repair_geometry" and request.get("repair_strength") == "cleanup")
    if unchanged and request["operation"] != "export_parts":
        for index, positions in original_positions.items():
            assert accessor_array(doc, binary, index).tobytes() == positions
    binary = compact_static(doc, binary)
    write_glb(output / "model.glb", doc, binary, extra)
    manifest = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256((output / "model.glb").read_bytes()).hexdigest(),
        "positions_unchanged": unchanged,
        "operation": evidence,
        "parts": parts_catalog(doc),
        "duration_seconds": round(time.monotonic() - started, 3),
        "appearance_review": "unreviewed",
        "scale_status": "inherited_unverified",
        "worker_revision": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"parts": len(manifest["parts"]), "seconds": manifest["duration_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
