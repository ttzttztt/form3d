"""Experimental geometry-conditioned part completion; never auto-publish an assembly."""
import argparse,gc,json,os,sys,time,traceback,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ.setdefault('OMP_NUM_THREADS','4')


def prepare(case,group_id,seed,samples,exclude_inferred=False):
    import numpy as np,trimesh
    from services.api.glb_document import read_glb,parts_catalog
    from furniture_parts import primitive_data
    from generate_partcrafter import digest
    source=ROOT/case['coarse_reference'];image=ROOT/case['image']
    if digest(source)!=case['coarse_sha256']or digest(image)!=case['image_sha256']:raise ValueError('Frozen source model or image changed')
    doc,binary,_=read_glb(source);meshes=[];selected=[];membership=[];all_bounds=[];excluded=[]
    for part in parts_catalog(doc):
        primitive=doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
        _,faces,world,*_=primitive_data(doc,binary,part,primitive)
        mesh=trimesh.Trimesh(world,faces,process=False);all_bounds.append(mesh.bounds)
        if exclude_inferred and part.get('completion_role')=='inferred_interface':
            excluded.append({'part_id':part['id'],'triangles':len(faces),'reason':'legacy_inferred_interface_not_observed_surface'});continue
        meshes.append(mesh)
        included=part['logical_group_id']==group_id;membership.extend([included]*len(faces))
        if included:selected.append(mesh)
    if not selected:raise ValueError('Selected legacy group does not exist')
    whole=trimesh.util.concatenate(meshes);part=trimesh.util.concatenate(selected)
    bounds=np.stack([np.min([b[0]for b in all_bounds],axis=0),np.max([b[1]for b in all_bounds],axis=0)])
    center=bounds.mean(axis=0);scale=float(np.max(bounds[1]-bounds[0])/1.9)
    if scale<=0:raise ValueError('Empty source geometry')
    for mesh in(whole,part):mesh.vertices=(mesh.vertices-center)/scale
    p,pi=trimesh.sample.sample_surface(part,samples,seed=seed);w,wi=trimesh.sample.sample_surface(whole,samples,seed=seed+1)
    cond=np.c_[p,part.face_normals[pi]];whole_cond=np.c_[w,whole.face_normals[wi],np.asarray(membership)[wi]]
    local_center=(p.max(axis=0)+p.min(axis=0))/2;local_scale=float(np.abs(p-local_center).max()/(.95*.7))
    local=cond.copy();local[:,:3]=(local[:,:3]-local_center)/local_scale
    return {'part_cond':cond.astype('float32'),'whole_cond':whole_cond.astype('float32'),'part_local_cond':local.astype('float32')},part,{
        'source_model':case['coarse_reference'],'source_model_sha256':case['coarse_sha256'],'source_origin':case['coarse_reference_origin'],
        'source_group_id':group_id,'selected_source_meshes':len(selected),'source_image_sha256':case['image_sha256'],
        'source_segmentation_is_verified':False,'image_conditioning':False,'global_center':center.tolist(),'global_scale':scale,
        'part_local_center':local_center.tolist(),'part_local_scale':local_scale,'whole_membership':'exact_sampled_source_triangle_owner',
        'neighbor_geometry_will_be_preserved':True,'physical_structure_verified':False,
        'exclude_inferred_interfaces_from_conditioning':exclude_inferred,'excluded_conditioning_geometry':excluded,
        'source_surfaces_are_still_legacy_reconstructions_not_photo_ground_truth':True}


def run(args):
    import numpy as np,torch,trimesh
    from generate_partcrafter import digest,write
    output=Path(args.output)
    if output.exists():raise ValueError('Preserve all previous completion attempts')
    cases=json.loads(Path(args.cases).read_text(encoding='utf-8'));case=next(c for c in cases if c['case']==args.case)
    data,source,binding=prepare(case,args.group_id,args.seed,args.samples,args.exclude_inferred_interfaces)
    output.mkdir(parents=True);started=time.monotonic();facts={'engine':'HoloPart','mode':'coarse_segmented_mesh_part_completion',
        'input_binding':binding,'is_new_sampling':False,'is_new_whole_furniture':False,'external_image_requests':False,
        'status':'preparing','parts':[],'seed':args.seed,'steps':args.steps,'tokens':args.tokens,'dense_grid_resolution':args.resolution,
        'surface_samples':args.samples,'worker_sha256':digest(__file__),'complete_assembly_accepted':False,'semantic_assignment_verified':False}
    def progress(stage,**extra):
        value={'stage':stage,'elapsed_seconds':round(time.monotonic()-started,3),**extra};write(output/'progress.json',value);print(json.dumps(value),flush=True)
    try:
        np.savez_compressed(output/'conditioning.npz',**data);facts['conditioning_sha256']=digest(output/'conditioning.npz')
        source.export(output/'source_part_normalized.glb',include_normals=True);write(output/'input_binding.json',binding)
        if args.prepare_only:facts['status']='prepared_only';progress('prepared_only');return
        provenance=ROOT/'.models/holopart/provenance_verified.json';model=json.loads(provenance.read_text(encoding='utf-8'))
        if not model.get('ready'):raise ValueError('Model weights have not all passed pinned hash verification')
        for row in model['files']:
            file=ROOT/'.models/holopart'/row['path']
            if digest(file)!=row['sha256']:raise ValueError('Installed model changed: '+row['path'])
        facts.update(model_revision=model['model_revision'],source_revision=model['source_revision'],model_provenance_sha256=digest(provenance))
        from holopart_runtime import load_pipeline_class
        pipeline,limits=load_pipeline_class();facts['runtime']=limits
        torch.set_num_threads(4);torch.manual_seed(args.seed);np.random.seed(args.seed);torch.cuda.reset_peak_memory_stats()
        progress('loading_model');pipe=pipeline.from_pretrained(str(ROOT/'.models/holopart'),torch_dtype=torch.float16,local_files_only=True,low_cpu_mem_usage=True)
        pipe.to('cuda',torch.float16);pipe.set_progress_bar_config(disable=True)
        original_fps=pipe.part_encoder._sample_features
        def seeded_features(self,x,num_tokens=2048,seed=None):return original_fps(x,num_tokens=num_tokens,seed=args.seed if seed is None else seed)
        pipe.part_encoder._sample_features=types.MethodType(seeded_features,pipe.part_encoder)
        facts['runtime']['region_point_selection_seeded']=True
        original_encode=pipe.encode_context_local
        def encode_with_offload(self,*a,**kw):
            self.transformer.to('cpu');self.vae.to('cpu');gc.collect();torch.cuda.empty_cache();progress('encoding_coarse_part_and_context')
            result=original_encode(*a,**kw)
            self.part_encoder.to('cpu');gc.collect();torch.cuda.empty_cache();self.transformer.to('cuda',torch.float16)
            progress('sampling_latent');return result
        pipe.encode_context_local=types.MethodType(encode_with_offload,pipe)
        tensors={k:torch.from_numpy(v)[None].cuda()for k,v in data.items()}
        with torch.inference_mode():
            latent=pipe(part_surface=tensors['part_cond'],whole_surface=tensors['whole_cond'],part_local_surface=tensors['part_local_cond'],num_inference_steps=args.steps,num_tokens=args.tokens,guidance_scale=3.5,
                generator=torch.Generator(device='cuda').manual_seed(args.seed),output_type='latent').samples
        facts['is_new_sampling']=True
        from safetensors.torch import save_file
        save_file({'latents':latent.detach().cpu().contiguous()},str(output/'sampled_latents.safetensors'));facts['sampled_latents_sha256']=digest(output/'sampled_latents.safetensors')
        pipe.transformer=None;pipe.part_encoder=None;gc.collect();torch.cuda.empty_cache();pipe.vae.to('cuda',torch.float16)
        progress('decoding_regular_grid');axis=np.linspace(-1.05,1.05,args.resolution,dtype=np.float32)
        points=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),axis=-1).reshape(-1,3)
        with torch.inference_mode():logits=pipe.vae.decode(latent,torch.from_numpy(points)[None].cuda(),num_chunks=6000,to_cpu=True).sample.float().reshape((args.resolution,)*3).cpu().numpy()
        np.savez_compressed(output/'field.npz',logits=logits,bounds=np.array([-1.05,1.05]));facts['field_sha256']=digest(output/'field.npz')
        if not np.isfinite(logits).all()or not logits.min()<0<logits.max():raise ValueError('Decoder produced no finite zero-level surface')
        from skimage.measure import marching_cubes
        vertices,faces,_,_=marching_cubes(logits,0,spacing=(2.1/(args.resolution-1),)*3,allow_degenerate=False)
        vertices=vertices-1.05;vertices=vertices*binding['part_local_scale']+np.array(binding['part_local_center'])
        vertices=vertices*binding['global_scale']+np.array(binding['global_center'])
        mesh=trimesh.Trimesh(vertices,faces,process=False);facts['winding_flipped_for_positive_volume']=bool(mesh.volume<0)
        if mesh.volume<0:mesh.invert()
        file=output/'part_00.glb';mesh.export(file,include_normals=True)
        facts.update(status='raw_candidate_ready',parts=[{'slot':0,'id':args.group_id,'file':file.name,'sha256':digest(file),'triangles':len(mesh.faces),
            'components':len(mesh.split(only_watertight=False)),'closed':bool(mesh.is_watertight),'bounds':mesh.bounds.tolist(),'semantic_kind':'legacy_group_unverified'}])
        facts['object_file']=file.name;facts['object_sha256']=digest(file);progress('raw_candidate_ready')
    except Exception as e:
        facts.update(status='failed',error=str(e));(output/'failure.log').write_text(traceback.format_exc(),encoding='utf-8');raise
    finally:
        facts['elapsed_seconds']=round(time.monotonic()-started,3)
        if torch.cuda.is_available():facts['gpu_peak_allocated_bytes']=torch.cuda.max_memory_allocated()
        write(output/'generation.json',facts)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cases',required=True);p.add_argument('--case',required=True);p.add_argument('--group-id',required=True);p.add_argument('--output',required=True)
    p.add_argument('--seed',type=int,default=42);p.add_argument('--steps',type=int,default=50);p.add_argument('--tokens',type=int,default=2048,choices=[512,1024,2048]);p.add_argument('--samples',type=int,default=20480);p.add_argument('--resolution',type=int,default=128,choices=[64,96,128,160]);p.add_argument('--prepare-only',action='store_true');p.add_argument('--exclude-inferred-interfaces',action='store_true');run(p.parse_args())
