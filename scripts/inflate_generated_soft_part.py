"""Declared 3D offset prior for a thin image-generated pillow, retaining the raw asset."""
import argparse,copy,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.tools/geometry_extra')]


def run(args):
    import igl,numpy as np,trimesh
    from skimage.measure import marching_cubes
    from photo_part_evidence import decimate_mesh
    from reconstruct_parts import intersections
    from generate_partcrafter import digest,write
    from services.api.glb_document import read_glb,write_glb
    source=Path(args.source);output=Path(args.output)
    if output.exists():raise ValueError('Preserve previous candidates')
    original=json.loads((source/'generation.json').read_text(encoding='utf-8'))
    if len(original['parts'])!=1 or original['parts'][0]['semantic_kind']!='back_cushion':raise ValueError('Requires one image-bound pillow candidate')
    source_file=source/original['parts'][0]['file']
    if digest(source_file)!=original['parts'][0]['sha256']:raise ValueError('Source geometry changed')
    mesh=trimesh.load(source_file,force='scene',process=False).to_geometry();mesh.merge_vertices(merge_tex=True,merge_norm=True)
    proxy=decimate_mesh(mesh,30000);radius=float(mesh.extents.max())*args.offset_ratio;step=float(mesh.extents.max())/args.resolution
    low=mesh.bounds[0]-radius-step*3;high=mesh.bounds[1]+radius+step*3
    grid_axes=[np.arange(low[i],high[i]+step*.5,step)for i in range(3)];shape=tuple(len(a)for a in grid_axes)
    if np.prod(shape)>4000000:raise ValueError('Offset grid exceeds bounded local processing size')
    queries=np.stack(np.meshgrid(*grid_axes,indexing='ij'),axis=-1).reshape(-1,3);started=time.monotonic();output.mkdir(parents=True)
    write(output/'progress.json',{'stage':'measuring_AI_surface_distance','grid_points':len(queries)})
    distance,*_=igl.signed_distance(np.ascontiguousarray(queries),np.ascontiguousarray(proxy.vertices),np.ascontiguousarray(proxy.faces,dtype=np.int64),igl.SIGNED_DISTANCE_TYPE_UNSIGNED)
    if not np.isfinite(distance).all():raise ValueError('Nonfinite signed distance')
    from scipy.ndimage import binary_fill_holes
    field=np.asarray(distance,dtype=np.float32).reshape(shape)-radius
    enclosed=binary_fill_holes(field<=0);field[enclosed]=np.minimum(field[enclosed],-step*.001)
    v,f,_,_=marching_cubes(field,level=0,spacing=(step,)*3,allow_degenerate=False)
    result=trimesh.Trimesh(np.asarray(v+low,dtype=np.float32),f,process=True)
    if result.volume<0:result.faces=result.faces[:,::-1]
    checks={'closed':bool(result.is_watertight),'components':len(result.split(only_watertight=False)),
        'consistent_winding':bool(result.is_winding_consistent),'volume':float(result.volume),'self_intersection_faces':intersections(result)}
    if not checks['closed']or checks['components']!=1 or not checks['consistent_winding']or checks['volume']<=0 or checks['self_intersection_faces']:
        write(output/'failure.json',{'status':'rejected','checks':checks,'published':False});result.export(output/'rejected_geometry.glb');raise ValueError('Offset prior did not produce one valid solid')
    # Neutral display only; the offset neither recovers fabric nor real scale.
    result.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='inferred_pillow_offset',baseColorFactor=[180,187,198,255],metallicFactor=0,roughnessFactor=.8))
    result.export(output/'part_00.glb',include_normals=True)
    doc,binary,extra=read_glb(output/'part_00.glb');identity=original['parts'][0]['id']
    for node in doc['nodes']:
        if 'mesh'in node:
            node['name']='靠枕（AI 形状与推测补厚）';node['extras']={'form_part_ids':{'0':identity+'__geometry'}}
            for primitive in doc['meshes'][node['mesh']]['primitives']:
                primitive['extras']={'form_logical_group_id':identity,'form_semantic_kind':'pillow','form_group_kind':'image_first_part','form_proposal_status':'needs_review','form_completion_note':'整体 AI 形状距离场补厚；不是实测背面与厚度'}
    write_glb(output/'part_00.glb',doc,binary,extra)
    method={'method':'unsigned_surface_offset_with_declared_enclosed_void_fill','offset_radius_normalized_units':radius,'offset_to_largest_span':args.offset_ratio,
        'resolution_largest_axis':args.resolution,'distance_analysis_faces':len(proxy.faces),'all_surfaces_reconstructed':True,
        'surface_deviation_to_original_photo':'not_checked','hidden_geometry_verified':False,'real_dimensions_verified':False,'UV_ready':False,
        'checks':checks,'elapsed_seconds':round(time.monotonic()-started,3)}
    facts=copy.deepcopy(original);facts.update(mode='image_part_with_explicit_offset_prior',is_new_sampling=False,source_generation_sha256=digest(source/'generation.json'),
        object_file='part_00.glb',object_sha256=digest(output/'part_00.glb'),parts=[{**original['parts'][0],'file':'part_00.glb','sha256':digest(output/'part_00.glb')}],completion=method,
        appearance_review='unreviewed',semantic_assignment_verified=False,complete_assembly=False)
    write(output/'generation.json',facts);write(output/'completion.json',method);write(output/'progress.json',{'stage':'candidate_ready_not_adopted'})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--offset-ratio',type=float,default=.035,choices=[.025,.035,.05]);p.add_argument('--resolution',type=int,default=96,choices=[64,96,128]);run(p.parse_args())
