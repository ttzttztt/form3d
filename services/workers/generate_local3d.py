"""Offline TripoSR inference in an isolated ML interpreter.

Uses CPU marching cubes (scikit-image) to avoid a platform-specific CUDA
extension; the learned image-to-triplane model still runs on CUDA.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".models" / "triposr"
SOURCE = ROOT / ".tools" / "TripoSR"
# Never fetch additional resources during a user's inference request.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["U2NET_HOME"] = str(MODEL)
os.environ.setdefault("OMP_NUM_THREADS", "4")


def write_json(path, value):
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows may briefly deny replacement while the parent polls this file.
    for attempt in range(12):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(.025 * (attempt + 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--resolution", type=int, choices=[128, 192, 256], default=192)
    parser.add_argument("--keep-background", action="store_true")
    args = parser.parse_args()
    start = time.monotonic()
    output = Path(args.output).resolve() if args.output else None
    counter = 0

    def progress(stage, message):
        nonlocal counter
        counter += 1
        item = {"sequence": counter, "stage": stage, "message": message,
                "elapsed_seconds": round(time.monotonic() - start, 2)}
        if output:
            try:
                write_json(output / "local_progress.json", item)
            except OSError as exc:
                # A progress notification is not a model-generation failure.
                print("PROGRESS_WRITE_WARNING " + type(exc).__name__, flush=True)
        print("IMG3D_EVENT " + json.dumps(item, ensure_ascii=True), flush=True)

    if output:
        output.mkdir(parents=True, exist_ok=True)
    progress("loading", "启动本地图生 3D 运行环境")
    import numpy as np
    import torch
    import trimesh
    from PIL import Image
    from skimage.measure import marching_cubes

    # Match torchmcubes' z/y/x output contract; upstream then converts to x/y/z.
    compatibility = types.ModuleType("torchmcubes")
    def cpu_marching_cubes(volume, level):
        vertices, faces, _, _ = marching_cubes(volume.detach().float().cpu().numpy(),
                                             level=level, allow_degenerate=False)
        return (torch.from_numpy(vertices[:, [2, 1, 0]].copy()),
                torch.from_numpy(faces.astype(np.int64).copy()))
    compatibility.marching_cubes = cpu_marching_cubes
    sys.modules["torchmcubes"] = compatibility
    sys.path.insert(0, str(SOURCE))
    from tsr.system import TSR
    from tsr.models.tokenizers import image as image_tokenizer
    from tsr.utils import to_gradio_3d_orientation

    def local_dino_config(repo_id, filename, **kwargs):
        if repo_id != "facebook/dino-vitb16" or filename != "config.json":
            raise ValueError("Unexpected remote resource requested during offline inference")
        return str(MODEL / "dino_config.json")
    image_tokenizer.hf_hub_download = local_dino_config
    required = [MODEL / name for name in ("model.ckpt", "config.yaml", "dino_config.json", "u2netp.onnx", "provenance.json")]
    if not all(path.is_file() for path in required):
        raise FileNotFoundError("Local model files missing; run services/workers/setup_local3d.py")
    if not torch.cuda.is_available():
        raise ValueError("本地自动建模需要可用的 CUDA 显卡，请检查 PyTorch 与显卡驱动")
    device = "cuda:0"
    torch.set_num_threads(4)
    if args.check:
        import rembg
        import onnxruntime
        ready = {"available": True, "python": str(Path(sys.executable).resolve()),
                 "model": "TripoSR", "device": torch.cuda.get_device_name(0),
                 "torch": torch.__version__, "cuda": torch.version.cuda,
                 "marching_cubes": "scikit-image (CPU)", "offline": True}
        write_json(MODEL / "runtime.json", ready)
        print(json.dumps(ready, ensure_ascii=True), flush=True)
        return
    if not args.input or not output:
        parser.error("--input and --output are required for generation")
    torch.manual_seed(42)
    torch.cuda.reset_peak_memory_stats()

    progress("background", "提取主体并准备本地模型输入")
    image = Image.open(args.input).convert("RGBA")
    background_method = "existing_alpha_or_input"
    if not args.keep_background:
        from local3d_preprocess import remove_product_background
        image, background_method = remove_product_background(image, MODEL)
    alpha = np.asarray(image.getchannel("A"))
    points = np.argwhere(alpha > 32)
    if len(points) < 64:
        raise ValueError("抠图后没有足够的主体像素，请调整选区，或关闭自动去背景后重试")
    top, left = points.min(axis=0)
    bottom, right = points.max(axis=0) + 1
    image = image.crop((int(left), int(top), int(right), int(bottom)))
    image.save(output / "foreground.png")
    side = max(32, int(max(image.size) / .85))
    square = Image.new("RGBA", (side, side), (128, 128, 128, 0))
    square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    background = Image.new("RGBA", square.size, (128, 128, 128, 255))
    model_input = Image.alpha_composite(background, square).convert("RGB")
    model_input = model_input.resize((512, 512), Image.Resampling.LANCZOS)
    model_input.save(output / "model_input.png")
    progress("loading", "加载 TripoSR 图生 3D 权重")
    model = TSR.from_pretrained(str(MODEL), config_name="config.yaml", weight_name="model.ckpt")
    model.eval().to(device)
    model.renderer.set_chunk_size(8192)
    progress("inference", "从当前图片推理三维形状与颜色")
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        codes = model([model_input], device=device)
    torch.cuda.synchronize()
    codes = codes.float()
    progress("extract", "提取三角网格与顶点颜色")
    with torch.inference_mode():
        mesh = model.extract_mesh(codes, has_vertex_color=True, resolution=args.resolution)[0]
    if len(mesh.faces) < 16 or not np.isfinite(mesh.vertices).all():
        raise ValueError("当前图片未产生可用三维网格，请换一张主体更完整的图片")
    # Official TripoSR orientation conversion puts Z-up generated meshes into
    # the Y-up convention expected by glTF and the workbench viewer.
    mesh = to_gradio_3d_orientation(mesh)
    # TripoSR's source reference camera faces +X; the official Gradio transform
    # leaves that face at -Z. Our viewer starts at +Z, so turn it toward the user.
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [0, 1, 0]))
    mesh.vertices[:, 1] -= mesh.bounds[0, 1]
    mesh.vertices[:, 0] -= mesh.bounds[:, 0].mean()
    mesh.vertices[:, 2] -= mesh.bounds[:, 2].mean()
    if mesh.volume < 0:
        mesh.invert()
    from local3d_export import prepare_vertex_appearance
    mesh = prepare_vertex_appearance(mesh)
    mesh.metadata.update(generator="TripoSR", units="normalized_unverified")
    progress("export", "导出带颜色的自包含 GLB")
    temporary = output / "model.generating.glb"
    mesh.export(str(temporary), file_type="glb", include_normals=True)
    temporary.replace(output / "model.glb")
    provenance = json.loads((MODEL / "provenance.json").read_text(encoding="utf-8"))
    summary = {
        "model": "TripoSR", "model_id": "stabilityai/TripoSR", "device": torch.cuda.get_device_name(0),
        "duration_seconds": round(time.monotonic() - start, 2),
        "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 1024 ** 2, 1),
        "resolution": args.resolution, "precision": "float16 inference / float32 mesh extraction",
        "background_method": background_method,
        "texture_source": "TripoSR predicted vertex colors", "offline": True,
        "coordinate_system": "glTF Y-up, reference front +Z",
        "color_encoding": "sRGB prediction converted to linear glTF vertex colors",
        "surface_material": "approximate nonmetal matte surface, not inferred PBR",
        "input_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
        "model_input_sha256": hashlib.sha256((output / "model_input.png").read_bytes()).hexdigest(),
        "vertices": len(mesh.vertices), "triangles": len(mesh.faces),
        "dimensions_normalized": mesh.extents.tolist(), "provenance": provenance,
    }
    write_json(output / "local_summary.json", summary)
    progress("generated", "本地模型已导出，准备检查 GLB")
    print(json.dumps(summary, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Parent owns validation/publication and stores detailed output locally.
        print("LOCAL3D_ERROR " + type(exc).__name__ + ": " + str(exc), file=sys.stderr, flush=True)
        raise
