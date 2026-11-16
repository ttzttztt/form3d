"""Run the real cut without publishing, then write a diagnostic colour copy."""

import copy, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services/workers")]
from edit_asset import main
from services.api.glb_document import read_glb, write_glb

if __name__ == "__main__":
    main()
    output = Path(sys.argv[sys.argv.index("--output") + 1])
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    doc, binary, extra = read_glb(output / "model.glb")
    groups = manifest["operation"]["part_group_ids"]
    start = len(doc.setdefault("materials", []))
    for name, color in [
        ("preview_source", [0.05, 0.48, 0.72, 1]),
        ("preview_inferred", [1, 0.32, 0.025, 1]),
        ("preview_body", [0.45, 0.48, 0.53, 0.18]),
    ]:
        mat = {
            "name": name,
            "pbrMetallicRoughness": {"baseColorFactor": color, "metallicFactor": 0, "roughnessFactor": 0.8},
            "doubleSided": True,
        }
        if color[3] < 1:
            mat["alphaMode"] = "BLEND"
        doc["materials"].append(mat)
    for mesh in doc["meshes"]:
        for p in mesh["primitives"]:
            meta = p.get("extras", {})
            selected = meta.get("form_logical_group_id") in groups
            p["material"] = (
                start + (1 if meta.get("form_completion_role") == "inferred_interface" else 0)
                if selected
                else start + 2
            )
    write_glb(output / "diagnostic.glb", doc, binary, extra)
