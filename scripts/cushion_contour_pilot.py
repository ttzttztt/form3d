import sys,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import numpy as np,trimesh
from shapely.geometry import MultiPoint
from solid_partition import partition_box
OUT=ROOT/'experiments/complete_cushion_20261112';d=np.load(OUT/'source_selection.npz');v=d['vertices'];f=d['faces'];guide=trimesh.Trimesh(v,f[d['selected']],process=False);guide.remove_unreferenced_vertices();source=trimesh.Trimesh(v,f,process=False)
run=json.loads((OUT/'actual_run.json').read_text(encoding='utf-8'));bounds=run['plan']['bounds_world'];hull=MultiPoint(guide.vertices[:,[0,2]]).convex_hull;diagonal=float(np.linalg.norm(source.extents));poly=hull.buffer(diagonal*.0015).simplify(diagonal*.003,preserve_topology=True);points=np.array(poly.exterior.coords)[:-1]
# Simplification can cut inside the measured hull: add outward clearance.
center=points.mean(0);points=center+(points-center)*1.015;area=np.sum(points[:,0]*np.roll(points[:,1],-1)-points[:,1]*np.roll(points[:,0],-1));points=points if area>0 else points[::-1]
planes=[]
for a,b in zip(points,np.roll(points,-1,axis=0)):
    delta=b-a;n=np.array([-delta[1],0,delta[0]]);n/=np.linalg.norm(n);planes.append((np.array([a[0],0,a[1]]),n))
for ratio in (1.,2.):
    for angle in np.arange(8)*np.pi/4:
        outward=np.array([np.cos(angle),ratio,np.sin(angle)]);outward/=np.linalg.norm(outward);support=float((guide.vertices@outward).max())+diagonal*.0003;planes.append((outward*support,-outward))
start=time.monotonic();_,seat,caps,body,body_caps,evidence=partition_box(source,bounds,planes)
for name,m in [('cushion_contour',seat),('body_contour',body)]:m.export(OUT/(name+'_pilot.glb'));print(name,{'faces':len(m.faces),'watertight':m.is_watertight,'bounds':m.bounds.tolist()},flush=True)
print({'planes':len(planes),'seconds':time.monotonic()-start,**evidence},flush=True)
np.savez_compressed(OUT/'contour_pilot.npz',seat_vertices=seat.vertices,seat_faces=seat.faces,seat_caps=caps,body_vertices=body.vertices,body_faces=body.faces,body_caps=body_caps,points=points)
