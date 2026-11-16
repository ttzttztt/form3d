"""Parametric hard parts for the parts-first route (CPU only).

  from-plan  --plan P --output OUT
      Every planned physical part is a hard part (e.g. tabletop + legs): build the whole
      assembly from the 2D masks and depth priors. No AI generation is involved.

  refine     --assembly A --output OUT
      A is an exported AI assembly (export_planned_assembly.py). Hard parts are replaced by a
      box/cylinder fitted to the AI mesh when the fit deviates little; other parts are kept.

Both write OUT/{model.glb, plan.json, assembly.json} in the format attach_assembly_candidate
expects. Provenance of the source plan / assembly is recorded; nothing is marked accepted.
"""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services" / "workers"), str(ROOT / ".tools" / "geometry_extra")]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    temporary = Path(path).with_suffix(".writing")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


PALETTE = [[0.65, 0.69, 0.75, 1], [0.52, 0.59, 0.67, 1], [0.7, 0.65, 0.58, 1]]


def add_primitive(doc, binary, mesh):
    from asset_operations import append_array

    return {
        "attributes": {
            "POSITION": append_array(doc, binary, mesh["vertices"], "VEC3"),
            "NORMAL": append_array(doc, binary, mesh["normals"], "VEC3"),
            "TEXCOORD_0": append_array(doc, binary, mesh["uvs"], "VEC2"),
        },
        "indices": append_array(doc, binary, mesh["faces"].ravel(), "SCALAR", 5125, 34963),
    }


def from_plan(args):
    import numpy as np
    from PIL import Image
    from parametric_parts import is_hard, layout_from_masks
    from services.api.assembly_models import AssemblyPlan
    from services.api.glb_document import write_glb

    folder, output = Path(args.plan), Path(args.output)
    if output.exists():
        raise ValueError("Preserve previous assemblies; choose a new output folder")
    plan = AssemblyPlan.model_validate_json((folder / "plan.json").read_text(encoding="utf-8"))
    observations = json.loads((folder / "observations.json").read_text(encoding="utf-8"))
    if plan.status != "planned":
        raise ValueError("Unresolved image inventory cannot be built")
    physical = [p for p in plan.parts if p.geometry_role == "physical_part"]
    soft = [p.kind for p in physical if not is_hard(plan.object_category, p.kind)]
    if soft:
        raise ValueError("Parametric build needs every part to be a hard part; soft parts: " + ", ".join(soft))
    rows = {row["mask_sha256"]: row for row in observations["parts"]}
    load = lambda name: np.asarray(Image.open(folder / name).convert("L")) > 127  # noqa: E731
    inputs = []
    for part in physical:
        row = rows[part.observations[0].mask_sha256]
        if digest(folder / row["mask_file"]) != row["mask_sha256"]:
            raise ValueError("A part mask changed after planning")
        inputs.append({"id": part.id, "kind": part.kind, "mask": load(row["mask_file"])})
    meshes, assumptions, parameters = layout_from_masks(plan.object_category, inputs, load("whole_mask.png"))

    doc = {
        "asset": {"version": "2.0", "generator": "img_to3D parametric parts"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "家具装配（参数化，需检查）", "children": [], "extras": {"assembly_plan_id": plan.id}}],
        "meshes": [],
        "materials": [],
        "buffers": [{"byteLength": 0}],
    }
    binary = bytearray()
    nodes = {}
    for part in plan.parts:
        nodes[part.id] = len(doc["nodes"])
        doc["nodes"].append(
            {"name": part.name, "extras": {"assembly_part_id": part.id, "geometry_role": part.geometry_role}}
        )
    for index, part in enumerate(physical):
        primitive = add_primitive(doc, binary, meshes[part.id])
        primitive["material"] = len(doc["materials"])
        doc["materials"].append(
            {
                "name": part.name + " · 中性检查材质",
                "pbrMetallicRoughness": {
                    "baseColorFactor": PALETTE[index % 3],
                    "metallicFactor": 0,
                    "roughnessFactor": 0.8,
                },
            }
        )
        primitive["extras"] = {
            "form_logical_group_id": part.id,
            "form_part_name": part.name,
            "form_semantic_kind": part.kind,
            "form_group_kind": "parametric_part",
            "form_proposal_status": "needs_review",
            "form_completion_note": "按原图掩码与品类先验拟合的参数化构件；深度与隐藏结构未验证",
        }
        doc["nodes"][nodes[part.id]]["mesh"] = len(doc["meshes"])
        doc["meshes"].append({"name": part.name, "primitives": [primitive]})
        primitive_id = part.id + "__geometry"
        doc["nodes"][nodes[part.id]]["extras"]["form_part_ids"] = {"0": primitive_id}
        vertices = meshes[part.id]["vertices"]
        part.status, part.primitive_ids, part.hidden_surface_status = "ready", [primitive_id], "inferred"
        part.bounds_world = [vertices.min(0).tolist(), vertices.max(0).tolist()]
    for part in plan.parts:
        parent = nodes[part.parent_id] if part.parent_id else 0
        doc["nodes"][parent].setdefault("children", []).append(nodes[part.id])
        if part.geometry_role == "structural_group":
            part.status = "ready"
    output.mkdir(parents=True)
    write_glb(output / "model.glb", doc, binary)
    model_sha = digest(output / "model.glb")
    for part in physical:
        part.model_sha256 = model_sha
    everything = np.vstack([m["vertices"] for m in meshes.values()])
    plan.status, plan.overall_bounds_world = (
        "ready_for_review",
        [everything.min(0).tolist(), everything.max(0).tolist()],
    )
    plan = AssemblyPlan.model_validate(plan.model_dump())
    write(output / "plan.json", plan.model_dump())
    write(
        output / "assembly.json",
        {
            "status": "candidate_ready_for_review",
            "source_engine": "parametric_from_masks",
            "source_plan_sha256": digest(folder / "plan.json"),
            "source_observations_sha256": digest(folder / "observations.json"),
            "model_sha256": model_sha,
            "part_ids": [p.id for p in physical],
            "parametric_fit": {
                "mode": "from_masks",
                "assumptions": assumptions,
                "parts": [{"part_id": pid, **value} for pid, value in parameters.items()],
            },
            "contacts": [],
            "placement_hypotheses": [{"method": "mask_layout_with_depth_prior", "assumptions": assumptions}],
            "materials": "independent_neutral_diagnostic_materials_not_recovered_textures",
            "semantic_assignment_verified": False,
            "physical_structure_verified": False,
            "appearance_accepted": False,
            "complete_assembly_accepted": False,
        },
    )
    print("PARAMETRIC_ASSEMBLY_BUILT", len(physical), flush=True)


def refine(args):
    from edit_asset import accessor_array
    from parametric_parts import fit_primitive, is_hard
    from services.api.assembly_models import AssemblyPlan
    from services.api.glb_document import compact_static, parts_catalog, read_glb, write_glb

    source, output = Path(args.assembly), Path(args.output)
    if output.exists():
        raise ValueError("Preserve previous assemblies; choose a new output folder")
    evidence = json.loads((source / "assembly.json").read_text(encoding="utf-8"))
    if digest(source / "model.glb") != evidence["model_sha256"]:
        raise ValueError("Source assembly model changed")
    plan = AssemblyPlan.model_validate_json((source / "plan.json").read_text(encoding="utf-8"))
    doc, binary, _ = read_glb(source / "model.glb")
    binary = bytearray(binary)
    owners = {p.id: p for p in plan.parts}
    rows = []
    for entry in parts_catalog(doc):
        part = owners.get(entry.get("logical_group_id"))
        if part is None or not is_hard(plan.object_category, part.kind):
            continue
        primitive = doc["meshes"][doc["nodes"][entry["node"]]["mesh"]]["primitives"][entry["primitive"]]
        vertices = accessor_array(doc, binary, primitive["attributes"]["POSITION"])
        faces = accessor_array(doc, binary, primitive["indices"]).reshape(-1, 3)
        try:
            built, report = fit_primitive(vertices, faces, part.kind)
        except Exception as exc:  # a failed fit keeps the AI part; it is reported, not hidden
            rows.append(
                {"part_id": part.id, "kind": part.kind, "replaced": False, "reason": f"fit_failed: {exc}"[:200]}
            )
            continue
        row = {"part_id": part.id, "kind": part.kind, "replaced": report["accepted"], **report}
        if report["accepted"]:
            replacement = add_primitive(doc, binary, built)
            primitive["attributes"] = replacement["attributes"]
            primitive["indices"] = replacement["indices"]
            primitive["attributes"].pop("TANGENT", None)
            primitive.setdefault("extras", {}).update(
                form_group_kind="parametric_part",
                form_completion_note="AI 部件已替换为拟合的参数化构件；偏差见 assembly.json",
            )
        else:
            row["reason"] = "deviation_above_threshold"
        rows.append(row)
    binary = compact_static(doc, binary)
    output.mkdir(parents=True)
    write_glb(output / "model.glb", doc, binary)
    model_sha = digest(output / "model.glb")
    for part in plan.parts:
        if part.geometry_role == "physical_part":
            part.model_sha256 = model_sha
    plan = AssemblyPlan.model_validate(plan.model_dump())
    write(output / "plan.json", plan.model_dump())
    refined = copy.deepcopy(evidence)
    refined.update(
        model_sha256=model_sha,
        source_assembly_sha256=evidence["model_sha256"],
        parametric_fit={"mode": "refine_ai_parts", "parts": rows},
    )
    write(output / "assembly.json", refined)
    print("PARAMETRIC_REFINED", sum(r["replaced"] for r in rows), len(rows), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("from-plan")
    build.add_argument("--plan", required=True)
    build.add_argument("--output", required=True)
    improve = commands.add_parser("refine")
    improve.add_argument("--assembly", required=True)
    improve.add_argument("--output", required=True)
    arguments = parser.parse_args()
    (from_plan if arguments.command == "from-plan" else refine)(arguments)
