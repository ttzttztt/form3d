"""Quality-gated solid proposals for saved logical groups.

Reconstructs the supplied surface assignment, not the real product's unseen
structure. Failed groups are kept intact; no technical patch becomes a part.
"""
import copy
import sys
import uuid
import hashlib
from pathlib import Path
import numpy as np
import trimesh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.tools/geometry_extra'))
from services.api.glb_document import parts_catalog,selected_primitives
from furniture_parts import primitive_data,replace_primitives
from solid_partition import prepare_mesh
from complete_part import mesh_stats

LIMITS={'source_p95_diagonal_ratio':.01,'source_p99_diagonal_ratio':.025,
        'source_max_diagonal_ratio':.06,'bounds_delta_diagonal_ratio':.025,
        'discarded_reconstructed_area_fraction':.015,
        'discarded_reconstructed_volume_fraction':.002}

class CandidateRejected(ValueError):
    def __init__(self,message,evidence):
        super().__init__(message);self.evidence=evidence


def intersections(mesh):
    import pymeshlab
    ms=pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(mesh.vertices,mesh.faces.astype(np.int32)))
    ms.compute_selection_by_self_intersections_per_face()
    return int(ms.current_mesh().face_selection_array().sum())


def keep_single_solid(mesh):
    components=sorted(mesh.split(only_watertight=False),key=lambda m:m.area,reverse=True)
    if not components:raise ValueError('没有形成可用实体')
    area=float(sum(m.area for m in components[1:])/mesh.area)
    volume=float(sum(abs(m.volume) for m in components[1:])/max(sum(abs(m.volume) for m in components),1e-15))
    if area>LIMITS['discarded_reconstructed_area_fraction'] or volume>LIMITS['discarded_reconstructed_volume_fraction']:
        raise CandidateRejected('重建产生多个明显实体，未丢弃背面或其他大块表面',{'reconstructed_components':len(components),'secondary_reconstructed_area_fraction':area,'secondary_reconstructed_volume_fraction':volume})
    return components[0],{'discarded_reconstructed_components':len(components)-1,'discarded_reconstructed_area_fraction':area,'discarded_reconstructed_volume_fraction':volume}


def source_deviation(source,candidate,count=6000):
    # Deterministic area-weighted surface samples; these are NOT a Hausdorff
    # distance, semantic accuracy, or an error relative to the physical product.
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.tools/geometry_extra'))
    import igl
    rng=np.random.default_rng(20261113)
    ids=rng.choice(len(source.faces),count,p=source.area_faces/source.area)
    bary=rng.random((count,2));root=np.sqrt(bary[:,0]);weights=np.c_[1-root,root*(1-bary[:,1]),root*bary[:,1]]
    samples=(source.triangles[ids]*weights[:,:,None]).sum(1)
    distance,*_=igl.signed_distance(np.ascontiguousarray(samples),np.ascontiguousarray(candidate.vertices),np.ascontiguousarray(candidate.faces,dtype=np.int64),igl.SIGNED_DISTANCE_TYPE_UNSIGNED)
    diagonal=max(float(np.linalg.norm(source.extents)),1e-12);distance=np.abs(distance)/diagonal
    return {'samples':count,'seed':20261113,'sampling':'area_weighted_random_barycentric_surface_points',
            'source_p95_diagonal_ratio':float(np.quantile(distance,.95)),
            'source_p99_diagonal_ratio':float(np.quantile(distance,.99)),
            'source_max_diagonal_ratio':float(distance.max()),
            'bounds_delta_diagonal_ratio':float(np.max(abs(source.bounds-candidate.bounds))/diagonal),
            'not_product_accuracy':True}


def solid_candidate(source,kind=None):
    from winding_surface import winding_surface
    source,_=prepare_mesh(source)
    if len(source.faces)>800000:raise ValueError('该部件超过 80 万面，请先减面再重建')
    if not np.isfinite(source.vertices).all() or source.area<=0:raise ValueError('源表面坐标或面积无效')
    if source.is_watertight:
        if not source.is_winding_consistent or source.volume<=0 or len(source.split(only_watertight=False))!=1 or intersections(source):
            raise ValueError('已有闭合网格的方向、连通性或自交检查未通过')
        return source,{'already_closed':True,'after':mesh_stats(source)}
    if kind=='bolster':
        # An open observed cylinder should become a full bolster, rather than
        # a thin closed shell around its visible half. Fit only when geometry
        # supports the AI label; no fixed-size template or text-only cylinder.
        from soft_shapes import bolster_profile
        mesh,method=bolster_profile(source)
    else:mesh,method=winding_surface(source,observed_distance=True)
    mesh,discarded=keep_single_solid(mesh)
    mesh,_=prepare_mesh(mesh)
    stats=mesh_stats(mesh)
    if not stats['watertight'] or not stats['winding_consistent'] or stats['volume']<=0:raise ValueError('GLB 存储精度下未形成一致闭合体')
    if intersections(mesh):raise ValueError('候选表面存在自交，未采用')
    deviation=source_deviation(source,mesh)
    failed=[key for key,value in deviation.items() if key in LIMITS and value>LIMITS[key]]
    if failed:raise CandidateRejected('重建偏离源表面或外形范围，未采用',{'source_deviation':deviation,'thresholds':LIMITS,'failed_checks':failed})
    return mesh,{'already_closed':False,'after':stats,'components':1,'self_intersection_faces':0,
                 'method':method,'source_deviation':deviation,'thresholds':LIMITS,**discarded,
                 'semantic_boundary_verified':False,'appearance_review':'unreviewed'}


def reconstruct_parts(doc,binary,request):
    from asset_operations import append_array
    from edit_asset import node_world_matrices
    if request.get('face_selection'):raise ValueError('请先保存整体部件分组，再生成实体预览')
    catalog=parts_catalog(doc)
    chosen=request.get('part_ids',[])
    if not chosen:raise ValueError('请选择已保存的完整部件组')
    if any(identity not in {p['id'] for p in catalog} for identity in chosen):raise ValueError('部件已变化，请重新选择')
    # Expand a selected technical surface to the entire logical part.
    keys={p.get('logical_group_id') or p['id'] for p in catalog if p['id'] in chosen}
    selected=[p for p in catalog if (p.get('logical_group_id') or p['id']) in keys]
    if sum(p['triangles'] for p in selected)>1600000:raise ValueError('当前范围超过 160 万面，请分组处理或先减面')
    groups={}
    for part,p in selected_primitives(doc,[p['id'] for p in selected]):
        key=part.get('logical_group_id') or part['id'];groups.setdefault(key,[]).append((part,p))
    if len(groups)>16:raise ValueError('一次最多处理 16 个完整部件')
    replacements={};records=[];accepted=[];worlds=node_world_matrices(doc)
    for group,entries in groups.items():
        record={'id':group,'name':entries[0][0]['name'],'status':'kept_source'};records.append(record)
        try:
            if len({part['node'] for part,p in entries})!=1:raise ValueError('跨节点部件暂不重建，请保留原分组')
            if len({part['material_signature'] for part,p in entries})!=1:raise ValueError('整体部件含多种材质，请在换材质前重建')
            meshes=[]
            for part,p in entries:
                if set(p['attributes'])-{'POSITION','NORMAL'} or p.get('extensions'):raise ValueError('带贴图、顶点颜色或压缩的部件暂不重建，以免丢失外观')
                material=doc.get('materials',[])[p['material']] if 'material' in p else {}
                if any('Texture' in k for k in material) or any('Texture' in k for k in material.get('pbrMetallicRoughness',{})) or material.get('extensions'):
                    raise ValueError('带贴图或扩展材质的部件暂不重建，以免丢失外观')
                _,faces,world,_,_,_=primitive_data(doc,binary,part,p)
                m=trimesh.Trimesh(world,faces,process=False);m.remove_unreferenced_vertices();meshes.append(m)
            source,_=prepare_mesh(trimesh.util.concatenate(meshes));candidate,evidence=solid_candidate(source,entries[0][0].get('semantic_kind'));record.update(evidence)
            if evidence['already_closed']:
                record['status']='already_closed';continue
            part,base=entries[0];inverse=np.linalg.inv(worlds[part['node']])
            local=(np.c_[candidate.vertices,np.ones(len(candidate.vertices))]@inverse.T)[:,:3].astype(np.float32)
            # Re-check the float32 local -> world round trip before emitting.
            stored=trimesh.Trimesh((np.c_[local,np.ones(len(local))]@worlds[part['node']].T)[:,:3],candidate.faces,process=False)
            stored,_=prepare_mesh(stored)
            if not stored.is_watertight or not stored.is_winding_consistent or intersections(stored):raise ValueError('节点变换后的存储精度检查未通过')
            import igl
            distance,*_=igl.signed_distance(np.ascontiguousarray(candidate.triangles_center),np.ascontiguousarray(source.vertices),np.ascontiguousarray(source.faces,dtype=np.int64),igl.SIGNED_DISTANCE_TYPE_UNSIGNED)
            inferred=np.abs(distance)>max(evidence['method'].get('grid_step_source_units',0)*2,float(np.linalg.norm(source.extents))*.006)
            made=[]
            complete_local=trimesh.Trimesh(local,candidate.faces,process=False)
            all_normals=complete_local.vertex_normals.copy()
            all_normals[np.linalg.norm(all_normals,axis=1)<1e-10]=[0,1,0]
            for role,mask in [('reconstructed_surface',~inferred),('inferred_interface',inferred)]:
                f=candidate.faces[mask]
                if not len(f):continue
                used=np.unique(f);lookup=np.full(len(local),-1,dtype=np.int64);lookup[used]=np.arange(len(used))
                p=copy.deepcopy(base);p['attributes']={'POSITION':append_array(doc,binary,local[used],'VEC3'),'NORMAL':append_array(doc,binary,all_normals[used],'VEC3')};p['indices']=append_array(doc,binary,lookup[f].ravel(),'SCALAR',5125,34963)
                p.setdefault('extras',{}).update(form_logical_group_id=group,form_group_kind='reconstructed_logical_part',form_completion_role=role,
                    form_completion_note='全部网格均为重建表面；远离源表面的区域为推测，不能恢复真实隐藏结构',form_proposal_status='reconstruction_review_required')
                # Stable first ID preserves saved group selection, additional
                # primitives are technical patches owned by the same group.
                made.append((p,part['id'] if not made else 'part_'+uuid.uuid4().hex))
            for ordinal,(old,p) in enumerate(entries):replacements.setdefault(old['node'],{})[old['primitive']]=made if ordinal==0 else []
            record.update(status='reconstructed',inferred_area_fraction=float(candidate.area_faces[inferred].sum()/candidate.area),all_output_surfaces_reconstructed=True)
            accepted.append(group)
        except (ValueError,np.linalg.LinAlgError) as exc:
            record['reason']=str(exc)
            if isinstance(exc,CandidateRejected):record['rejection_evidence']=exc.evidence
    if not accepted:
        raise ValueError('没有需要且能安全重建的部件。'+ '；'.join(r['name']+'：'+r.get('reason','已经闭合') for r in records)[:170])
    replace_primitives(doc,replacements)
    revision=hashlib.sha256(b''.join((Path(__file__).parent/name).read_bytes() for name in ('reconstruct_parts.py','winding_surface.py','soft_shapes.py','cylinder_evidence.py'))).hexdigest()
    return {'operation':'reconstruct_parts','part_group_ids':accepted,'groups':records,'positions_unchanged':False,'reconstruction_revision':revision,
            'appearance_review':'unreviewed','semantic_boundary_verified':False,'real_hidden_geometry_recovered':False,
            'limits':['闭合检查只验证网格，不能证明部件边界或实物形状正确。','全部输出面均为重建，橙色区域缺少附近源表面支持。','不符合保护阈值的组保留源网格，不冒充重建成功。']}
