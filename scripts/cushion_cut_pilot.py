import json,time
from pathlib import Path
import numpy as np,trimesh
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/complete_cushion_20261112';d=np.load(OUT/'source_selection.npz');source=trimesh.Trimesh(d['vertices'],d['faces'],process=False)
bounds=np.array([[-.55,.27,-.40],[.55,1.15,.82]])
origins=[];normals=[]
for axis in range(3):
    for side in (0,1):
        n=np.eye(3)[axis]*(1 if side==0 else -1);o=np.eye(3)[axis]*bounds[side,axis];origins.append(o);normals.append(n)
inside=source;outside=[]
start=time.monotonic()
for o,n in zip(origins,normals):
    outside.append(trimesh.intersections.slice_mesh_plane(inside,-n,o,cap=False))
    inside=trimesh.intersections.slice_mesh_plane(inside,n,o,cap=False)
solid=trimesh.intersections.slice_mesh_plane(source,np.array(normals),np.array(origins),cap=True,engine='earcut')
cap=np.zeros(len(solid.faces),bool)
for o,n in zip(origins,normals):cap|=np.all(abs((solid.vertices[solid.faces]-o)@n)<1e-8,axis=1)
caps=trimesh.Trimesh(solid.vertices,solid.faces[cap],process=False);inverse=trimesh.Trimesh(caps.vertices,caps.faces[:,::-1],process=False);remainder=trimesh.util.concatenate(outside+[inverse]);remainder.merge_vertices(digits_vertex=7);remainder.remove_unreferenced_vertices();solid.merge_vertices(digits_vertex=7);solid.remove_unreferenced_vertices()
for name,m in [('cushion',solid),('body',remainder)]:
    m.export(OUT/(name+'_pilot.glb'));edges,counts=np.unique(m.edges_sorted,axis=0,return_counts=True);print(name,{'faces':len(m.faces),'watertight':m.is_watertight,'volume':m.volume,'boundary_edges':int((counts==1).sum()),'nonmanifold_edges':int((counts>2).sum())},flush=True)
print({'seconds':time.monotonic()-start,'cap_faces':int(cap.sum()),'observed_area_error':float(abs(inside.area+sum(m.area for m in outside)-source.area)/source.area)},flush=True)
from solid_partition import partition_box
_,seat,seat_caps,body,body_caps,evidence=partition_box(source,bounds)
for name,m in [('cushion_stitched',seat),('body_stitched',body)]:
    m.export(OUT/(name+'_pilot.glb'));edges,counts=np.unique(m.edges_sorted,axis=0,return_counts=True);print(name,{'faces':len(m.faces),'watertight':m.is_watertight,'volume':float(m.volume),'boundary_edges':int((counts==1).sum()),'nonmanifold_edges':int((counts>2).sum())},flush=True)
print(evidence,flush=True)
