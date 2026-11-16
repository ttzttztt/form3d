from pathlib import Path
import json,numpy as np,trimesh
OUT=Path(__file__).resolve().parents[1]/'experiments/complete_cushion_20261112'
mesh=trimesh.load(OUT/'body_pilot.glb',force='mesh',process=False)
for digits in (9,8,7,6):
    m=mesh.copy();m.merge_vertices(digits_vertex=digits)
    for clean in (False,True):
        if clean:
            f=m.faces;m.update_faces((f[:,0]!=f[:,1])&(f[:,0]!=f[:,2])&(f[:,1]!=f[:,2]));m.update_faces(m.unique_faces());m.remove_unreferenced_vertices()
        e,c=np.unique(m.edges_sorted,axis=0,return_counts=True);b=e[c==1];l=np.linalg.norm(m.vertices[b[:,0]]-m.vertices[b[:,1]],axis=1)
        print({'digits':digits,'clean':clean,'boundary':len(b),'nonmanifold':int((c>2).sum()),'boundary_lengths':l.tolist(),'bounds':m.vertices[np.unique(b)].tolist()},flush=True)
        if digits==8 and clean:m.export(OUT/'body_cleaned_pilot.glb')
