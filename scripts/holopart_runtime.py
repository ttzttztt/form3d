"""Explicit real CPU farthest-point sampling for local HoloPart on Windows.

This is a deterministic NumPy implementation, not a torch_cluster CUDA kernel.
It preserves FPS semantics but is not claimed bitwise equivalent for ties.
"""
import importlib.util,importlib.machinery,sys,types
from pathlib import Path
import numpy as np


def fps(x,batch=None,ratio=.5,random_start=True,**kwargs):
    import torch
    if kwargs:raise ValueError('Unsupported FPS arguments: '+str(sorted(kwargs)))
    if x.ndim!=2 or not torch.isfinite(x).all()or not 0<ratio<=1:raise ValueError('FPS requires finite points and a ratio in (0,1]')
    values=x.detach().float().cpu().numpy().astype(np.float64)
    labels=np.zeros(len(values),dtype=np.int64)if batch is None else batch.detach().cpu().numpy()
    if labels.shape!=(len(values),):raise ValueError('Invalid FPS batch labels')
    output=[]
    for label in np.unique(labels):
        indices=np.flatnonzero(labels==label);points=values[indices];count=int(np.ceil(len(points)*float(ratio)))
        current=int(torch.randint(len(points),(1,)).item())if random_start else 0
        distances=np.full(len(points),np.inf);selected=np.zeros(len(points),dtype=bool)
        for _ in range(count):
            output.append(int(indices[current]));selected[current]=True
            distances=np.minimum(distances,np.sum((points-points[current])**2,axis=1))
            distances[selected]=-np.inf;current=int(np.argmax(distances))
    return torch.tensor(output,dtype=torch.long,device=x.device)


def load_pipeline_class():
    source=Path(__file__).resolve().parents[1]/'.tools/HoloPart';sys.path.insert(0,str(source))
    native=importlib.util.find_spec('torch_cluster')is not None
    if not native:
        module=types.ModuleType('torch_cluster');module.__spec__=importlib.machinery.ModuleSpec('torch_cluster',loader=None)
        module.fps=fps;sys.modules['torch_cluster']=module
    from holopart.pipelines.pipeline_holopart import HoloPartPipeline
    return HoloPartPipeline,{'fps_backend':'torch_cluster'if native else'numpy_cpu_exact_greedy','fps_bitwise_equivalence_to_cuda_verified':False}
