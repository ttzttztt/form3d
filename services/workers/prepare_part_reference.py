# -*- coding: utf-8 -*-
"""Local original-photo part proposals; no hallucinated image completion."""

import argparse, gc, hashlib, inspect, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".tools/SAM2"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def run(args):
    from PIL import Image

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    original = Image.open(args.input).convert("RGBA")
    if (
        not getattr(args, "detect_parts", False)
        and list(args.target) == [0.0, 0.0, 1.0, 1.0]
        and original.getchannel("A").getextrema()[0] < 128
    ):
        alpha = original.getchannel("A")
        bb = alpha.getbbox()
        if not bb:
            raise ValueError("提供的部件图片是全透明的")
        digest = hashlib.sha256(original.tobytes()).hexdigest()[:32]
        original.save(out / (digest + ".png"))
        white = Image.new("RGBA", original.size, "white")
        white.alpha_composite(original)
        white.convert("RGB").save(out / (digest + "_preview.png"))
        alpha.save(out / (digest + "_mask.png"))
        candidate = {
            "id": digest,
            "file": digest + ".png",
            "preview": digest + "_preview.png",
            "mask_file": digest + "_mask.png",
            "label": "提供的透明部件参考",
            "source_image_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
            "score_is_accuracy": False,
            "hidden_regions_completed": None,
            "input_semantics_verified": False,
        }
        (out / "references.json").write_text(
            json.dumps(
                {
                    "candidates": [candidate],
                    "kind": args.kind,
                    "method": "provided_alpha_preserved",
                    "requires_reference_confirmation": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return
    import numpy as np, torch
    from PIL import Image, ImageDraw
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    white = Image.new("RGBA", original.size, "white")
    white.alpha_composite(original)
    image = white.convert("RGB")
    w, h = image.size
    x, y, bw, bh = args.target
    pad = 0.025
    bounds = [
        max(0, int((x - pad) * w)),
        max(0, int((y - pad) * h)),
        min(w, int((x + bw + pad) * w)),
        min(h, int((y + bh + pad) * h)),
    ]
    product = image.crop(bounds)
    product.save(out / "product.png")
    started = time.monotonic()
    prompt = (
        "pillow. throw pillow. back cushion."
        if args.kind == "pillow"
        else "bolster pillow. cylindrical pillow."
        if args.kind == "bolster"
        else "seat cushion. sofa seat cushion."
    )
    print("REFERENCE_STAGE detecting", flush=True)
    processor = AutoProcessor.from_pretrained(str(ROOT / ".models/grounding-dino-tiny"), local_files_only=True)
    model = (
        AutoModelForZeroShotObjectDetection.from_pretrained(
            str(ROOT / ".models/grounding-dino-tiny"), local_files_only=True, disable_custom_kernels=True
        )
        .to("cuda")
        .eval()
    )
    inputs = processor(
        images=product, text=prompt, return_tensors="pt", size={"shortest_edge": 640, "longest_edge": 960}
    ).to("cuda")
    with torch.inference_mode():
        outputs = model(**inputs)
    threshold = (
        "threshold"
        if "threshold" in inspect.signature(processor.post_process_grounded_object_detection).parameters
        else "box_threshold"
    )
    raw = processor.post_process_grounded_object_detection(
        outputs,
        input_ids=inputs.input_ids,
        text_threshold=0.20,
        target_sizes=[(product.height, product.width)],
        **{threshold: 0.25},
    )[0]
    detections = []
    from detect_semantic_views import box_iou

    for score, box in sorted(zip(raw["scores"].cpu().tolist(), raw["boxes"].cpu().tolist()), reverse=True):
        box = [max(0, min(product.width if i % 2 == 0 else product.height, float(v))) for i, v in enumerate(box)]
        if min(box[2] - box[0], box[3] - box[1]) < 24 or any(box_iou(box, d["box"]) > 0.75 for d in detections):
            continue
        detections.append({"box": box, "detector_score": score})
        if len(detections) == 8:
            break
    whole_boxes = []
    if getattr(args, "whole_product_mask", False):
        whole_inputs = processor(
            images=product,
            text="sofa. couch. armchair. chair.",
            return_tensors="pt",
            size={"shortest_edge": 640, "longest_edge": 960},
        ).to("cuda")
        with torch.inference_mode():
            whole_outputs = model(**whole_inputs)
        whole = processor.post_process_grounded_object_detection(
            whole_outputs,
            input_ids=whole_inputs.input_ids,
            text_threshold=0.20,
            target_sizes=[(product.height, product.width)],
            **{threshold: 0.28},
        )[0]
        for score, box in sorted(zip(whole["scores"].cpu().tolist(), whole["boxes"].cpu().tolist()), reverse=True):
            box = [max(0, min(product.width if i % 2 == 0 else product.height, float(v))) for i, v in enumerate(box)]
            if min(box[2] - box[0], box[3] - box[1]) < 64 or any(box_iou(box, b["box"]) > 0.65 for b in whole_boxes):
                continue
            whole_boxes.append({"box": box, "score": float(score)})
        del whole_inputs, whole_outputs
    del model, processor, inputs, outputs
    gc.collect()
    torch.cuda.empty_cache()
    if not detections:
        raise ValueError("原图中未找到可靠的部件候选，请使用更清晰的部件图片")
    print("REFERENCE_STAGE segmenting", flush=True)
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
    candidates = []
    overlay = product.copy()
    draw = ImageDraw.Draw(overlay)
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        predictor.set_image(np.array(product))
        whole_record = None
        if len(whole_boxes) == 1:
            whole_masks, whole_scores, _ = predictor.predict(
                box=np.asarray(whole_boxes[0]["box"], np.float32), multimask_output=False
            )
            whole_mask = np.asarray(whole_masks[0]) > 0
            fraction = float(whole_mask.mean())
            if float(whole_scores[0]) >= 0.7 and 0.02 < fraction < 0.95:
                Image.fromarray(np.uint8(whole_mask) * 255).save(out / "whole_product_mask.png")
                whole_record = {
                    "file": "whole_product_mask.png",
                    "sha256": hashlib.sha256((out / "whole_product_mask.png").read_bytes()).hexdigest(),
                    "method": "grounding_dino_single_furniture_box_and_sam",
                    "sam_score_is_accuracy": False,
                    "physical_structure_completed": False,
                }
        for di, detection in enumerate(detections):
            box = np.asarray(detection["box"], np.float32)
            draw.rectangle(box.tolist(), outline="red", width=2)
            draw.text((float(box[0]), float(box[1])), str(di), fill="red")
            variants = [(None, None)]
            for fraction in ((0.5, 0.35), (0.5, 0.6)):
                point = box[:2] + (box[2:] - box[:2]) * fraction
                negative = []
                if args.kind == "cushion":
                    negative.append([point[0], min(product.height - 2, product.height * 0.94)])
                for other in detections:
                    if other is detection:
                        continue
                    center = (np.asarray(other["box"][:2]) + other["box"][2:]) / 2
                    if box_iou(box, other["box"]) < 0.15 and np.linalg.norm(center - point) > 30:
                        negative.append(center.tolist())
                pts = np.vstack([point, np.asarray(negative).reshape(-1, 2)]).astype(np.float32)
                labels = np.r_[1, np.zeros(len(negative), int)]
                variants.append((pts, labels))
            for vi, (points, labels) in enumerate(variants):
                masks, scores, _ = predictor.predict(
                    box=box, point_coords=points, point_labels=labels, multimask_output=True
                )
                for mi, (mask, score) in enumerate(zip(masks, scores)):
                    mask = np.asarray(mask) > 0
                    if not np.isfinite(score) or score < 0.65 or mask.sum() < 300:
                        continue
                    if any((mask & c["mask"]).sum() / max((mask | c["mask"]).sum(), 1) > 0.90 for c in candidates):
                        continue
                    candidates.append(
                        {
                            "mask": mask,
                            "sam_score_prediction": float(score),
                            "detector_score": detection["detector_score"],
                            "detection": di,
                            "prompt": "box" if points is None else "automatic_positive_and_neighbour_exclusions",
                            "box": box.tolist(),
                        }
                    )
    overlay.save(out / "detections.png")
    records = []
    candidates.sort(key=lambda c: c["sam_score_prediction"] * c["detector_score"], reverse=True)
    for ordinal, candidate in enumerate(candidates[:16]):
        mask = candidate.pop("mask")
        alpha = Image.fromarray(np.uint8(mask) * 255)
        rgba = product.convert("RGBA")
        rgba.putalpha(alpha)
        bb = alpha.getbbox()
        padding = 8
        crop = [
            max(0, bb[0] - padding),
            max(0, bb[1] - padding),
            min(product.width, bb[2] + padding),
            min(product.height, bb[3] + padding),
        ]
        part = rgba.crop(crop)
        digest = hashlib.sha256(np.uint8(mask).tobytes()).hexdigest()[:32]
        file = digest + ".png"
        part.save(out / file)
        white = Image.new("RGBA", part.size, "white")
        white.alpha_composite(part)
        white.convert("RGB").save(out / (digest + "_preview.png"))
        Image.fromarray(np.uint8(mask) * 255).save(out / (digest + "_mask.png"))
        records.append(
            {
                "id": digest,
                "file": file,
                "preview": digest + "_preview.png",
                "mask_file": digest + "_mask.png",
                "source_crop_in_product_pixels": crop,
                "label": f"参考 {ordinal + 1}",
                "source_image_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
                **candidate,
                "score_is_accuracy": False,
                "hidden_regions_completed": False,
            }
        )
    if not records:
        raise ValueError("部件分割未得到可用参考，原模型保留")
    manifest = {
        "candidates": records,
        "kind": args.kind,
        "source_image_size": [w, h],
        "product_crop_pixels": bounds,
        "detector": "Grounding DINO Tiny",
        "segmenter": "SAM 2.1 Hiera Tiny",
        "requires_reference_confirmation": True,
        "duration_seconds": time.monotonic() - started,
    }
    if getattr(args, "whole_product_mask", False):
        manifest.update(whole_product_mask=whole_record, whole_furniture_instances=len(whole_boxes))
    (out / "references.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REFERENCE_READY", len(records), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--target", nargs=4, type=float, required=True)
    p.add_argument("--kind", choices=["pillow", "cushion", "bolster"], required=True)
    p.add_argument("--detect-parts", action="store_true")
    p.add_argument("--whole-product-mask", action="store_true")
    run(p.parse_args())
