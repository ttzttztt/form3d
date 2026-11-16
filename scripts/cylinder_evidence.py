"""Robust cylinder evidence rejects a text label unsupported by observed geometry."""
import numpy as np

def fit_cylinder(centers,normals,area,diagonal):
    if len(centers)<100:return None
    mean=np.average(centers,axis=0,weights=area);cov=((centers-mean)*area[:,None]).T@(centers-mean)/area.sum();eigen,vectors=np.linalg.eigh(cov)
    if eigen[-1]/max(eigen[-2],1e-12)<2:return None
    axis=vectors[:,-1];initial_side=abs(normals@axis)<.40
    if initial_side.sum()>80:
        moment=(normals[initial_side]*area[initial_side,None]).T@normals[initial_side];normal_values,normal_vectors=np.linalg.eigh(moment);candidate=normal_vectors[:,0]
        if normal_values[0]<normal_values[1]*.15 and abs(candidate@axis)>.8:axis=candidate
    helper=np.eye(3)[np.argmin(abs(axis))];u=np.cross(axis,helper);u/=np.linalg.norm(u);basis=np.c_[u,np.cross(axis,u)];points=(centers-mean)@basis;n=normals@basis;nl=np.linalg.norm(n,axis=1);side=abs(normals@axis)<.40
    available=np.flatnonzero(side)
    if len(available)<80:return None
    rng=np.random.default_rng(20261113);sample=rng.choice(available,min(6000,len(available)),replace=False,p=area[available]/area[available].sum());p=points[sample];ns=n[sample];ns/=np.maximum(np.linalg.norm(ns,axis=1,keepdims=True),1e-12);best=None;best_count=0
    for _ in range(250):
        triplet=p[rng.choice(len(p),3,replace=False)];matrix=2*(triplet[1:]-triplet[0]);right=(triplet[1:]**2).sum(1)-(triplet[0]**2).sum()
        if abs(np.linalg.det(matrix))<diagonal**2*1e-6:continue
        center=np.linalg.solve(matrix,right);radius=np.linalg.norm(triplet[0]-center)
        if not diagonal*.015<radius<diagonal*.18:continue
        radial=p-center;distance=np.linalg.norm(radial,axis=1);alignment=(radial*ns).sum(1)/np.maximum(distance,1e-12);inside=(abs(distance-radius)<max(radius*.12,diagonal*.003))&(alignment>.78);count=int(inside.sum())
        angles=np.arctan2(radial[inside,1],radial[inside,0]);coverage=len(np.unique(np.floor((angles+np.pi)/(2*np.pi)*12).astype(int)))
        if coverage<10:continue
        if count>best_count:best_count=count;best=(center,radius,inside)
    if best is None or best_count<len(p)*.22:return None
    center,radius,inside=best
    from scipy.optimize import least_squares
    fitted=least_squares(lambda x:np.linalg.norm(p[inside]-x[:2],axis=1)-x[2],np.r_[center,radius],bounds=([-np.inf,-np.inf,diagonal*.015],[np.inf,np.inf,diagonal*.18]),loss='soft_l1',f_scale=diagonal*.003,max_nfev=30).x;center=fitted[:2];radius=fitted[2]
    radial=points-center;distance=np.linalg.norm(radial,axis=1);alignment=(radial*n).sum(1)/np.maximum(distance*nl,1e-12);sides=side&(abs(distance-radius)<max(radius*.15,diagonal*.004))&(alignment>.75)
    angles=np.arctan2(radial[sides,1],radial[sides,0]);angular_bins=len(np.unique(np.floor((angles+np.pi)/(2*np.pi)*12).astype(int)));along=(centers-mean)@axis
    if angular_bins<10 or sides.sum()<80 or area[sides].sum()<area.sum()*.40:return None
    lo,hi=np.quantile(along[sides],[.01,.99])
    if hi-lo<radius*2.5:return None
    # Face centres stop short of an end on coarse/long triangles. End-facing
    # observed faces inside the fitted radius may extend by one radius.
    end_margin=max(diagonal*.015,radius)
    ends=(abs(normals@axis)>.65)&(distance<radius*1.12)&(along>lo-end_margin)&(along<hi+end_margin)
    mask=sides|ends
    return mask,{'method':'robust_circle_in_plane_normal_to_principal_axis','radius_source_units':float(radius),'axis':axis.tolist(),'axis_point_source_units':(mean+basis@center).tolist(),'axial_observed_interval_source_units':[float(lo),float(hi)],'angular_bins_observed':angular_bins,'side_area_fraction':float(area[sides].sum()/area.sum()),'fit_is_geometric_evidence_not_semantic_accuracy':True}
