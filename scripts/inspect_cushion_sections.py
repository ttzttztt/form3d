import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import numpy as np,trimesh
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
OUT=ROOT/'experiments/complete_cushion_20261112';d=np.load(OUT/'source_selection.npz');v=d['vertices'];f=d['faces'];mesh=trimesh.Trimesh(v,f,process=False);sel=trimesh.Trimesh(v,f[d['selected']],process=False)
fig,axes=plt.subplots(2,4,figsize=(16,9),layout='constrained')
tasks=[(0,x,[2,1],f'x={x}') for x in (0,.4,.55,.65)]+[(1,y,[0,2],f'y={y}') for y in (.35,.55,.85,1.1)]
for ax,(axis,pos,plane,title) in zip(axes.ravel(),tasks):
    normal=np.eye(3)[axis];origin=normal*pos
    for m,color in [(mesh,'#555555'),(sel,'#9854df')]:
        lines=trimesh.intersections.mesh_plane(m,normal,origin)
        ax.add_collection(LineCollection(lines[:,:,plane],colors=color,linewidths=1))
    ax.autoscale();ax.set_aspect('equal');ax.set_title(title);ax.set_xlabel('xyz'[plane[0]]);ax.set_ylabel('xyz'[plane[1]]);ax.grid(alpha=.25)
fig.savefig(OUT/'source_sections.png',dpi=140)
