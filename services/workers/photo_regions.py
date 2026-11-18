"""Category-agnostic part regions in the photo: SAM 2 "segment everything" inside the furniture.

    photo_regions.py --plan PLAN_FOLDER --output OUT

A grid of single-point prompts covers the furniture mask; every prompt returns SAM's three nested
proposals. Proposals are kept when SAM is confident and stable, then de-duplicated greedily
(non-maximum suppression by mask IoU / containment), preferring mid-sized, high-scoring masks, and
finally the chosen regions are made disjoint. Names come from the planner's detector masks where they
overlap (e.g. "drawer"), otherwise the region stays an unnamed "part". No furniture rules are used.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services/workers"), str(ROOT / ".tools/SAM2")]

GRID = 24  # points per side over the furniture's bounding box
MIN_SCORE = 0.75
MIN_AREA, MAX_AREA = 0.004, 0.6  # fraction of the furniture mask
OVERLAP = 0.5  # a proposal mostly covered by an already chosen region is a duplicate
NAME_IOU = 0.3


def proposals(predictor, whole):
    ys, xs = np.nonzero(whole)
    gx = np.linspace(xs.min(), xs.max(), GRID)
    gy = np.linspace(ys.min(), ys.max(), GRID)
    points = np.array([(x, y) for y in gy for x in gx if whole[int(y), int(x)]])
    found = []
    for start in range(0, len(points), 64):
        batch = points[start : start + 64]
        masks, scores, _ = predictor.predict(
            point_coords=batch[:, None, :], point_labels=np.ones((len(batch), 1)), multimask_output=True
        )
        masks = np.asarray(masks).reshape(len(batch), 3, *whole.shape) > 0
        scores = np.asarray(scores).reshape(len(batch), 3)
        for b in range(len(batch)):
            for k in range(3):
                found.append((float(scores[b, k]), masks[b, k]))
    return found


def select(found, whole):
    total = whole.sum()
    candidates = []
    for score, mask in found:
        mask = mask & whole
        area = mask.sum() / total
        if score < MIN_SCORE or not MIN_AREA <= area <= MAX_AREA:
            continue
        candidates.append((score, mask))
    # Prefer confident masks; among similar scores prefer the smaller (more specific) one.
    candidates.sort(key=lambda c: (-round(c[0], 2), c[1].sum()))
    chosen, taken = [], np.zeros(whole.shape, bool)
    for score, mask in candidates:
        if (mask & taken).sum() > OVERLAP * mask.sum():
            continue
        mask = mask & ~taken  # disjoint regions
        if mask.sum() < MIN_AREA * total:
            continue
        chosen.append((score, mask))
        taken |= mask
    return chosen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    import torch
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    plan_folder, output = Path(args.plan), Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    product = Image.open(plan_folder / "product.png").convert("RGB")
    whole = np.asarray(Image.open(plan_folder / "whole_mask.png").convert("L")) > 127
    large = ROOT / ".models/sam2.1-hiera-large/sam2.1_hiera_large.pt"
    use_large = large.is_file()
    predictor = SAM2ImagePredictor(
        build_sam2(
            "configs/sam2.1/sam2.1_hiera_l.yaml" if use_large else "configs/sam2.1/sam2.1_hiera_t.yaml",
            str(large if use_large else ROOT / ".models/sam2.1-hiera-tiny/sam2.1_hiera_tiny.pt"),
            device="cuda",
            apply_postprocessing=False,
        )
    )
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        predictor.set_image(np.asarray(product))
        found = proposals(predictor, whole)
    chosen = select(found, whole)

    observations = json.loads((plan_folder / "observations.json").read_text(encoding="utf-8"))
    named = [
        (row["kind"], np.asarray(Image.open(plan_folder / row["mask_file"]).convert("L")) > 127)
        for row in observations["parts"]
    ]
    regions = []
    for index, (score, mask) in enumerate(chosen):
        kind, best = "part", NAME_IOU
        for candidate_kind, candidate in named:
            iou = (mask & candidate).sum() / max((mask | candidate).sum(), 1)
            inside = (mask & candidate).sum() / max(mask.sum(), 1)
            if max(iou, 0.8 * inside) > best:
                kind, best = candidate_kind, max(iou, 0.8 * inside)
        file = f"region_{index:02d}.png"
        Image.fromarray(np.uint8(mask) * 255).save(output / file)
        regions.append(
            {
                "id": f"region_{index:02d}",
                "kind": kind,
                "mask_file": file,
                "sam_score": score,
                "area_fraction": float(mask.sum() / whole.sum()),
            }
        )
    (output / "regions.json").write_text(
        json.dumps(
            {
                "method": "sam2_point_grid_nms",
                "segmenter": "large" if use_large else "tiny",
                "regions": regions,
                "coverage": float(sum(r["area_fraction"] for r in regions)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("PHOTO_REGIONS", len(regions), flush=True)


if __name__ == "__main__":
    main()
