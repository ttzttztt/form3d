"""Local text detection + box/automatic point SAM proposals on calibrated renders."""

import argparse, gc, inspect, json, os, sys, time
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".tools/SAM2"))


def box_iou(a, b):
    inter = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return inter / max((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter, 1e-9)


def main(folder, category):
    import numpy as np, torch
    from PIL import Image, ImageDraw
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    torch.set_num_threads(4)
    records = []
    views = json.loads((folder / "views.json").read_text(encoding="utf-8"))
    start = time.monotonic()
    processor = AutoProcessor.from_pretrained(str(ROOT / ".models/grounding-dino-tiny"), local_files_only=True)
    model = (
        AutoModelForZeroShotObjectDetection.from_pretrained(
            str(ROOT / ".models/grounding-dino-tiny"), local_files_only=True, disable_custom_kernels=True
        )
        .to("cuda")
        .eval()
    )
    if category == "auto":
        object_votes = []
        for view in views[:2]:
            image = Image.open(folder / view["image"]).convert("RGB")
            inputs = processor(
                images=image,
                text="sofa. armchair. chair. table. cabinet.",
                return_tensors="pt",
                size={"shortest_edge": 640, "longest_edge": 960},
            ).to("cuda")
            with torch.inference_mode():
                outputs = model(**inputs)
            threshold_key = (
                "threshold"
                if "threshold" in inspect.signature(processor.post_process_grounded_object_detection).parameters
                else "box_threshold"
            )
            raw = processor.post_process_grounded_object_detection(
                outputs,
                input_ids=inputs.input_ids,
                text_threshold=0.22,
                target_sizes=[(image.height, image.width)],
                **{threshold_key: 0.30},
            )[0]
            for score, label in zip(raw["scores"].cpu().tolist(), raw.get("text_labels", raw.get("labels", []))):
                label = str(label)
                kind = next((k for k in ("sofa", "chair", "table", "cabinet") if k in label), None)
                if kind:
                    object_votes.append((score, kind))
        if not object_votes:
            raise ValueError("AI 未能判断家具类型，未强制套用沙发或书柜分类")
        category = max(object_votes)[1]
        print("SEMANTIC_CATEGORY", category, flush=True)
    prompts = (
        [("pillow", "pillow."), ("seat", "seat cushion.")]
        if category in ("sofa", "chair", "auto")
        else [("tabletop", "tabletop."), ("support", "table leg.")]
        if category == "table"
        else [("panel", "cabinet door. shelf.")]
    )
    for view in views:
        image = Image.open(folder / view["image"]).convert("RGB")
        detections = []
        for kind, text in prompts:
            inputs = processor(
                images=image, text=text, return_tensors="pt", size={"shortest_edge": 640, "longest_edge": 960}
            ).to("cuda")
            with torch.inference_mode():
                outputs = model(**inputs)
            threshold_key = (
                "threshold"
                if "threshold" in inspect.signature(processor.post_process_grounded_object_detection).parameters
                else "box_threshold"
            )
            raw = processor.post_process_grounded_object_detection(
                outputs,
                input_ids=inputs.input_ids,
                text_threshold=0.20,
                target_sizes=[(image.height, image.width)],
                **{threshold_key: 0.27 if kind == "pillow" else 0.30},
            )[0]
            for score, box, label in zip(
                raw["scores"].cpu().tolist(), raw["boxes"].cpu().tolist(), raw.get("text_labels", raw.get("labels", []))
            ):
                box = [max(0, min(image.width if i % 2 == 0 else image.height, float(x))) for i, x in enumerate(box)]
                if min(box[2] - box[0], box[3] - box[1]) < 20:
                    continue
                detections.append({"kind": kind, "detector_score": float(score), "box": box, "raw_label": str(label)})
        kept = []
        for d in sorted(detections, key=lambda d: d["detector_score"], reverse=True):
            if any(k["kind"] == d["kind"] and box_iou(k["box"], d["box"]) > 0.78 for k in kept):
                continue
            kept.append(d)
            if len(kept) >= 12:
                break
        records.append({"view": view["index"], "detections": kept, "masks": []})
        print("SEMANTIC_DETECTION", view["index"], len(kept), flush=True)
    del model, processor, inputs, outputs
    gc.collect()
    torch.cuda.empty_cache()
    predictor = SAM2ImagePredictor(
        build_sam2(
            "configs/sam2.1/sam2.1_hiera_t.yaml",
            str(ROOT / ".models/sam2.1-hiera-tiny/sam2.1_hiera_tiny.pt"),
            device="cuda",
            apply_postprocessing=False,
        ),
        max_hole_area=0,
        max_sprinkle_area=0,
    )
    for record, view in zip(records, views):
        image = Image.open(folder / view["image"]).convert("RGB")
        candidates = []
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            predictor.set_image(np.asarray(image))
            for di, d in enumerate(record["detections"]):
                box = np.asarray(d["box"], dtype=np.float32)
                lo = box[:2]
                extent = box[2:] - lo
                prompts = (
                    [None] + [lo + extent * np.asarray(r) for r in ((0.5, 0.5), (0.18, 0.5), (0.82, 0.5))]
                    if d["kind"] == "pillow"
                    else [None]
                )
                for point in prompts:
                    masks, scores, _ = predictor.predict(
                        box=box,
                        point_coords=None if point is None else point[None, :],
                        point_labels=None if point is None else np.ones(1, dtype=int),
                        multimask_output=True,
                    )
                    for mask, score in zip(masks, scores):
                        if not np.isfinite(score) or score < 0.68 or mask.sum() < 250:
                            continue
                        y0, x0 = np.maximum(np.floor(box[[1, 0]]).astype(int), 0)
                        y1, x1 = np.ceil(box[[3, 2]]).astype(int)
                        inside = mask[y0:y1, x0:x1].sum() / mask.sum()
                        if inside < 0.80:
                            continue
                        candidate = {
                            "kind": d["kind"],
                            "detector_score": d["detector_score"],
                            "mask_quality_prediction": float(score),
                            "detection": di,
                            "prompt": "box" if point is None else "automatic_point_and_box",
                            "mask": mask,
                        }
                        duplicate = next(
                            (
                                p
                                for p in candidates
                                if p["kind"] == d["kind"]
                                and np.logical_and(mask, p["mask"]).sum() / max(np.logical_or(mask, p["mask"]).sum(), 1)
                                > 0.88
                            ),
                            None,
                        )
                        if duplicate:
                            if duplicate["mask_quality_prediction"] < score:
                                duplicate.update(candidate)
                        else:
                            candidates.append(candidate)
        candidates.sort(key=lambda c: c["mask_quality_prediction"] * c["detector_score"], reverse=True)
        for mi, candidate in enumerate(candidates[:32]):
            mask = candidate.pop("mask")
            file = f"semantic_mask_{view['index']}_{mi}.png"
            Image.fromarray(np.uint8(mask) * 255).save(folder / file)
            record["masks"].append({**candidate, "mask_file": file, "pixels": int(mask.sum())})
        overlay = image.copy()
        draw = ImageDraw.Draw(overlay)
        for d in record["detections"]:
            draw.rectangle(d["box"], outline="red" if d["kind"] == "pillow" else "blue", width=2)
        overlay.save(folder / f"detections_{view['index']}.png")
        print("SEMANTIC_MASKS", view["index"], len(record["masks"]), flush=True)
        (folder / "detections.json").write_text(
            json.dumps(
                {
                    "detector": "Grounding DINO Tiny",
                    "segmenter": "SAM 2.1 Hiera Tiny",
                    "category": category,
                    "automatic_prompts": True,
                    "score_is_accuracy": False,
                    "seconds": round(time.monotonic() - start, 3),
                    "views": records,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True)
    parser.add_argument("--category", default="sofa")
    a = parser.parse_args()
    main(Path(a.folder), a.category)
