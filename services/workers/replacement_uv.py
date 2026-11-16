# -*- coding: utf-8 -*-
"""Shared-density UV for new logical parts; preserves every world triangle."""

import numpy as np
from services.api.glb_document import parts_catalog, selected_primitives
from edit_asset import accessor_array, node_world_matrices
from asset_operations import append_array
from part_tools import reindex
from uv_quality import uv_diagnostics


def prepare_replacement_uv(doc, binary, group_ids):
    parts = parts_catalog(doc)
    ids = [p["id"] for p in parts if (p.get("logical_group_id") or p["id"]) in group_ids]
    entries = selected_primitives(doc, ids)
    worlds = node_world_matrices(doc)
    bounds = {}
    prepared = []
    for part, primitive in entries:
        vertices = accessor_array(doc, binary, primitive["attributes"]["POSITION"])
        faces = accessor_array(doc, binary, primitive["indices"]).reshape(-1, 3)
        world = (np.c_[vertices, np.ones(len(vertices))] @ worlds[part["node"]].T)[:, :3]
        used = np.unique(faces)
        key = part.get("logical_group_id") or part["id"]
        low, high = world[used].min(0), world[used].max(0)
        if key in bounds:
            bounds[key] = (np.minimum(bounds[key][0], low), np.maximum(bounds[key][1], high))
        else:
            bounds[key] = (low, high)
        prepared.append((part, primitive, vertices, faces, world, key))
    rows = []
    for part, primitive, vertices, faces, world, key in prepared:
        if "TEXCOORD_0" in primitive["attributes"]:
            rows.append({"part_id": part["id"], "status": "existing_uv_preserved"})
            continue
        low, high = bounds[key]
        scale = max(float((high - low).max()), 1e-12)
        triangles = world[faces]
        normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        axis = np.argmax(abs(normals), axis=1)
        chart = axis * 2 + (normals[np.arange(len(faces)), axis] < 0)
        unique, inverse = np.unique(np.c_[np.repeat(chart, 3), faces.ravel()], axis=0, return_inverse=True)
        mapping = unique[:, 1]
        newfaces = inverse.reshape(-1, 3)
        a = unique[:, 0] // 2
        u = (a + 1) % 3
        v = (a + 2) % 3
        row = np.arange(len(mapping))
        points = world[mapping]
        coords = np.c_[(points[row, u] - low[u]) / scale, (points[row, v] - low[v]) / scale]
        coords[unique[:, 0] % 2 == 1, 0] = 1 - coords[unique[:, 0] % 2 == 1, 0]
        uv = coords * 0.30 + np.c_[(unique[:, 0] % 3) / 3 + 0.015, (unique[:, 0] // 3) / 2 + 0.1]
        checks = uv_diagnostics(points, newfaces, uv)
        if checks["collapsed_geometry_area_fraction"] > 0.001:
            raise ValueError("新部件 UV 有较大塌缩，未发布材质候选")
        reindex(doc, binary, primitive, mapping, newfaces)
        primitive["attributes"]["TEXCOORD_0"] = append_array(doc, binary, uv, "VEC2")
        primitive["attributes"].pop("TANGENT", None)
        rows.append(
            {
                "part_id": part["id"],
                "status": "created",
                "method": "shared_logical_group_six_charts",
                "quality": checks,
                "positions_and_triangle_order_preserved": True,
            }
        )
    return {
        "parts": rows,
        "shared_density_within_logical_group": True,
        "seams_require_visual_review": True,
        "real_texture_scale_verified": False,
    }
