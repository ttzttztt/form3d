"""Automatic seat seam and footprint trials on measured closed body candidates."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.tools/geometry_extra')]
import numpy as np,trimesh,pymeshlab,manifold3d as md
from shapely import concave_hull
from shapely.geometry import MultiPoint
from scipy.ndimage import gaussian_filter1d
from services.api.glb_document import read_glb,selected_primitives
from furniture_parts import primitive_data
from solid_partition import prepare_mesh
from complete_part import mesh_stats
out=ROOT/'experiments/solid_parts_20261113';records=[]
for case,ordinal in [('leather_sofa',1),('corduroy_sofa',0)]:
    doc,binary,_=read_glb(ROOT/'experiments/semantic_parts_20261113'/case/'model.glb');meshes=[]
    for part,p in selected_primitives(doc,[]):
        if part['semantic_kind']!='seat':continue
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);meshes.append(trimesh.Trimesh(w,f,process=False))
    observed,_=prepare_mesh(trimesh.util.concatenate(meshes));source=trimesh.load(out/f'{case}_bounded_{ordinal}.glb',force='mesh',process=False)
    low,high=observed.bounds;h=high[1]-low[1];diag=np.linalg.norm(observed.extents);c=observed.triangles_center;n=observed.face_normals;area=observed.area_faces
    topmask=(n[:,1]>.85)&(c[:,1]>low[1]+h*.2)&(c[:,1]<low[1]+h*.9);hist,edges=np.histogram(c[topmask,1],bins=100,range=(low[1],high[1]),weights=area[topmask]);hist=gaussian_filter1d(hist,1);j=int(np.argmax(hist));top=(edges[j]+edges[j+1])/2
    e=observed.vertices[observed.face_adjacency_edges];delta=e[:,1]-e[:,0];length=np.linalg.norm(delta,axis=1);middle=e.mean(1);angle=observed.face_adjacency_angles;concave=~observed.face_adjacency_convex
    valid=concave&(abs(delta[:,1])/np.maximum(length,1e-12)<.25)&(angle>.1)&(middle[:,1]>top-h*.3)&(middle[:,1]<top-h*.04)
    hist,edges=np.histogram(middle[valid,1],bins=100,range=(low[1],high[1]),weights=length[valid]*angle[valid]);hist=gaussian_filter1d(hist,1);j=int(np.argmax(hist));bottom=(edges[j]+edges[j+1])/2
    topfaces=(n[:,1]>.65)&(abs(c[:,1]-top)<h*.035);xz=observed.vertices[np.unique(observed.faces[topfaces])][:,[0,2]];polygon=concave_hull(MultiPoint(xz),ratio=.15).buffer(diag*.003).simplify(diag*.001,preserve_topology=True)
    upper=top+h*.045;cut=trimesh.creation.extrude_polygon(polygon,upper-bottom,engine='earcut');cut.vertices=cut.vertices[:,[0,2,1]];cut.vertices[:,1]+=bottom;cut.invert()
    def solid(m):
        s=md.Manifold(md.Mesh(np.asarray(m.vertices,np.float32),np.asarray(m.faces,np.uint32)));assert s.status()==md.Error.NoError,s.status();return s
    a,b=solid(source),solid(cut);parts={}
    for name,value in [('seat',a^b),('frame',a-b)]:
        raw=value.to_mesh();mesh=trimesh.Trimesh(raw.vert_properties[:,:3],raw.tri_verts,process=False);mesh,_=prepare_mesh(mesh);ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(mesh.vertices,mesh.faces.astype(np.int32)));ms.compute_selection_by_self_intersections_per_face();file=f'{case}_seat_trial_{name}.glb';mesh.export(out/file);parts[name]={'file':file,'after':mesh_stats(mesh),'components':len(mesh.split(only_watertight=False)),'self_intersection_faces':int(ms.current_mesh().face_selection_array().sum())}
    records.append({'case':case,'seat_top_y':top,'seat_bottom_y':bottom,'upper_y':upper,'footprint_xz':list(polygon.exterior.coords),'parts':parts});(out/'seat_solid_probe.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print(json.dumps(records[-1]),flush=True)
