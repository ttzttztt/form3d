# -*- coding: utf-8 -*-
"""Decoder-only native PartCrafter imports, isolated from the existing engines."""
import importlib.machinery,importlib.util,sys,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'.tools/PartCrafter'


def load_pipeline_class():
    sys.path.insert(0,str(SOURCE))
    point_encoder_available=importlib.util.find_spec('torch_cluster')is not None
    if not point_encoder_available:
        # Image-to-parts uses the learned decoder, never the mesh point encoder.
        # Fail if that unavailable path is accidentally invoked; no fake FPS.
        dependency=types.ModuleType('torch_cluster')
        dependency.__spec__=importlib.machinery.ModuleSpec('torch_cluster',loader=None)
        def unavailable_fps(*args,**kwargs):
            raise RuntimeError('Point-cloud encoding requires torch_cluster; only image-conditioned decoding is enabled')
        dependency.fps=unavailable_fps;sys.modules['torch_cluster']=dependency
    from src.pipelines.pipeline_partcrafter import PartCrafterPipeline
    return PartCrafterPipeline,{'point_cloud_encoding_available':point_encoder_available,'image_conditioned_decoder_only':True}


if __name__=='__main__':
    import json,torch,transformers,diffusers,accelerate
    pipeline,limits=load_pipeline_class()
    print(json.dumps({'import_passed':True,'python':sys.executable,'torch':torch.__version__,'transformers':transformers.__version__,'diffusers':diffusers.__version__,'accelerate':accelerate.__version__,'cuda_available':torch.cuda.is_available(),'device':torch.cuda.get_device_name(0)if torch.cuda.is_available()else None,**limits},indent=2))
