import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.api.glb_document import read_glb
from mesh_quality import inspect_document

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    doc, binary, _ = read_glb(args.input)
    Path(args.output).write_text(
        json.dumps(inspect_document(doc, binary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
