"""Split a generated whole-furniture mesh into parts using the photo's part masks.

    segment_shape_by_photo.py --mesh model.glb --plan PLAN_FOLDER --output OUT

1. Fit a camera so the mesh silhouette matches the photo silhouette (photo_part_evidence.fit_camera).
2. Rasterise face ids at photo resolution; every visible face takes the photo part whose mask covers
   most of its pixels (pixels inside the furniture but outside every part mask mean "body").
3. Hidden faces take the label of the nearest labelled face along the surface, where crossing a sharp
   edge costs more than walking across a smooth one, so labels stop at creases between boards.
4. Small islands are merged into their neighbours.

Writes segmented.glb (one mesh per part, named by plan part id), segmentation.json (camera, per-part
visible/hidden face counts and photo IoU). Category-independent: no furniture rules are used.
Hidden-face labels are inferred, and recorded as such.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import trimesh
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services" / "workers")]

LABEL_FACES = 20000  # faces kept for labelling; HoloPart only needs part surface samples
CREASE_COST = 8.0  # extra cost for crossing a 90-degree edge, relative to walking one edge length
MIN_ISLAND = 0.004  # islands smaller than this fraction of all faces are merged into a neighbour
CREASE_DEGREES = 30.0  # edges sharper than this bound geometric regions
SPLIT_SHARE = 0.1  # a region keeps per-face labels when its second label has this share of votes
GROOVE_DEGREES = 15.0  # neighbour pull falls off with the angle between faces
SMOOTH_ROUNDS = 12
DATA_WEIGHT = 1.5  # photo evidence vs. neighbour agreement (3 neighbours per face)
SEAM_DEGREES = float(os.getenv("IMG3D_SEAM_DEGREES", "20"))  # a groove/crease within two faces of the border
SMOOTH_SEAM = float(os.getenv("IMG3D_SMOOTH_SEAM", "0.3"))  # borders with fewer sharp edges than this merge
MIN_SEAM_EDGES = 6  # parts touching along fewer edges are left alone
BODY = "__body__"


def face_ids(mesh, matrix, size):
    """Per-pixel visible face index (-1 = background), perspective-correct depth test."""
    from photo_part_evidence import project

    width, height = size
    pixels, depth = project(mesh.vertices, matrix)
    zbuffer = np.full((height, width), np.inf)
    ids = np.full((height, width), -1, np.int32)
    for number, face in enumerate(mesh.faces):
        z = depth[face]
        if np.any(z <= 0):
            continue
        a, b, c = pixels[face]
        x0, y0 = np.maximum(0, np.floor(np.min([a, b, c], 0))).astype(int)
        x1, y1 = np.minimum([width - 1, height - 1], np.ceil(np.max([a, b, c], 0))).astype(int)
        if x1 < x0 or y1 < y0:
            continue
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-10:
            continue
        yy, xx = np.mgrid[y0 : y1 + 1, x0 : x1 + 1] + 0.5
        w0 = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / den
        w1 = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-8) & (w1 >= -1e-8) & (w2 >= -1e-8)
        inverse = w0 / z[0] + w1 / z[1] + w2 / z[2]
        local = np.where(inverse > 0, 1 / np.maximum(inverse, 1e-20), np.inf)
        buffer = zbuffer[y0 : y1 + 1, x0 : x1 + 1]
        visible = inside & (local < buffer)
        buffer[visible] = local[visible]
        ids[y0 : y1 + 1, x0 : x1 + 1][visible] = number
    return ids


def surface_graph(mesh):
    """Face adjacency graph; edge cost = centroid distance x (1 + crease penalty)."""
    pairs = mesh.face_adjacency
    angles = mesh.face_adjacency_angles  # 0 = coplanar
    centres = mesh.triangles_center
    length = np.linalg.norm(centres[pairs[:, 0]] - centres[pairs[:, 1]], axis=1)
    cost = length * (1 + CREASE_COST * (angles / (np.pi / 2)) ** 2) + 1e-9
    n = len(mesh.faces)
    graph = coo_matrix((np.r_[cost, cost], (np.r_[pairs[:, 0], pairs[:, 1]], np.r_[pairs[:, 1], pairs[:, 0]])), (n, n))
    return graph.tocsr()


def label_faces(mesh, ids, part_masks, whole):
    """Visible faces from the photo, hidden ones by surface propagation. Returns (labels, visible)."""
    names = list(part_masks) + [BODY]
    # Pixel owner: the smallest covering part mask (the more specific part wins), else body.
    owner = np.full(ids.shape, -1, np.int32)
    owner[whole] = len(names) - 1
    for k in sorted(range(len(part_masks)), key=lambda k: -part_masks[names[k]].sum()):
        owner[part_masks[names[k]]] = k
    seen = (ids >= 0) & (owner >= 0)
    votes = np.zeros((len(mesh.faces), len(names)))
    np.add.at(votes, (ids[seen], owner[seen]), 1)
    visible = votes.sum(1) > 0
    labels = np.where(visible, votes.argmax(1), -1)
    graph = surface_graph(mesh)
    sources = np.flatnonzero(visible)
    if len(sources) and (~visible).any():
        _, _, nearest = dijkstra(graph, indices=sources, min_only=True, return_predecessors=True)
        hidden = ~visible & (nearest >= 0)
        labels[hidden] = labels[nearest[hidden]]
    labels[labels < 0] = len(names) - 1
    # Snap to geometry: regions bounded by creases take their majority label, unless the photo
    # clearly splits the region (e.g. a flush drawer front with no groove), then faces keep theirs.
    # Generated meshes have rounded edges, so neighbour angles never form a crease. Group faces
    # instead by the nearest of 26 directions (box faces, edges, corners): flat panels separate,
    # bevels become small regions that the island pass below absorbs.
    directions = np.array([d for d in np.ndindex(3, 3, 3) if d != (1, 1, 1)], float) - 1
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    facing = np.argmax(mesh.face_normals @ directions.T, axis=1)
    pairs = mesh.face_adjacency
    smooth = facing[pairs[:, 0]] == facing[pairs[:, 1]]
    n = len(labels)
    count, region = connected_components(
        coo_matrix((np.ones(smooth.sum()), (pairs[smooth, 0], pairs[smooth, 1])), (n, n)), directed=False
    )
    for r in range(count):
        members = region == r
        tally = np.bincount(labels[members], weights=np.maximum(votes[members].sum(1), 0.05), minlength=len(names))
        order = np.argsort(-tally)
        if len(order) > 1 and tally[order[1]] > SPLIT_SHARE * tally.sum():
            continue
        labels[members] = order[0]
    # Boundary smoothing (iterated conditional modes): a face keeps photo evidence but follows its
    # neighbours, and neighbours across a groove or edge pull less, so borders settle into grooves.
    angles = mesh.face_adjacency_angles
    weight = np.exp(-((angles / np.radians(GROOVE_DEGREES)) ** 2))
    evidence = votes / np.maximum(votes.sum(1, keepdims=True), 1)
    for _ in range(SMOOTH_ROUNDS):
        score = DATA_WEIGHT * evidence.copy()
        np.add.at(score, (pairs[:, 0], labels[pairs[:, 1]]), weight)
        np.add.at(score, (pairs[:, 1], labels[pairs[:, 0]]), weight)
        labels = score.argmax(1)
    # Merge small islands of a label into the most common neighbouring label.
    pairs = mesh.face_adjacency
    for _ in range(3):
        same = labels[pairs[:, 0]] == labels[pairs[:, 1]]
        n = len(labels)
        g = coo_matrix((np.ones(same.sum()), (pairs[same, 0], pairs[same, 1])), (n, n))
        count, component = connected_components(g, directed=False)
        sizes = np.bincount(component, minlength=count)
        small = sizes[component] < MIN_ISLAND * n
        if not small.any():
            break
        for c in np.unique(component[small]):
            members = component == c
            border = np.r_[
                pairs[members[pairs[:, 0]] & ~members[pairs[:, 1]], 1],
                pairs[members[pairs[:, 1]] & ~members[pairs[:, 0]], 0],
            ]
            if len(border):
                labels[members] = np.bincount(labels[border], minlength=len(names)).argmax()
    labels, merged = merge_smooth_seams(mesh, labels, len(names))
    merged = {names[keep]: [names[k] for k in gone] for keep, gone in merged.items()}
    return [names[k] for k in labels], visible, merged


def merge_smooth_seams(mesh, labels, count):
    """Merge neighbouring parts whose shared border runs over smooth surface.

    Photo regions also follow colour and print (a patterned band on a plain stool). A physical
    part boundary is a groove, crease or step in the generated surface; a border that crosses
    continuous surface is decoration. Sharpness is taken over a two-face ring, since borders settle
    next to grooves rather than exactly on them. Returns (labels, {kept: [absorbed, ...]}).
    """
    pairs, angles = mesh.face_adjacency, mesh.face_adjacency_angles
    sharp = np.zeros(len(labels))
    np.maximum.at(sharp, pairs[:, 0], angles)
    np.maximum.at(sharp, pairs[:, 1], angles)
    for _ in range(2):
        grown = sharp.copy()
        np.maximum.at(grown, pairs[:, 0], sharp[pairs[:, 1]])
        np.maximum.at(grown, pairs[:, 1], sharp[pairs[:, 0]])
        sharp = grown
    edge_sharp = np.maximum(sharp[pairs[:, 0]], sharp[pairs[:, 1]]) > np.radians(SEAM_DEGREES)
    labels, merged = labels.copy(), {}
    while True:
        a, b = labels[pairs[:, 0]], labels[pairs[:, 1]]
        cross = a != b
        if not cross.any():
            break
        key = np.minimum(a, b)[cross] * count + np.maximum(a, b)[cross]
        keys, inverse, edges = np.unique(key, return_inverse=True, return_counts=True)
        share = np.bincount(inverse, weights=edge_sharp[cross]) / edges
        candidates = np.flatnonzero((share < SMOOTH_SEAM) & (edges >= MIN_SEAM_EDGES))
        if not len(candidates):
            break
        best = candidates[np.argmin(share[candidates])]
        x, y = divmod(int(keys[best]), count)
        keep, gone = (x, y) if (labels == x).sum() >= (labels == y).sum() else (y, x)
        labels[labels == gone] = keep
        merged.setdefault(keep, []).extend([gone, *merged.pop(gone, [])])
    return labels, merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--regions", help="photo_regions.py output folder; replaces the planner masks")
    args = parser.parse_args()
    from photo_part_evidence import decimate_mesh, fit_camera

    plan_folder, output = Path(args.plan), Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    mesh = decimate_mesh(trimesh.load(args.mesh, force="mesh"), LABEL_FACES)
    mesh.merge_vertices()
    load = lambda name: np.asarray(Image.open(plan_folder / name).convert("L")) > 127  # noqa: E731
    whole = load("whole_mask.png")
    contours, _ = cv2.findContours(whole.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros(whole.shape, np.uint8)
    cv2.drawContours(filled, contours, -1, 1, -1)
    whole = filled > 0
    camera = fit_camera({"whole": decimate_mesh(mesh, 3000)}, whole, front_hemisphere=True)
    matrix = np.asarray(camera["projection_from_world"])
    size = tuple(camera["image_size"])
    ids = face_ids(mesh, matrix, size)

    if args.regions:
        folder = Path(args.regions)
        rows = json.loads((folder / "regions.json").read_text(encoding="utf-8"))["regions"]
        parts = [{"id": r["id"], "kind": r["kind"]} for r in rows]
        masks = {r["id"]: (np.asarray(Image.open(folder / r["mask_file"]).convert("L")) > 127) & whole for r in rows}
    else:
        plan = json.loads((plan_folder / "plan.json").read_text(encoding="utf-8"))
        observations = json.loads((plan_folder / "observations.json").read_text(encoding="utf-8"))
        rows = {r["mask_sha256"]: r for r in observations["parts"]}
        parts = [
            p
            for p in plan["parts"]
            if p.get("geometry_role", "physical_part") == "physical_part" and p.get("observations")
        ]
        masks = {p["id"]: load(rows[p["observations"][0]["mask_sha256"]]["mask_file"]) & whole for p in parts}
    labels, visible, merged = label_faces(mesh, ids, masks, whole)

    labels = np.asarray(labels)
    scene, report = trimesh.Scene(), []
    kinds = {p["id"]: p["kind"] for p in parts}
    for name in [p["id"] for p in parts] + [BODY]:
        chosen = labels == name
        if not chosen.any():
            report.append({"part_id": name, "faces": 0, "status": "no_surface"})
            continue
        piece = mesh.submesh([np.flatnonzero(chosen)], append=True)
        scene.add_geometry(piece, node_name=name, geom_name=name)
        drawn = np.isin(ids, np.flatnonzero(chosen))
        mask = masks.get(name, whole & ~np.any(list(masks.values()), axis=0) if masks else whole)
        iou = float((drawn & mask).sum() / max((drawn | mask).sum(), 1))
        report.append(
            {
                "part_id": name,
                "kind": kinds.get(name, "body"),
                "faces": int(chosen.sum()),
                "visible_faces": int((chosen & visible).sum()),
                "hidden_faces_inferred": int((chosen & ~visible).sum()),
                "photo_iou": iou,
            }
        )
    scene.export(output / "segmented.glb")
    (output / "segmentation.json").write_text(
        json.dumps(
            {
                "method": "photo_mask_lifting_with_crease_aware_propagation",
                "camera": {k: v for k, v in camera.items() if k != "projection_from_world"},
                "projection_from_world": camera["projection_from_world"],
                "label_faces": len(mesh.faces),
                "parts": report,
                "hidden_labels_inferred": True,
                "merged_smooth_seams": merged,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # Diagnostic overlay: each part's visible faces in its own colour over the photo.
    product = np.asarray(Image.open(plan_folder / "product.png").convert("RGB")).copy()
    palette = np.array(
        [[230, 120, 40], [50, 130, 210], [60, 170, 90], [200, 60, 190], [220, 200, 50], [120, 80, 40], [90, 200, 200]]
    )
    index = {name: k for k, name in enumerate(dict.fromkeys(labels))}
    face_colour = palette[[index[l] % len(palette) for l in labels]]
    shown = ids >= 0
    product[shown] = (0.4 * product[shown] + 0.6 * face_colour[ids[shown]]).astype(np.uint8)
    Image.fromarray(product).save(output / "segmentation_overlay.png")
    print(
        "SHAPE_SEGMENTED",
        len([r for r in report if r["faces"]]),
        "silhouette_iou %.3f" % camera["silhouette_iou"],
        flush=True,
    )


if __name__ == "__main__":
    main()
