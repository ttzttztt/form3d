# -*- coding: utf-8 -*-
"""Conservative whole-instance propagation with explicit observation vetoes."""

import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra


def merge_observation_evidence(evidence, merges):
    """Opposite-side merges have disjoint view sets, so view counts can add."""
    for item in merges:
        a, b = item["from_label"] - 1, item["to_label"] - 1
        evidence["support_views"][b] = np.minimum(
            evidence["visible_views"], evidence["support_views"][b] + evidence["support_views"][a]
        )
        evidence["scores"][b] = np.minimum(1, evidence["scores"][b] + evidence["scores"][a])


def enforce_observation_veto(labels, groups, evidence):
    labels = labels.copy()
    removed = 0
    for group in groups:
        ids = np.flatnonzero(labels == group["label"])
        support = evidence["support_views"][group["label"] - 1, ids]
        visible = evidence["visible_views"][ids]
        veto = (visible >= 2) & (support * 2 < visible)
        labels[ids[veto]] = 0
        removed += int(veto.sum())
    return labels, removed


def refine_supported_regions(vertices, faces, centers, area, labels, groups, evidence):
    labels = labels.copy()
    raw = labels.copy()
    visible = np.asarray(evidence["visible_views"])
    support = np.asarray(evidence["support_views"])
    scores = np.asarray(evidence["scores"])
    if support.shape != scores.shape or support.shape[1] != len(faces) or len(visible) != len(faces):
        raise ValueError("多视角归属证据与源网格不匹配")
    mesh = trimesh.Trimesh(vertices, faces, process=False)
    mesh.merge_vertices(digits_vertex=8)
    adj = mesh.face_adjacency
    cosine = (mesh.face_normals[adj[:, 0]] * mesh.face_normals[adj[:, 1]]).sum(1)
    distance = np.linalg.norm(centers[adj[:, 0]] - centers[adj[:, 1]], axis=1) * (1 + 8 * np.maximum(0, 1 - cosine))
    graph = coo_matrix(
        (np.r_[distance, distance], (np.r_[adj[:, 0], adj[:, 1]], np.r_[adj[:, 1], adj[:, 0]])),
        shape=(len(faces), len(faces)),
    ).tocsr()
    diagonal = float(np.linalg.norm(np.ptp(vertices[faces.ravel()], axis=0)))
    removed = 0
    contradicted = 0
    anchors = np.zeros(len(faces), bool)
    retained = []
    for group in groups:
        label = group["label"]
        votes = support[label - 1]
        strength = scores[label - 1]
        ids = np.flatnonzero(labels == label)
        # A mask from one view cannot overrule two visible views excluding it.
        veto = (visible[ids] >= 2) & (votes[ids] * 2 < visible[ids])
        contradicted += int(veto.sum())
        labels[ids[veto]] = 0
        ids = ids[~veto]
        if not len(ids):
            continue
        strong = (votes >= 2) & (votes * 2 >= visible) & (strength >= 0.12)
        anchors |= strong & (labels == label)
        _, cc = connected_components(graph[ids][:, ids], directed=False)
        anchor_area = np.bincount(cc, weights=area[ids] * strong[ids])
        threshold = max(float(anchor_area.max()) * 0.015, float(area.sum()) * 0.00015)
        keep = anchor_area >= threshold
        drop = ids[~keep[cc]]
        removed += len(drop)
        labels[drop] = 0
        kept = ids[keep[cc]]
        if not len(kept):
            continue
        group = dict(group)
        group["bounds"] = [centers[kept].min(0).tolist(), centers[kept].max(0).tolist()]
        retained.append(group)
    seeds = np.flatnonzero(labels)
    if len(seeds):
        dist, _, nearest = dijkstra(graph, directed=False, indices=seeds, min_only=True, return_predecessors=True)
        empty = (labels == 0) & (nearest >= 0) & (dist < diagonal * 0.10)
        nearest_label = labels[np.maximum(nearest, 0)]
        for group in retained:
            label = group["label"]
            votes = support[label - 1]
            low, high = np.asarray(group["bounds"])
            spatial = np.all((centers >= low - diagonal * 0.025) & (centers <= high + diagonal * 0.025), axis=1)
            # Visible exclusions are evidence; a completely unseen surface is
            # merely unknown and can receive a short, recorded propagation.
            allowed = (visible == 0) | ((votes > 0) & (votes * 2 >= visible))
            chosen = empty & spatial & allowed & (nearest_label == label)
            labels[chosen] = label
    records = []
    for group in retained:
        label = group["label"]
        mask = labels == label
        votes = support[label - 1]
        weight = float(area[mask].sum())
        records.append(
            {
                "label": label,
                "area": weight,
                "direct_multiview_area": float(area[mask & (votes >= 2)].sum()),
                "propagated_area": float(area[mask & (raw != label)].sum()),
                "contradicted_visible_area": float(area[mask & (visible >= 2) & (votes * 2 < visible)].sum()),
                "faces": int(mask.sum()),
            }
        )
    return (
        labels,
        retained,
        {
            "method": "multiview_supported_bounded_geodesic",
            "unobserved_assignment": "short geodesic propagation is inferred, not a new observation",
            "max_geodesic_diagonal_ratio": 0.10,
            "visible_exclusion_veto": True,
            "contradicted_assignments_removed": contradicted,
            "unsupported_component_faces_removed": removed,
            "unassigned_after": int((labels == 0).sum()),
            "unassigned_area_fraction": float(area[labels == 0].sum() / area.sum()),
            "groups": records,
        },
    )
