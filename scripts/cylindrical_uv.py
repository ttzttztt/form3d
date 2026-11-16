"""Continuous circumference chart plus separate caps; selected local axis is explicit."""
import numpy as np
def cylindrical_unwrap(vertices,faces,axis='y'):
    a='xyz'.index(axis);u=(a+1)%3;w=(a+2)%3;low=vertices.min(0);high=vertices.max(0);center=(low+high)/2;radius=float(np.linalg.norm(vertices[:,[u,w]]-center[[u,w]],axis=1).max());height=float(high[a]-low[a]);diagonal=max(float(np.linalg.norm(high-low)),1e-9)
    if radius<diagonal*1e-5 or height<diagonal*1e-5:raise ValueError('当前部件不适合圆柱展开，请改用图集或快速分区')
    t=vertices[faces];normal=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);normal/=np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-15);labels=np.where(normal[:,a]>.75,1,np.where(normal[:,a]<-.75,2,0));theta=(np.arctan2(vertices[:,u]-center[u],vertices[:,w]-center[w])+np.pi)/(2*np.pi);angles=theta[faces];cross=(np.ptp(angles,axis=1)>.5)&(labels==0);wrapped=np.zeros_like(faces,dtype=int);wrapped[cross]=(angles[cross]<.5);pairs=np.c_[faces.ravel(),np.repeat(labels,3),wrapped.ravel()];unique,inverse=np.unique(pairs,axis=0,return_inverse=True);mapping=unique[:,0];chart=unique[:,1];p=vertices[mapping];gap=diagonal*.02;circumference=2*np.pi*radius;uv=np.zeros((len(mapping),2));side=chart==0;uv[side,0]=(theta[mapping[side]]+unique[side,2])*circumference;uv[side,1]=p[side,a]-low[a]
    for label in (1,2):
        mask=chart==label;uv[mask,0]=(p[mask,u]-center[u])+radius+(2*radius+gap if label==2 else 0);uv[mask,1]=(p[mask,w]-center[w])+radius+height+gap
    extent=max(float(uv.max()),circumference,height+2*radius+gap);uv=(uv+gap)/(extent+2*gap)
    return mapping,inverse.reshape(-1,3),uv,{'algorithm':'continuous_cylinder_and_caps','axis':axis,'charts':3,'seam_note':'One circumference cut plus cap boundaries; local Y by default, inspect irregular shapes','positions_preserved':True}
