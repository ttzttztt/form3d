"""Offline SAM 2.1 Tiny box-prompt segmentation. Never completes hidden geometry."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".models" / "sam2.1-hiera-tiny"
SOURCE = ROOT / ".tools" / "SAM2"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "4")


def write_json(path, value):
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(12):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(0.025 * (attempt + 1))


def run(args):
    started = time.monotonic()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    import numpy as np
    import torch
    from PIL import Image, ImageChops, ImageDraw

    sys.path.insert(0, str(SOURCE))
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    if not torch.cuda.is_available():
        raise ValueError("SAM 2 精细分割需要可用的 CUDA 环境")
    torch.set_num_threads(4)
    torch.cuda.reset_peak_memory_stats()
    image = Image.open(args.input).convert("RGBA")
    width, height = image.size
    x, y, w, h = args.target
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1.000001 or y + h > 1.000001:
        raise ValueError("Target is outside source image")
    bounds = [round(x * width), round(y * height), round((x + w) * width), round((y + h) * height)]
    if bounds[2] - bounds[0] < 16 or bounds[3] - bounds[1] < 16:
        raise ValueError("Target is too small for segmentation")
    print("SAM2_STAGE loading", flush=True)
    model = build_sam2(
        "configs/sam2.1/sam2.1_hiera_t.yaml",
        str(MODEL / "sam2.1_hiera_tiny.pt"),
        device="cuda",
        apply_postprocessing=False,
    )
    predictor = SAM2ImagePredictor(model, max_hole_area=0, max_sprinkle_area=0)
    background = Image.new("RGBA", image.size, "white")
    rgb = Image.alpha_composite(background, image).convert("RGB")
    phase = time.monotonic()
    print("SAM2_STAGE predicting", flush=True)
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        predictor.set_image(np.array(rgb))
        masks, scores, _ = predictor.predict(box=np.asarray(bounds, dtype=np.float32), multimask_output=False)
    torch.cuda.synchronize()
    inference_seconds = time.monotonic() - phase
    mask = np.asarray(masks[0], dtype=bool)
    if mask.shape != (height, width) or not np.isfinite(scores).all():
        raise ValueError("SAM 2 returned invalid mask or score")
    full_mask = Image.fromarray(mask.astype(np.uint8) * 255)
    cropped_mask = full_mask.crop(bounds)
    reference = image.crop(bounds)
    if args.prepared:
        prepared = Image.open(args.prepared).convert("RGBA")
        if prepared.size != reference.size:
            raise ValueError("Prepared image size does not match the source target")
        reference = prepared
    alpha = ImageChops.multiply(reference.getchannel("A"), cropped_mask)
    if not alpha.getbbox():
        raise ValueError("SAM 2 produced no foreground in the target")
    foreground = reference.copy()
    foreground.putalpha(alpha)
    foreground.save(output / "segmented.png")
    alpha.save(output / "segmentation_mask.png")
    if args.save_full_mask:
        full_mask.save(output / "segmentation_mask_full.png")
    # Green is retained by the prediction; red is discarded. Neither is truth.
    original = np.asarray(reference.convert("RGB")).astype(np.float32)
    selected = np.asarray(alpha) > 127
    tint = np.where(selected[..., None], np.asarray([35, 200, 95]), np.asarray([235, 65, 65]))
    overlay = Image.fromarray(np.clip(original * 0.68 + tint * 0.32, 0, 255).astype(np.uint8))
    overlay.save(output / "segmentation_overlay.png")
    preview = Image.new("RGBA", foreground.size, "white")
    Image.alpha_composite(preview, foreground).convert("RGB").save(output / "segmentation_preview.png")
    summary = {
        "method": "sam2_box",
        "model": "SAM 2.1 Hiera Tiny",
        "prompt": "target_box_only",
        "point_prompts_used": False,
        "source_image_size": [width, height],
        "target_normalized": list(args.target),
        "target_pixels": bounds,
        "mask_bbox_in_roi": list(alpha.getbbox()),
        "duration_seconds": round(time.monotonic() - started, 3),
        "inference_seconds": round(inference_seconds, 3),
        "peak_vram_allocated_mib": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
        "peak_vram_reserved_mib": round(torch.cuda.max_memory_reserved() / 1024**2, 1),
        "model_predicted_iou": float(scores[0]),
        "score_note": "Model prediction only; not measured mask IoU or segmentation accuracy",
        "foreground_pixels": int(selected.sum()),
        "foreground_fraction": float(selected.mean()),
        "source_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
        "prepared_sha256": hashlib.sha256(Path(args.prepared).read_bytes()).hexdigest() if args.prepared else None,
        "mask_sha256": hashlib.sha256((output / "segmentation_mask.png").read_bytes()).hexdigest(),
        "segmented_sha256": hashlib.sha256((output / "segmented.png").read_bytes()).hexdigest(),
        "manual_erase_alpha_preserved": bool(args.prepared),
        "cuda_extension_used": False,
        "hidden_surface_completion": False,
        "offline": True,
        "worker_revision": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "provenance": json.loads((MODEL / "provenance.json").read_text(encoding="utf-8")),
    }
    write_json(output / "segmentation_summary.json", summary)
    write_json(
        MODEL / "runtime.json",
        {
            "available": True,
            "inference_tested": True,
            "python": str(Path(sys.executable).resolve()),
            "device": torch.cuda.get_device_name(0),
            "model": "SAM 2.1 Hiera Tiny",
            "worker_revision": summary["worker_revision"],
        },
    )
    print(json.dumps(summary, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--prepared")
    parser.add_argument("--target", type=float, nargs=4, required=True, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--save-full-mask", action="store_true")
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        destination = Path(args.output)
        destination.mkdir(parents=True, exist_ok=True)
        write_json(
            destination / "segmentation_failure.json",
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        print("SEGMENTATION_ERROR " + str(exc), file=sys.stderr, flush=True)
        raise
