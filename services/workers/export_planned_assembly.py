"""Export image-linked native slots as stable editable parts, after real geometry checks."""
import argparse,copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'services/workers'),str(ROOT/'.tools/geometry_extra')]


def run(args):
    import numpy as np,trimesh,igl
    from generate_partcrafter import digest,write
    from services.api.assembly_models import AssemblyPlan,AssemblyRelation
    from services.api.glb_document import write_glb,read_glb,parts_catalog,compact_static
    from asset_operations import append_array
    from replacement_uv import prepare_replacement_uv
    from mesh_integrity import exact_storage_mesh
    from reconstruct_parts import intersections
    source=Path(args.source);evidence=Path(args.observations);output=Path(args.output)
    if output.exists():raise ValueError('Preserve previous assemblies')
    plan=AssemblyPlan.model_validate_json((evidence/'plan.json').read_text(encoding='utf-8'))
    if plan.status!='planned':raise ValueError('Unresolved image inventory cannot be exported as a complete assembly')
    generation=json.loads((source/'generation.json').read_text(encoding='utf-8'));audit=json.loads((source/args.audit/'audit.json').read_text(encoding='utf-8'))
    if audit['generation_sha256']!=digest(source/'generation.json')or audit['photo_evidence']['observations_sha256']!=digest(evidence/'observations.json'):raise ValueError('Audit and generation evidence changed')
    if audit['geometry_gate']!='passed':raise ValueError('The native geometry has not passed integrity checks')
    if generation.get('plan_binding',{}).get('plan_sha256')!=digest(evidence/'plan.json'):raise ValueError('Generation was not bound to this plan')
    matches={row['raw_slot']:row for row in audit['photo_evidence']['matches']if row['link_status']=='photo_linked_hypothesis'}
    doc={'asset':{'version':'2.0','generator':'img_to3D image-first assembly'},'scene':0,'scenes':[{'nodes':[0]}],
        'nodes':[{'name':'家具装配（需检查）','children':[],'extras':{'assembly_plan_id':plan.id,'physical_structure_verified':False}}],
        'meshes':[],'materials':[],'buffers':[{'byteLength':0}]};binary=bytearray();geometry={};bindings=[];seen=set()
    palette=[[.65,.69,.75,1],[.52,.59,.67,1],[.7,.65,.58,1]]
    node_indices={}
    for planned in plan.parts:
        node_indices[planned.id]=len(doc['nodes']);doc['nodes'].append({'name':planned.name,'extras':{'assembly_part_id':planned.id,'geometry_role':planned.geometry_role}})
    for row in generation['parts']:
        link=matches.get(row['slot'])
        if link is None:raise ValueError('An unmatched native slot cannot become a semantic part')
        candidates=[p for p in plan.parts if any(o.mask_sha256==link['mask_sha256']for o in p.observations)]
        if len(candidates)!=1:raise ValueError('A projected slot does not identify exactly one planned part')
        part=candidates[0]
        if part.id in seen:raise ValueError('Two native slots map to the same part')
        file=source/row['file']
        if digest(file)!=row['sha256']:raise ValueError('Raw slot changed')
        mesh,cleanup=exact_storage_mesh(trimesh.load(file,force='scene',process=False).to_geometry())
        if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume<=0 or len(mesh.split(only_watertight=False))!=1 or intersections(mesh):raise ValueError('Part integrity failed after exact position cleanup')
        normal=mesh.vertex_normals.copy();bad=np.linalg.norm(normal,axis=1)<.5
        if bad.any():
            for face,face_normal in zip(mesh.faces,mesh.face_normals):
                for index in face:
                    if bad[index]:normal[index]=face_normal;bad[index]=False
        if bad.any():raise ValueError('No normal for a referenced vertex')
        position=append_array(doc,binary,mesh.vertices,'VEC3');normals=append_array(doc,binary,normal,'VEC3')
        indices=append_array(doc,binary,mesh.faces.astype(np.uint32).ravel(),'SCALAR',5125,34963)
        material=len(doc['materials']);doc['materials'].append({'name':part.name+' · 中性检查材质','pbrMetallicRoughness':{'baseColorFactor':palette[material%len(palette)],'metallicFactor':0,'roughnessFactor':.8}})
        primitive={'attributes':{'POSITION':position,'NORMAL':normals},'indices':indices,'material':material,
            'extras':{'form_logical_group_id':part.id,'form_part_name':part.name,'form_semantic_kind':part.kind,
                'form_group_kind':'planned_native_part','form_proposal_status':'needs_review','form_completion_note':'单图生成；隐藏表面与真实尺寸未验证'}}
        mesh_index=len(doc['meshes']);doc['meshes'].append({'name':part.name,'primitives':[primitive]});primitive_id=part.id+'__geometry'
        node=doc['nodes'][node_indices[part.id]];node['mesh']=mesh_index;node['extras']['form_part_ids']={'0':primitive_id}
        geometry[part.id]=mesh;seen.add(part.id);part.status='ready';part.primitive_ids=[primitive_id];part.bounds_world=mesh.bounds.tolist();part.hidden_surface_status='inferred'
        bindings.append({'part_id':part.id,'raw_slot':row['slot'],'mask_sha256':link['mask_sha256'],'source_slot_sha256':row['sha256'],'cleanup':cleanup})
    physical=[p for p in plan.parts if p.geometry_role=='physical_part']
    if seen!={p.id for p in physical}:raise ValueError('Some planned physical parts have no generated geometry')
    for part in plan.parts:
        parent=node_indices[part.parent_id]if part.parent_id is not None else 0
        doc['nodes'][parent].setdefault('children',[]).append(node_indices[part.id])
        if part.geometry_role=='structural_group':part.status='ready'
    placement=[]
    if args.level_tabletop:
        if not args.align_table_contact:raise ValueError('Leveling requires contact verification')
        tops=[p for p in physical if p.kind=='tabletop'];supports=[p for p in physical if p.kind in('leg','frame')]
        if plan.object_category!='table'or len(tops)!=1 or len(supports)!=1:raise ValueError('Leveling requires one tabletop and one support assembly')
        top=tops[0];plate=geometry[top.id];_,vectors=np.linalg.eigh(np.cov(plate.vertices.T));normal=vectors[:,0]
        if normal[1]<0:normal=-normal
        angle=float(np.degrees(np.arccos(np.clip(normal[1],-1,1))))
        if angle>25:raise ValueError('Tabletop orientation is too ambiguous for limited rigid correction')
        from assembly_pose import shortest_up_rotation
        transform=np.eye(4);transform[:3,:3]=shortest_up_rotation(normal);center=plate.centroid
        transform[:3,3]=center-transform[:3,:3]@center
        moved=plate.copy();moved.apply_transform(transform);geometry[top.id]=moved;top.bounds_world=moved.bounds.tolist()
        quaternion=trimesh.transformations.quaternion_from_matrix(transform)
        node=doc['nodes'][node_indices[top.id]];node['rotation']=quaternion[[1,2,3,0]].tolist();node['translation']=transform[:3,3].tolist()
        placement.append({'part_id':top.id,'method':'inferred_rigid_tabletop_leveling','angle_degrees':angle,
            'assumption':'tabletop_should_be_horizontal_in_gltf_y_up_frame','transform':transform.tolist(),
            'source_vertex_positions_changed':False,'physical_orientation_verified':False})
    if args.align_table_contact:
        tops=[p for p in physical if p.kind=='tabletop'];supports=[p for p in physical if p.kind in('leg','frame')]
        if plan.object_category!='table'or len(tops)!=1 or len(supports)!=1:raise ValueError('Contact alignment currently requires one tabletop and one support assembly')
        top=tops[0];support=supports[0];plate=geometry[top.id];base=geometry[support.id]
        _,vectors=np.linalg.eigh(np.cov(plate.vertices.T));normal=vectors[:,0]
        if normal[1]<0:normal=-normal
        origin=base.vertices[int(np.argmax(base.vertices@normal))]
        triangles=plate.triangles;e1=triangles[:,1]-triangles[:,0];e2=triangles[:,2]-triangles[:,0]
        h=np.cross(np.broadcast_to(normal,e2.shape),e2);det=np.einsum('ij,ij->i',e1,h);valid=abs(det)>1e-12
        inverse=np.zeros(len(det));inverse[valid]=1/det[valid];s=origin-triangles[:,0]
        u=np.einsum('ij,ij->i',s,h)*inverse;q=np.cross(s,e1);v=q@normal*inverse;t=np.einsum('ij,ij->i',e2,q)*inverse
        valid &= (u>=-1e-8)&(v>=-1e-8)&(u+v<=1+1e-8)&(t>1e-8)
        if not valid.any():raise ValueError('No supported upward contact ray hits the tabletop')
        distance=float(t[valid].min());scene_diag=float(np.linalg.norm(np.ptp(np.vstack([plate.vertices,base.vertices]),axis=0)))
        if distance>scene_diag*.05:raise ValueError('Required placement correction is too large for automatic contact alignment')
        shift=-normal*distance;node=doc['nodes'][node_indices[top.id]];node['translation']=(np.asarray(node.get('translation',[0,0,0]))+shift).tolist()
        moved=plate.copy();moved.apply_translation(shift);geometry[top.id]=moved;top.bounds_world=moved.bounds.tolist()
        residual,*_=igl.signed_distance(np.asarray([origin]),np.ascontiguousarray(moved.vertices),np.ascontiguousarray(moved.faces,dtype=np.int64),igl.SIGNED_DISTANCE_TYPE_UNSIGNED)
        if float(abs(residual[0]))>scene_diag*1e-6:raise ValueError('The proposed contact anchor did not meet the tabletop')
        placement.append({'part_id':top.id,'method':'inferred_rigid_contact_alignment_along_fitted_tabletop_normal',
            'translation_normalized_units':shift.tolist(),'shift_to_scene_diagonal':distance/scene_diag,
            'contact_anchor_normalized_units':origin.tolist(),'verified_anchor_surface_distance_normalized_units':float(abs(residual[0])),
            'source_vertex_positions_changed':False,'contact_is_manufacturing_ground_truth':False})
    uv=prepare_replacement_uv(doc,binary,list(seen));bounds=np.array([np.min([m.bounds[0]for m in geometry.values()],axis=0),np.max([m.bounds[1]for m in geometry.values()],axis=0)]);diagonal=float(np.linalg.norm(bounds[1]-bounds[0]));contacts=[]
    items=list(geometry.items())
    for index,(a_id,a)in enumerate(items):
        for b_id,b in items[index+1:]:
            intersection=trimesh.boolean.intersection([a,b],engine='manifold');overlap=float(abs(intersection.volume))if len(intersection.faces)else 0.
            if overlap:gap=0.
            else:
                points=a.vertices[::max(1,len(a.vertices)//4000)];distance,*_=igl.signed_distance(np.ascontiguousarray(points),np.ascontiguousarray(b.vertices),np.ascontiguousarray(b.faces,dtype=np.int64),igl.SIGNED_DISTANCE_TYPE_UNSIGNED);gap=float(abs(distance).min())
            contacts.append({'a':a_id,'b':b_id,'intersection_volume_normalized_units':overlap,'intersection_fraction_of_smaller_part':overlap/min(a.volume,b.volume),
                'sampled_vertex_surface_gap_normalized_units':gap,'gap_to_scene_diagonal':gap/diagonal,'gap_measurement_is_approximate':True})
    output.mkdir(parents=True);write_glb(output/'model.glb',doc,binary)
    for part in physical:part.model_sha256=digest(output/'model.glb')
    plan.status='ready_for_review';plan.overall_bounds_world=bounds.tolist()
    if plan.object_category=='table':
        tops=[p for p in physical if p.kind=='tabletop'];supports=[p for p in physical if p.kind in('leg','frame')]
        for top in tops:
            for support in supports:plan.relations.append(AssemblyRelation(part_id=top.id,target_part_id=support.id,kind='supported_by',evidence='inferred'))
    plan=AssemblyPlan.model_validate(plan.model_dump());write(output/'plan.json',plan.model_dump())
    for part in physical:
        subset=copy.deepcopy(doc);node=next(n for n in subset['nodes']if n.get('extras',{}).get('assembly_part_id')==part.id)
        node.pop('children',None);subset['nodes']=[node];subset['scenes']=[{'nodes':[0]}];subset['scene']=0;subbinary=compact_static(subset,bytearray(binary));write_glb(output/(part.id+'.glb'),subset,subbinary)
    write(output/'assembly.json',{'status':'candidate_ready_for_review','source_generation_sha256':digest(source/'generation.json'),
        'source_engine':generation['engine'],
        'source_plan_sha256':digest(evidence/'plan.json'),'source_audit_sha256':digest(source/args.audit/'audit.json'),'model_sha256':digest(output/'model.glb'),
        'bindings':bindings,'contacts':contacts,'placement_hypotheses':placement,'uv':uv,'materials':'independent_neutral_diagnostic_materials_not_recovered_textures',
        'coordinate_frame':'native_shared_frame_preserved','semantic_assignment_verified':False,'physical_structure_verified':False,'appearance_accepted':False,
        'complete_assembly_accepted':False,'part_ids':[p.id for p in physical]})
    write(output/'generation.json',{'engine':generation['engine'],'mode':'assembled_candidate_from_image_linked_parts','is_new_sampling':False,
        'source_generation_sha256':digest(source/'generation.json'),'object_file':'model.glb','object_sha256':digest(output/'model.glb'),
        'shared_coordinate_frame':True,'semantic_assignment_verified':False,'physical_structure_verified':False,'complete_assembly_accepted':False,
        'parts':[{'slot':i,'id':p.id,'semantic_kind':p.kind,'semantic_assignment_verified':False,'file':p.id+'.glb','sha256':digest(output/(p.id+'.glb'))}for i,p in enumerate(physical)]})
    print('ASSEMBLY_CANDIDATE_EXPORTED',len(physical),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--observations',required=True);p.add_argument('--audit',default='audit_02');p.add_argument('--output',required=True);p.add_argument('--align-table-contact',action='store_true');p.add_argument('--level-tabletop',action='store_true',help='Explicit inferred rigid leveling; not a photo-measured orientation');run(p.parse_args())
