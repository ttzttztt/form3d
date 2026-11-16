# -*- coding: utf-8 -*-
"""Small rigid/uniform pose adjustments, bounded by source and every view."""
import cv2
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from photo_part_evidence import decimate_mesh,project,rasterize,bbox,mask_iou
from part_registration import surface_samples,observed_pose_surface


def refine_photo_pose(mesh,source,kind,views):
    if not views:return mesh,{'applied':False,'reason':'no_photo_constraints'}
    center=mesh.centroid;diagonal=max(float(np.linalg.norm(source.extents)),1e-12)
    matrix=np.asarray(views[0]['matrix']);pixel,depth=project(center[None],matrix);u,v=pixel[0];z=depth[0]
    jac=np.stack([(matrix[0,:3]-u*matrix[2,:3])/z,(matrix[1,:3]-v*matrix[2,:3])/z])
    _,_,vh=np.linalg.svd(jac);directions=vh[:2].T
    analysis=decimate_mesh(mesh,1400);initial_points=surface_samples(mesh,5000)[0]
    pose=observed_pose_surface(source,kind)[0];target_points=surface_samples(pose,1500)[0];tree=cKDTree(initial_points)
    prepared=[]
    for view in views:
        expected=view['mask'];p=np.asarray(view['matrix']);size=expected.shape[::-1]
        pixels,_=project(analysis.vertices,p);bb=bbox(expected);low=np.minimum(bb[:2],pixels.min(0));high=np.maximum(bb[2:],pixels.max(0));padding=(high-low)*.15
        low=np.maximum(0,low-padding);high=np.minimum(size,high+padding);extent=np.maximum(high-low,1)
        factor=min(192/extent);out_size=tuple(max(8,int(round(value*factor)))for value in extent)
        affine=np.array([[factor,0,-low[0]*factor],[0,factor,-low[1]*factor],[0,0,1.]])
        expected_small=cv2.warpAffine(expected.astype('uint8'),affine[:2],out_size,flags=cv2.INTER_NEAREST)>0
        p=affine@p;others=view['others']
        _,_,other_depth=rasterize(others,p,out_size,return_depth=True)
        prepared.append((expected_small,p,out_size,other_depth))
    evaluations=0;cache={}
    def evaluate(parameters):
        nonlocal evaluations
        parameters=np.asarray(parameters,float);key=tuple(np.round(parameters,7))
        if key in cache:return cache[key]
        shift=directions@parameters[:2]*diagonal;scale=1+parameters[2]
        if np.linalg.norm(shift)>diagonal*.03 or not .96<=scale<=1.04:return(-np.inf,[],np.inf)
        inverse=(target_points-center-shift)/scale+center
        proximity=float(np.quantile(tree.query(inverse)[0]*scale,.85)/diagonal)
        if proximity>.06:return(-np.inf,[],proximity)
        candidate=trimesh.Trimesh((analysis.vertices-center)*scale+center+shift,analysis.faces,process=False)
        scores=[]
        for expected,p,size,other_depth in prepared:
            labels,_,candidate_depth=rasterize({'target':candidate},p,size,return_depth=True)
            visible=(labels==1)&(candidate_depth<=other_depth+1e-9)
            scores.append(mask_iou(expected,visible))
        evaluations+=1;result=(float(np.mean(scores)),scores,proximity);cache[key]=result;return result
    best=np.zeros(3);initial=evaluate(best);current=initial
    if not np.isfinite(initial[0]):
        return mesh,{'applied':False,'reason':'initial_source_support_insufficient_for_bounded_photo_refinement','source_surface_distance_p85_diagonal_ratio':float(initial[2])if np.isfinite(initial[2])else None,'physical_pose_verified':False}
    for step in(.012,.006):
        neighbors=[best+np.array([a,b,0])for a,b in((step,0),(-step,0),(0,step),(0,-step),(step,step),(step,-step),(-step,step),(-step,-step))]
        neighbors.extend([best+np.array([0,0,s])for s in(-step,step)])
        for candidate in neighbors:
            if np.any(abs(candidate[:2])>.02)or abs(candidate[2])>.04:continue
            measured=evaluate(candidate)
            if measured[0]>current[0]+1e-6 and all(a>=b-.01 for a,b in zip(measured[1],initial[1])):best=candidate;current=measured
    accepted=bool(current[0]>=initial[0]+.005 and np.isfinite(current[0]))
    evidence={'applied':accepted,'evaluations':evaluations,'before_view_ious':initial[1],'after_view_ious':current[1]if accepted else initial[1],
              'source_surface_distance_p85_diagonal_ratio':current[2]if accepted else initial[2],
              'maximum_translation_diagonal_ratio':.03,'maximum_uniform_scale_change':.04,
              'same_reference_used_for_constraint_and_comparison':True,'physical_pose_verified':False}
    if not accepted:return mesh,evidence
    shift=directions@best[:2]*diagonal;scale=1+best[2];transform=np.eye(4);transform[:3,:3]*=scale;transform[:3,3]=center*(1-scale)+shift
    result=mesh.copy();result.apply_transform(transform);evidence['adjustment_in_world']=transform.tolist()
    return result,evidence
