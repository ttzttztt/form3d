# -*- coding: utf-8 -*-
"""Candidate evidence dimensions; ranking is never a physical accuracy score."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'.tools/geometry_extra'))
import numpy as np
import trimesh
from services.api.glb_document import parts_catalog
from furniture_parts import primitive_data
from solid_partition import prepare_mesh
from reconstruct_parts import intersections
from part_registration import surface_samples
from shape_simplification import component_count


def neighbor_penetration(result,source,doc,binary,selected_ids):
    import igl
    diagonal=max(float(np.linalg.norm(source.extents)),1e-12);targets=set(selected_ids);groups={}
    for part in parts_catalog(doc):
        if part['id']in targets:continue
        primitive=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
        _,faces,world,_,_,_=primitive_data(doc,binary,part,primitive)
        key=part.get('logical_group_id')or part['id'];groups.setdefault(key,[]).append(trimesh.Trimesh(world,faces,process=False))
    point_sets=[]
    for mesh in(source,result):
        points=surface_samples(mesh,1800)[0]
        if mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0:
            interior=points*.92+mesh.centroid*.08
            signed,*_=igl.signed_distance(np.ascontiguousarray(interior),np.ascontiguousarray(mesh.vertices),np.ascontiguousarray(mesh.faces,dtype=np.int64),igl.SIGNED_DISTANCE_TYPE_PSEUDONORMAL)
            points=np.vstack([points,interior[signed<0]])
        point_sets.append(points)
    entries=[];skipped=0
    for key,meshes in groups.items():
        neighbor,_=prepare_mesh(trimesh.util.concatenate(meshes))
        if np.any(result.bounds[1]<neighbor.bounds[0])or np.any(result.bounds[0]>neighbor.bounds[1]):continue
        if not neighbor.is_watertight or not neighbor.is_winding_consistent or neighbor.volume<=0:skipped+=1;continue
        measures=[]
        for points in point_sets:
            signed,*_=igl.signed_distance(np.ascontiguousarray(points),np.ascontiguousarray(neighbor.vertices),np.ascontiguousarray(neighbor.faces,dtype=np.int64),igl.SIGNED_DISTANCE_TYPE_PSEUDONORMAL)
            depth=np.maximum(-signed,0)/diagonal
            measures.append({'sample_fraction_deeper_than_008_diagonal':float(np.mean(depth>.008)),'maximum_sampled_depth_diagonal_ratio':float(depth.max())})
        before,after=measures
        severe=after['sample_fraction_deeper_than_008_diagonal']>max(.10,before['sample_fraction_deeper_than_008_diagonal']+.08)and after['maximum_sampled_depth_diagonal_ratio']>before['maximum_sampled_depth_diagonal_ratio']+.015
        entries.append({'group_id':key,'before':before,'after':after,'severe_increase':bool(severe)})
    return {'closed_neighbors_tested':len(entries),'open_or_invalid_neighbors_skipped':skipped,'neighbors':entries,
            'severe_increase':any(e['severe_increase']for e in entries),'sampling':'surface_points_plus_verified_near_surface_interior_points',
            'sampling_is_not_exact_collision_detection':True}


def assess_candidate(result,source,doc,binary,selected_ids,views,target_faces,operation):
    count=int(intersections(result));components=component_count(result)
    healthy=bool(result.is_watertight and result.is_winding_consistent and result.volume>0 and components==1 and count==0)
    penetration=neighbor_penetration(result,source,doc,binary,selected_ids)
    face_angles=result.face_adjacency_angles;sharp=result.face_adjacency[face_angles>np.deg2rad(110)]
    sharp_area=float(result.area_faces[np.unique(sharp)].sum()/max(result.area,1e-12))if len(sharp)else 0.
    mean_iou=float(np.mean([v['part_silhouette_iou_after']for v in views]))
    worst_penetration=max((e['after']['sample_fraction_deeper_than_008_diagonal']for e in penetration['neighbors']),default=0.)
    score=float(np.clip(.8*mean_iou+.1*(1-sharp_area)+.1*(1-worst_penetration),0,1))
    extra_views=sum(v.get('additional_reference',v.get('independent_photo',False))for v in views)
    photo_pass=all(v['passed']for v in views)
    photo_declined=any(v['part_silhouette_iou_after']<v['part_silhouette_iou_before']for v in views)
    dimensions=[
      {'key':'integrity','label':'部件完整性','status':'blocked'if not healthy or penetration['severe_increase']else'warning'if penetration['open_or_invalid_neighbors_skipped']else'passed','summary':'与相邻闭合部件的穿插明显增加'if penetration['severe_increase']else('单一闭合体，无检测到的自交；部分邻件开口，穿插检查不完整'if penetration['open_or_invalid_neighbors_skipped']else'单一闭合体，无检测到的自交')if healthy else'闭合、体积或自交检查未通过','metrics':{'triangles':len(result.faces),'components':components,'self_intersection_faces':count,'neighbor_penetration':penetration}},
      {'key':'photo','label':'照片吻合程度','status':'blocked'if not photo_pass else'warning'if photo_declined else'passed','summary':'部分视角轮廓未通过'if not photo_pass else'轮廓检查通过，但有视角略有下降'if photo_declined else'所用视角的轮廓检查通过','metrics':{'views':views,'is_product_accuracy':False}},
      {'key':'performance','label':'运行性能','status':'passed'if len(result.faces)<=target_faces*1.02 else'warning','summary':f'部件 {len(result.faces):,} 面，目标约 {target_faces:,} 面','metrics':{'triangles':len(result.faces),'target_faces':target_faces}},
      {'key':'uncertainty','label':'待确认区域','status':'unverified','summary':f'有 {extra_views} 张补充视图支持筛选；尺寸与隐藏形状仍未实测'if extra_views else'缺少独立侧面/背面证据，厚度和隐藏形状仍含推测','metrics':{'additional_views_used':extra_views,'physical_dimensions_verified':False,'occluded_roof_fraction':(operation.get('surface_repair')or{}).get('occluded_roof_area_fraction')}}
    ]
    return {'eligible':healthy and not penetration['severe_increase'],'dimensions':dimensions,
            'ranking':{'score':score,'mean_photo_iou':mean_iou,'sharp_fold_area_fraction':sharp_area,'maximum_neighbor_penetration_sample_fraction':worst_penetration,'policy':'80% photo silhouette, 10% absence of extreme folds, 10% sampled closed-neighbor clearance; heuristic ranking only','is_product_accuracy':False}}
