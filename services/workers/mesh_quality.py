"""Measured geometry diagnostics and bounded, optional repair. No hole invention."""

import numpy as np
from scipy import sparse
from services.api.glb_document import parts_catalog, selected_primitives
from furniture_parts import primitive_data


def geometry_stats(v, f):
    import trimesh

    triangle = v[f]
    areas = np.linalg.norm(np.cross(triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0]), axis=1) / 2
    scale = max(float(np.ptp(v[f.ravel()], axis=0).max()), 1e-12)
    degenerate = areas < scale * scale * 1e-12
    # Only same-winding duplicates. Opposite faces may be an intentional sheet.
    unique_vertices, inverse = np.unique(np.round(v / scale, 7), axis=0, return_inverse=True)
    welded = inverse[f]
    minimum = np.argmin(welded, axis=1)
    canonical = np.take_along_axis(welded, (minimum[:, None] + np.arange(3)) % 3, axis=1)
    _, first = np.unique(canonical, axis=0, return_index=True)
    duplicate = np.ones(len(f), dtype=bool)
    duplicate[first] = False
    mesh = trimesh.Trimesh(v, f, process=False)
    mesh.merge_vertices()
    edges = mesh.edges_sorted
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return {
        "triangles": len(f),
        "degenerate_faces": int(degenerate.sum()),
        "duplicate_faces": int(duplicate.sum()),
        "boundary_edges": int((counts == 1).sum()),
        "nonmanifold_edges": int((counts > 2).sum()),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
    }, degenerate | duplicate


def inspect_document(doc, binary):
    all_vertices = []
    all_faces = []
    offset = 0
    rows = []
    for part in parts_catalog(doc):
        p = doc["meshes"][doc["nodes"][part["node"]]["mesh"]]["primitives"][part["primitive"]]
        _, f, w, _, _, _ = primitive_data(doc, binary, part, p)
        used = np.unique(f)
        lookup = np.full(len(w), -1, dtype=np.int64)
        lookup[used] = np.arange(len(used))
        all_vertices.append(w[used])
        all_faces.append(lookup[f] + offset)
        offset += len(used)
        stats, _ = geometry_stats(w[used], lookup[f])
        rows.append({"part_id": part["id"], **stats})
    combined, _ = geometry_stats(np.concatenate(all_vertices), np.concatenate(all_faces))
    return {
        "whole_model": combined,
        "mesh_primitives": rows,
        "limits": [
            "Boundary edges can be intentional openings; no automatic hole filling.",
            "This does not measure resemblance to the reference photo.",
            "Part boundaries are evaluated again on the combined model, not counted as damage.",
        ],
    }


def repair_geometry(doc, binary, request):
    from asset_operations import append_array

    evidence = []
    for part, p in selected_primitives(doc, request.get("part_ids", [])):
        v, f, _, _, _, _ = primitive_data(doc, binary, part, p)
        before, bad = geometry_stats(v, f)
        kept = f[~bad]
        if not len(kept):
            raise ValueError("没有可保留的有效三角面，原版本保留")
        cleanup_stats, _ = geometry_stats(v, kept)
        retained_bad_faces = 0
        if (
            cleanup_stats["boundary_edges"] > before["boundary_edges"]
            or cleanup_stats["nonmanifold_edges"] > before["nonmanifold_edges"]
            or (before["watertight"] and not cleanup_stats["watertight"])
        ):
            # A tiny/collinear face can still close a valid surface. Removing it
            # would require a topology repair that this conservative tool cannot prove.
            kept = f
            retained_bad_faces = int(bad.sum())
        moved = v.astype(float).copy()
        diagonal = max(float(np.linalg.norm(np.ptp(v[np.unique(kept)], axis=0))), 1e-12)
        energy_before = energy_after = 0.0
        maximum = 0.0
        if request.get("repair_strength") == "gentle":
            if set(p["attributes"]) - {"POSITION", "NORMAL", "COLOR_0"}:
                raise ValueError("带 UV 或切线的部件暂只支持清理重复/退化面，以免破坏接缝")
            # Preserve every region boundary and sharp crease.
            edges = np.concatenate((kept[:, [0, 1]], kept[:, [1, 2]], kept[:, [2, 0]]))
            edges.sort(1)
            owners = np.tile(np.arange(len(kept)), 3)
            order = np.lexsort((edges[:, 1], edges[:, 0]))
            sorted_edges = edges[order]
            sorted_owners = owners[order]
            unique, starts, counts = np.unique(sorted_edges, axis=0, return_index=True, return_counts=True)
            locked = np.zeros(len(v), dtype=bool)
            locked[np.unique(unique[counts != 2])] = True
            normals = np.cross(v[kept[:, 1]] - v[kept[:, 0]], v[kept[:, 2]] - v[kept[:, 0]])
            normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
            pairs = np.flatnonzero(counts == 2)
            first = sorted_owners[starts[pairs]]
            second = sorted_owners[starts[pairs] + 1]
            sharp = np.sum(normals[first] * normals[second], axis=1) < np.cos(np.deg2rad(42))
            locked[np.unique(unique[pairs[sharp]])] = True
            graph = sparse.csr_matrix(
                (np.ones(len(unique) * 2), (np.r_[unique[:, 0], unique[:, 1]], np.r_[unique[:, 1], unique[:, 0]])),
                shape=(len(v), len(v)),
            )
            degree = np.asarray(graph.sum(1)).ravel()
            free = (degree > 0) & ~locked

            def laplace(points):
                return graph @ points / np.maximum(degree[:, None], 1) - points

            energy_before = float(np.mean(np.linalg.norm(laplace(moved)[free], axis=1))) if free.any() else 0.0
            for _ in range(3):
                for amount in (0.35, -0.36):
                    moved[free] += amount * laplace(moved)[free]
            delta = moved - v
            distance = np.linalg.norm(delta, axis=1)
            factor = np.minimum(1, diagonal * 0.002 / np.maximum(distance, 1e-15))
            moved = v + delta * factor[:, None]
            maximum = float(np.max(np.linalg.norm(moved - v, axis=1)))
            energy_after = float(np.mean(np.linalg.norm(laplace(moved)[free], axis=1))) if free.any() else 0.0
            if energy_before > 0 and energy_after > energy_before * 1.02:
                raise ValueError("平滑没有降低当前局部噪声指标，未发布结果")
            p["attributes"]["POSITION"] = append_array(doc, binary, moved, "VEC3")
            new_normals = np.zeros_like(moved)
            face_normals = np.cross(moved[kept[:, 1]] - moved[kept[:, 0]], moved[kept[:, 2]] - moved[kept[:, 0]])
            for k in range(3):
                np.add.at(new_normals, kept[:, k], face_normals)
            lengths = np.linalg.norm(new_normals, axis=1, keepdims=True)
            new_normals /= np.maximum(lengths, 1e-12)
            new_normals[lengths[:, 0] < 1e-12] = [0, 1, 0]
            p["attributes"]["NORMAL"] = append_array(doc, binary, new_normals, "VEC3")
        p["indices"] = append_array(doc, binary, kept.astype("<u4").ravel(), "SCALAR", 5125, 34963)
        after, _ = geometry_stats(moved, kept)
        if after["nonmanifold_edges"] > before["nonmanifold_edges"]:
            raise ValueError("修复增加了非流形边，未发布结果")
        if after["boundary_edges"] > before["boundary_edges"] or (before["watertight"] and not after["watertight"]):
            raise ValueError("修复会增加开口或破坏闭合性，未发布结果")
        if after["degenerate_faces"] > before["degenerate_faces"]:
            raise ValueError("修复增加了退化面，未发布结果")
        evidence.append(
            {
                "part_id": part["id"],
                "before": before,
                "after": after,
                "max_displacement_ratio": maximum / diagonal,
                "laplacian_mean_before": energy_before,
                "laplacian_mean_after": energy_after,
                "positions_changed": bool(maximum),
                "locked_boundaries": True,
                "retained_bad_faces_to_preserve_topology": retained_bad_faces,
            }
        )
    if not any(p["positions_changed"] or p["before"]["triangles"] != p["after"]["triangles"] for p in evidence):
        raise ValueError("没有需要清理的坏面或可安全平滑的位置，无需创建修复版本")
    return {
        "operation": "repair_geometry",
        "strength": request.get("repair_strength"),
        "parts": evidence,
        "note": "Bounded mesh cleanup, not hidden structure reconstruction or proof of photo fidelity. No hole filling.",
    }
