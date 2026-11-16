"""Separate existing closed components without changing positions, UV or materials."""

import copy, uuid
import numpy as np, trimesh
from services.api.glb_document import selected_primitives
from furniture_parts import primitive_data, replace_primitives


def separate_solids(doc, binary, request):
    from asset_operations import append_array
    from complete_part import mesh_stats

    targets = selected_primitives(doc, request["part_ids"])
    vertices = []
    faces = []
    offset = 0
    lengths = []
    for part, p in targets:
        _, f, w, _, _, _ = primitive_data(doc, binary, part, p)
        used = np.unique(f)
        lookup = np.full(len(w), -1, dtype=int)
        lookup[used] = np.arange(len(used))
        vertices.append(w[used])
        faces.append(lookup[f] + offset)
        offset += len(used)
        lengths.append(len(f))
    source = trimesh.Trimesh(np.concatenate(vertices), np.concatenate(faces), process=False)
    source.merge_vertices(digits_vertex=8)
    components = trimesh.graph.connected_components(source.face_adjacency, nodes=np.arange(len(source.faces)))
    if not 2 <= len(components) <= 16:
        raise ValueError("没有 2～16 个稳定闭合连通体，请检查选中的部件")
    components = sorted(components, key=lambda indices: tuple(source.triangles_center[indices].mean(0)[[0, 2, 1]]))
    labels = np.full(len(source.faces), -1, dtype=int)
    groups = []
    for ordinal, indices in enumerate(components):
        m = trimesh.Trimesh(source.vertices, source.faces[indices], process=False)
        m.remove_unreferenced_vertices()
        stats = mesh_stats(m)
        if not stats["watertight"] or not stats["winding_consistent"] or stats["volume"] <= 0:
            raise ValueError("连通体中存在开放表面，未作为完整部件发布")
        group = "group_" + uuid.uuid4().hex
        groups.append({"id": group, "name": (request.get("name") or "独立部件") + f" {ordinal + 1}", **stats})
        labels[indices] = ordinal
    offset = 0
    replacements = {}
    for (part, p), length in zip(targets, lengths):
        _, f, _, _, _, _ = primitive_data(doc, binary, part, p)
        local = labels[offset : offset + length]
        offset += length
        created = []
        for key in np.unique(local):
            primitive = copy.deepcopy(p)
            subset = f[local == key]
            primitive["indices"] = append_array(doc, binary, subset.ravel(), "SCALAR", 5125, 34963)
            g = groups[int(key)]
            primitive.setdefault("extras", {}).update(
                form_logical_group_id=g["id"],
                form_part_name=g["name"],
                form_selection_role="selected",
                form_group_kind="existing_closed_component",
                form_proposal_status="review_required",
            )
            created.append((primitive, "part_" + uuid.uuid4().hex))
        replacements.setdefault(part["node"], {})[part["primitive"]] = created
    replace_primitives(doc, replacements)
    return {
        "operation": "separate_solids",
        "part_group_ids": [g["id"] for g in groups],
        "components": groups,
        "positions_unchanged": True,
        "new_inferred_faces": 0,
        "materials_and_attributes_preserved": True,
        "triangles_preserved": len(source.faces),
    }
