import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from services.api.assistant_assets import attach_asset
from services.api.store import Store

if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    notes = json.loads((directory / "modeling_notes.json").read_text(encoding="utf-8"))
    result = attach_asset(Store(Path(os.getenv("IMG3D_DATA_DIR", str(ROOT / ".data")))), args.job,
                          directory / "model.glb", notes, directory / "preview.png", directory / "source.blend")
    print(json.dumps({"job_id": result["id"], "status": result["status"], "model_url": result.get("model_url")}, ensure_ascii=True))
