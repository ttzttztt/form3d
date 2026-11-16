"""Run open-vocabulary detection locally. No product images leave this machine."""
import argparse
import json
import os
from pathlib import Path
import time
import hashlib

PROMPT = "cabinet. bookcase. sofa. armchair. chair. table. vase. potted plant. floor lamp."
LABELS = [
    ("bookcase", "书柜", "cabinet"), ("cabinet", "柜子", "cabinet"),
    ("armchair", "扶手椅", "sofa"), ("sofa", "沙发", "sofa"),
    ("potted plant", "盆栽", "plant"), ("plant", "盆栽", "plant"),
    ("vase", "花瓶", "vase"), ("table", "桌子", "table"),
    ("chair", "椅子", "chair"), ("lamp", "落地灯", "lamp"),
]


def iou(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    area_a, area_b = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    return intersection / max(area_a + area_b - intersection, 1e-8)


def detect(image_path, model_path, device="auto"):
    start = time.monotonic()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    import inspect
    import torch
    import transformers
    from PIL import Image
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    torch.set_num_threads(min(8, os.cpu_count() or 4))
    device = "cuda" if device == "auto" and torch.cuda.is_available() else "cpu" if device == "auto" else device
    processor = AutoProcessor.from_pretrained(str(model_path), local_files_only=True)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(str(model_path), local_files_only=True, disable_custom_kernels=True)
    model.to(device).eval()
    image = Image.open(image_path).convert("RGB")
    inputs = processor(images=image, text=PROMPT, return_tensors="pt", size={"shortest_edge": 640, "longest_edge": 960}).to(device)
    with torch.inference_mode():
        outputs = model(**inputs)
    postprocessor = processor.post_process_grounded_object_detection
    threshold_key = "threshold" if "threshold" in inspect.signature(postprocessor).parameters else "box_threshold"
    raw = postprocessor(outputs, input_ids=inputs.input_ids, text_threshold=.20,
                        target_sizes=[(image.height, image.width)], **{threshold_key: .23})[0]
    names = raw.get("text_labels", raw.get("labels", []))
    candidates = []
    for score, box, label in zip(raw["scores"].cpu().tolist(), raw["boxes"].cpu().tolist(), names):
        category = next((entry for entry in LABELS if entry[0] in str(label).lower()), None)
        if not category:
            continue
        x0, y0, x1, y1 = box
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(image.width, x1), min(image.height, y1)
        if x1 - x0 < 16 or y1 - y0 < 16:
            continue
        candidates.append({"label": category[1], "category": category[2], "raw_label": str(label),
                           "score": round(score, 4), "box": [x0, y0, x1, y1]})
    # Remove duplicate aliases but keep separate objects of the same category.
    kept = []
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        if any(iou(candidate["box"], previous["box"]) > .65 for previous in kept):
            continue
        kept.append(candidate)
        if len(kept) >= 30:
            break
    for index, candidate in enumerate(kept):
        x0, y0, x1, y1 = candidate.pop("box")
        candidate["id"] = "object_%02d" % index
        candidate["target"] = {"x": x0 / image.width, "y": y0 / image.height,
                               "width": (x1 - x0) / image.width, "height": (y1 - y0) / image.height}
    return {"model": "IDEA-Research/grounding-dino-tiny", "detector_revision": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12], "prompt": PROMPT, "transformers_version": transformers.__version__,
            "device": device, "duration_seconds": round(time.monotonic() - start, 2),
            "method": "local_open_vocabulary_detection", "objects": kept, "image_size": list(image.size)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=str(Path(__file__).resolve().parents[1] / ".models" / "grounding-dino-tiny"))
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    args = parser.parse_args()
    result = detect(Path(args.input), Path(args.model), args.device)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"objects": len(result["objects"]), "device": result["device"], "duration_seconds": result["duration_seconds"]}), flush=True)
