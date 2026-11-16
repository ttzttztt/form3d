"""Bounded oriented-distance reconstruction. Every output triangle is reconstructed."""
import gc
import numpy as np
import trimesh

def bounded_field_mesh(source,guide,resolution=160):
    from scipy.spatial import cKDTree
    from skimage.measure import marching_cubes
    center=np.average(source.triangles_center,axis=0,weights=source.area_faces);cov=((source.triangles_center-center)*source.area_faces[:,None]).T@(source.triangles_center-center)/source.area
    _,basis=np.linalg.eigh(cov);basis=basis[:,::-1]
    if np.linalg.det(basis)<0:basis[:,-1]*=-1
    diagonal=max(float(np.linalg.norm(source.extents)),1e-9);sv=(source.vertices-center)@basis;low=sv.min(0)-diagonal*.003;high=sv.max(0)+diagonal*.003;step=float((high-low).max()/resolution);glow=low-step*3;ghigh=high+step*3;shape=np.ceil((ghigh-glow)/step).astype(int)+1
    cloud=np.vstack([guide.vertices,guide.triangles_center]);normals=np.vstack([guide.vertex_normals,guide.face_normals]);points=(cloud-center)@basis;normals=normals@basis;tree=cKDTree(points);field=np.empty(np.prod(shape),dtype=np.float32)
    stride=int(shape[1]*shape[2]);tail=int(shape[2]);total=len(field)
    for start in range(0,total,150000):
        flat=np.arange(start,min(start+150000,total));q=glow+np.c_[flat//stride,(flat//tail)%shape[1],flat%shape[2]]*step;_,nearest=tree.query(q,workers=6);signed=((q-points[nearest])*normals[nearest]).sum(1);box=np.maximum(low-q,q-high).max(1);field[start:start+len(flat)]=np.maximum(signed,box)
    field=field.reshape(tuple(shape));v,f,_,_=marching_cubes(field,level=0,spacing=(step,)*3,gradient_direction='ascent',allow_degenerate=False);v=(v+glow)@basis.T+center;mesh=trimesh.Trimesh(v,f,process=False)
    if mesh.volume<0:mesh.faces=mesh.faces[:,::-1]
    return mesh,{'grid_shape':shape.tolist(),'grid_step_source_units':step,'resolution':resolution,'method':'screened_surface_oriented_distance_with_observed_PCA_bounds','all_output_surfaces_reconstructed':True,'real_hidden_geometry_recovered':False}
