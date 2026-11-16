"""Offline, memory-efficient Hunyuan3D-2mini shape inference and honest telemetry.

Exports geometry with a neutral material. No generated texture is implied.
The official FP16 checkpoint, config and source are pinned by setup_hunyuan3d.
"""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / '.models' / 'hunyuan3d-2mini'
SOURCE = ROOT / '.tools' / 'Hunyuan3D-2'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['U2NET_HOME'] = str(ROOT / '.models' / 'triposr')
os.environ.setdefault('OMP_NUM_THREADS', '4')

from generate_local3d import write_json


def load_pipeline(progress):
    import torch
    import yaml
    from accelerate import init_empty_weights
    from safetensors.torch import load_file
    from hy3dgen.shapegen.pipelines import Hunyuan3DDiTFlowMatchingPipeline, instantiate_from_config

    config = yaml.safe_load((MODEL / 'hunyuan3d-dit-v2-mini' / 'config.yaml').read_text(encoding='utf-8'))
    checkpoint = MODEL / 'hunyuan3d-dit-v2-mini' / 'model.fp16.safetensors'
    progress('loading', '以内存映射方式加载 Hunyuan3D-2mini FP16 权重')
    # Meta construction + assign avoids allocating an FP32 copy of the 3.8 GB
    # checkpoint. CUDA torch is shared, but all other packages are isolated.
    state = load_file(str(checkpoint), device='cpu')
    modules = {}
    loading = {}
    for group in ('model', 'vae', 'conditioner'):
        with init_empty_weights(include_buffers=False):
            module = instantiate_from_config(config[group])
        group_state = {key[len(group)+1:]: value for key,value in state.items() if key.startswith(group+'.')}
        dropped = []
        if group == 'vae':
            # The shape checkpoint omits the VAE's mesh-encoding branch. It is
            # never used by image-to-shape forward/decode, so do not instantiate
            # random or meta parameters for it and pretend they were trained.
            for name in ('encoder', 'pre_kl'):
                if not any(key.startswith(name+'.') for key in group_state):
                    delattr(module, name)
                    dropped.append(name)
        result = module.load_state_dict(group_state, strict=True, assign=True)
        if any(parameter.is_meta for parameter in module.parameters()):
            raise ValueError('Checkpoint left uninitialized parameters in '+group)
        modules[group] = module.eval()
        loading[group] = {'missing_keys':list(result.missing_keys),
                          'unexpected_keys':list(result.unexpected_keys),
                          'unused_encoding_modules_omitted':dropped}
    del state, group_state
    gc.collect()
    pipeline = Hunyuan3DDiTFlowMatchingPipeline(
        **modules, scheduler=instantiate_from_config(config['scheduler']),
        image_processor=instantiate_from_config(config['image_processor']),
        device='cpu', dtype=torch.float16)
    # The giant DINO encoder can overflow FP16 activations. BF16 has the same
    # parameter storage size but a wider exponent range on this Ampere GPU.
    # The conditioned embeddings are cast back by the official pipeline.
    pipeline.conditioner.to(dtype=torch.bfloat16)
    # This upstream plain pipeline class has Diffusers-style offload methods
    # but does not define DiffusionPipeline.components. Register the exact
    # modules it already owns so its published offload sequence can execute.
    pipeline.components={name:getattr(pipeline,name) for name in ('conditioner','model','vae')}
    pipeline.enable_model_cpu_offload(device='cuda')
    # Upstream's sampling code reads self.device; keep execution on CUDA while
    # Accelerate moves the conditioner, DiT and VAE there one at a time.
    pipeline.device = torch.device('cuda:0')
    # Full-grid decoding is slower but avoids the upstream hierarchical
    # decoder's empty refinement batches on this runtime. Keep original VAE.
    pipeline.vae.enable_flashvdm_decoder(enabled=False)
    return pipeline, loading


def run(args):
    started = time.monotonic()
    output = Path(args.output).resolve() if args.output else None
    if output:
        output.mkdir(parents=True, exist_ok=True)
    sequence = 0
    def progress(stage, message, **extra):
        nonlocal sequence
        sequence += 1
        value = {'sequence':sequence,'stage':stage,'message':message,
                 'elapsed_seconds':round(time.monotonic()-started,3), **extra}
        if output:
            try:
                write_json(output / 'local_progress.json', value)
            except OSError as exc:
                print('PROGRESS_WRITE_WARNING '+type(exc).__name__, flush=True)
        print('IMG3D_EVENT '+json.dumps(value,ensure_ascii=True),flush=True)
    progress('loading','启动 Hunyuan3D 独立运行环境')
    import numpy as np
    import torch
    import trimesh
    import psutil
    from PIL import Image
    sys.path.insert(0,str(SOURCE))
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
    if not torch.cuda.is_available():
        raise ValueError('Hunyuan3D 需要可用的 CUDA 显卡')
    required = [MODEL / 'hunyuan3d-dit-v2-mini' / file for file in ('config.yaml','model.fp16.safetensors')]
    if not all(path.is_file() for path in required):
        raise FileNotFoundError('Hunyuan3D 权重或配置尚未下载完成')
    torch.set_num_threads(4)
    if args.check:
        runtime = {'available':True,'model':'Hunyuan3D-2mini','mode':'shape_only',
                   'python':str(Path(sys.executable).resolve()),'torch':torch.__version__,
                   'device':torch.cuda.get_device_name(0),'offline':True}
        write_json(MODEL / 'runtime.json',runtime)
        print(json.dumps(runtime,ensure_ascii=True),flush=True)
        return
    if not output or not args.input:
        raise ValueError('--input 和 --output 为必填参数')

    torch.manual_seed(args.seed)
    torch.cuda.reset_peak_memory_stats()
    phases = {}
    process = psutil.Process()
    monitor_stop = threading.Event()
    memory = {'peak_process_rss_bytes':process.memory_info().rss}
    def monitor():
        while not monitor_stop.wait(.1):
            memory['peak_process_rss_bytes'] = max(memory['peak_process_rss_bytes'],process.memory_info().rss)
    watcher = threading.Thread(target=monitor,daemon=True)
    watcher.start()
    try:
        phase = time.monotonic()
        progress('background','准备 Hunyuan3D 形状参考图')
        image = Image.open(args.input).convert('RGBA')
        background_method = 'provided_input_alpha'
        if not args.keep_background:
            from local3d_preprocess import remove_product_background
            image,background_method=remove_product_background(image,ROOT/'.models'/'triposr')
        bounds=image.getchannel('A').point(lambda value:255 if value>32 else 0).getbbox()
        if bounds is None:
            raise ValueError('抠图后无可用主体，请调整目标区域')
        image=image.crop(bounds)
        image.save(output/'foreground.png')
        image.save(output/'model_input.png')
        phases['preparation_seconds']=time.monotonic()-phase
        phase = time.monotonic()
        pipeline, loading = load_pipeline(progress)
        numeric_checks={}
        def check_conditioner(module, inputs, values):
            for name,tensor in values.items():
                finite=bool(torch.isfinite(tensor).all())
                numeric_checks['conditioner_'+name]={'finite':finite,'dtype':str(tensor.dtype),
                    'max_abs':float(tensor.float().abs().max()) if finite else None}
                if not finite:
                    raise ValueError('Image conditioner produced non-finite embeddings; no usable model was generated')
        pipeline.conditioner.register_forward_hook(check_conditioner)
        original_extractor=pipeline.vae.surface_extractor
        def checked_extractor(grid_logits,**kwargs):
            finite=bool(torch.isfinite(grid_logits).all())
            numeric_checks['sdf_grid']={'finite':finite,'shape':list(grid_logits.shape),
                'min':float(grid_logits.min()) if finite else None,
                'max':float(grid_logits.max()) if finite else None}
            write_json(output/'numeric_checks.json',numeric_checks)
            if not finite:
                raise ValueError('VAE produced non-finite signed-distance grid')
            if not numeric_checks['sdf_grid']['min']<0<numeric_checks['sdf_grid']['max']:
                raise ValueError('No zero-crossing surface in SDF grid: '+json.dumps(numeric_checks['sdf_grid']))
            return original_extractor(grid_logits,**kwargs)
        pipeline.vae.surface_extractor=checked_extractor
        torch.cuda.synchronize()
        phases['load_seconds']=time.monotonic()-phase
        progress('inference','Hunyuan3D 正在推理几何形状；本轮不生成纹理')
        phase = time.monotonic()
        def on_step(step, timestep, outputs):
            latent=outputs.prev_sample
            if not bool(torch.isfinite(latent).all()):
                raise ValueError('Non-finite shape latents at sampling step '+str(step+1))
            if step % 5 == 0 or step == args.steps-1:
                progress('inference','Hunyuan3D 形状采样 %d/%d'%(step+1,args.steps),
                         sampling_step=step+1,sampling_steps=args.steps)
        with torch.inference_mode():
            meshes=pipeline(image=image,num_inference_steps=args.steps,guidance_scale=5.,
                            generator=torch.Generator(device='cuda').manual_seed(args.seed),
                            octree_resolution=args.resolution,num_chunks=4096,
                            callback=on_step,callback_steps=1,enable_pbar=True)
        torch.cuda.synchronize()
        phases['inference_and_decode_seconds']=time.monotonic()-phase
        if not meshes or meshes[0] is None:
            raise ValueError('Hunyuan3D 未能提取可用网格')
        mesh=meshes[0]
        if len(mesh.faces)<16 or not np.isfinite(mesh.vertices).all():
            raise ValueError('Hunyuan3D 网格为空或包含无效坐标')
        progress('export','导出中性灰色几何 GLB，保留完整网格')
        phase=time.monotonic()
        mesh.vertices[:,1]-=mesh.bounds[0,1]
        mesh.vertices[:,0]-=mesh.bounds[:,0].mean()
        mesh.vertices[:,2]-=mesh.bounds[:,2].mean()
        if mesh.volume<0:
            mesh.invert()
        mesh.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name='Neutral gray geometry review material; no generated texture',
            baseColorFactor=[.62,.62,.62,1],metallicFactor=0,roughnessFactor=.85))
        mesh.metadata.update(generator='Hunyuan3D-2mini',texture_source='none',scale_status='normalized_unverified')
        temporary=output/'model.generating.glb'
        mesh.export(str(temporary),file_type='glb',include_normals=True)
        temporary.replace(output/'model.glb')
        phases['export_seconds']=time.monotonic()-phase
        summary={'model':'Hunyuan3D-2mini','model_id':'tencent/Hunyuan3D-2mini',
                 'model_variant':'hunyuan3d-dit-v2-mini','mode':'shape_only',
                 'duration_seconds':round(time.monotonic()-started,3),
                 'phases_seconds':{key:round(value,3) for key,value in phases.items()},
                 'peak_vram_mb':round(torch.cuda.max_memory_allocated()/1024**2,1),
                 'peak_vram_reserved_mb':round(torch.cuda.max_memory_reserved()/1024**2,1),
                 'peak_process_rss_mb':round(memory['peak_process_rss_bytes']/1024**2,1),
                 'vram_measurement':'PyTorch allocator; excludes driver, desktop and other processes',
                 'rss_measurement':'process working set sampled every 100 ms; not total system RAM',
                 'steps':args.steps,'seed':args.seed,'resolution':args.resolution,'guidance_scale':5.,
                 'precision':'BF16 image conditioner; FP16 DiT and VAE',
                 'numeric_checks':numeric_checks,
                 'memory_strategy':'meta initialization, mmap weights, component CPU offload',
                 'volume_decoder':'official VanillaVolumeDecoder, full grid, CPU marching cubes',
                 'background_method':background_method,'texture_source':'none; neutral material only',
                 'input_sha256':hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
                 'foreground_sha256':hashlib.sha256((output/'foreground.png').read_bytes()).hexdigest(),
                 'model_sha256':hashlib.sha256((output/'model.glb').read_bytes()).hexdigest(),
                 'vertices':len(mesh.vertices),'triangles':len(mesh.faces),
                 'dimensions_normalized':mesh.extents.tolist(),'watertight':bool(mesh.is_watertight),
                 'coordinate_system':'glTF Y-up; source model orientation retained',
                 'worker_revision':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 'device':torch.cuda.get_device_name(0),'offline':True,
                 'checkpoint_loading':loading,
                 'provenance':json.loads((MODEL/'provenance.json').read_text(encoding='utf-8'))}
        write_json(output/'local_summary.json',summary)
        progress('generated','Hunyuan3D 几何已导出，等待文件检查和外观验收')
        print(json.dumps(summary,ensure_ascii=True),flush=True)
    finally:
        monitor_stop.set()
        watcher.join(timeout=1)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input')
    parser.add_argument('--output')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--keep-background',action='store_true')
    parser.add_argument('--steps',type=int,default=30,choices=[20,30,50])
    parser.add_argument('--resolution',type=int,default=256,choices=[256,384])
    parser.add_argument('--seed',type=int,default=42)
    args=parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        if args.output:
            failure={'status':'failed','error_type':type(exc).__name__,'error':str(exc),
                     'traceback':traceback.format_exc(),'measured_success_metrics':None}
            write_json(Path(args.output)/'failure.json',failure)
        print('LOCAL3D_ERROR '+type(exc).__name__+': '+str(exc),file=sys.stderr,flush=True)
        raise
