"""Offline semantic planning with a local VLM; boxes remain unverified proposals."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("PYTORCH_ALLOC_CONF", "garbage_collection_threshold:0.7,max_split_size_mb:128")

PROMPT = """Identify the visible furniture and its complete parts in the image.
Return a JSON object with key "furniture", a list of furniture instances.
Each instance must have:
- "category": choose ONE value from sofa, chair, table, cabinet, other.
- "bbox": [left, top, right, bottom], numbers from 0 to 1000 relative to the FULL image.
- "parts": a list with ONE entry for EACH visible part instance.
Each part must have:
- "kind": choose ONE value from seat_cushion, back_cushion, bolster, backrest, armrest, frame, body, leg, tabletop, door, drawer, shelf, panel, other.
- "bbox": [left, top, right, bottom], numbers from 0 to 1000 relative to the FULL image.
- "description": a short visual description of this specific part.
List all individual seat cushions, back cushions and small pillows separately. A square pillow is back_cushion; a cylindrical pillow is bolster. ONE complete pillow is ONE part including its sides. Do not split fabric panels. A visibly continuous support base can be one frame.
Use body for a continuous upholstered seating/base unit without a visible removable seat-pad boundary. Never invent a separate seat cushion or internal frame for that unit. Do not label the whole furniture including pillows as one cushion or armrest. Do not invent hidden legs or internal frames. Exclude plants, books, people, dishes and decor. Separate furniture instances from each other. If no part can be identified, use an empty parts list. Write actual labels, never copy the list of options into a field. Return valid JSON only."""

COMPACT_PROMPT = """Locate the furniture and its visible whole parts. Return compact JSON only, with this structure: an object containing furniture (a list); each furniture has category, bbox, parts; each part has kind and bbox.
Choose one category: sofa, chair, table, cabinet, other.
Choose one kind per actual part: seat_cushion, back_cushion, bolster, backrest, armrest, frame, body, leg, tabletop, door, drawer, shelf, panel, other.
bbox is [left,top,right,bottom], coordinates 0 to 1000 in this image.
Count separate cushions and pillows separately. A complete square pillow is back_cushion; a complete cylindrical pillow is bolster. Use body for a continuous upholstered seating/base unit when no removable pad boundary is visible; do not invent a seat cushion or frame inside it. Include the full visible outline of each part. Do not subdivide fabric, repeat parts, list absent part types, or call the whole sofa including pillows one cushion. Exclude books, plants, people and dishes. Do not invent hidden components. Stop after listing the actual visible parts. No descriptions or commentary."""

# The body prompt helped the leather sofa but regressed on corduroy. Keep it
# explicit until broader image tests support using it as the default.
CONTINUOUS_BODY_PROMPT = PROMPT
CONTINUOUS_BODY_COMPACT_PROMPT = COMPACT_PROMPT
PROMPT = (
    PROMPT.replace("frame, body, leg", "frame, leg")
    .replace(
        "Use body for a continuous upholstered seating/base unit without a visible removable seat-pad boundary. Never invent a separate seat cushion or internal frame for that unit. ",
        "",
    )
    .replace("whole furniture including pillows as", "whole furniture as")
)
COMPACT_PROMPT = (
    COMPACT_PROMPT.replace("frame, body, leg", "frame, leg")
    .replace(
        "Use body for a continuous upholstered seating/base unit when no removable pad boundary is visible; do not invent a seat cushion or frame inside it. ",
        "",
    )
    .replace("whole sofa including pillows one", "whole sofa one")
)


def run(args):
    import torch
    from PIL import Image, ImageDraw
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration, BitsAndBytesConfig
    from transformers.generation.streamers import BaseStreamer
    from transformers import StoppingCriteria, StoppingCriteriaList
    from generate_partcrafter import write
    from services.api.assembly_proposals import normalize_proposal

    folder = Path(args.output)
    if folder.exists():
        raise ValueError("Use a new output folder to retain previous proposals")
    folder.mkdir(parents=True)
    started = time.monotonic()
    (folder / "progress.json").write_text(json.dumps({"stage": "loading_model"}), encoding="utf-8")
    model_path = ROOT / (".models/assembly-vlm-qwen3-" + args.model_size)
    provenance = json.loads((model_path / "provenance.json").read_text(encoding="utf-8"))
    torch.set_num_threads(4)
    torch.cuda.reset_peak_memory_stats()
    if args.quantization == "nf4":
        if args.vision_cpu:
            raise ValueError("The NF4 experiment uses one GPU placement; choose no CPU vision offload")
        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            str(model_path),
            dtype=torch.float16,
            device_map={"": 0},
            local_files_only=True,
            attn_implementation=args.attention,
            quantization_config=quantization,
        ).eval()
    elif args.vision_cpu:
        # A resident CPU vision encoder avoids Accelerate's meta offload
        # tensors interfering with Qwen's positional-embedding device lookup.
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            str(model_path), dtype=torch.float16, local_files_only=True, attn_implementation=args.attention
        ).eval()
        model.model.language_model.to("cuda")
        model.lm_head.to("cuda")
        model.tie_weights()
        model.model.visual.to(dtype=torch.float32)
        original_features = model.model.get_image_features

        def cpu_image_features(self, pixel_values, image_grid_thw=None, **kwargs):
            vision_started = time.monotonic()
            (folder / "progress.json").write_text(
                json.dumps({"stage": "encoding_image_on_cpu", "case": case["case"], "completed_cases": len(results)}),
                encoding="utf-8",
            )
            features = original_features(
                pixel_values.to("cpu"), image_grid_thw.to("cpu") if image_grid_thw is not None else None, **kwargs
            )
            (folder / "progress.json").write_text(
                json.dumps(
                    {
                        "stage": "decoding_text_on_gpu",
                        "case": case["case"],
                        "completed_cases": len(results),
                        "vision_seconds": round(time.monotonic() - vision_started, 3),
                    }
                ),
                encoding="utf-8",
            )
            return features

        model.model.get_image_features = types.MethodType(cpu_image_features, model.model)
    else:
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            str(model_path),
            dtype=torch.float16,
            device_map={"": 0},
            local_files_only=True,
            attn_implementation=args.attention,
        ).eval()
    processor = AutoProcessor.from_pretrained(
        str(model_path), local_files_only=True, min_pixels=112 * 112, max_pixels=args.image_edge**2
    )
    cases = (
        json.loads(Path(args.cases).read_text(encoding="utf-8"))
        if args.cases
        else [{"case": "single", "image": args.input}]
    )
    if args.case:
        cases = [case for case in cases if case["case"] in args.case]
    if not cases:
        raise ValueError("No selected cases")
    results = []
    for case in cases:
        if (folder / "cancel_requested").exists():
            break
        case_started = time.monotonic()
        destination = folder / case["case"]
        destination.mkdir()
        source = Path(case["image"])
        image = Image.open(source).convert("RGB")
        original_size = image.size
        crop_box = [0, 0, *original_size]
        if args.crop_target:
            if "target" not in case:
                raise ValueError("Selected-target planning requires a frozen target")
            t = case["target"]
            crop_box = [
                max(0, round((t["x"] - 0.015) * image.width)),
                max(0, round((t["y"] - 0.015) * image.height)),
                min(image.width, round((t["x"] + t["width"] + 0.015) * image.width)),
                min(image.height, round((t["y"] + t["height"] + 0.015) * image.height)),
            ]
            image = image.crop(crop_box)
        image.save(destination / "planner_input.png")
        prompt = (
            (CONTINUOUS_BODY_COMPACT_PROMPT if args.compact else CONTINUOUS_BODY_PROMPT)
            if args.continuous_body
            else (COMPACT_PROMPT if args.compact else PROMPT)
        )
        actual_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        if case.get("image_sha256", actual_sha) != actual_sha:
            raise ValueError("A frozen test image changed")
        (folder / "progress.json").write_text(
            json.dumps({"stage": "planning", "case": case["case"], "completed_cases": len(results)}), encoding="utf-8"
        )
        messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
        inputs = processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt"
        ).to("cuda")
        (destination / "input_diagnostics.json").write_text(
            json.dumps(
                {
                    "image_grid_thw": inputs["image_grid_thw"].tolist(),
                    "prompt_tokens": int(inputs["input_ids"].shape[-1]),
                    "vision_device": str(next(model.model.visual.parameters()).device),
                    "vision_dtype": str(next(model.model.visual.parameters()).dtype),
                    "text_device": str(model.get_input_embeddings().weight.device),
                    "text_dtype": str(model.get_input_embeddings().weight.dtype),
                }
            ),
            encoding="utf-8",
        )

        class ProgressStreamer(BaseStreamer):
            def __init__(self):
                self.first = True
                self.count = 0
                self.ids = []
                self.abort_reason = None

            def put(self, value):
                if self.first:
                    self.first = False
                    return
                self.count += value.numel()
                self.ids.extend(value.detach().cpu().reshape(-1).tolist())
                if self.count % 32 == 0:
                    before = torch.cuda.memory_reserved()
                    torch.cuda.empty_cache()
                    partial = processor.decode(self.ids, skip_special_tokens=True)
                    (destination / "partial_response.txt").write_text(partial, encoding="utf-8")
                    pairs = []
                    for kind, coords in re.findall(r'"kind"\s*:\s*"([^"]+)"\s*,\s*"bbox"\s*:\s*\[([^\]]+)\]', partial):
                        try:
                            pairs.append((kind, tuple(json.loads("[" + coords + "]"))))
                        except (ValueError, TypeError):
                            pass
                    if len(pairs) != len(set(pairs)):
                        self.abort_reason = "repeated_identical_semantic_part"
                    if (folder / "cancel_requested").exists():
                        self.abort_reason = "cancel_requested"
                    write(
                        folder / "progress.json",
                        {
                            "stage": "planning",
                            "case": case["case"],
                            "completed_cases": len(results),
                            "generated_tokens": self.count,
                            "case_elapsed_seconds": round(time.monotonic() - case_started, 3),
                            "gpu_allocated_bytes": torch.cuda.memory_allocated(),
                            "gpu_reserved_bytes": torch.cuda.memory_reserved(),
                            "reserved_before_cache_release": before,
                        },
                    )

            def end(self):
                pass

        streamer = ProgressStreamer()

        class StopOnInvalidLoop(StoppingCriteria):
            def __call__(self, *a, **kw):
                return streamer.abort_reason is not None

        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                max_new_tokens=args.max_tokens,
                do_sample=False,
                streamer=streamer,
                stopping_criteria=StoppingCriteriaList([StopOnInvalidLoop()]),
            )
        raw = processor.batch_decode(generated[:, inputs["input_ids"].shape[-1] :], skip_special_tokens=True)[0]
        (destination / "raw_response.txt").write_text(raw, encoding="utf-8")
        record = {
            "case": case["case"],
            "model_id": provenance["model_id"],
            "model_revision": provenance["model_revision"],
            "input_sha256": actual_sha,
            "image_size": list(original_size),
            "planner_input_crop_pixels": crop_box,
            "planner_input_sha256": hashlib.sha256((destination / "planner_input.png").read_bytes()).hexdigest(),
            "planning_scope": "selected_target_crop" if args.crop_target else "full_image",
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "external_image_requests": False,
            "proposal_only": True,
            "semantic_assignment_verified": False,
            "physical_structure_verified": False,
            "vision_encoder_on_cpu": args.vision_cpu,
            "text_dtype": "float16",
            "attention_implementation": args.attention,
            "runtime_quantization": args.quantization,
            "elapsed_seconds": round(time.monotonic() - case_started, 3),
            "output_tokens": int(generated.shape[-1] - inputs["input_ids"].shape[-1]),
        }
        try:
            if streamer.abort_reason:
                raise ValueError(streamer.abort_reason)
            parsed = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
            parsed, normalization_warnings = normalize_proposal(parsed)
            if not isinstance(parsed.get("furniture"), list):
                raise ValueError("No furniture list")
            for furniture in parsed["furniture"]:
                if furniture.get("category") not in ("sofa", "chair", "table", "cabinet", "other"):
                    raise ValueError("Unsupported category")
                for item in [furniture] + furniture.get("parts", []):
                    box = item["bbox"]
                    if (
                        len(box) != 4
                        or not all(isinstance(v, (int, float)) and 0 <= v <= 1000 for v in box)
                        or box[2] <= box[0]
                        or box[3] <= box[1]
                    ):
                        raise ValueError("Invalid normalized box")
                    item["bbox"] = [
                        (crop_box[i % 2] + v * image.size[i % 2] / 1000) / original_size[i % 2] * 1000
                        for i, v in enumerate(box)
                    ]
            record.update(status="proposal_ready", normalization_warnings=normalization_warnings, **parsed)
            overlay = Image.open(source).convert("RGB")
            draw = ImageDraw.Draw(overlay)
            colors = ["#d18b08", "#196ac4", "#9d43c4", "#179a75", "#ca415a"]
            for furniture in parsed["furniture"]:
                for index, part in enumerate(furniture.get("parts", [])):
                    box = [v * original_size[i % 2] / 1000 for i, v in enumerate(part["bbox"])]
                    draw.rectangle(box, outline=colors[index % len(colors)], width=3)
                    draw.text(box[:2], f"{index + 1}:{part['kind']}", fill=colors[index % len(colors)])
            overlay.save(destination / "boxes.png")
        except (ValueError, KeyError, TypeError) as exc:
            record.update(status="failed", error=str(exc))
        write(destination / "semantic_proposal.json", record)
        results.append(record)
        print(
            json.dumps(
                {"case": case["case"], "status": record["status"], "elapsed_seconds": record["elapsed_seconds"]}
            ),
            flush=True,
        )
        del inputs, generated
        torch.cuda.empty_cache()
    write(
        folder / "progress.json",
        {
            "stage": "cancelled" if (folder / "cancel_requested").exists() else "proposals_ready",
            "completed_cases": len(results),
        },
    )
    (folder / "run.json").write_text(
        json.dumps(
            {
                "results": results,
                "model_revision": provenance["model_revision"],
                "total_elapsed_seconds": round(time.monotonic() - started, 3),
                "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input")
    source.add_argument("--cases")
    parser.add_argument("--case", action="append")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-tokens", type=int, default=2200)
    parser.add_argument("--vision-cpu", action="store_true")
    parser.add_argument("--quantization", choices=["none", "nf4"], default="none")
    parser.add_argument("--model-size", choices=["2b", "4b"], default="2b")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument(
        "--continuous-body",
        action="store_true",
        help="Experimental whole upholstered body prompt; not enabled by default",
    )
    parser.add_argument("--crop-target", action="store_true")
    parser.add_argument("--image-edge", type=int, choices=[384, 512, 640, 768], default=512)
    parser.add_argument("--attention", choices=["eager", "sdpa"], default="eager")
    args = parser.parse_args()
    existed = Path(args.output).exists()
    try:
        run(args)
    except Exception as exc:
        if not existed and Path(args.output).is_dir() and not (Path(args.output) / "failure.json").exists():
            (Path(args.output) / "failure.json").write_text(
                json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        raise
