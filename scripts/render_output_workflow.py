"""Render actual rejected and retried deliveries in identical review scenes."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from render_quality_benchmark import render_model
OUT=ROOT/'experiments/output_quality_20261111/real_runs/flat_vase'
for label,folder in [('hunyuan_rejected','01_hunyuan-mini'),('triposr_retry','02_triposr')]:
    render_model(OUT/'attempts'/folder/'model.glb',OUT/'renders',label,views_requested=['front','oblique','side','opposite_oblique'])
print('ACTUAL_RETRY_COMPARISON_RENDERED',flush=True)
