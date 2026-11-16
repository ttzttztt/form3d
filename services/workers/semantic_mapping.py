"""Calibrated mask lifting and instance association; never labels mesh fragments as new parts."""

import json
from pathlib import Path
import numpy as np
from PIL import Image


def project_visible(centers, view, tolerance=0.006):
    points = np.c_[centers, np.ones(len(centers))]
    clip = points @ np.asarray(view["clip_from_source"]).T
    ndc = clip[:, :3] / np.maximum(clip[:, 3, None], 1e-12)
    w, h = view["image_size"]
    x = np.floor((ndc[:, 0] + 1) * w / 2).astype(int)
    y = np.floor((1 - ndc[:, 1]) * h / 2).astype(int)
    valid = (clip[:, 3] > 0) & (abs(ndc[:, 0]) < 0.998) & (abs(ndc[:, 1]) < 0.998) & (abs(ndc[:, 2]) < 1)
    x = np.clip(x, 0, w - 1)
    y = np.clip(y, 0, h - 1)
    camera = points @ np.asarray(view["view_from_source"]).T
    distance = np.linalg.norm(camera[:, :3], axis=1)
    depth = np.asarray(Image.open(view["depth_path"]), dtype=float) / 65535 * view["depth_scale"]
    seen = depth[y, x]
    valid &= abs(distance - seen) < tolerance
    return x, y, valid, abs(distance - seen)


def overlap(a, b, area):
    inter = np.intersect1d(a, b, assume_unique=True)
    weight = area[inter].sum()
    return float(weight / max(area[a].sum() + area[b].sum() - weight, 1e-12)), float(
        weight / max(min(area[a].sum(), area[b].sum()), 1e-12)
    )


def associate_instances(candidates, area, diagonal):
    """Cross-view unions cannot combine two disjoint same-view instance observations."""
    clusters = [{i} for i in range(len(candidates))]
    owner = list(range(len(candidates)))
    edges = []
    conflicts = set()
    for i, a in enumerate(candidates):
        for j in range(i):
            b = candidates[j]
            if a["kind"] != b["kind"]:
                continue
            if np.linalg.norm(a["center"] - b["center"]) > diagonal * 0.4:
                continue
            iou, small = overlap(a["faces"], b["faces"], area)
            if a["view"] == b["view"] and iou < 0.08:
                conflicts.add((j, i))
            if (iou > 0.23 or small > 0.72) and (a["view"] != b["view"] or iou > 0.8):
                edges.append((iou + 0.2 * small, j, i))
    for score, i, j in sorted(edges, reverse=True):
        a, b = owner[i], owner[j]
        if a == b:
            continue
        if any(tuple(sorted((u, v))) in conflicts for u in clusters[a] for v in clusters[b]):
            continue
        clusters[a] |= clusters[b]
        for item in clusters[b]:
            owner[item] = a
        clusters[b] = set()
    return [sorted(c) for c in clusters if c]


def map_masks(folder, centers, normals, area, vertices, evidence=None):
    folder = Path(folder)
    data = json.loads((folder / "detections.json").read_text(encoding="utf-8"))
    views = json.loads((folder / "views.json").read_text(encoding="utf-8"))
    candidates = []
    visibility = []
    diagnostics = []
    source_area = area.sum()
    diagonal = np.linalg.norm(np.ptp(vertices, axis=0))
    ymin = vertices[:, 1].min()
    height = np.ptp(vertices[:, 1])
    normalized_y = (centers[:, 1] - ymin) / max(height, 1e-12)
    up = (normals[:, 1] > 0.7) & (normalized_y > 0.17) & (normalized_y < 0.67)
    histogram, bins = np.histogram(normalized_y[up], bins=48, range=(0, 1), weights=area[up])
    seat_height = float((bins[np.argmax(histogram)] + bins[np.argmax(histogram) + 1]) / 2) if up.any() else 0.5
    for view, record in zip(views, data["views"]):
        x, y, visible, error = project_visible(centers, {**view, "depth_path": folder / view["depth"]})
        visibility.append(visible)
        items = []
        diagnostics.append(
            {
                "view": view["index"],
                "visible_faces": int(visible.sum()),
                "median_depth_error_visible": float(np.median(error[visible])) if visible.any() else None,
            }
        )
        for mask in record["masks"]:
            values = np.asarray(Image.open(folder / mask["mask_file"])) > 127
            ids = np.flatnonzero(visible & values[y, x])
            weight = area[ids].sum()
            if len(ids) < 32 or weight < source_area * 0.0015:
                continue
            cloud = centers[ids]
            center = np.average(cloud, axis=0, weights=area[ids])
            extent = np.ptp(cloud, axis=0)
            if mask["kind"] == "pillow" and (extent[1] > height * 0.72 or weight > source_area * 0.4):
                continue
            if weight > source_area * 0.88:
                continue
            kind = mask["kind"]
            # Text grounding alone calls an upright back pillow a "seat cushion" too.
            # Use its observed height to resolve that conflict; keep the raw prompt in evidence.
            if (
                kind == "seat"
                and (center[1] - ymin) / max(height, 1e-12) > seat_height + 0.17
                and extent[1] > 0.16 * height
            ):
                kind = "pillow"
            if (
                kind == "pillow"
                and (center[1] - ymin) / max(height, 1e-12) < seat_height + 0.10
                and extent[1] < height * 0.20
            ):
                kind = "seat"
            quality = mask["mask_quality_prediction"] * mask["detector_score"]
            candidate = {
                "faces": ids,
                "kind": kind,
                "view": view["index"],
                "center": center,
                "weight": float(weight),
                "quality": float(quality),
                "mask_file": mask["mask_file"],
            }
            # Dense small masks inside a detected part are useful hypotheses; tiny wrinkles are not.
            if any(p["kind"] == candidate["kind"] and overlap(p["faces"], ids, area)[0] > 0.84 for p in items):
                continue
            items.append(candidate)
        items.sort(key=lambda c: c["quality"], reverse=True)
        candidates.extend(items[:18])
    if not candidates:
        raise ValueError("AI 没有得到可用的完整部件候选，原版本保留")
    clusters = associate_instances(candidates, area, diagonal)
    tracks = []
    for members in clusters:
        observations = [candidates[i] for i in members]
        seen = {c["view"] for c in observations}
        weight = max(c["weight"] for c in observations)
        if observations[0]["kind"] == "seat" and len(seen) < 2:
            continue
        if len(seen) < 2:
            continue
        if weight < source_area * 0.003:
            continue
        scores = np.zeros(len(centers), dtype=np.float32)
        support = np.zeros(len(centers), dtype=np.uint8)
        for vi in seen:
            local = np.zeros(len(centers), dtype=np.float32)
            for c in observations:
                if c["view"] == vi:
                    local[c["faces"]] = np.maximum(local[c["faces"]], c["quality"])
            scores += local
            support += local > 0
        scores /= np.maximum(np.sum(visibility, axis=0), 1)
        tracks.append(
            {
                "kind": observations[0]["kind"],
                "members": members,
                "views": sorted(seen),
                "scores": scores,
                "support": support,
                "quality": max(c["quality"] for c in observations),
            }
        )
    tracks.sort(key=lambda t: (len(t["views"]), t["quality"]), reverse=True)
    tracks = tracks[:24]
    if not tracks:
        raise ValueError("跨视角候选不稳定，原版本保留")
    score = np.stack([t["scores"] for t in tracks])
    best = score.argmax(0)
    strength = score.max(0)
    labels = np.where(strength > 0.055, best + 1, 0)
    pillows = [i for i, t in enumerate(tracks) if t["kind"] == "pillow"]
    if pillows:
        soft = score[pillows]
        which = soft.argmax(0)
        confident = soft.max(0) > 0.08
        labels[confident] = np.asarray(pillows)[which[confident]] + 1
    groups = []
    for ti, track in enumerate(tracks, 1):
        ids = np.flatnonzero(labels == ti)
        weight = area[ids].sum()
        if len(ids) < 32 or weight < source_area * 0.004:
            labels[ids] = 0
            continue
        cloud = centers[ids]
        center = np.average(cloud, axis=0, weights=area[ids])
        cov = ((cloud - center) * area[ids, None]).T @ (cloud - center) / weight
        eigen = np.linalg.eigvalsh(cov)[::-1]
        kind = track["kind"]
        shape = (
            "bolster"
            if kind == "pillow" and eigen[0] / max(eigen[1], 1e-12) > 3.5 and eigen[1] / max(eigen[2], 1e-12) < 2.2
            else kind
        )
        groups.append(
            {
                "label": ti,
                "kind": shape,
                "source_kind": kind,
                "views": track["views"],
                "observations": len(track["members"]),
                "area_fraction": float(weight / source_area),
                "center": center.tolist(),
                "bounds": [cloud.min(0).tolist(), cloud.max(0).tolist()],
                "pca_eigenvalues": eigen.tolist(),
                "quality_prediction": track["quality"],
            }
        )
    if not groups:
        raise ValueError("候选仅有细碎表面，未生成可用的整体部件")
    if evidence is not None:
        evidence.update(
            visible_views=np.sum(visibility, axis=0).astype(np.uint8),
            support_views=np.stack([t["support"] for t in tracks]),
            scores=score,
            raw_labels=labels.copy(),
        )
    diagnostics.append(
        {
            "candidate_masks": len(candidates),
            "instance_tracks": len(tracks),
            "retained_instances": len(groups),
            "source_faces": len(labels),
            "unassigned_faces": int((labels == 0).sum()),
        }
    )
    return labels, groups, diagnostics
