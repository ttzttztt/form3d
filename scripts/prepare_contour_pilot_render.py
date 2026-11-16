from pathlib import Path
import numpy as np,trimesh
from trimesh.visual.material import PBRMaterial
from trimesh.visual.texture import TextureVisuals
OUT=Path(__file__).resolve().parents[1]/'experiments/complete_cushion_20261112';d=np.load(OUT/'contour_pilot.npz');v=d['seat_vertices'];f=d['seat_faces'];caps=d['seat_caps']
for diagnostic in (False,True):
    parts=[]
    for inferred in (False,True):
        fs=f[caps==inferred]
        if inferred:vertices=v[fs].reshape(-1,3);faces=np.arange(len(vertices)).reshape(-1,3)
        else:vertices=v;faces=fs
        m=trimesh.Trimesh(vertices,faces,process=False);m.remove_unreferenced_vertices();m.visual=TextureVisuals(material=PBRMaterial(baseColorFactor=[240,160,68,255] if diagnostic and inferred else [65,130,170,255],roughnessFactor=.85));parts.append(m)
    trimesh.Scene(parts).export(OUT/('contour_pilot_diagnostic.glb' if diagnostic else 'contour_pilot_colored.glb'))
