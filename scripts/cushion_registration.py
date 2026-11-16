"""Constrained cushion registration using the observed horizontal outline.

Flat surface ICP alone cannot constrain rotation inside a broad seat plane.
This aligns the two outlines, then checks the sampled surface fit separately.
It estimates installation, not the true dimensions or hidden product shape.
"""
import numpy as np
import trimesh
from scipy.spatial import ConvexHull, cKDTree
from shapely.geometry import Polygon


def outline(mesh, count=384):
    points=np.asarray(mesh.vertices)[:,[0,2]]
    hull=ConvexHull(points)
    polygon=Polygon(points[hull.vertices])
    edge=polygon.exterior
    samples=np.array([edge.interpolate(t).coords[0]for t in np.linspace(0,edge.length,count,endpoint=False)])
    rectangle=np.asarray(polygon.minimum_rotated_rectangle.exterior.coords)[:4]
    sides=rectangle[1:3]-rectangle[:2]
    lengths=np.linalg.norm(sides,axis=1)
    axis=sides[int(lengths.argmax())]
    return samples,polygon,np.sort(lengths)[::-1],float(np.arctan2(axis[1],axis[0]))


def fit_cushion(candidate,target,bottom=None):
    from part_registration import basis,surface_samples
    _,axes,_=basis(surface_samples(candidate,4000)[0])
    if abs(axes[:,2]@[0,1,0])<.85:
        raise ValueError('生成坐垫的厚度方向不明确，未自动装回')
    points,polygon,spans,angle=outline(candidate)
    observed,observed_polygon,observed_spans,observed_angle=outline(target)
    initial_scale=float(np.median(observed_spans/spans))
    diagonal=max(float(np.linalg.norm(target.extents)),1e-12)
    target_tree=cKDTree(observed);results=[]
    for offset in np.linspace(0,2*np.pi,24,endpoint=False):
        theta=observed_angle-angle+offset
        rotation=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
        scale=initial_scale;shift=observed.mean(0)-points.mean(0)@rotation.T*scale
        for _ in range(24):
            transformed=points@rotation.T*scale+shift
            da,ia=target_tree.query(transformed)
            db,ib=cKDTree(transformed).query(observed)
            a=np.vstack([points,points[ib]])
            b=np.vstack([observed[ia],observed])
            errors=np.r_[da,db];keep=errors<=np.quantile(errors,.9)
            a=a[keep];b=b[keep];ac=a.mean(0);bc=b.mean(0)
            u,_,vh=np.linalg.svd((a-ac).T@(b-bc));rotation=vh.T@u.T
            if np.linalg.det(rotation)<0:vh[-1]*=-1;rotation=vh.T@u.T
            scale=float(np.sum(((a-ac)@rotation.T)*(b-bc))/np.sum((a-ac)**2))
            scale=float(np.clip(scale,initial_scale*.7,initial_scale*1.3))
            shift=bc-ac@rotation.T*scale
        transformed=points@rotation.T*scale+shift
        distance=np.r_[target_tree.query(transformed)[0],cKDTree(transformed).query(observed)[0]]
        score=float(np.quantile(distance,.9)/diagonal)
        results.append((score,scale,rotation.copy(),shift.copy()))
    score,scale,rotation,shift=min(results,key=lambda result:result[0])
    if score>.035:raise ValueError('生成坐垫的外轮廓与原座面不匹配，未自动装回')
    matrix=np.eye(4);matrix[:3,:3]*=scale
    matrix[np.ix_([0,2],[0,2])]=rotation*scale
    matrix[[0,2],3]=shift
    matrix[1,3]=(float(target.bounds[0,1])if bottom is None else bottom)-candidate.vertices[:,1].min()*scale
    aligned=candidate.copy().apply_transform(matrix)
    _,installed_polygon,_,_=outline(aligned)
    outside=float(installed_polygon.difference(observed_polygon.buffer(diagonal*.015)).area/installed_polygon.area)
    if outside>.06:raise ValueError('新坐垫明显超出原座面范围，未自动装回')
    if aligned.extents[1]>max(target.extents[1]*2.5,diagonal*.12):raise ValueError('新坐垫厚度明显超出原座面，未自动装回')
    samples=surface_samples(target,4000)[0]
    generated=surface_samples(aligned,14000)[0]
    surface_error=float(np.quantile(cKDTree(generated).query(samples)[0],.85)/diagonal)
    return aligned,{
        'method':'horizontal_convex_outline_bidirectional_similarity_ICP',
        'candidate_to_source_world':matrix.tolist(),'uniform_scale':scale,
        'thickness_constraint':None,'sampled_core_distance_p85_diagonal_ratio':surface_error,
        'outline_distance_p90_diagonal_ratio':score,'outside_observed_footprint_area_fraction':outside,
        'footprint_is_convex_estimate':True,'pose_is_estimated':True,'real_scale_verified':False,
        'requires_full_shape_review':True,
    }
