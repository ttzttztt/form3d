"""A declared thickness prior for an AI paper pillow; never measured hidden shape."""
import argparse,copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.tools/geometry_extra')]


def complete(mesh,ratio=.18,resolution=48):
    import numpy as np,trimesh
    from shapely.geometry import MultiPoint
    from reconstruct_parts import intersections
    from part_registration import surface_samples,basis
    from soft_part_repair import grid_in_hull,interpolate,sheets
    components=sorted(mesh.split(only_watertight=False),key=lambda m:m.area,reverse=True)
    if not components:raise ValueError('No source surface')
    offset=float(np.max(abs(mesh.bounds-components[0].bounds))/max(np.linalg.norm(components[0].extents),1e-12))
    if offset>.05:raise ValueError('Distant fragments do not support one coherent pillow outline')
    # This route refits an envelope containing every source fragment. It does
    # not relax the existing single-solid cleanup thresholds or drop a back.
    source=mesh
    discarded={'source_components':len(components),'source_fragments_discarded':False,'maximum_fragment_bounds_offset_diagonal_ratio':offset}
    points,_=surface_samples(source,6000);center,axes,spans=basis(points)
    if axes[2,2]<0:axes[:,1:]*=-1
    local=(source.triangles_center-center)@axes;normals=source.face_normals@axes
    front=normals[:,2]>.35
    if front.sum()<20:raise ValueError('No usable broad source surface')
    projected=(source.vertices-center)@axes[:,:2]
    polygon=MultiPoint(projected).convex_hull
    xy,faces,distance,_=grid_in_hull(projected,resolution,polygon)
    delta1=xy[faces[:,1]]-xy[faces[:,0]];delta2=xy[faces[:,2]]-xy[faces[:,0]]
    twice_area=abs(delta1[:,0]*delta2[:,1]-delta1[:,1]*delta2[:,0])
    valid=twice_area>float(np.ptp(projected,axis=0).max())**2*1e-12
    degenerate_count=int((~valid).sum());faces=faces[valid]
    top=interpolate(local[front,:2],local[front,2],xy)
    from scipy.sparse import coo_matrix,diags
    from scipy.sparse.linalg import spsolve
    edges=np.vstack([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]);edges=np.unique(np.sort(edges,axis=1),axis=0)
    rows=np.r_[edges[:,0],edges[:,1]];cols=np.r_[edges[:,1],edges[:,0]]
    adjacency=coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(len(xy),len(xy))).tocsr()
    laplacian=diags(np.asarray(adjacency.sum(1)).ravel())-adjacency
    system=diags(np.ones(len(xy)))+.5*laplacian;unsmoothed=top.copy()
    for _ in range(12):top=spsolve(system,top)
    width=float(np.ptp(projected,axis=0).max());height=float(np.ptp(projected,axis=0).min())
    depth=height*ratio;rim=height*.006
    profile=np.clip(distance/max(distance.max(),1e-12),0,1)**.6
    bottom=top-(rim+(depth-rim)*profile)
    result=sheets(xy,faces,top,bottom,axes,center)
    # Review the actual GLB storage precision. Nearly collinear float64
    # triangles can produce different contact diagnostics after float32 export.
    result.vertices=np.asarray(result.vertices,dtype=np.float32).astype(np.float64)
    checks={'closed':bool(result.is_watertight),'winding':bool(result.is_winding_consistent),'volume':float(result.volume),'self_intersection_faces':intersections(result)}
    if not checks['closed']or not checks['winding']or checks['volume']<=0 or checks['self_intersection_faces']:
        error=ValueError('Inferred pillow failed solid checks: '+json.dumps(checks));error.candidate=result;error.checks=checks
        raise error
    # Independent front/back charts and a physical-width side strip. The
    # coordinates use normalized model units, not an asserted real texel scale.
    count=len(xy);front_faces=faces.copy();back_faces=faces[:,::-1]+count
    vertices=result.vertices.copy();uv=np.vstack([(xy-xy.min(0))/width,(xy-xy.min(0))/width+[1.1,0]])
    edge_rows=np.vstack([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]);keys=np.sort(edge_rows,axis=1)
    _,indices,counts=np.unique(keys,axis=0,return_index=True,return_counts=True);walls=[];offset=0.
    vertex_rows=[vertices];uv_rows=[uv];base=2*count
    for a,b in edge_rows[indices[counts==1]]:
        edge_length=float(np.linalg.norm(xy[b]-xy[a]));vertex_rows.append(vertices[[a,b,a+count,b+count]])
        uv_rows.append(np.array([[offset/width,0],[(offset+edge_length)/width,0],[offset/width,(top[a]-bottom[a])/width],[(offset+edge_length)/width,(top[b]-bottom[b])/width]])+[0,1.1])
        walls.extend([[base+1,base,base+2],[base+2,base+3,base+1]]);base+=4;offset+=edge_length
    visual=trimesh.visual.TextureVisuals(uv=np.vstack(uv_rows),material=trimesh.visual.material.PBRMaterial(name='neutral_inferred_pillow',baseColorFactor=[180,187,198,255],metallicFactor=0,roughnessFactor=.8))
    exported=trimesh.Trimesh(np.vstack(vertex_rows),np.vstack([front_faces,back_faces,np.asarray(walls)]),visual=visual,process=False)
    exported.remove_unreferenced_vertices()
    return exported,{'method':'AI_surface_outline_and_explicit_inferred_pillow_depth','maximum_depth_to_short_planar_span':ratio,
        'maximum_depth_normalized_units':depth,'rim_depth_normalized_units':rim,'front_back_orientation_verified':False,
        'all_surfaces_reconstructed':True,'source_projected_footprint':'convex_envelope_of_dominant_AI_component',
        'removed_degenerate_parameter_triangles':degenerate_count,'checked_storage_precision':'glTF_float32',
        'height_field_regularization_steps':12,'maximum_regularization_shift_normalized_units':float(abs(top-unsmoothed).max()),
        'hidden_surface_status':'shape_prior_inferred','physical_dimensions_verified':False,'UV_real_texel_scale_verified':False,**discarded}


def run(args):
    import trimesh
    from generate_partcrafter import digest,write
    from services.api.glb_document import read_glb,write_glb
    source=Path(args.source);output=Path(args.output)
    if output.exists():raise ValueError('Keep previous attempts; choose another output folder')
    original=json.loads((source/'generation.json').read_text(encoding='utf-8'))
    if len(original['parts'])!=1 or original['parts'][0]['semantic_kind']!='back_cushion':raise ValueError('This route is only for one image-bound pillow proposal')
    path=source/original['parts'][0]['file']
    if digest(path)!=original['parts'][0]['sha256']:raise ValueError('Generated source changed')
    mesh=trimesh.load(path,force='scene',process=False).to_geometry();mesh.merge_vertices(merge_tex=True,merge_norm=True,digits_vertex=7)
    try:result,method=complete(mesh,args.ratio)
    except Exception as exc:
        output.mkdir(parents=True)
        if hasattr(exc,'candidate'):exc.candidate.export(output/'rejected_geometry.glb',include_normals=True)
        write(output/'failure.json',{'status':'failed','error':str(exc),'checks':getattr(exc,'checks',None),'published':False})
        raise
    output.mkdir(parents=True)
    result.export(output/'part_00.glb',include_normals=True)
    doc,binary,extra=read_glb(output/'part_00.glb');identity=original['parts'][0]['id']
    for node in doc['nodes']:
        if 'mesh'in node:
            node['name']='靠枕（背面与厚度推测）';node['extras']={'form_part_ids':{'0':identity+'__geometry'}}
            for primitive in doc['meshes'][node['mesh']]['primitives']:
                primitive['extras']={'form_logical_group_id':identity,'form_semantic_kind':'pillow','form_group_kind':'image_first_part','form_proposal_status':'needs_review','form_completion_note':'AI 轮廓、重建表面和厚度先验；真实背面未验证'}
    write_glb(output/'part_00.glb',doc,binary,extra)
    facts=copy.deepcopy(original);facts.update(mode='image_part_with_inferred_depth',is_new_sampling=False,object_file='part_00.glb',
        object_sha256=digest(output/'part_00.glb'),source_generation_sha256=digest(source/'generation.json'),
        parts=[{**original['parts'][0],'file':'part_00.glb','sha256':digest(output/'part_00.glb')}],completion=method,
        semantic_assignment_verified=False,complete_assembly=False,appearance_review='unreviewed')
    write(output/'generation.json',facts);write(output/'completion.json',method)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--ratio',type=float,default=.18,choices=[.12,.15,.18,.2,.25]);run(p.parse_args())
