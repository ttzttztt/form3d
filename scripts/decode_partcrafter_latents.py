"""Retry mesh extraction from hashed sampled latents without new AI sampling."""
import argparse,gc,json,os,shutil,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'


def run(args):
    import numpy as np,torch,trimesh
    from safetensors.torch import load_file
    from generate_partcrafter import digest,write
    from partcrafter_runtime import load_pipeline_class
    load_pipeline_class()
    from src.models.autoencoders.autoencoder_kl_triposg import TripoSGVAEModel
    from src.utils.inference_utils import hierarchical_extract_geometry
    source=Path(args.source);output=Path(args.output)
    if output.exists():raise ValueError('Use a fresh output folder')
    original=json.loads((source/'generation.json').read_text(encoding='utf-8'))
    latents_file=source/'sampled_latents.safetensors'
    if digest(latents_file)!=original['sampled_latents_sha256']:raise ValueError('Sampled latent checkpoint changed')
    output.mkdir(parents=True);started=time.monotonic();torch.set_num_threads(4);torch.cuda.reset_peak_memory_stats()
    facts={key:original[key]for key in('engine','input_sha256','requested_parts','part_count_source','seed','tokens_per_part','steps','model_revision','source_revision','sampled_latents_sha256')}
    facts.update(mode='joint_image_to_parts_decode_retry',is_new_sampling=False,sampling_generation_sha256=digest(source/'generation.json'),
        decoder_mode=args.decoder,dense_octree_depth=args.dense_depth,hierarchical_octree_depth=args.mesh_depth,
        semantic_assignment_verified=False,physical_structure_verified=False,external_image_requests=False,parts=[],status='running',worker_revision=digest(__file__))
    if 'plan_binding'in original:facts['plan_binding']=original['plan_binding']
    shutil.copyfile(source/'model_input.png',output/'model_input.png')
    try:
        vae=TripoSGVAEModel.from_pretrained(str(ROOT/'.models/partcrafter/vae'),torch_dtype=torch.float16,local_files_only=True,low_cpu_mem_usage=True).to('cuda',torch.float16).eval()
        if args.decoder=='upstream_flash':vae.set_flash_decoder()
        else:vae.set_default_attn_processor()
        latents=load_file(str(latents_file),device='cuda')['latents']
        scene=trimesh.Scene();failed=[]
        with torch.inference_mode():
            for index,z in enumerate(latents):
                write(output/'progress.json',{'stage':'decoding','part_index':index+1,'total':len(latents),'elapsed_seconds':round(time.monotonic()-started,3)})
                row={'slot':index,'id':original['parts'][index]['id']if len(original['parts'])>index else'unknown','semantic_kind':'unknown','semantic_assignment_verified':False}
                try:
                    def geometry(points):return vae.decode(z.unsqueeze(0),sampled_points=points,num_chunks=args.chunk).sample
                    vertices,faces=hierarchical_extract_geometry(geometry,'cuda',latents.dtype,bounds=(-1.005,-1.005,-1.005,1.005,1.005,1.005),dense_octree_depth=args.dense_depth,hierarchical_octree_depth=args.mesh_depth,max_num_expanded_coords=args.max_coords)
                    mesh=trimesh.Trimesh(vertices.astype(np.float32),faces)
                    if not len(mesh.faces)or not np.isfinite(mesh.vertices).all():raise ValueError('No finite decoded mesh')
                    mesh.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='neutral_geometry_review',baseColorFactor=[180,187,198,255],metallicFactor=0,roughnessFactor=.8))
                    file=f'part_{index:02d}.glb';mesh.export(output/file,include_normals=True);scene.add_geometry(mesh,node_name=row['id'],geom_name=row['id'])
                    row.update(status='raw_candidate',file=file,sha256=digest(output/file),triangles=len(mesh.faces),vertices=len(mesh.vertices),bounds=mesh.bounds.tolist(),watertight=bool(mesh.is_watertight),consistent_winding=bool(mesh.is_winding_consistent),volume=float(mesh.volume),components=len(mesh.split(only_watertight=False)))
                except Exception as exc:
                    row.update(status='failed',reason=str(exc));failed.append(index);(output/f'failure_{index:02d}.log').write_text(traceback.format_exc(),encoding='utf-8')
                facts['parts'].append(row);print('DECODED',index,row['status'],flush=True);gc.collect();torch.cuda.empty_cache()
        if failed:raise ValueError('Some slots failed; no complete assembly published')
        scene.export(output/'object.glb',include_normals=True);facts.update(status='raw_candidates_ready',object_sha256=digest(output/'object.glb'),shared_coordinate_frame=True,appearance_review='unreviewed')
    except Exception as exc:
        facts.update(status='failed',error=str(exc));raise
    finally:
        facts.update(elapsed_seconds=round(time.monotonic()-started,3),gpu_peak_allocated_bytes=torch.cuda.max_memory_allocated())
        write(output/'generation.json',facts)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--decoder',choices=['exact','upstream_flash'],default='exact');p.add_argument('--dense-depth',type=int,default=7);p.add_argument('--mesh-depth',type=int,default=8);p.add_argument('--chunk',type=int,default=25000);p.add_argument('--max-coords',type=int,default=16000000);run(p.parse_args())
