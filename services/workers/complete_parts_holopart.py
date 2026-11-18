"""Complete each surface part of a segmented mesh into a closed solid with local HoloPart.

    complete_parts_holopart.py --input segmented.glb --output OUT [--steps 10] [--seed 42]

Input: a GLB scene with one mesh per part (segment_shape_by_photo.py). Each part is completed in the
context of the whole object (HoloPart's whole-surface condition), so hidden faces are filled in by the
model. Output: completed.glb (one mesh per part, same names) and completion.json. Completed hidden
geometry is generated, never observed. Runs locally; nothing is uploaded.
"""

import argparse
import importlib.machinery
import json
import sys
import time
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services/workers"), str(ROOT / ".tools/HoloPart")]
WEIGHTS = ROOT / ".models/holopart"
SAMPLES = 20480  # surface samples per condition, as in the HoloPart reference script
NORMALIZE = 0.7


def install_torch_cluster_stub():
    """HoloPart imports torch_cluster (fps, nearest); Windows wheels are unavailable here."""
    import torch
    from holopart_runtime import fps

    if "torch_cluster" in sys.modules:
        return

    def nearest(x, y, batch_x=None, batch_y=None):
        out = []
        for start in range(0, len(x), 8192):
            out.append(torch.cdist(x[start : start + 8192].float(), y.float()).argmin(1))
        return torch.cat(out)

    module = types.ModuleType("torch_cluster")
    module.__spec__ = importlib.machinery.ModuleSpec("torch_cluster", loader=None)
    module.fps, module.nearest = fps, nearest
    sys.modules["torch_cluster"] = module
    # diso (CUDA marching cubes) only serves the flash decoder; the hierarchical one uses skimage.
    if "diso" not in sys.modules:
        diso = types.ModuleType("diso")
        diso.__spec__ = importlib.machinery.ModuleSpec("diso", loader=None)
        diso.DiffDMC = None
        sys.modules["diso"] = diso


def conditions(scene, device):
    import torch
    import trimesh

    names = list(scene.geometry)
    whole = trimesh.util.concatenate([scene.geometry[n] for n in names])
    labelled, part_cond, local_cond, centres, scales = [], [], [], [], []
    for index, name in enumerate(names):
        mesh = scene.geometry[name]
        points, faces = mesh.sample(SAMPLES, return_index=True)
        normals = mesh.face_normals[faces]
        labelled.append(np.c_[points, np.full(len(points), index)])
        cond = torch.FloatTensor(np.c_[points, normals])
        local = cond.clone()
        centre = (local[:, :3].max(0)[0] + local[:, :3].min(0)[0]) / 2
        local[:, :3] -= centre
        scale = (local[:, :3].abs().max() / (0.95 * NORMALIZE)).item()
        local[:, :3] /= scale
        part_cond.append(cond)
        local_cond.append(local)
        centres.append(centre)
        scales.append(scale)
    labelled = np.concatenate(labelled)
    points, faces = whole.sample(SAMPLES, return_index=True)
    normals = whole.face_normals[faces]
    owner = sys.modules["torch_cluster"].nearest(torch.FloatTensor(points), torch.FloatTensor(labelled[:, :3]))
    owner = labelled[owner.numpy(), 3]
    whole_cond = [torch.FloatTensor(np.c_[points, normals, (owner == i).astype(np.float32)]) for i in range(len(names))]
    return names, {
        "whole_cond": torch.stack(whole_cond).to(device),
        "part_cond": torch.stack(part_cond).to(device),
        "part_local_cond": torch.stack(local_cond).to(device),
        "centres": centres,
        "scales": scales,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--octree-depth", type=int, default=7)
    parser.add_argument("--refine-depth", type=int, help="hierarchical refinement depth (default: octree depth + 1)")
    parser.add_argument("--parts", help="comma-separated part names to complete (default: all)")
    args = parser.parse_args()
    from scipy.spatial import cKDTree
    import torch
    import trimesh

    install_torch_cluster_stub()
    from holopart.inference_utils import hierarchical_extract_geometry
    from holopart.pipelines.pipeline_holopart import HoloPartPipeline

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    scene = trimesh.load(args.input, force="scene")
    pipe = HoloPartPipeline.from_pretrained(str(WEIGHTS)).to("cuda", torch.float16)
    names, batch = conditions(scene, "cuda")
    result, report = trimesh.Scene(), []
    wanted = set(args.parts.split(",")) if args.parts else set(names)
    diagonal = float(np.linalg.norm(scene.extents))
    for i, name in enumerate(names):
        if name not in wanted:
            continue
        tick = time.monotonic()
        with torch.no_grad():
            latent = pipe(
                part_surface=batch["part_cond"][i : i + 1],
                whole_surface=batch["whole_cond"][i : i + 1],
                part_local_surface=batch["part_local_cond"][i : i + 1],
                num_inference_steps=args.steps,
                guidance_scale=3.5,
                generator=torch.Generator(device="cuda").manual_seed(args.seed),
                output_type="latent",
            ).samples
            torch.cuda.synchronize()
            sampled = time.monotonic()
            decoded = hierarchical_extract_geometry(
                lambda x: pipe.vae.decode(latent[:1], sampled_points=x).sample,
                "cuda",
                bounds=(-1.05, -1.05, -1.05, 1.05, 1.05, 1.05),
                dense_octree_depth=args.octree_depth,
                hierarchical_octree_depth=args.refine_depth or args.octree_depth + 1,
            )
        pieces = [trimesh.Trimesh(v.astype(np.float32), f) for v, f in decoded if len(f)]
        if not pieces:
            report.append({"part_id": name, "status": "empty_decode"})
            continue
        mesh = trimesh.util.concatenate(pieces)
        mesh.apply_scale(batch["scales"][i])
        mesh.apply_translation(batch["centres"][i].numpy())
        source = scene.geometry[name]
        # Fidelity: the completed solid must still cover the observed surface it was grown from.
        gap, _ = cKDTree(mesh.sample(30000)).query(source.sample(5000))
        result.add_geometry(mesh, node_name=name, geom_name=name)
        report.append(
            {
                "part_id": name,
                "status": "completed",
                "faces": int(len(mesh.faces)),
                "watertight": bool(mesh.is_watertight),
                "volume": float(abs(mesh.volume)) if mesh.is_watertight else None,
                "source_area": float(source.area),
                "completed_area": float(mesh.area),
                "sample_seconds": round(sampled - tick, 1),
                "decode_seconds": round(time.monotonic() - sampled, 1),
                "source_gap_mean_rel": float(gap.mean() / diagonal),
                "source_gap_p95_rel": float(np.percentile(gap, 95) / diagonal),
            }
        )
        print("PART_COMPLETED", i + 1, len(names), name, flush=True)
        torch.cuda.empty_cache()
    result.export(output / "completed.glb")
    (output / "completion.json").write_text(
        json.dumps(
            {
                "method": "holopart_local",
                "steps": args.steps,
                "seed": args.seed,
                "hidden_geometry": "generated_not_observed",
                "parts": report,
                "elapsed_seconds": time.monotonic() - started,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("HOLOPART_DONE", sum(r["status"] == "completed" for r in report), len(names), flush=True)


if __name__ == "__main__":
    main()
