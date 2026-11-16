"""Volume-guided surface partition with explicitly inferred planar interfaces.

No unseen product structure is recovered. Source surfaces are clipped, and both
sides receive the same estimated interface with opposite winding.
"""

import numpy as np
import trimesh
from scipy.spatial import cKDTree


def stitch_collinear_boundaries(mesh, labels, tolerance):
    """Resolve T junctions by subdividing edges, without moving their surfaces."""
    labels = np.asarray(labels)
    split_count = 0
    for _ in range(4):
        edges = mesh.edges_sorted
        unique, first, counts = np.unique(edges, axis=0, return_index=True, return_counts=True)
        boundary = unique[counts == 1]
        if not len(boundary):
            break
        candidates = np.unique(boundary)
        tree = cKDTree(mesh.vertices[candidates])
        owners = mesh.edges_face[first[counts == 1]]
        replacements = {}
        for (a, b), owner in zip(boundary, owners):
            start, end = mesh.vertices[[a, b]]
            delta = end - start
            length = np.linalg.norm(delta)
            if length <= tolerance:
                continue
            ids = candidates[tree.query_ball_point((start + end) / 2, length / 2 + tolerance)]
            position = (mesh.vertices[ids] - start) @ delta / (length * length)
            distance = np.linalg.norm(mesh.vertices[ids] - (start + position[:, None] * delta), axis=1)
            valid = (position > tolerance / length) & (position < 1 - tolerance / length) & (distance < tolerance)
            ids = ids[valid][np.argsort(position[valid])]
            ids = ids[~np.isin(ids, mesh.faces[owner])]
            if not len(ids):
                continue
            pieces = replacements.setdefault(int(owner), [mesh.faces[owner]])
            index = next(i for i, piece in enumerate(pieces) if a in piece and b in piece)
            face = pieces.pop(index)
            edge = next(i for i in range(3) if {int(face[i]), int(face[(i + 1) % 3])} == {int(a), int(b)})
            if face[edge] != a:
                ids = ids[::-1]
            chain = [face[edge], *ids, face[(edge + 1) % 3]]
            opposite = face[(edge + 2) % 3]
            pieces.extend([[chain[i], chain[i + 1], opposite] for i in range(len(chain) - 1)])
            split_count += len(ids)
        if not replacements:
            break
        faces = []
        new_labels = []
        for i, face in enumerate(mesh.faces):
            group = replacements.get(i, [face])
            faces.extend(group)
            new_labels.extend([labels[i]] * len(group))
        mesh = trimesh.Trimesh(mesh.vertices, np.asarray(faces), process=False)
        labels = np.asarray(new_labels)
    return mesh, labels, split_count


def clean_labelled(mesh, labels):
    f = mesh.faces
    keep = (f[:, 0] != f[:, 1]) & (f[:, 0] != f[:, 2]) & (f[:, 1] != f[:, 2])
    labels = np.asarray(labels)[keep]
    mesh.update_faces(keep)
    unique = mesh.unique_faces()
    labels = labels[unique]
    mesh.update_faces(unique)
    return mesh, labels


def prepare_mesh(mesh, force_float32=True):
    """Weld float32 positions and discard only index-collapsed/duplicate faces."""
    mesh = trimesh.Trimesh(
        np.asarray(mesh.vertices, dtype=np.float32 if force_float32 else np.float64), mesh.faces, process=False
    )
    mesh.merge_vertices(digits_vertex=8)
    f = mesh.faces
    keep = (f[:, 0] != f[:, 1]) & (f[:, 0] != f[:, 2]) & (f[:, 1] != f[:, 2])
    removed = int((~keep).sum())
    mesh.update_faces(keep)
    unique = mesh.unique_faces()
    removed += int((~unique).sum())
    mesh.update_faces(unique)
    mesh.remove_unreferenced_vertices()
    return mesh, removed


def partition_box(source, bounds, extra_planes=()):
    bounds = np.asarray(bounds, dtype=float)
    if bounds.shape != (2, 3) or not np.isfinite(bounds).all() or np.any(bounds[1] <= bounds[0]):
        raise ValueError("完整部件范围无效")
    source, removed = prepare_mesh(source)
    diagonal = max(float(np.linalg.norm(source.extents)), 1e-9)
    if len(source.faces) > 1600000:
        raise ValueError("完整部件处理最多支持 160 万面，请先减面")
    origins = []
    normals = []
    for axis in range(3):
        for side in (0, 1):
            normals.append(np.eye(3)[axis] * (1 if side == 0 else -1))
            origins.append(np.eye(3)[axis] * bounds[side, axis])
    for origin, normal in extra_planes:
        origins.append(np.asarray(origin, dtype=float))
        normals.append(np.asarray(normal, dtype=float))
    active = []
    for i, (o, n) in enumerate(zip(origins, normals)):
        dots = (source.vertices - o) @ n
        if float(dots.max()) < -diagonal * 1e-9:
            raise ValueError("范围没有包含源模型，请重新检查位置")
        if float(dots.min()) < -diagonal * 1e-9 and float(dots.max()) > diagonal * 1e-9:
            active.append(i)
    origins = [origins[i] for i in active]
    normals = [normals[i] for i in active]
    if not origins:
        raise ValueError("范围没有切开源网格，无需重建")
    inside = source
    outside = []
    for o, n in zip(origins, normals):
        outside.append(trimesh.intersections.slice_mesh_plane(inside, -n, o, cap=False))
        inside = trimesh.intersections.slice_mesh_plane(inside, n, o, cap=False)
        if not len(inside.faces):
            raise ValueError("范围没有包含可用表面，请重新检查正面、侧面与底面")
    solid = trimesh.intersections.slice_mesh_plane(
        source, np.asarray(normals), np.asarray(origins), cap=True, engine="earcut"
    )
    cap = np.zeros(len(solid.faces), dtype=bool)
    for o, n in zip(origins, normals):
        cap |= np.all(abs((solid.vertices[solid.faces] - o) @ n) < diagonal * 1e-8, axis=1)
    # A plane coinciding with an existing surface cannot be claimed as a new cap.
    observed_planes = np.zeros(len(inside.faces), bool)
    for o, n in zip(origins, normals):
        observed_planes |= np.all(abs((inside.vertices[inside.faces] - o) @ n) < diagonal * 1e-8, axis=1)
    if observed_planes.any():
        raise ValueError("范围边界恰好与原表面重合，请把边界稍微向外移动")
    if not cap.any():
        raise ValueError("此范围没有需要重建的切口，请使用已有部件")
    # Validate the float32 coordinate precision that GLB will store.
    solid.vertices = np.asarray(solid.vertices, dtype=np.float32)
    solid.merge_vertices(digits_vertex=8)
    solid, cap = clean_labelled(solid, cap)
    solid, cap, seat_stitches = stitch_collinear_boundaries(solid, cap, diagonal * 1e-7)
    inverse = trimesh.Trimesh(solid.vertices, solid.faces[cap][:, ::-1], process=False)
    remainder = trimesh.util.concatenate(outside + [inverse])
    remainder.vertices = np.asarray(remainder.vertices, dtype=np.float32)
    remainder.merge_vertices(digits_vertex=8)
    rest_labels = np.r_[
        np.zeros(sum(len(m.faces) for m in outside), dtype=bool), np.ones(len(inverse.faces), dtype=bool)
    ]
    remainder, rest_labels = clean_labelled(remainder, rest_labels)
    remainder, rest_labels, rest_stitches = stitch_collinear_boundaries(remainder, rest_labels, diagonal * 1e-7)
    area_error = float(abs(inside.area + sum(m.area for m in outside) - source.area) / max(source.area, 1e-15))
    if area_error > 1e-6:
        raise ValueError("分割未保留原表面积，原版本保留")
    return (
        source,
        solid,
        cap,
        remainder,
        rest_labels,
        {
            "collapsed_or_duplicate_source_faces_removed": removed,
            "t_junction_edge_splits": seat_stitches + rest_stitches,
            "source_surface_area_relative_error": area_error,
            "bounds_world": bounds.tolist(),
            "cut_planes": len(origins),
            "inferred_interfaces": "planar volume cut on both sides, not recovered product structure",
        },
    )
