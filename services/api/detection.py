"""Bridge to an isolated local ML interpreter; the web API stays lightweight."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from .gpu import GPU_LOCK

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".models" / "grounding-dino-tiny"
LOCK = GPU_LOCK
DETECTOR_REVISION = hashlib.sha256((ROOT / "services" / "workers" / "detect_objects.py").read_bytes()).hexdigest()[:12]


def vision_python():
    configured = os.getenv("VISION_PYTHON")
    if configured:
        return configured if Path(configured).is_file() else None
    local = ROOT / ".venv-vision" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if local.is_file():
        return str(local)
    if importlib.util.find_spec("torch") and importlib.util.find_spec("transformers"):
        return sys.executable
    return None


def detector_status():
    ready = all((MODEL / file).is_file() for file in ["config.json", "model.safetensors", "preprocessor_config.json", "tokenizer_config.json", "vocab.txt"])
    return {"available": bool(vision_python() and ready), "model": "Grounding DINO Tiny", "mode": "local",
            "weights_ready": ready, "runtime_ready": bool(vision_python()),
            "categories": ["柜子", "书柜", "花瓶", "沙发", "扶手椅", "椅子", "盆栽", "桌子", "落地灯"]}


def analyze_image(store, image_id):
    image = store.image(image_id)
    if not image:
        return
    try:
        # Limit local GPU concurrency. No image is submitted to an outside API.
        with LOCK:
            store.update_image(image_id, lambda item: item.update(analysis={"status": "running", "objects": []}))
            output = store.root / "images" / image_id / "detection.json"
            completed = subprocess.run([vision_python(), str(ROOT / "services" / "workers" / "detect_objects.py"),
                                        "--input", str(store.root / image["normalized_path"]), "--output", str(output),
                                        "--model", str(MODEL), "--device", os.getenv("VISION_DEVICE", "auto")],
                                       capture_output=True, timeout=240, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            (output.parent / "detection.log").write_bytes(completed.stdout + b"\n" + completed.stderr)
            if completed.returncode or not output.is_file():
                raise ValueError("本地识别未能完成，可点击重新识别；详情见图片目录中的 detection.log")
            result = json.loads(output.read_text(encoding="utf-8"))
            result["status"] = "completed"
            store.update_image(image_id, lambda item: item.update(analysis=result))
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else "本地识别暂时失败，可重新识别或手工选择目标"
        store.update_image(image_id, lambda item: item.update(analysis={"status": "failed", "objects": [], "error": message}))
