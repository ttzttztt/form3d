# -*- coding: utf-8 -*-
"""Flat-pillow silhouette evidence: keep broad surfaces, flag narrow extensions.

Only changes triangle ownership; no surface is removed from the asset.
"""
import numpy as np
from PIL import Image,ImageDraw
from scipy.ndimage import distance_transform_edt,binary_fill_holes,label


def pillow_footprint(vertices,faces,centers,normals,area,indices,resolution=256):
    cloud=centers[indices];weights=area[indices];center=np.average(cloud,axis=0,weights=weights);cov=((cloud-center)*weights[:,None]).T@(cloud-center)/weights.sum();values,basis=np.linalg.eigh(cov);basis=basis[:,::-1];values=values[::-1]
    ratio=float(values[2]/max(values[1],1e-12));moment=(normals[indices]*weights[:,None]).T@normals[indices]/weights.sum();nv,nb=np.linalg.eigh(moment);dominance=float(nv[-1]/max(nv.sum(),1e-12))
    if dominance<.52:return np.ones(len(indices),bool),{'applied':False,'reason':'no_reliable_flat_pillow_plane','thickness_eigenvalue_ratio':ratio,'normal_axis_dominance':dominance}
    normal=nb[:,-1];u=basis[:,0]-normal*(basis[:,0]@normal)
    if np.linalg.norm(u)<1e-6:u=basis[:,1]-normal*(basis[:,1]@normal)
    u/=np.linalg.norm(u);basis=np.c_[u,np.cross(normal,u),normal]
    uv=(vertices-center)@basis[:,:2];part_uv=uv[np.unique(faces[indices])];low,high=part_uv.min(0),part_uv.max(0);step=float((high-low).max()/resolution);pad=5;size=np.ceil((high-low)/step).astype(int)+2*pad+1
    canvas=Image.new('L',tuple(size.tolist()),0);draw=ImageDraw.Draw(canvas);pixel=(uv-low)/step+pad
    parallel=abs(normals[indices]@basis[:,2])>.45
    for face in faces[indices[parallel]]:draw.polygon([tuple(x)for x in pixel[face]],fill=255)
    silhouette=binary_fill_holes(np.asarray(canvas)>0);distance=distance_transform_edt(silhouette);radius=max(2.,float(distance.max())*.22);core=distance>=radius
    cc,count=label(core)
    if count>1:
        sizes=np.bincount(cc.ravel());sizes[0]=0;largest=np.argmax(sizes)
        if np.sort(sizes)[-2]>sizes[largest]*.15:return np.ones(len(indices),bool),{'applied':False,'reason':'multiple_broad_lobes_need_review','thickness_eigenvalue_ratio':ratio}
        core=cc==largest
    opened=distance_transform_edt(~core)<=radius
    xy=np.rint((cloud-center)@basis[:,:2]/step-low/step+pad).astype(int);xy=np.clip(xy,0,size-1);keep=opened[xy[:,1],xy[:,0]]
    return keep,{'applied':True,'method':'broad_flat_surface_silhouette_opening','thickness_eigenvalue_ratio':ratio,'normal_axis_dominance':dominance,'radius_source_units':radius*step,'resolution':resolution,'flagged_area_fraction':float(weights[~keep].sum()/weights.sum()),'semantic_accuracy_verified':False}
