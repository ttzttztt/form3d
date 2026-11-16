# -*- coding: utf-8 -*-
"""Build an immutable replacement preview, preserving all unrelated primitives."""
import argparse,copy,hashlib,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'services/workers'),str(ROOT/'.tools/geometry_extra')]
import numpy as np,trimesh
from services.api.glb_document import read_glb,write_glb,parts_catalog,selected_primitives,compact_static
from furniture_parts import primitive_data,replace_primitives
from asset_operations import append_array
from edit_asset import node_world_matrices
from reconstruct_parts import keep_single_solid,intersections
from solid_partition import prepare_mesh
from complete_part import mesh_stats
from part_registration import register_part

def selected_group(doc,binary,part_ids,allow_uv=False):
    if doc.get('animations')or doc.get('skins'):raise ValueError('带动画或骨骼的模型暂不支持部件重生成')
    catalog=parts_catalog(doc);chosen=[p for p in catalog if p['id']in part_ids]
    if len(chosen)!=len(set(part_ids)):raise ValueError('所选部件已变化，请刷新后重试')
    groups={p.get('logical_group_id')or p['id']for p in chosen}
    if len(groups)!=1:raise ValueError('一次只重生成一个完整部件组')
    key=next(iter(groups));entries=selected_primitives(doc,[p['id']for p in catalog if(p.get('logical_group_id')or p['id'])==key]);meshes=[]
    if len({p['node']for p,q in entries})!=1:raise ValueError('跨节点部件暂不自动替换')
    if len({p['material_signature']for p,q in entries})!=1:raise ValueError('部件含多种材质，请在局部换材质前重生成')
    for part,p in entries:
        allowed={'POSITION','NORMAL','TEXCOORD_0','TANGENT'}if allow_uv else{'POSITION','NORMAL'}
        if set(p['attributes'])-allowed or p.get('extensions')or p.get('targets')or p.get('mode',4)!=4:raise ValueError('带贴图、顶点颜色、形变或压缩的部件暂不替换，以免丢失外观')
        mat=doc.get('materials',[])[p['material']]if'material'in p else{}
        if mat.get('extensions')or any('Texture'in k for k in mat)or any('Texture'in k for k in mat.get('pbrMetallicRoughness',{})):raise ValueError('带贴图或扩展材质的部件暂不替换')
        _,f,w,_,_,_=primitive_data(doc,binary,part,p);m=trimesh.Trimesh(w,f,process=False);m.remove_unreferenced_vertices();meshes.append(m)
    mesh,_=prepare_mesh(trimesh.util.concatenate(meshes));return key,entries,mesh

def cushion_slot(source):
    from scipy.ndimage import gaussian_filter1d
    low,high=source.bounds;height=high[1]-low[1];c=source.triangles_center;n=source.face_normals;a=source.area_faces;up=(n[:,1]>.80)&(c[:,1]>low[1]+height*.2)&(c[:,1]<=high[1]+height*1e-6)
    hist,edges=np.histogram(c[up,1],bins=100,range=(low[1],high[1]),weights=a[up]);hist=gaussian_filter1d(hist,1);i=int(hist.argmax());top=float((edges[i]+edges[i+1])/2)
    if hist[i]<=0:raise ValueError('没有可靠的座面高度，不能自动替换坐垫')
    elevated=c[:,1]>top+height*.12
    if a[elevated].sum()>source.area*.06:raise ValueError('这个分组同时包含扶手或靠背，不能按坐垫整体替换')
    edge=source.vertices[source.face_adjacency_edges];delta=edge[:,1]-edge[:,0];length=np.linalg.norm(delta,axis=1);mid=edge.mean(1);angle=source.face_adjacency_angles;valid=(~source.face_adjacency_convex)&(abs(delta[:,1])/np.maximum(length,1e-12)<.25)&(angle>.1)&(mid[:,1]>top-height*.30)&(mid[:,1]<top-height*.04);hh,ee=np.histogram(mid[valid,1],bins=100,range=(low[1],high[1]),weights=length[valid]*angle[valid]);hh=gaussian_filter1d(hh,1);j=int(hh.argmax());bottom=float((ee[j]+ee[j+1])/2)
    if hh[j]<=0:raise ValueError('未观察到稳定接缝，不能确定坐垫底部')
    if not source.is_watertight or not source.is_winding_consistent or source.volume<=0:raise ValueError('坐面与座架分组尚未闭合，请先生成独立部件候选后再替换坐垫')
    upper=trimesh.intersections.slice_mesh_plane(source,[0,1,0],[0,bottom,0],cap=False);frame=trimesh.intersections.slice_mesh_plane(source,[0,-1,0],[0,bottom,0],cap=True,engine='earcut');frame,_=prepare_mesh(frame)
    if not frame.is_watertight or len(frame.split(only_watertight=False))!=1 or intersections(frame):raise ValueError('座架切口未通过闭合检查，保留原模型')
    return upper,frame,{'seat_top_y':top,'cut_bottom_y':bottom,'method':'observed_upward_band_and_concave_seam_candidate','boundary_is_estimated':True,'requires_cut_review':True,'frame_geometry_changed':True}

def replace_generated(doc,binary,request,candidate=None):
    progress=request.get('_progress',lambda phase:None)
    progress('checking_source_scope')
    group,entries,source=selected_group(doc,binary,request['part_ids'],allow_uv=request.get('_allow_uv_rebuild',False));preserve=request.get('method')=='source_seam';discarded={}
    if not preserve:candidate,_=prepare_mesh(candidate);candidate,discarded=keep_single_solid(candidate)
    changed={p['id']for p,q in entries};worlds=node_world_matrices(doc)
    def signatures():
        from edit_asset import accessor_array
        result={}
        for p in parts_catalog(doc):
            if p['id']in changed:continue
            q=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']]
            chunks=[worlds[p['node']].tobytes(),p['material_signature'].encode()]
            for key,index in sorted(q['attributes'].items()):chunks.extend([key.encode(),accessor_array(doc,binary,index).tobytes()])
            if 'indices'in q:chunks.append(accessor_array(doc,binary,q['indices']).tobytes())
            result[p['id']]=hashlib.sha256(b''.join(chunks)).hexdigest()
        return result
    before=signatures()
    if not preserve and(not candidate.is_watertight or not candidate.is_winding_consistent or candidate.volume<=0 or intersections(candidate)):raise ValueError('生成部件没有通过单一闭合体和自交检查')
    kind=request['kind'];slot=None;frame=None;target=source;repair_region=None;surface_repair=request.get('_surface_repair')
    if kind=='cushion' and any(p.get('semantic_kind')=='seat'for p,q in entries):target,frame,slot=cushion_slot(source)
    if preserve:
        if kind!='cushion'or slot is None:raise ValueError('保留原表面修复需要包含接缝的坐面与座架分组')
        aligned=trimesh.intersections.slice_mesh_plane(source,[0,1,0],[0,slot['cut_bottom_y'],0],cap=True,engine='earcut')
        placement={'method':'source_surface_preserved_seam_partition','pose_is_estimated':False,'real_scale_verified':False}
        error=abs(aligned.volume+frame.volume-source.volume)/max(abs(source.volume),1e-15)
        if error>1e-5:raise ValueError('坐垫与座架切分体积校验失败，保留原模型')
        placement['volume_partition_relative_error']=float(error)
        from shapely.geometry import MultiPoint
        from soft_part_repair import rebuild_occluded_seat
        occluders=[]
        for other in parts_catalog(doc):
            if other['id']in changed or other.get('semantic_kind')not in('pillow','bolster'):continue
            primitive=doc['meshes'][doc['nodes'][other['node']]['mesh']]['primitives'][other['primitive']]
            _,_,vertices,_,_,_=primitive_data(doc,binary,other,primitive)
            if vertices[:,1].max()>slot['cut_bottom_y']:
                poly=MultiPoint(vertices[:,[0,2]]).convex_hull
                if poly.area>0:occluders.append(poly.buffer(float(np.linalg.norm(source.extents))*.006))
        aligned,repair_region,surface_repair=rebuild_occluded_seat(aligned,slot['seat_top_y'],slot['cut_bottom_y'],occluders,request.get('_photo_context'))
        if surface_repair:
            placement['method']='source_guided_seam_and_occlusion_reconstruction'
            placement['initial_cut_volume_partition_relative_error']=placement.pop('volume_partition_relative_error')
    elif request.get('_prepared_world'):
        aligned=candidate;placement=request['_placement']
    else:
        progress('aligning');aligned,placement=register_part(candidate,target,kind,bottom=slot['cut_bottom_y']if slot else None)
    if kind=='pillow' and not preserve and not request.get('_prepared_world'):
        from soft_part_repair import fill_paper_pillow,shell_volume_ratio
        aligned,surface_repair=fill_paper_pillow(aligned,target,placement)
        if surface_repair:placement['candidate_transform_is_initialization_only']=True
        elif shell_volume_ratio(aligned)<.18:raise ValueError('生成靠枕仍是弯曲薄壳，且没有可靠的前后表面支持补厚；请更换部件参考图')
    if request.get('_photo_pose_views')and kind in('pillow','bolster'):
        progress('refining_photo_pose')
        from photo_pose_refinement import refine_photo_pose
        aligned,photo_pose=refine_photo_pose(aligned,target,kind,request['_photo_pose_views']);placement['photo_refinement']=photo_pose
        if photo_pose.get('applied')and not surface_repair and'candidate_to_source_world'in placement:
            placement['candidate_to_source_world']=(np.asarray(photo_pose['adjustment_in_world'])@np.asarray(placement['candidate_to_source_world'])).tolist()
    progress('checking_storage');aligned,_=prepare_mesh(aligned)
    if not aligned.is_watertight or intersections(aligned):raise ValueError('对齐后的存储精度检查未通过')
    part,base=entries[0];world=node_world_matrices(doc)[part['node']]
    if np.linalg.det(world[:3,:3])<=0:raise ValueError('镜像或退化节点变换暂不支持自动替换')
    inverse=np.linalg.inv(world);new_group='group_'+uuid.uuid4().hex if frame is not None else group;created=[]
    def emit(mesh,key,name,role,identity):
        local=(np.c_[mesh.vertices,np.ones(len(mesh.vertices))]@inverse.T)[:,:3].astype(np.float32);m=trimesh.Trimesh(local,mesh.faces,process=False);stored,_=prepare_mesh(m)
        if not stored.is_watertight or not stored.is_winding_consistent or stored.volume<=0 or len(stored.split(only_watertight=False))!=1 or intersections(stored):raise ValueError('部件在最终 GLB 坐标精度下未通过闭合检查')
        cap=None;roof=None
        if preserve:
            tolerance=max(float(np.linalg.norm(source.extents))*1e-6,1e-8)
            local_world=(np.c_[stored.vertices,np.ones(len(stored.vertices))]@world.T)[:,:3]
            cap=np.all(abs(local_world[stored.faces,1]-slot['cut_bottom_y'])<tolerance,axis=1)
            roof=np.zeros(len(stored.faces),bool)
            if key==new_group and repair_region is not None:
                from shapely.geometry import Point
                triangles=local_world[stored.faces];centers=triangles.mean(1);cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
                roof=(cross[:,1]>0)&np.array([repair_region.covers(Point(point))for point in centers[:,[0,2]]])
        chunks=[(np.ones(len(stored.faces),bool),role)]if not preserve else[(~(cap|roof),'reconstructed_surface'if key==new_group and surface_repair else'observed_surface'),(cap,'inferred_interface'),(roof&~cap,'inferred_surface')]
        emitted=0
        for mask,stored_role in chunks:
            faces=stored.faces[mask]
            if not len(faces):continue
            used=np.unique(faces);remap=np.full(len(stored.vertices),-1,dtype=int);remap[used]=np.arange(len(used));faces=remap[faces];local=stored.vertices[used].astype(np.float32);surface=trimesh.Trimesh(local,faces,process=False);normals=surface.vertex_normals.copy();normals[np.linalg.norm(normals,axis=1)<1e-10]=[0,1,0];p=copy.deepcopy(base);p['attributes']={'POSITION':append_array(doc,binary,local,'VEC3'),'NORMAL':append_array(doc,binary,normals,'VEC3')};p['indices']=append_array(doc,binary,faces.ravel(),'SCALAR',5125,34963);p.setdefault('extras',{}).update(form_part_name=name,form_logical_group_id=key,form_group_kind='regenerated_logical_part',form_completion_role=stored_role,form_proposal_status='regeneration_review_required',form_semantic_kind=kind if key==new_group else'support',form_completion_note=('沿估计接缝拆分；遮挡区域和底面需检查'if preserve else('根据已有分区几何补全；隐藏形状含推测'if request.get('_geometry_conditioned_completion')else'按原图重新生成；隐藏表面与位置均含推测'))if key==new_group else'保留座架并增加推测切口');created.append((p,identity if emitted==0 else'part_'+uuid.uuid4().hex));emitted+=1
    if frame is not None:emit(frame,group,'座架（接口待确认）','inferred_interface',part['id'])
    emit(aligned,new_group,('坐垫'if kind=='cushion'else'圆柱抱枕'if kind=='bolster'else part['name'])+('（原形修复候选）'if preserve and surface_repair else'（保留原表面）'if preserve else'（重生成候选）'),'reconstructed_surface'if surface_repair else'regenerated_surface',('part_'+uuid.uuid4().hex)if frame is not None else part['id'])
    replacements={}
    for i,(old,p)in enumerate(entries):replacements.setdefault(old['node'],{})[old['primitive']]=created if i==0 else[]
    replace_primitives(doc,replacements)
    after=signatures();after={k:v for k,v in after.items()if k in before}
    if after!=before:raise ValueError('相邻部件保留校验失败，未采用替换')
    return {'operation':'replace_part','method':'source_seam'if preserve else'ai_regeneration','surface_repair':surface_repair,'part_group_ids':[new_group],'source_group_id':group,'kind':kind,'placement':placement,'slot':slot,'part':mesh_stats(aligned),'frame':mesh_stats(frame)if frame is not None else None,'source_group':mesh_stats(source),'discarded_generated_artifacts':discarded,'unrelated_groups_unchanged':True,'appearance_review':'unreviewed','real_hidden_geometry_recovered':False}

def write_preview(doc,binary,extra,operation,out,source_sha256,candidate_sha256=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);binary=compact_static(doc,binary);write_glb(out/'model.glb',doc,binary,extra)
    # Aligned standalone part retains source scene coordinates.
    from part_tools import export_parts
    standalone=copy.deepcopy(doc);sb=bytearray(binary);ids=[p['id']for p in parts_catalog(doc)if p.get('logical_group_id')in operation['part_group_ids']];export_parts(standalone,sb,{'part_ids':ids});write_glb(out/'part.glb',standalone,compact_static(standalone,sb),extra)
    diagnostic=copy.deepcopy(doc);start=len(diagnostic.setdefault('materials',[]))
    for name,color in [('preview_inferred',[1,.32,.025,1]),('preview_source',[.05,.48,.72,1]),('preview_body',[.45,.48,.53,.18])]:
        mat={'name':name,'pbrMetallicRoughness':{'baseColorFactor':color,'metallicFactor':0,'roughnessFactor':.8},'doubleSided':True}
        if color[3]<1:mat['alphaMode']='BLEND'
        diagnostic['materials'].append(mat)
    for mesh in diagnostic['meshes']:
        for primitive in mesh['primitives']:
            g=primitive.get('extras',{}).get('form_logical_group_id');preserve=operation['method']=='source_seam';primitive['material']=start+((0 if primitive.get('extras',{}).get('form_completion_role')in('inferred_interface','inferred_surface')else 1)if g in operation['part_group_ids']and preserve else 0 if g in operation['part_group_ids'] else 1 if operation['slot']and g==operation['source_group_id']and not preserve else 2)
    write_glb(out/'diagnostic.glb',diagnostic,binary,extra);manifest={'operation':operation,'source_sha256':source_sha256,'candidate_sha256':candidate_sha256,'model_sha256':hashlib.sha256((out/'model.glb').read_bytes()).hexdigest(),'appearance_review':'unreviewed','positions_unchanged':operation['method']=='keep'};(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');return manifest

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--candidate');p.add_argument('--request',required=True);p.add_argument('--output',required=True);a=p.parse_args();doc,binary,extra=read_glb(a.input);candidate=trimesh.load(a.candidate,force='mesh',process=False)if a.candidate else None;request=json.loads(Path(a.request).read_text(encoding='utf-8'));operation=replace_generated(doc,binary,request,candidate);write_preview(doc,binary,extra,operation,a.output,hashlib.sha256(Path(a.input).read_bytes()).hexdigest(),hashlib.sha256(Path(a.candidate).read_bytes()).hexdigest()if a.candidate else None);print(json.dumps(operation,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
