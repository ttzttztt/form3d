"""Local repair preview from hash-bound legacy groups; no task or original is changed."""
import argparse,copy,json,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.tools/geometry_extra')]


def run(args):
    import numpy as np,trimesh
    from generate_partcrafter import digest,write
    from services.api.glb_document import read_glb,write_glb,parts_catalog,compact_static
    from services.api.geometry import validate_glb
    from replace_generated_part import replace_generated
    from replacement_uv import prepare_replacement_uv
    from part_tools import export_parts
    from furniture_parts import primitive_data
    from mesh_integrity import exact_storage_mesh
    from reconstruct_parts import intersections
    output=Path(args.output)
    if output.exists():raise ValueError('Keep prior preview and failure evidence')
    case=next(c for c in json.loads(Path(args.cases).read_text(encoding='utf-8'))if c['case']==args.case)
    source=ROOT/case['coarse_reference'];source_sha=digest(source)
    if source_sha!=case['coarse_sha256']:raise ValueError('Frozen coarse source changed')
    completions=[];seen=set()
    for location in args.completion:
        folder=Path(location);data=json.loads((folder/'generation.json').read_text(encoding='utf-8'));binding=data['input_binding']
        if data['status']!='raw_candidate_ready'or binding['source_model_sha256']!=source_sha:raise ValueError('Completion does not belong to this source')
        group=binding['source_group_id']
        if group in seen:raise ValueError('Duplicate completion for one group')
        seen.add(group);part=data['parts'][0];file=folder/part['file']
        if digest(file)!=part['sha256']:raise ValueError('Completion geometry changed')
        completions.append((folder,data,file))
    output.mkdir(parents=True)
    try:
        doc,binary,extra=read_glb(source);operations=[]
        for folder,data,file in completions:
            group=data['input_binding']['source_group_id'];chosen=[p for p in parts_catalog(doc)if p['logical_group_id']==group]
            if not chosen:raise ValueError('Legacy target group disappeared')
            kind=chosen[0]['semantic_kind'];kind='body'if kind=='seat'else kind
            candidate=trimesh.load(file,force='scene',process=False).to_geometry()
            operation=replace_generated(doc,binary,{'part_ids':[p['id']for p in chosen],'kind':kind,'_allow_uv_rebuild':True,
                '_prepared_world':True,'_geometry_conditioned_completion':True,
                '_placement':{'method':'HoloPart_coarse_context_conditioned_shared_world_pose','pose_is_estimated':True,
                    'source_generation_sha256':digest(folder/'generation.json'),'real_scale_verified':False}},candidate)
            operation.update(generation_engine='HoloPart',image_conditioning=False)
            operations.append(operation)
        uv=prepare_replacement_uv(doc,binary,list(seen));binary=compact_static(doc,binary);write_glb(output/'model.glb',doc,binary,extra)
        validation=validate_glb(output/'model.glb');write(output/'validation.json',validation)
        if validation['status']!='pass':raise ValueError('Full GLB validation did not pass')
        groups={};physical={}
        for p in parts_catalog(doc):
            group=p['logical_group_id']or p['id'];groups.setdefault(group,[]).append(p)
        rows=[]
        for slot,(group,parts)in enumerate(groups.items()):
            isolated=copy.deepcopy(doc);ib=bytearray(binary);export_parts(isolated,ib,{'part_ids':[p['id']for p in parts]});ib=compact_static(isolated,ib)
            file=f'part_{slot:02d}.glb';write_glb(output/file,isolated,ib,extra)
            meshes=[]
            for p in parts:
                primitive=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];_,faces,world,*_=primitive_data(doc,binary,p,primitive)
                meshes.append(trimesh.Trimesh(world,faces,process=False))
            mesh,cleanup=exact_storage_mesh(trimesh.util.concatenate(meshes));physical[group]=mesh
            facts={'slot':slot,'id':group,'semantic_kind':parts[0]['semantic_kind'],'file':file,'sha256':digest(output/file),
                'closed':bool(mesh.is_watertight),'components':len(mesh.split(only_watertight=False)),'self_intersections':intersections(mesh),
                'source':'HoloPart_completion'if group in seen else'preserved_legacy_geometry','cleanup':cleanup};rows.append(facts)
        contacts=[];items=list(physical.items())
        for index,(a_id,a)in enumerate(items):
            for b_id,b in items[index+1:]:
                if not a.is_watertight or not b.is_watertight:contacts.append({'a':a_id,'b':b_id,'status':'not_measured_open_legacy_shape'});continue
                intersection=trimesh.boolean.intersection([a,b],engine='manifold');volume=float(abs(intersection.volume))if len(intersection.faces)else 0
                fraction=float(volume/min(abs(a.volume),abs(b.volume)))
                contacts.append({'a':a_id,'b':b_id,'overlap_volume_in_source_units':volume,'fraction_of_smaller_part':fraction,'requires_geometry_review':fraction>.02})
        manifest={'status':'local_repair_preview_only','case':case['case'],'source_model_sha256':source_sha,'source_file_unchanged':digest(source)==source_sha,
            'operations':operations,'uv':uv,'contacts':contacts,'material_origin':'preserved_legacy_materials_not_recovered_photo_texture',
            'is_new_whole_furniture_from_image':False,'image_conditioning':False,'semantic_assignment_verified':False,
            'physical_structure_verified':False,'complete_assembly_accepted':False,'parts':rows}
        write(output/'assembly.json',manifest)
        write(output/'generation.json',{'engine':'HoloPart','mode':'assembly_of_coarse_geometry_conditioned_repairs','is_new_sampling':False,
            'source_model_sha256':source_sha,'source_generation_sha256s':[digest(f/'generation.json')for f,_,_ in completions],
            'object_file':'model.glb','object_sha256':digest(output/'model.glb'),'parts':rows,'complete_assembly_accepted':False})
        print(json.dumps({'parts':len(rows),'replaced_groups':len(seen),'contacts':contacts}),flush=True)
    except Exception as e:
        write(output/'failure.json',{'status':'failed','error':str(e),'source_file_unchanged':digest(source)==source_sha})
        (output/'failure.log').write_text(traceback.format_exc(),encoding='utf-8');raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cases',required=True);p.add_argument('--case',required=True);p.add_argument('--completion',action='append',required=True);p.add_argument('--output',required=True);run(p.parse_args())
