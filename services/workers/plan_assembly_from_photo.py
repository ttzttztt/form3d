# -*- coding: utf-8 -*-
"""Local original-photo part proposals before any 3D part generation."""

import argparse, gc, hashlib, inspect, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services/workers"), str(ROOT / ".tools/SAM2")]
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
PROMPTS = {
    "sofa": [
        ("back_cushion", "throw pillow. back cushion."),
        ("seat_cushion", "seat cushion."),
        ("bolster", "cylindrical bolster pillow."),
        ("armrest", "sofa armrest."),
    ],
    "chair": [
        ("seat_cushion", "chair seat."),
        ("backrest", "chair backrest."),
        ("armrest", "chair armrest."),
        ("leg", "chair leg."),
    ],
    "table": [("tabletop", "tabletop."), ("leg", "table leg. table pedestal.")],
    "cabinet": [("door", "cabinet door."), ("drawer", "cabinet drawer."), ("shelf", "cabinet shelf.")],
}


def run(args):
    import cv2, numpy as np, torch
    from PIL import Image, ImageDraw
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    from services.api.assembly_planning import plan_from_image_observations
    from generate_partcrafter import write
    from detect_semantic_views import box_iou

    folder = Path(args.output)
    if folder.exists():
        raise ValueError("Use a new proposal folder; preserve prior evidence")
    folder.mkdir(parents=True)
    started = time.monotonic()
    source = Path(args.input)
    image = Image.open(source).convert("RGBA")
    width, height = image.size
    x, y, w, h = args.target
    bounds = [round(x * width), round(y * height), round((x + w) * width), round((y + h) * height)]
    crop = image.crop(bounds)
    white = Image.new("RGBA", crop.size, "white")
    white.alpha_composite(crop)
    product = white.convert("RGB")
    product.save(folder / "product.png")
    torch.set_num_threads(4)
    device = "cuda"
    processor = AutoProcessor.from_pretrained(str(ROOT / ".models/grounding-dino-tiny"), local_files_only=True)
    model = (
        AutoModelForZeroShotObjectDetection.from_pretrained(
            str(ROOT / ".models/grounding-dino-tiny"), local_files_only=True, disable_custom_kernels=True
        )
        .to(device)
        .eval()
    )
    threshold_key = (
        "threshold"
        if "threshold" in inspect.signature(processor.post_process_grounded_object_detection).parameters
        else "box_threshold"
    )
    detection_audit = []

    def detect(prompt, threshold=0.25):
        inputs = processor(
            images=product, text=prompt, return_tensors="pt", size={"shortest_edge": 640, "longest_edge": 960}
        ).to(device)
        with torch.inference_mode():
            outputs = model(**inputs)
        raw = processor.post_process_grounded_object_detection(
            outputs,
            input_ids=inputs.input_ids,
            text_threshold=0.20,
            target_sizes=[(product.height, product.width)],
            **{threshold_key: threshold},
        )[0]
        kept = []
        labels = raw.get("text_labels", raw.get("labels", []))
        for score, box, label in sorted(
            zip(raw["scores"].cpu().tolist(), raw["boxes"].cpu().tolist(), labels), reverse=True
        ):
            box = [max(0, min(product.width if i % 2 == 0 else product.height, float(v))) for i, v in enumerate(box)]
            if min(box[2] - box[0], box[3] - box[1]) < 16 or any(box_iou(box, r["box"]) > 0.80 for r in kept):
                continue
            kept.append({"score": float(score), "box": box, "raw_label": str(label), "query": prompt})
        detection_audit.append({"query": prompt, "detections": kept})
        return kept

    whole = detect(
        "sofa. couch."
        if args.category == "sofa"
        else "chair. armchair."
        if args.category == "chair"
        else "table."
        if args.category == "table"
        else "cabinet. bookcase.",
        0.28,
    )
    proposals = []
    for kind, prompt in PROMPTS[args.category]:
        proposals.extend({**r, "kind": kind} for r in detect(prompt))
        print("PART_PLANNING_DETECTED", kind, len(proposals), flush=True)
    clutter = detect("laptop. book. person. cat. potted plant.", 0.30)
    model = processor = None  # release GPU memory; detect() is not called after this
    gc.collect()
    torch.cuda.empty_cache()
    # Large separates textured cushions far better than Tiny; PLANNER_SAM=tiny forces the small one.
    large = ROOT / ".models/sam2.1-hiera-large/sam2.1_hiera_large.pt"
    use_large = large.is_file() and os.getenv("PLANNER_SAM", "auto") != "tiny"
    segmenter = "SAM 2.1 Hiera Large" if use_large else "SAM 2.1 Hiera Tiny"
    predictor = SAM2ImagePredictor(
        build_sam2(
            "configs/sam2.1/sam2.1_hiera_l.yaml" if use_large else "configs/sam2.1/sam2.1_hiera_t.yaml",
            str(large if use_large else ROOT / ".models/sam2.1-hiera-tiny/sam2.1_hiera_tiny.pt"),
            device=device,
            apply_postprocessing=False,
        ),
        max_hole_area=0,
        max_sprinkle_area=0,
    )
    accepted = []
    rejected = []
    clutter_records = []
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        predictor.set_image(np.asarray(product))
        if crop.getchannel("A").getextrema()[0] < 128:
            whole_mask = np.asarray(crop.getchannel("A")) > 128
            whole_method = "provided_alpha"
        else:
            if not whole:
                raise ValueError("No reliable whole furniture instance inside the selected target")
            center = np.array(product.size) / 2
            chosen = max(
                whole,
                key=lambda r: (
                    r["score"]
                    - 0.15 * np.linalg.norm((np.array(r["box"][:2]) + r["box"][2:]) / 2 - center) / max(product.size)
                ),
            )
            # SAM's single default for a whole-furniture box is often only its largest sub-part
            # (the tabletop, the cushions). Take the largest of the multimask proposals that is
            # confident and stays inside the box, so parts are not judged "outside the furniture".
            box = np.asarray(chosen["box"], np.float32)
            masks, scores, _ = predictor.predict(box=box, multimask_output=True)
            x0, y0, x1, y1 = [int(round(v)) for v in box]
            whole_options = []
            for mask, score in zip(masks, scores):
                mask = np.asarray(mask) > 0
                inside = mask[y0:y1, x0:x1].sum() / max(mask.sum(), 1)
                if float(score) >= 0.6 and inside >= 0.9:
                    whole_options.append((int(mask.sum()), float(score), mask))
            if not whole_options:
                raise ValueError("Whole furniture mask is uncertain")
            whole_mask = max(whole_options, key=lambda r: r[0])[2]
            whole_method = "local_furniture_detection_and_sam"
        if whole_mask.sum() < 300:
            raise ValueError("Whole furniture mask is too small")
        for item in clutter:
            masks, scores, _ = predictor.predict(box=np.asarray(item["box"], np.float32), multimask_output=False)
            if float(scores[0]) < 0.7:
                continue
            mask = np.asarray(masks[0]) > 0
            overlap = mask & whole_mask
            if overlap.sum() / max(whole_mask.sum(), 1) > 0.35:
                clutter_records.append(
                    {**item, "excluded": False, "reason": "occluder_mask_too_large_for_automatic_removal"}
                )
                continue
            if overlap.any():
                whole_mask[mask] = False
                clutter_records.append({**item, "excluded": True, "removed_foreground_pixels": int(overlap.sum())})
        for number, item in enumerate(proposals):
            # A query containing "sofa armrest" can return only the token "sofa".
            # A query string is not a detected part label.
            required = {
                "armrest": ("arm",),
                "leg": ("leg", "pedestal"),
                "door": ("door",),
                "drawer": ("drawer",),
                "shelf": ("shelf",),
                "tabletop": ("top",),
                "backrest": ("back",),
                "seat_cushion": ("seat",),
            }.get(item["kind"])
            if required and not any(token in item["raw_label"].lower() for token in required):
                rejected.append({**item, "reason": "detected_label_does_not_support_part_kind"})
                continue
            box = np.asarray(item["box"], np.float32)
            variants = [(None, None)]
            for fx, fy in ((0.5, 0.35), (0.5, 0.60)):
                point = box[:2] + (box[2:] - box[:2]) * [fx, fy]
                negative = []
                if item["kind"] == "seat_cushion":
                    negative.append([point[0], min(product.height - 2, box[3] - (box[3] - box[1]) * 0.025)])
                for other in proposals:
                    if other is item:
                        continue
                    center = (np.array(other["box"][:2]) + other["box"][2:]) / 2
                    if box_iou(box, other["box"]) < 0.15 and np.linalg.norm(center - point) > 30:
                        negative.append(center)
                points = np.vstack([point, np.asarray(negative).reshape(-1, 2)]).astype(np.float32)
                variants.append((points, np.r_[1, np.zeros(len(negative), int)]))
            candidates = []
            all_masks = []
            for points, labels in variants:
                masks, scores, _ = predictor.predict(
                    box=box, point_coords=points, point_labels=labels, multimask_output=True
                )
                all_masks.extend(zip(masks, scores))
            filters = {}  # which check removed each SAM candidate, for diagnosis

            def drop(reason):
                filters[reason] = filters.get(reason, 0) + 1

            for mask, score in all_masks:
                mask = np.asarray(mask) > 0
                if float(score) < 0.6 or mask.sum() < 150:
                    drop("low_sam_score_or_tiny")
                    continue
                containment = float((mask & whole_mask).sum() / max(mask.sum(), 1))
                fraction = float((mask & whole_mask).sum() / max(whole_mask.sum(), 1))
                bx0, by0, bx1, by1 = [int(round(v)) for v in item["box"]]
                inside_box = float(mask[by0:by1, bx0:bx1].sum() / max(mask.sum(), 1))
                limit = (
                    0.8
                    if item["kind"] in ("seat_cushion", "door", "shelf", "backrest")
                    else 0.4
                    if item["kind"] in ("back_cushion", "bolster")
                    else 0.35
                    if item["kind"] == "armrest"
                    else 0.65
                )
                if item["kind"] == "tabletop":
                    limit = 0.85  # a top can cover most of a table seen from above
                # Loosened from 0.88/0.85: SAM masks of real parts often spill a little past the
                # detector box (round tops, cushions), which dropped many true parts.
                if containment < 0.8:
                    drop("outside_furniture_mask")
                    continue
                if inside_box < 0.75:
                    drop("spills_out_of_detector_box")
                    continue
                if fraction > limit:
                    drop("too_large_for_kind")
                    continue
                mask &= whole_mask
                _, _, components, _ = cv2.connectedComponentsWithStats(mask.astype("uint8"), 8)
                dominant = (
                    float(components[1:, cv2.CC_STAT_AREA].max() / max(mask.sum(), 1)) if len(components) > 1 else 0.0
                )
                if item["kind"] in ("back_cushion", "seat_cushion", "bolster") and dominant < 0.9:
                    drop("fragmented")
                    continue
                if item["kind"] == "bolster":
                    yy, xx = np.nonzero(mask)
                    cov = np.cov(np.c_[xx, yy].T)
                    eigen = np.linalg.eigvalsh(cov)
                    elongation = float(np.sqrt(eigen[1] / max(eigen[0], 1e-6)))
                    if elongation < 1.7:
                        drop("not_elongated")
                        continue
                candidates.append((float(score), mask))
            if not candidates:
                rejected.append({**item, "reason": "no_contained_single_part_mask", "filters": filters})
                continue
            score, mask = max(candidates, key=lambda r: r[0])
            duplicates = [p for p in accepted if (mask & p["mask"]).sum() / max((mask | p["mask"]).sum(), 1) > 0.75]
            if duplicates:
                old = duplicates[0]
                if old["kind"] != item["kind"]:
                    old.setdefault("competing_kinds", []).append(item["kind"])
                    # Scores from different text queries are not calibrated
                    # competing class probabilities. Preserve the conflict.
                    old.setdefault(
                        "kind_evidence",
                        [
                            {
                                "kind": old["kind"],
                                "raw_label": old["raw_label"],
                                "query": old["query"],
                                "score": old["detector_score"],
                            }
                        ],
                    ).append(
                        {
                            "kind": item["kind"],
                            "raw_label": item["raw_label"],
                            "query": item["query"],
                            "score": item["score"],
                        }
                    )
                    old["kind"] = "unknown"
                continue
            accepted.append(
                {
                    "kind": item["kind"],
                    "detector_score": item["score"],
                    "sam_quality_prediction": score,
                    "mask": mask,
                    "detector_box": item["box"],
                    "raw_label": item["raw_label"],
                    "query": item["query"],
                }
            )
    from part_kind_rules import resolve_kind

    for item in accepted:
        if item.get("kind_evidence"):
            item["kind"], item["kind_resolution"] = resolve_kind(item["kind_evidence"], item["mask"], whole_mask)
    cabinet_layout = None
    if args.category == "cabinet":
        # Cabinets: perspective + front-layout analysis replaces the open-vocabulary detector parts,
        # which miss shelves and invent doors. The detector result is kept in the audit.
        import cabinet_geometry

        try:
            geometry, cells, built, assumptions, iou = cabinet_geometry.analyse(
                np.asarray(product.convert("RGB")), whole_mask
            )
            if iou < cabinet_geometry.MIN_REPROJECTION_IOU:
                raise ValueError(f"reprojection IoU {iou:.2f} below {cabinet_geometry.MIN_REPROJECTION_IOU}")
            masks = cabinet_geometry.part_masks(geometry, built, whole_mask.shape)
            replaced = [i["kind"] for i in accepted]
            accepted = [
                {
                    "kind": part["kind"],
                    "mask": mask & cabinet_geometry.filled(whole_mask) if seen == "partial" else mask,
                    "layout_part_id": part["id"],
                    "layout_name": part["name"],
                    "visibility": seen,
                    "hidden_structure_inferred": part["inferred"],
                }
                for part, (mask, seen) in zip(built, masks)
                if mask.any()
            ]
            cabinet_layout = {
                "method": "two_point_perspective_front_layout",
                "geometry": json.loads(json.dumps(geometry, default=float)),
                "cells": cells,
                "assumptions": assumptions,
                "reprojection_iou": iou,
            }
            write(folder / "cabinet_geometry.json", cabinet_layout)
        except ValueError as exc:
            cabinet_layout = {"error": str(exc)}
    foreground = product.convert("RGBA")
    foreground.putalpha(Image.fromarray(whole_mask.astype("uint8") * 255))
    foreground.save(folder / "generation_input.png")
    Image.fromarray(whole_mask.astype("uint8") * 255).save(folder / "whole_mask.png")
    records = []
    overlay = np.asarray(product).copy()
    palette = [(233, 167, 49), (51, 128, 199), (156, 94, 191), (36, 170, 148), (225, 95, 116), (122, 154, 51)]
    for ordinal, item in enumerate(accepted):
        overlay[item["mask"]] = (
            overlay[item["mask"]] * 0.6 + np.asarray(palette[ordinal % len(palette)]) * 0.4
        ).astype("uint8")
    overlay = Image.fromarray(overlay)
    draw = ImageDraw.Draw(overlay)
    for ordinal, item in enumerate(accepted):
        mask = item.pop("mask")
        mask_bytes = np.uint8(mask) * 255
        identity = hashlib.sha256(mask_bytes.tobytes()).hexdigest()[:32]
        file = identity + "_mask.png"
        Image.fromarray(mask_bytes).save(folder / file)
        yy, xx = np.nonzero(mask)
        box = [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)]
        draw.rectangle(box, outline="#236bd3", width=3)
        draw.text(tuple(box[:2]), f"{ordinal + 1}:{item['kind']}", fill="#c32929")
        x0 = max(x, (bounds[0] + box[0]) / width)
        y0 = max(y, (bounds[1] + box[1]) / height)
        x1 = min(x + w, (bounds[0] + box[2]) / width)
        y1 = min(y + h, (bounds[1] + box[3]) / height)
        records.append(
            {
                **item,
                "mask_file": file,
                "mask_sha256": hashlib.sha256((folder / file).read_bytes()).hexdigest(),
                "target": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
                "visibility": "partial",
                "evidence_kind": "original_photo",
            }
        )
    overlay.save(folder / "observations.png")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    target = {"x": x, "y": y, "width": w, "height": h}
    plan = plan_from_image_observations(args.image_id, source_sha, args.category, target, records)
    write(folder / "plan.json", plan.model_dump())
    write(
        folder / "observations.json",
        {
            "detector": "Grounding DINO Tiny",
            "segmenter": segmenter,
            "planning_phase": "before_3d_generation",
            "input_sha256": source_sha,
            "source_crop_pixels": bounds,
            "whole_mask_method": whole_method,
            "generation_input_sha256": hashlib.sha256((folder / "generation_input.png").read_bytes()).hexdigest(),
            "parts": records,
            "rejected": rejected,
            "detection_audit": detection_audit,
            "cabinet_layout": cabinet_layout
            and {k: cabinet_layout[k] for k in ("method", "reprojection_iou", "error") if k in cabinet_layout},
            "clutter": clutter_records,
            "detected_furniture_candidates": len(whole),
            "scores_are_accuracy": False,
            "inpainting": False,
            "elapsed_seconds": time.monotonic() - started,
        },
    )
    print("PART_PLAN_READY", len(plan.parts), plan.status, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--image-id", required=True)
    p.add_argument("--category", required=True, choices=["sofa", "chair", "table", "cabinet"])
    p.add_argument("--target", nargs=4, type=float, default=[0, 0, 1, 1])
    p.add_argument("--output", required=True)
    run(p.parse_args())
