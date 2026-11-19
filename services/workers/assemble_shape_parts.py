"""Assemble shape-first parts into an importable, editable assembly.

    assemble_shape_parts.py --plan PLAN --image NORMALIZED --regions R --segmentation S --completion C
                            --output OUT

Per part: the HoloPart solid when it still covers the observed surface (p95 gap <= MAX_GAP of the
object diagonal), otherwise the observed surface thickened into a closed shell and flagged for review.
The plan's parts are the photo regions (plus the remaining body), so every part keeps its photo mask
as evidence. Writes model.glb, plan.json and assembly.json (fit_parametric_parts.write_assembly).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services" / "workers"), str(ROOT / ".tools" / "geometry_extra")]

MAX_GAP = 0.03  # completed solid may stray this far (fraction of object diagonal) from the observed surface
SHELL = 0.012  # thickness of a thickened surface, fraction of the object diagonal
MAX_FACES = 15000  # per part in the published GLB
BODY = "__body__"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def thicken(surface, thickness):
    """Closed shell from an open surface: offset copy inwards plus side walls along the boundary."""
    surface = surface.copy()
    surface.merge_vertices()
    n = len(surface.vertices)
    inner = surface.vertices - surface.vertex_normals * thickness
    faces = [surface.faces, surface.faces[:, ::-1] + n]
    edges = np.sort(surface.edges, axis=1)
    _, index, counts = np.unique(edges, axis=0, return_index=True, return_counts=True)
    for a, b in surface.edges[index[counts == 1]]:  # boundary edges keep their face orientation
        faces.append(np.array([[b, a, a + n], [b, a + n, b + n]]))
    return trimesh.Trimesh(np.vstack([surface.vertices, inner]), np.vstack(faces), process=True)


def as_primitive(mesh):
    from photo_part_evidence import decimate_mesh

    mesh = decimate_mesh(mesh, MAX_FACES)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    # glTF requires unit normals; vertices left only on sliver faces can sum to a zero vector.
    normals = np.asarray(mesh.vertex_normals, np.float64)
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.where(length > 1e-8, normals / np.maximum(length, 1e-12), [0.0, 1.0, 0.0])
    return {
        "vertices": np.asarray(mesh.vertices, np.float32),
        "normals": normals.astype(np.float32),
        "uvs": np.zeros((len(mesh.vertices), 2), np.float32),
        "faces": np.asarray(mesh.faces, np.uint32),
    }


def main():
    parser = argparse.ArgumentParser()
    for name in ("--plan", "--image", "--regions", "--segmentation", "--completion", "--output"):
        parser.add_argument(name, required=True)
    args = parser.parse_args()
    from fit_parametric_parts import write, write_assembly
    from services.api.assembly_models import AssemblyPlan
    from services.api.assembly_planning import plan_from_image_observations

    plan_folder, output = Path(args.plan), Path(args.output)
    regions_folder, seg_folder, comp_folder = Path(args.regions), Path(args.segmentation), Path(args.completion)
    if output.exists():
        raise ValueError("Preserve previous assemblies; choose a new output folder")
    source_plan = json.loads((plan_folder / "plan.json").read_text(encoding="utf-8"))
    observations = json.loads((plan_folder / "observations.json").read_text(encoding="utf-8"))
    regions = {r["id"]: r for r in json.loads((regions_folder / "regions.json").read_text(encoding="utf-8"))["regions"]}
    segmentation = json.loads((seg_folder / "segmentation.json").read_text(encoding="utf-8"))
    completion = {
        r["part_id"]: r for r in json.loads((comp_folder / "completion.json").read_text(encoding="utf-8"))["parts"]
    }
    surfaces = trimesh.load(seg_folder / "segmented.glb", force="scene").geometry
    solids = trimesh.load(comp_folder / "completed.glb", force="scene").geometry
    diagonal = float(np.linalg.norm(trimesh.util.concatenate(list(surfaces.values())).extents))

    whole = np.asarray(Image.open(plan_folder / "whole_mask.png").convert("L")) > 127
    width, height = Image.open(args.image).size
    crop = observations["source_crop_pixels"]
    target = source_plan["furniture_target"]
    masks_folder = output / "masks"
    masks_folder.mkdir(parents=True)

    def record(name, kind, mask):
        mask_bytes = np.uint8(mask) * 255
        file = masks_folder / (name.strip("_") + ".png")
        Image.fromarray(mask_bytes).save(file)
        yy, xx = np.nonzero(mask)
        x0 = max(target["x"], (crop[0] + xx.min()) / width)
        y0 = max(target["y"], (crop[1] + yy.min()) / height)
        x1 = min(target["x"] + target["width"], (crop[0] + xx.max() + 1) / width)
        y1 = min(target["y"] + target["height"], (crop[1] + yy.max() + 1) / height)
        return {
            "kind": kind,
            "mask_sha256": digest(file),
            "target": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
            "visibility": "partial",
            "evidence_kind": "original_photo",
            "segment": name,
        }

    def region_mask(name):
        return np.asarray(Image.open(regions_folder / regions[name]["mask_file"]).convert("L")) > 127

    merged = segmentation.get("merged_smooth_seams", {})  # regions joined across smooth surface
    records, region_union = [], np.zeros(whole.shape, bool)
    for row in segmentation["parts"]:
        name = row["part_id"]
        if not row.get("faces") or name == BODY:
            continue
        mask = region_mask(name)
        for absorbed in merged.get(name, []):
            if absorbed != BODY:
                mask |= region_mask(absorbed)
        region_union |= mask
        kind = regions[name]["kind"]
        records.append(record(name, "other" if kind in ("part", "unknown") else kind, mask))
    if any(r["part_id"] == BODY and r.get("faces") for r in segmentation["parts"]):
        rest = whole & ~region_union
        records.append(record(BODY, "body", rest if rest.sum() > 50 else whole))
    plan = plan_from_image_observations(
        source_plan["primary_image_id"],
        source_plan["primary_image_sha256"],
        source_plan["object_category"],
        target,
        records,
    )
    plan = AssemblyPlan.model_validate(plan.model_dump())
    by_mask = {r["mask_sha256"]: r["segment"] for r in records}
    physical = [p for p in plan.parts if p.geometry_role == "physical_part"]

    meshes, notes, report = {}, {}, []
    for part in physical:
        segment = by_mask[part.observations[0].mask_sha256]
        done = completion.get(segment, {})
        gap = done.get("source_gap_p95_rel")
        if done.get("status") == "completed" and gap is not None and gap <= MAX_GAP and segment in solids:
            mesh, method = solids[segment], "holopart_completion"
            notes[part.id] = "可见表面来自原图；背面与遮挡部分由 HoloPart 补全（生成，未观察）"
        else:
            mesh, method = thicken(surfaces[segment], SHELL * diagonal), "observed_surface_thickened"
            notes[part.id] = "补全结果偏离原表面，改为把可见表面加厚成实体；需要检查"
        meshes[part.id] = as_primitive(mesh)
        part.hidden_surface_status = "inferred"
        report.append(
            {
                "part_id": part.id,
                "segment": segment,
                "kind": part.kind,
                "geometry": method,
                "completion_gap_p95_rel": gap,
                "needs_review": method != "holopart_completion",
            }
        )
    write_assembly(
        output,
        plan,
        physical,
        meshes,
        generator="img_to3D shape-first parts",
        root_name="家具装配（整体生成后按原图拆分，需检查）",
        group_kind="shape_first_part",
        note="",
        notes=notes,
        source_engine="hunyuan3d_2mini_photo_split_holopart",
        sources={
            "source_plan_sha256": digest(plan_folder / "plan.json"),
            "segmentation_sha256": digest(seg_folder / "segmentation.json"),
            "completion_sha256": digest(comp_folder / "completion.json"),
        },
        fit={
            "shape_first": {
                "max_gap": MAX_GAP,
                "parts": report,
                "camera_silhouette_iou": segmentation["camera"]["silhouette_iou"],
            }
        },
        method="photo_mask_lifting_with_crease_aware_propagation",
        assumptions=[
            "整体形状由 Hunyuan3D-2mini 从单张照片生成，尺寸为比例模型",
            "部件边界来自原图分区投影到整体网格；被遮挡的面按表面连续性推断",
            "部件背面与内部由 HoloPart 补全或由可见表面加厚，均非观察所得",
        ],
    )
    write(output / "shape_first_report.json", {"parts": report})
    print("SHAPE_FIRST_ASSEMBLY_BUILT", len(physical), sum(r["needs_review"] for r in report), flush=True)


if __name__ == "__main__":
    main()
