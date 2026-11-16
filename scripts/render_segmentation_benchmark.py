"""Blender entrypoint: compare actual old/new deliveries, same review scene."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from render_quality_benchmark import render_model

OUTPUT=ROOT/'experiments'/'segmentation_20261111'/'armchair'
render_model(ROOT/'experiments/quality_20261111/armchair/hunyuan/attempt_001/model.glb',
             OUTPUT/'renders','old_hunyuan')
render_model(OUTPUT/'web_run/model.glb',OUTPUT/'renders','sam2_hunyuan')
print('SEGMENTATION COMPARISON: actual old and new GLBs rendered',flush=True)
