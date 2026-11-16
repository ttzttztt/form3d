# -*- coding: utf-8 -*-
"""Automatic SAM seat prompts from observed surface geometry, with ambiguity refusal."""
import numpy as np
from scipy.ndimage import gaussian_filter1d
from semantic_mapping import project_visible


def spread_points(xy,weights,count=4,min_spacing=18):
    if not len(xy):return []
    center=np.average(xy,axis=0,weights=weights);chosen=[int(np.argmin(np.linalg.norm(xy-center,axis=1)))];distance=np.linalg.norm(xy-xy[chosen[0]],axis=1)
    for _ in range(count-1):
        i=int(np.argmax(distance))
        if distance[i]<min_spacing:break
        chosen.append(i);distance=np.minimum(distance,np.linalg.norm(xy-xy[i],axis=1))
    return xy[chosen].astype(float).tolist()


def seat_geometry_prompts(vertices,centers,normals,area,views,folder):
    from pathlib import Path
    low=vertices.min(0);height=float(np.ptp(vertices[:,1]));up=(normals[:,1]>.78)&(centers[:,1]>low[1]+height*.17)&(centers[:,1]<low[1]+height*.67)
    if not up.any():return {'available':False,'reason':'no_mid_height_upward_surface','views':[]}
    hist,edges=np.histogram(centers[up,1],bins=100,range=(low[1],low[1]+height),weights=area[up]);hist=gaussian_filter1d(hist,1);peak=int(hist.argmax());top=float((edges[peak]+edges[peak+1])/2);other=hist.copy();other[max(0,peak-7):min(100,peak+8)]=0;dominance=float(hist[peak]/max(float(other.max()),1e-12))
    if dominance<1.5:return {'available':False,'reason':'ambiguous_seat_height','peak_dominance':dominance,'views':[]}
    positive=(normals[:,1]>.6)&(abs(centers[:,1]-top)<height*.035)
    if area[positive].sum()<area.sum()*.025:return {'available':False,'reason':'upward_surface_too_small','views':[]}
    lower=(centers[:,1]<top-height*.11)&(centers[:,1]>low[1]+height*.10)
    higher=centers[:,1]>top+height*.12
    records=[]
    for view in views:
        x,y,seen,_=project_visible(centers,{**view,'depth_path':Path(folder)/view['depth']});xy=np.c_[x,y]
        pos=seen&positive;neg_low=seen&lower;neg_high=seen&higher
        positives=spread_points(xy[pos],area[pos],count=4,min_spacing=28)
        negatives=spread_points(xy[neg_low],area[neg_low],count=4,min_spacing=30)+spread_points(xy[neg_high],area[neg_high],count=4,min_spacing=30)
        negatives=[p for p in negatives if all(np.linalg.norm(np.asarray(p)-q)>=18 for q in positives)]
        records.append({'view':view['index'],'positive_points':positives,'negative_points':negatives})
    return {'available':True,'method':'dominant_observed_upward_surface_and_height_exclusions','seat_top_source_units':top,'peak_dominance':dominance,'requires_manual_points':False,'views':records,'semantic_accuracy_verified':False}


def seat_prompt_variants(box,cue):
    box=np.asarray(box);positive=np.asarray(cue.get('positive_points',[]),float).reshape(-1,2);negative=np.asarray(cue.get('negative_points',[]),float).reshape(-1,2)
    positive=positive[np.all((positive>=box[:2]+3)&(positive<=box[2:]-3),axis=1)]
    if not len(positive):return []
    negative=negative[np.all((negative>=box[:2])&(negative<=box[2:]),axis=1)]
    variants=[]
    for seeds in (positive[:1],positive):
        points=np.vstack([seeds,negative]);labels=np.r_[np.ones(len(seeds),int),np.zeros(len(negative),int)]
        if not any(np.array_equal(points,p)for p,l in variants):variants.append((points.astype(np.float32),labels))
    return variants
