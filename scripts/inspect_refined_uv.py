"""Geometric UV diagnostics, independent of texture appearance or photo similarity."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from services.api.glb_document import read_glb,parts_catalog
from edit_asset import accessor_array,node_world_matrices

def metrics(path,identity):
    doc,binary,_=read_glb(path);part=next(p for p in parts_catalog(doc) if p['id']==identity);p=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']];v=accessor_array(doc,binary,p['attributes']['POSITION']);uv=accessor_array(doc,binary,p['attributes']['TEXCOORD_0']);f=accessor_array(doc,binary,p['indices']).reshape(-1,3);world=(np.c_[v,np.ones(len(v))]@node_world_matrices(doc)[part['node']].T)[:,:3];used=np.unique(f);diagonal=max(float(np.linalg.norm(np.ptp(world[used],axis=0))),1e-9);_,weld=np.unique(np.round(world/diagonal,7),axis=0,return_inverse=True)
    a=np.concatenate((f[:,0],f[:,1],f[:,2]));b=np.concatenate((f[:,1],f[:,2],f[:,0]));swap=weld[a]>weld[b];left=np.where(swap,b,a);right=np.where(swap,a,b);edges=np.c_[weld[left],weld[right]];owner=np.tile(np.arange(len(f)),3);coords=np.c_[uv[left],uv[right]];order=np.lexsort((edges[:,1],edges[:,0]));e=edges[order];u=coords[order];same=np.all(e[1:]==e[:-1],axis=1);starts=np.r_[0,np.flatnonzero(~same)+1];counts=np.diff(np.r_[starts,len(e)]);group=np.repeat(np.arange(len(starts)),counts);changes=same&np.any(abs(u[1:]-u[:-1])>1e-5,axis=1);seams=np.zeros(len(starts),dtype=bool);seams[group[1:][changes]]=True;lengths=np.linalg.norm(world[left[order[starts]]]-world[right[order[starts]]],axis=1);continuous=same&~changes;aowner=owner[order[:-1][continuous]];bowner=owner[order[1:][continuous]];graph=sparse.csr_matrix((np.ones(len(aowner)*2),(np.r_[aowner,bowner],np.r_[bowner,aowner])),shape=(len(f),len(f)));charts,_=connected_components(graph,directed=False)
    t=world[f];edge=t[:,1]-t[:,0];other=t[:,2]-t[:,0];area=np.linalg.norm(np.cross(edge,other),axis=1)/2;ut=uv[f];ue=ut[:,1]-ut[:,0];uo=ut[:,2]-ut[:,0];uv_area=abs(ue[:,0]*uo[:,1]-ue[:,1]*uo[:,0])/2;valid=area>diagonal**2*1e-12;length=np.linalg.norm(edge[valid],axis=1);x=np.sum(edge[valid]*other[valid],axis=1)/np.maximum(length,1e-15);y=np.sqrt(np.maximum(np.sum(other[valid]**2,axis=1)-x*x,1e-30));j=np.zeros((valid.sum(),2,2));j[:,:,0]=ue[valid]/length[:,None];j[:,:,1]=(uo[valid]-j[:,:,0]*x[:,None])/y[:,None];s=np.linalg.svd(j,compute_uv=False);ratio=s[:,0]/np.maximum(s[:,1],1e-15);weights=area[valid];total=max(float(weights.sum()),1e-15)
    return {'faces':len(f),'seam_length_model_units':float(lengths[seams].sum()),'normalized_seam_length':float(lengths[seams].sum()/diagonal),'open_boundary_length':float(lengths[counts==1].sum()),'uv_continuity_components':int(charts),'collapsed_geometry_area_fraction':float(area[uv_area<1e-12].sum()/max(area.sum(),1e-15)),'area_fraction_anisotropy_over_4':float(weights[ratio>4].sum()/total),'geometric_mean_anisotropy':float(np.exp(np.sum(weights*np.log(np.clip(ratio,1,1000)))/total)),'note':'UV geometry diagnostics only; no image resemblance or material accuracy measurement.'}

if __name__=='__main__':
    folder=ROOT/'experiments/selection_refinement_20261112';results=[]
    for c in json.loads((folder/'uv_runs.json').read_text(encoding='utf-8')):
        row={'case':c['case'],'part_ids':c['part_ids']}
        for mode in ('box','proxy','cylinder'):
            path=folder/(c['case']+'_'+mode+'.glb')
            if path.exists():row[mode]=metrics(path,c['part_ids'][0])
        results.append(row);print(json.dumps({'case':c['case'],'uv':{k:(v['normalized_seam_length'],v['area_fraction_anisotropy_over_4']) for k,v in row.items() if isinstance(v,dict)}}),flush=True)
    (folder/'uv_metrics.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
