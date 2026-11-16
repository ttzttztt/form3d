"""Lightweight input-preparation bridge metadata; ML stays in a child process."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class InputNeedsAttention(ValueError):
    """The user must change the input; no usable model is being published."""


def preflight_python():
    configured = os.getenv("PREFLIGHT_PYTHON")
    candidate = (
        Path(configured)
        if configured
        else ROOT / ".venv-preflight" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    return str(candidate.resolve()) if candidate.is_file() else None


def preflight_status():
    interpreter = preflight_python()
    runtime = {}
    try:
        runtime = json.loads((ROOT / ".models/input-preflight/runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {
        "available": bool(
            interpreter
            and runtime.get("inference_tested")
            and os.path.normcase(interpreter) == os.path.normcase(runtime.get("python", ""))
        ),
        "model": "RapidOCR + Grounding DINO input screening",
        "hidden_surface_completion": False,
        "clutter_detection_tested": bool(runtime.get("clutter_inference_tested")),
    }
