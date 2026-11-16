# -*- coding: utf-8 -*-
"""Split a weak frame attachment at its mesh neck, preserving the full source."""
import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import maximum_flow,breadth_first_order,connected_components


def pillow_neck_cut(vertices,faces,centers,normals,area,indices,seat_top):
    height=float(np.ptp(vertices[:,1]));diagonal=float(np.linalg.norm(np.ptp(vertices,axis=0)));y=centers[indices,1];positive=y>seat_top+height*.10;negative=y<seat_top-height*.035
    negative_area=float(area[indices[negative]].sum()/area[indices].sum())
    if negative.sum()<4 or positive.sum()<16:return np.ones(len(indices),bool),{'applied':False,'reason':'no_separated_frame_exclusion_seeds'}
    if negative_area>.18:return np.ones(len(indices),bool),{'applied':False,'reason':'large_lower_surface_needs_review','negative_area_fraction':negative_area}
    mesh=trimesh.Trimesh(vertices,faces,process=False);mesh.merge_vertices(digits_vertex=8);adj=mesh.face_adjacency;lookup=np.full(len(faces),-1,dtype=np.int64);lookup[indices]=np.arange(len(indices));valid=(lookup[adj[:,0]]>=0)&(lookup[adj[:,1]]>=0);pairs=lookup[adj[valid]];edges=mesh.face_adjacency_edges[valid];length=np.linalg.norm(mesh.vertices[edges[:,0]]-mesh.vertices[edges[:,1]],axis=1);angle=mesh.face_adjacency_angles[valid];cost=length/diagonal*(.02+np.exp(-(angle/.52)**2));capacity=np.maximum(1,np.rint(cost*1e6)).astype(np.int64)
    n=len(indices);source=n;sink=n+1;ps=np.flatnonzero(positive);ns=np.flatnonzero(negative);row=np.r_[pairs[:,0],pairs[:,1],np.full(len(ps),source),ns];col=np.r_[pairs[:,1],pairs[:,0],ps,np.full(len(ns),sink)];values=np.r_[capacity,capacity,np.full(len(ps)+len(ns),10000000,dtype=np.int64)];graph=coo_matrix((values,(row,col)),shape=(n+2,n+2)).tocsr();flow=maximum_flow(graph,source,sink);residual=graph-flow.flow;residual.data=(residual.data>0).astype(np.int64);residual.eliminate_zeros();reachable=breadth_first_order(residual,source,directed=True,return_predecessors=False);keep=np.zeros(n,bool);keep[reachable[reachable<n]]=True
    local=coo_matrix((np.ones(len(pairs)*2),(np.r_[pairs[:,0],pairs[:,1]],np.r_[pairs[:,1],pairs[:,0]])),shape=(n,n)).tocsr();_,cc=connected_components(local,directed=False);has_pos=np.bincount(cc,weights=positive)>0;has_neg=np.bincount(cc,weights=negative)>0;keep[~(has_pos[cc]&has_neg[cc])]=True
    fraction=float(area[indices[~keep]].sum()/area[indices].sum())
    if fraction>.20:return np.ones(n,bool),{'applied':False,'reason':'large_cut_needs_review','candidate_removed_area_fraction':fraction}
    return keep,{'applied':True,'method':'minimum_cut_between_observed_upper_pillow_and_lower_frame_seeds','frame_seed_below_source_units':seat_top-height*.035,'positive_seed_above_source_units':seat_top+height*.10,'removed_area_fraction':fraction,'removed_faces':int((~keep).sum()),'source_geometry_removed':False,'semantic_accuracy_verified':False}
