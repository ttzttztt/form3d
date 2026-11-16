"""Select a local target mask without loading ML libraries in FastAPI."""

import json
import os
from pathlib import Path
from statistics import median

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".models" / "sam2.1-hiera-tiny"


def segmentation_python():
    configured = os.getenv("SAM2_PYTHON")
    candidate = (
        Path(configured)
        if configured
        else ROOT / ".venv-sam2" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    return str(candidate.resolve()) if candidate.is_file() else None


def segmentation_status():
    weights = (MODEL / "sam2.1_hiera_tiny.pt").is_file() and (MODEL / "provenance.json").is_file()
    source = (ROOT / ".tools" / "SAM2" / "sam2" / "sam2_image_predictor.py").is_file()
    runtime = {}
    try:
        runtime = json.loads((MODEL / "runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    interpreter = segmentation_python()
    checked = bool(
        interpreter
        and runtime.get("inference_tested")
        and os.path.normcase(interpreter) == os.path.normcase(runtime.get("python", ""))
    )
    return {
        "available": bool(weights and source and checked),
        "model": "SAM 2.1 Hiera Tiny",
        "mode": "local_box_prompt",
        "weights_ready": weights,
        "runtime_ready": checked,
        "score_is_accuracy": False,
        "hidden_surface_completion": False,
    }


def image_background_kind(path):
    """Conservative routing only, not a semantic foreground quality score."""
    with Image.open(path) as source:
        image = source.convert("RGBA")
    w, h = image.size
    edges = []
    for bounds in ((0, 0, w, 1), (0, h - 1, w, h), (0, 0, 1, h), (w - 1, 0, w, h)):
        edges.extend(image.crop(bounds).getdata())
    if sum(pixel[3] < 32 for pixel in edges) / len(edges) > 0.5:
        return "provided_alpha"
    background = [median(pixel[channel] for pixel in edges) for channel in range(3)]
    close = sum(max(abs(pixel[channel] - background[channel]) for channel in range(3)) <= 8 for pixel in edges) / len(
        edges
    )
    return "white_background" if min(background) >= 235 and close >= 0.97 else "scene"


def choose_segmentation(path, requested, available, source_path=None):
    # A tight crop may touch a metallic edge and stop looking white. Route
    # from the unchanged source, while preserving any already supplied alpha.
    prepared_kind = image_background_kind(path)
    kind = prepared_kind if prepared_kind == "provided_alpha" else image_background_kind(source_path or path)
    if requested == "sam2":
        if not available:
            raise ValueError("SAM 2 精细分割尚未完成实际运行验证")
        return "sam2", kind
    if requested == "basic":
        return "basic", kind
    # A white source with subject touching the crop edge benefits from an
    # instance mask: connected-white removal can retain soft floor shadows.
    needs_instance = kind == "scene" or kind == "white_background" and prepared_kind == "scene"
    return ("sam2" if needs_instance and available else "basic"), kind
