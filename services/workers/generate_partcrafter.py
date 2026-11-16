# -*- coding: utf-8 -*-
"""Offline joint image-to-parts inference. Raw slots are not semantic labels."""

import argparse, gc, hashlib, json, os, sys, time, traceback, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services/workers")]
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "4")


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def write(path, value):
    temporary = path.with_suffix(".writing")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.02 * (attempt + 1))


def run(args):
    import numpy as np
    from PIL import Image
    import torch, trimesh
    from partcrafter_runtime import load_pipeline_class

    binding = None
    if args.plan:
        from services.api.assembly_inputs import validate_generation_binding

        binding = validate_generation_binding(args.plan, args.input)
        if args.num_parts is not None and args.num_parts != binding["num_parts"]:
            raise ValueError("Requested count disagrees with the bound assembly plan")
        args.num_parts = binding["num_parts"]
        args.count_source = "image_plan"
    elif args.num_parts is None or args.count_source == "image_plan":
        raise ValueError("An image-derived count requires --plan; manual probes require --num-parts")
    output = Path(args.output)
    if output.exists():
        raise ValueError("Choose a new output folder; preserve previous attempts")
    output.mkdir(parents=True)
    started = time.monotonic()
    facts = {
        "engine": "PartCrafter",
        "mode": "joint_image_to_parts",
        "input_sha256": digest(args.input),
        "requested_parts": args.num_parts,
        "part_count_source": args.count_source,
        "seed": args.seed,
        "tokens_per_part": args.tokens,
        "steps": args.steps,
        "dense_octree_depth": args.dense_depth,
        "hierarchical_octree_depth": args.mesh_depth,
        "semantic_assignment_verified": False,
        "physical_structure_verified": False,
        "external_image_requests": False,
        "parts": [],
        "status": "running",
        "worker_revision": digest(__file__),
    }
    if binding:
        facts["plan_binding"] = binding
    facts["cfg_part_layout"] = args.cfg_part_layout
    sequence = 0

    def progress(stage, **extra):
        nonlocal sequence
        sequence += 1
        value = {"sequence": sequence, "stage": stage, "elapsed_seconds": round(time.monotonic() - started, 3), **extra}
        write(output / "progress.json", value)
        print(json.dumps(value), flush=True)

    try:
        progress("preparing_image")
        image = Image.open(args.input).convert("RGBA")
        bounds = image.getchannel("A").getbbox()
        if bounds is None:
            raise ValueError("Input image is transparent")
        cropped = image.crop(bounds)
        side = max(cropped.size)
        canvas = Image.new("RGBA", (round(side / 0.85),) * 2, "white")
        canvas.alpha_composite(cropped, ((canvas.width - cropped.width) // 2, (canvas.height - cropped.height) // 2))
        canvas = canvas.convert("RGB")
        canvas.thumbnail((768, 768))
        canvas.save(output / "model_input.png")
        facts["model_input_sha256"] = digest(output / "model_input.png")
        facts["preprocessing"] = {
            "provided_alpha_bounds": list(bounds),
            "foreground_fraction_of_square": 0.85,
            "inpainting": False,
        }
        model = ROOT / ".models/partcrafter"
        provenance = json.loads((model / "provenance.json").read_text(encoding="utf-8"))
        facts["model_revision"] = provenance["model_revision"]
        facts["source_revision"] = provenance["source_revision"]
        source = ROOT / ".tools/PartCrafter"
        facts["pipeline_source_sha256"] = digest(source / "src/pipelines/pipeline_partcrafter.py")
        if (source / "local_adaptations.json").is_file():
            facts["source_adaptations"] = json.loads((source / "local_adaptations.json").read_text(encoding="utf-8"))
        for entry in provenance["files"]:
            if not (model / entry["path"]).is_file() or (model / entry["path"]).stat().st_size != entry["bytes"]:
                raise ValueError("Installed model file is missing or truncated")
        pipeline_class, limits = load_pipeline_class()
        facts["runtime_limits"] = limits
        if not torch.cuda.is_available():
            raise ValueError("Native parts inference requires the local CUDA device")
        torch.set_num_threads(4)
        torch.manual_seed(args.seed)
        np.random.seed(args.seed)
        torch.cuda.reset_peak_memory_stats()
        progress("loading_weights")
        pipe = pipeline_class.from_pretrained(
            str(model), torch_dtype=torch.float16, local_files_only=True, low_cpu_mem_usage=True
        )
        # from_pretrained casts weights; explicitly cast nonpersistent positional
        # buffers too, matching upstream's .to(device, dtype) inference path.
        pipe.to("cuda", torch.float16)
        pipe.set_progress_bar_config(disable=True)
        original_encode = pipe.encode_image

        def encode_identical_once(self, images, device, num_images_per_prompt):
            if isinstance(images, list) and images and all(item is images[0] for item in images):
                embedded, negative = original_encode(images[:1], device, num_images_per_prompt)
                result = embedded.repeat(len(images), 1, 1), negative.repeat(len(images), 1, 1)
            else:
                result = original_encode(images, device, num_images_per_prompt)
            # The VAE is not used while sampling. The image encoder is not
            # needed after conditioning. Keep only denoising weights in VRAM.
            self.vae.to("cpu")
            self.image_encoder_dinov2.to("cpu")
            gc.collect()
            torch.cuda.empty_cache()
            facts["non_sampling_models_offloaded_during_denoising"] = True
            progress("conditioning_ready_sampling_weights_only")
            return result

        pipe.encode_image = types.MethodType(encode_identical_once, pipe)
        facts["identical_image_encoder_conditioning_deduplicated"] = True
        original_decode = pipe.vae.decode
        decode_slots = {}

        def decode_with_progress(z, sampled_points, *a, **kw):
            key = (z.untyped_storage().data_ptr(), z.storage_offset())
            if key not in decode_slots:
                decode_slots[key] = len(decode_slots) + 1
                progress("decoding_part", part_index=decode_slots[key], total=args.num_parts)
            return original_decode(z, sampled_points, *a, **kw)

        pipe.vae.decode = decode_with_progress
        facts["parameter_dtypes"] = {
            name: str(module.dtype)
            for name, module in [
                ("image_encoder", pipe.image_encoder_dinov2),
                ("transformer", pipe.transformer),
                ("vae", pipe.vae),
            ]
        }
        progress("sampling", step=0, total=args.steps)

        def callback(pipeline, index, timestep, values):
            progress("sampling", step=index + 1, total=args.steps)
            if index + 1 == args.steps:
                from safetensors.torch import save_file

                save_file(
                    {"latents": values["latents"].detach().cpu().contiguous()},
                    str(output / "sampled_latents.safetensors"),
                )
                facts["sampled_latents_sha256"] = digest(output / "sampled_latents.safetensors")
                # Sampling is finished. These weights are unused by mesh decode;
                # free their VRAM instead of spilling decoder tensors into shared RAM.
                # Release sampling weights; moving the whole transformer to
                # RAM needlessly competes with mesh decoding on 16 GB hosts.
                pipeline.transformer = None
                pipeline.image_encoder_dinov2 = None
                gc.collect()
                torch.cuda.empty_cache()
                pipeline.vae.to("cuda", torch.float16)
                facts["sampling_models_offloaded_before_decode"] = True
                facts["sampling_models_released_after_last_step"] = True
            return values

        # The tensor path explicitly resets slot identities for each CFG branch.
        # Keep the upstream integer layout available for controlled comparisons.
        layout = (
            args.num_parts
            if args.cfg_part_layout == "upstream"
            else torch.tensor([args.num_parts] * (2 if args.guidance > 1 else 1))
        )
        generated = pipe(
            image=[canvas] * args.num_parts,
            attention_kwargs={"num_parts": layout},
            num_tokens=args.tokens,
            num_inference_steps=args.steps,
            guidance_scale=args.guidance,
            generator=torch.Generator(device="cuda").manual_seed(args.seed),
            dense_octree_depth=args.dense_depth,
            hierarchical_octree_depth=args.mesh_depth,
            max_num_expanded_coords=16000000,
            callback_on_step_end=callback,
        )
        progress("exporting_raw_parts")
        meshes = generated.meshes
        scene = trimesh.Scene()
        failed = []
        if len(meshes) != args.num_parts:
            raise ValueError("Native generator returned a different slot count")
        for index, mesh in enumerate(meshes):
            identity = (
                "part_"
                + hashlib.sha256(
                    (facts["input_sha256"] + str(args.seed) + str(args.num_parts) + str(index)).encode()
                ).hexdigest()[:32]
            )
            row = {"slot": index, "id": identity, "semantic_kind": "unknown", "semantic_assignment_verified": False}
            if mesh is None or not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
                row.update(status="failed", reason="decoder_returned_no_finite_mesh")
                failed.append(index)
            else:
                mesh.visual = trimesh.visual.TextureVisuals(
                    material=trimesh.visual.material.PBRMaterial(
                        name="neutral_geometry_review",
                        baseColorFactor=[180, 187, 198, 255],
                        metallicFactor=0,
                        roughnessFactor=0.8,
                    )
                )
                file = f"part_{index:02d}.glb"
                mesh.export(output / file, include_normals=True)
                scene.add_geometry(mesh, geom_name=identity, node_name=identity)
                row.update(
                    status="raw_candidate",
                    file=file,
                    sha256=digest(output / file),
                    triangles=len(mesh.faces),
                    vertices=len(mesh.vertices),
                    bounds=mesh.bounds.tolist(),
                    watertight=bool(mesh.is_watertight),
                    consistent_winding=bool(mesh.is_winding_consistent),
                    volume=float(mesh.volume),
                    components=len(mesh.split(only_watertight=False)),
                )
            facts["parts"].append(row)
        if failed:
            raise ValueError("Some native part slots failed to decode; no dummy meshes or complete assembly published")
        scene.export(output / "object.glb", include_normals=True)
        facts.update(
            status="raw_candidates_ready",
            shared_coordinate_frame=True,
            object_sha256=digest(output / "object.glb"),
            appearance_review="unreviewed",
            semantic_assignment_verified=False,
        )
        progress("raw_candidates_ready")
        del pipe
        gc.collect()
        torch.cuda.empty_cache()
    except Exception as exc:
        facts.update(status="failed", error=str(exc))
        (output / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        facts["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if torch.cuda.is_available():
            facts["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
            facts["gpu_peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
        write(output / "generation.json", facts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--num-parts", type=int, choices=range(1, 17))
    parser.add_argument("--count-source", choices=["manual_experiment", "image_plan"], default="manual_experiment")
    parser.add_argument("--cfg-part-layout", choices=["upstream", "repeated_ids"], default="upstream")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tokens", type=int, default=1024, choices=[256, 512, 1024, 2048])
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--guidance", type=float, default=7.0)
    parser.add_argument("--dense-depth", type=int, default=7, choices=[6, 7, 8])
    parser.add_argument("--mesh-depth", type=int, default=8, choices=[7, 8, 9])
    run(parser.parse_args())
