# -*- coding: utf-8 -*-
"""Uniform-scale, rigid registration to reliable observed surfaces, not true pose recovery."""

import itertools
import numpy as np
import trimesh
from scipy.spatial import cKDTree


def surface_samples(mesh, count, seed=20261113):
    rng = np.random.default_rng(seed)
    ids = rng.choice(len(mesh.faces), count, p=mesh.area_faces / mesh.area)
    b = rng.random((count, 2))
    r = np.sqrt(b[:, 0])
    weights = np.c_[1 - r, r * (1 - b[:, 1]), r * b[:, 1]]
    return (mesh.triangles[ids] * weights[:, :, None]).sum(1), mesh.face_normals[ids]


def basis(points):
    center = points.mean(0)
    _, vectors = np.linalg.eigh(np.cov((points - center).T))
    vectors = vectors[:, ::-1]
    if np.linalg.det(vectors) < 0:
        vectors[:, -1] *= -1
    projected = (points - center) @ vectors
    span = np.quantile(projected, 0.98, axis=0) - np.quantile(projected, 0.02, axis=0)
    return center, vectors, np.maximum(span, 1e-8)


def rigid_delta(a, b):
    ca = a.mean(0)
    cb = b.mean(0)
    u, _, v = np.linalg.svd((a - ca).T @ (b - cb))
    rot = v.T @ u.T
    if np.linalg.det(rot) < 0:
        v[-1] *= -1
        rot = v.T @ u.T
    return rot, cb - rot @ ca


def observed_pose_surface(target, kind, view_direction=None):
    """Use a broad visible face for open pillows, not their attachment fringe.

    This is a geometric pose hypothesis, not semantic boundary verification.
    The full original group is retained for replacement and visual review.
    """
    evidence = {"method": "whole_group", "source_area_fraction": 1.0}
    if kind != "pillow" or (target.is_watertight and view_direction is None):
        return target, evidence
    _, directions = surface_samples(target, 256)
    support = np.array([target.area_faces[target.face_normals @ d > 0.72].sum() for d in directions])
    if view_direction is not None:
        support *= np.maximum(0, directions @ view_direction)
    direction = directions[int(support.argmax())]
    mask = target.face_normals @ direction > 0.72
    surface = target.submesh([mask], append=True, repair=False)
    components = sorted(surface.split(only_watertight=False), key=lambda m: m.area, reverse=True)
    if not components:
        raise ValueError("源靠枕没有稳定的可见表面，不能估计放置位置")
    surface = components[0]
    fraction = float(surface.area / target.area)
    if fraction < 0.30:
        raise ValueError("源靠枕表面过于碎散，请先修正整体部件范围")
    evidence = {
        "method": "dominant_connected_visible_normal_patch",
        "source_area_fraction": fraction,
        "normal_cosine_threshold": 0.72,
        "thickness_not_observed": True,
        "semantic_boundary_verified": False,
        "requires_full_shape_review": True,
    }
    return surface, evidence


def fit_part(candidate, target, kind="pillow", bottom=None):
    for mesh in (candidate, target):
        if not len(mesh.faces) or not np.isfinite(mesh.vertices).all() or not np.isfinite(mesh.area) or mesh.area <= 0:
            raise ValueError("部件表面为空或坐标无效，未替换原模型")
    if kind == "cushion":
        from cushion_registration import fit_cushion

        return fit_cushion(candidate, target, bottom)
    pose_surface, pose_evidence = observed_pose_surface(target, kind)
    source_points, source_normals = surface_samples(candidate, 14000)
    target_points, target_normals = surface_samples(pose_surface, 4000)
    # Ignore sparse attachment fragments in the initial target estimate. The
    # complete target is still measured after registration and shown in preview.
    center, axes, span = basis(target_points)
    projected = (target_points - center) @ axes
    lo, hi = np.quantile(projected, [0.035, 0.965], axis=0)
    core = np.all((projected >= lo) & (projected <= hi), axis=1)
    target_points = target_points[core]
    target_normals = target_normals[core]
    tc, tb, ts = basis(target_points)
    sc, sb, ss = basis(source_points)
    pre = np.eye(4)
    candidate_vertices = candidate.vertices.copy()
    thickness = None
    # An open assignment can contain only the visible front and unrelated
    # boundary scraps. Its PCA depth is not an observed pillow thickness.
    if kind == "pillow":
        from observed_thickness import paired_thickness

        measured = paired_thickness(target, pose_surface) if not target.is_watertight else None
        if measured:
            pose_evidence = {
                **pose_evidence,
                "thickness_not_observed": False,
                "thickness_is_source_mesh_estimate": True,
            }
        desired = measured["core_thickness_source_units"] if measured else ts[2] if target.is_watertight else None
        planar_scale = float(np.median(ts[:2] / ss[:2]))
        factor = float(desired / (ss[2] * planar_scale)) if desired is not None else 1.0
        if not 0.5 <= factor <= 5.0:
            raise ValueError("生成部件的厚度与源表面差异过大，未自动拉伸替换")
        if factor < 0.67 or factor > 1.5:
            stretch = sb @ np.diag([1.0, 1.0, factor]) @ sb.T
            offset = sc - stretch @ sc
            pre[:3, :3] = stretch
            pre[:3, 3] = offset
            source_points = source_points @ stretch.T + offset
            source_normals = source_normals @ np.linalg.inv(stretch)
            source_normals /= np.maximum(np.linalg.norm(source_normals, axis=1, keepdims=True), 1e-12)
            candidate_vertices = candidate_vertices @ stretch.T + offset
            sc, sb, ss = basis(source_points)
            thickness = {
                **(measured or {"method": "observed_core_thickness_constraint"}),
                "normal_axis_scale": factor,
                "not_real_dimension_measurement": True,
            }
    tree = cKDTree(source_points)
    results = []
    for permutation in itertools.permutations(range(3)):
        # A broad pillow face must stay broad after fitting. Matching a thin
        # edge to a face can otherwise inflate the candidate to cover a plane.
        if kind == "pillow" and permutation[2] != 2:
            continue
        for signs in itertools.product((-1, 1), repeat=3):
            rot = tb @ np.diag(signs) @ sb[:, permutation].T
            if np.linalg.det(rot) < 0:
                continue
            scale = float(np.median(ts[:2] / ss[list(permutation)[:2]]))
            translation = tc - scale * (rot @ sc)
            for _ in range(12):
                local = (target_points - translation) @ rot / scale
                distance, near = tree.query(local, k=4, workers=4)
                normals = source_normals[near] @ rot.T
                alignment = np.einsum("nki,ni->nk", normals, target_normals)
                cost = np.where(alignment > 0, distance, distance + ts.max())
                chosen = np.argmin(cost, axis=1)
                ids = near[np.arange(len(near)), chosen]
                matched = source_points[ids] @ rot.T * scale + translation
                error = np.linalg.norm(matched - target_points, axis=1)
                keep = error <= np.quantile(error, 0.80)
                delta, shift = rigid_delta(matched[keep], target_points[keep])
                rot = delta @ rot
                translation = delta @ translation + shift
            transformed = source_points @ rot.T * scale + translation
            if kind == "pillow":
                if abs((rot @ sb[:, 2]) @ tb[:, 2]) < 0.92:
                    continue
                projected = (transformed - tc) @ tb
                fitted_span = np.quantile(projected, 0.98, axis=0) - np.quantile(projected, 0.02, axis=0)
                if np.any(fitted_span[:2] / ts[:2] > 1.4) or np.any(fitted_span[:2] / ts[:2] < 0.7):
                    continue
            if kind == "cushion":
                # Cushion installation is horizontal. Reject sideways solutions.
                covariance = np.cov(transformed.T)
                _, vectors = np.linalg.eigh(covariance)
                if abs(vectors[:, 0] @ [0, 1, 0]) < 0.80:
                    continue
                if bottom is not None:
                    translation[1] += bottom - float((candidate_vertices @ rot.T * scale + translation)[:, 1].min())
                    transformed = source_points @ rot.T * scale + translation
            d = cKDTree(transformed).query(target_points, workers=4)[0]
            score = float(np.quantile(d, 0.85))
            results.append((score, scale, rot.copy(), translation.copy()))
    if not results:
        raise ValueError("没有找到合理的部件朝向，未替换原模型")
    score, scale, rot, translation = min(results, key=lambda x: x[0])
    vertices = candidate_vertices @ rot.T * scale + translation
    aligned = trimesh.Trimesh(vertices, candidate.faces, process=False)
    matrix = np.eye(4)
    matrix[:3, :3] = rot * scale
    matrix[:3, 3] = translation
    matrix = matrix @ pre
    diag = max(float(np.linalg.norm(target.extents)), 1e-12)
    return aligned, {
        "method": "PCA_initializations_uniform_scale_trimmed_one_sided_rigid_ICP",
        "candidate_to_source_world": matrix.tolist(),
        "uniform_scale": scale,
        "thickness_constraint": thickness,
        "thickness_constraint_skipped_for_open_source": kind == "pillow"
        and not target.is_watertight
        and thickness is None,
        "pose_surface": pose_evidence,
        "sampled_core_distance_p85_diagonal_ratio": score / diag,
        "target_core_samples": len(target_points),
        "pose_is_estimated": True,
        "real_scale_verified": False,
    }


def register_part(candidate, target, kind="pillow", bottom=None):
    aligned, placement = fit_part(candidate, target, kind, bottom)
    if placement["sampled_core_distance_p85_diagonal_ratio"] > 0.06:
        raise ValueError("新部件无法贴合可靠源表面，未自动装回")
    return aligned, placement
