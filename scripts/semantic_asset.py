"""Source-preserving semantic instances. A logical part is not a connected patch."""
import copy,json,sys,uuid
from pathlib import Path
import numpy as np,trimesh
from services.api.glb_document import parts_catalog,selected_primitives,write_glb,compact_static,set_part_ids
from furniture_parts import primitive_data,replace_primitives
from semantic_mapping import map_masks
PALETTE=['#e6a43b','#377fc1','#9a62c6','#27a89a','#e06978','#80a342','#ca7e45','#6279be','#c2a12d','#619aa8']

def merge_opposite_sides(labels,groups,centers,normals,area,diagonal):
    merged=[];removed=set()
    for i,a in enumerate(groups):
        if a['label'] in removed or a['source_kind']!='pillow':continue
        for b in groups[:i]:
            if b['label'] in removed or b['source_kind']!='pillow' or set(a['views'])&set(b['views']):continue
            ia=np.flatnonzero(labels==a['label']);ib=np.flatnonzero(labels==b['label']);ca=np.average(centers[ia],axis=0,weights=area[ia]);cb=np.average(centers[ib],axis=0,weights=area[ib])
            if np.linalg.norm(ca-cb)>diagonal*.12:continue
            na=np.average(normals[ia],axis=0,weights=area[ia]);nb=np.average(normals[ib],axis=0,weights=area[ib]);na/=max(np.linalg.norm(na),1e-12);nb/=max(np.linalg.norm(nb),1e-12)
            if np.dot(na,nb)>-.25:continue
            normal=na-nb;normal/=max(np.linalg.norm(normal),1e-12);axis=np.eye(3)[np.argmin(abs(normal))];u=np.cross(normal,axis);u/=np.linalg.norm(u);v=np.cross(normal,u);basis=np.c_[u,v]
            pa=centers[ia]@basis;pb=centers[ib]@basis;la,ha=np.quantile(pa,[.02,.98],axis=0);lb,hb=np.quantile(pb,[.02,.98],axis=0);intersection=np.prod(np.maximum(0,np.minimum(ha,hb)-np.maximum(la,lb)));ratio=intersection/max(min(np.prod(ha-la),np.prod(hb-lb)),1e-12)
            if ratio<.55:continue
            labels[ia]=b['label'];b['views']=sorted(set(a['views'])|set(b['views']));b['observations']+=a['observations'];removed.add(a['label']);merged.append({'from_label':a['label'],'to_label':b['label'],'tangent_footprint_overlap':float(ratio)});break
    return labels,[g for g in groups if g['label'] not in removed],merged

def separate_cylinder_from_flat_pillow(labels,groups,centers,normals,area,diagonal):
    from cylinder_evidence import fit_cylinder
    from scipy.spatial import cKDTree
    fits={}
    for group in groups:
        if group['source_kind']!='pillow':continue
        ids=np.flatnonzero(labels==group['label']);result=fit_cylinder(centers[ids],normals[ids],area[ids],diagonal)
        if result is not None:fits[group['label']]=(ids,result[0],result[1])
    plain=[g['label'] for g in groups if g['source_kind']=='pillow' and g['label'] not in fits];targets=np.flatnonzero(np.isin(labels,plain));tree=cKDTree(centers[targets]) if len(targets) else None;records=[]
    for group in groups:
        if group['label'] not in fits:continue
        ids,inside,evidence=fits[group['label']];outside=ids[~inside];labels[outside]=0
        if tree is not None and len(outside):
            d,nearest=tree.query(centers[outside]);assign=d<diagonal*.08;labels[outside[assign]]=labels[targets[nearest[assign]]]
        group['cylinder_fit']=evidence;group['kind']='bolster';records.append({'label':group['label'],'reassigned_non_cylindrical_faces':len(outside),**evidence})
    unknown=np.flatnonzero(labels==0)
    if len(unknown) and area[unknown].sum()<area.sum()*.003:
        known=np.flatnonzero(labels);d,nearest=cKDTree(centers[known]).query(centers[unknown]);assign=d<diagonal*.02;labels[unknown[assign]]=labels[known[nearest[assign]]]
    return labels,records

def refine_regions(vertices,faces,centers,area,labels,groups):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra,connected_components
    mesh=trimesh.Trimesh(vertices,faces,process=False);mesh.merge_vertices(digits_vertex=8);adjacency=mesh.face_adjacency
    distance=np.linalg.norm(centers[adjacency[:,0]]-centers[adjacency[:,1]],axis=1)
    normals=mesh.face_normals;cosine=(normals[adjacency[:,0]]*normals[adjacency[:,1]]).sum(1);distance*=1+3*np.maximum(0,1-cosine)
    graph=coo_matrix((np.r_[distance,distance],(np.r_[adjacency[:,0],adjacency[:,1]],np.r_[adjacency[:,1],adjacency[:,0]])),shape=(len(faces),len(faces))).tocsr()
    diagonal=np.linalg.norm(np.ptp(vertices,axis=0));removed=0
    for iteration in range(2):
        # Remove isolated colour specks, without turning each connected patch into a new part.
        for group in groups:
            ids=np.flatnonzero(labels==group['label'])
            if not len(ids):continue
            _,cc=connected_components(graph[ids][:,ids],directed=False);weights=np.bincount(cc,weights=area[ids]);keep=weights>=max(weights.max()*.06,area.sum()*.0008);drop=ids[~keep[cc]];removed+=len(drop);labels[drop]=0
            chosen=ids[keep[cc]];cloud=centers[chosen];group['bounds']=[cloud.min(0).tolist(),cloud.max(0).tolist()]
        # Fill sampling gaps and unseen backs using bounded geodesic evidence.
        seeds=np.flatnonzero(labels);d,_,nearest=dijkstra(graph,directed=False,indices=seeds,min_only=True,return_predecessors=True)
        valid=(labels==0)&(nearest>=0)&(d<diagonal*.35)
        for group in groups:
            low,high=np.asarray(group['bounds']);inside=np.all((centers>=low-diagonal*.06)&(centers<=high+diagonal*.06),axis=1);chosen=valid&inside&(labels[np.maximum(nearest,0)]==group['label']);labels[chosen]=group['label']
    return labels,{'unobserved_assignment':'bounded surface geodesic propagation, not new observations','isolated_face_assignments_reconsidered':removed,'unassigned_after':int((labels==0).sum())}

def create_semantic_asset(doc,binary,folder):
    set_part_ids(doc);targets=selected_primitives(doc,[]);prepared=[];vertices=[];faces=[];centers=[];normals=[];areas=[];offset=0
    for part,p in targets:
        if p.get('extras',{}).get('form_completion_role'):raise ValueError('请对原始模型进行 AI 整体识别，避免把已有推测面当作观察证据')
        v,f,w,c,n,a=primitive_data(doc,binary,part,p);prepared.append((part,p,v,f,w));vertices.append(w);faces.append(f+offset);offset+=len(w);centers.append(c);normals.append(n);areas.append(a)
    world=np.vstack(vertices);all_faces=np.vstack(faces);c=np.vstack(centers);a=np.concatenate(areas)
    n=np.vstack(normals);observations={};labels,groups,diagnostics=map_masks(folder,c,n,a,world,evidence=observations)
    if len(np.unique(labels))<2:raise ValueError('AI 只得到整件模型，未识别出多个整体部件；原版本保留')
    from supported_regions import refine_supported_regions,merge_observation_evidence,enforce_observation_veto
    labels,groups,propagation=refine_supported_regions(world,all_faces,c,a,labels,groups,observations)
    labels,groups,opposite=merge_opposite_sides(labels,groups,c,n,a,np.linalg.norm(np.ptp(world,axis=0)));propagation['opposite_sides_merged']=opposite
    merge_observation_evidence(observations,opposite)
    labels,cylinders=separate_cylinder_from_flat_pillow(labels,groups,c,n,a,np.linalg.norm(np.ptp(world,axis=0)));propagation['cylinder_checks']=cylinders
    labels,vetoed=enforce_observation_veto(labels,groups,observations);propagation['post_grouping_contradictions_removed']=vetoed
    groups=[g for g in groups if np.any(labels==g['label'])]
    propagation['unassigned_after']=int((labels==0).sum());propagation['unassigned_area_fraction']=float(a[labels==0].sum()/a.sum())
    if len(np.unique(labels))<2:raise ValueError('AI 只得到整件模型，未识别出多个整体部件；原版本保留')
    for group in groups:
        ids=np.flatnonzero(labels==group['label']);cloud=c[ids];weight=a[ids].sum();center=np.average(cloud,axis=0,weights=a[ids]);cov=((cloud-center)*a[ids,None]).T@(cloud-center)/weight;values,vectors=np.linalg.eigh(cov);eigen=values[::-1];axis=vectors[:,-1];radial=cloud-center-np.outer((cloud-center)@axis,axis);radius=np.linalg.norm(radial,axis=1);side=abs(n[ids]@axis)<.45
        radial_cv=1.;alignment=0.
        if side.sum()>32:
            mean=np.average(radius[side],weights=a[ids][side]);radial_cv=float(np.sqrt(np.average((radius[side]-mean)**2,weights=a[ids][side]))/max(mean,1e-12));alignment=float(np.average(abs((n[ids][side]*radial[side]/np.maximum(radius[side,None],1e-12)).sum(1)),weights=a[ids][side]))
        group['kind']='bolster' if group.get('cylinder_fit') else group['source_kind'];group['pca_eigenvalues']=eigen.tolist();group['center']=center.tolist();group['shape_evidence']={'radial_coefficient_of_variation':radial_cv,'normal_radial_alignment':alignment,'classification_is_heuristic':True}
    np.savez_compressed(Path(folder)/'assignments.npz',labels=labels)
    np.savez_compressed(Path(folder)/'mapping_evidence.npz',visible_views=observations['visible_views'],support_views=observations['support_views'],scores=observations['scores'],raw_labels=observations['raw_labels'])
    names={};counts={};records=[]
    for group in groups:
        kind=group['kind'];counts[kind]=counts.get(kind,0)+1;prefix={'pillow':'靠枕','bolster':'圆柱抱枕','seat':'坐面与主体','tabletop':'桌面','support':'支撑','panel':'板件'}.get(kind,'部件');names[group['label']]=f'{prefix} {counts[kind]}';group.update(name=names[group['label']],id='group_'+uuid.uuid4().hex,color=PALETTE[(len(names)-1)%len(PALETTE)])
    other={'label':0,'name':'主体与未确认区域','id':'group_'+uuid.uuid4().hex,'color':'#a9b0bb','kind':'unknown'};lookup={g['label']:g for g in groups+[other]};replacements={};start=0
    from asset_operations import append_array
    for part,p,v,f,w in prepared:
        current=labels[start:start+len(f)];start+=len(f);created=[]
        for label in np.unique(current):
            group=lookup[int(label)];new=copy.deepcopy(p);new['indices']=append_array(doc,binary,f[current==label].astype('<u4').ravel(),'SCALAR',5125,34963)
            new.setdefault('extras',{}).update(form_part_name=group['name'],form_group_kind='ai_semantic_instance',form_source_part=part.get('source_part_id') or part['id'],form_logical_group_id=group['id'],form_proposal_status='semantic_review_required',form_semantic_color=group['color'],form_semantic_kind=group['kind']);new['extras'].pop('form_selection_role',None);created.append((new,'part_'+uuid.uuid4().hex))
        replacements.setdefault(part['node'],{})[part['primitive']]=created
    replace_primitives(doc,replacements)
    for label in np.unique(labels):
        group=lookup[int(label)];mask=labels==label;mesh=trimesh.Trimesh(world,all_faces[mask],process=False);mesh.remove_unreferenced_vertices();mesh.merge_vertices(digits_vertex=8)
        direct=float(a[mask&(observations['support_views'][int(label)-1]>=2)].sum()/a[mask].sum())if label else 0.
        records.append({**group,'faces':int(mask.sum()),'watertight':bool(mesh.is_watertight),'surface_only':not bool(mesh.is_watertight),'area_fraction_final':float(a[mask].sum()/a.sum()),'multiview_observed_area_fraction':direct,'needs_boundary_review':bool(label==0 or direct<.7)})
    return {'operation':'semantic_parts','method':'local_grounding_dino_sam2_calibrated_multiview_instances','semantic_classification':True,'groups':records,'diagnostics':diagnostics,'propagation':propagation,'triangles_preserved':len(labels),'positions_unchanged':True,'hidden_geometry_recovered':False,'review_status':'review_required','limits':['识别的是源模型表面归属，粘连模型的真实隐藏边界仍不确定。','同一实例的多个面片合并为一个逻辑部件，不按面片碎分。']}

def write_style_preview(doc,binary,extra,path):
    diagnostic=copy.deepcopy(doc);materials={}
    for part,p in selected_primitives(diagnostic,[]):
        group=part.get('logical_group_id') or part['id'];color=p.get('extras',{}).get('form_semantic_color','#a9b0bb')
        if group not in materials:
            values=[int(color[i:i+2],16)/255 for i in (1,3,5)];linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values];materials[group]=len(diagnostic.setdefault('materials',[]));diagnostic['materials'].append({'name':part['name'],'pbrMetallicRoughness':{'baseColorFactor':linear+[1],'metallicFactor':0,'roughnessFactor':.8}})
        p['material']=materials[group];p['attributes'].pop('COLOR_0',None)
    compact=compact_static(diagnostic,binary);write_glb(path,diagnostic,compact,extra)
