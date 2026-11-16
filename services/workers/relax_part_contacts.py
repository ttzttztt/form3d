"""Bounded rigid contact hypothesis. Preserves surfaces; does not establish real pose."""
import argparse,copy,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'services/workers'),str(ROOT/'.tools/geometry_extra')]
import numpy as np


def solve(meshes,anchor,max_fraction=.04,pose_guard=None,extra_directions=()):
    import manifold3d as mf
    solids={key:mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices,dtype=np.float32),tri_verts=np.asarray(m.faces,dtype=np.uint32)))for key,m in meshes.items()}
    if any(s.volume()<=0 for s in solids.values()):raise ValueError('Contact correction requires valid solid inputs')
    bounds=np.array([np.min([m.bounds[0]for m in meshes.values()],axis=0),np.max([m.bounds[1]for m in meshes.values()],axis=0)])
    diagonal=float(np.linalg.norm(bounds[1]-bounds[0]));limit=diagonal*max_fraction
    offsets={key:np.zeros(3)for key in solids};evaluations=0
    def assess(shifts):
        nonlocal evaluations
        evaluations+=1
        if pose_guard is not None and not pose_guard(shifts):return float('inf'),[],{}
        current={key:s.translate(shifts[key].tolist())for key,s in solids.items()};pairs=[];score=0.;gaps={}
        keys=list(current)
        for index,a in enumerate(keys):
            for b in keys[index+1:]:
                volume=float((current[a]^current[b]).volume());fraction=max(0.,volume/min(solids[a].volume(),solids[b].volume()))
                pairs.append({'a':a,'b':b,'overlap_fraction_of_smaller_part':fraction});score+=100*fraction
        for key in keys:
            if key==anchor:continue
            gap=float(current[key].min_gap(current[anchor],diagonal*.01));gaps[key]=gap
            if gap>diagonal*.004:score+=100+gap/diagonal*100
            score+=float(np.linalg.norm(shifts[key])/diagonal)
        return score,pairs,gaps
    before=assess(offsets)
    if not np.isfinite(before[0]):raise ValueError('Initial pose fails the supplied constraint')
    best=before
    for iteration in range(2):
        for key in solids:
            if key==anchor:continue
            radial=meshes[key].centroid-meshes[anchor].centroid;radial/=max(np.linalg.norm(radial),1e-12)
            directions=[*np.eye(3),*-np.eye(3),radial,-radial,*extra_directions]
            origin=offsets[key].copy();lengths=([.0025,.005,.01,.02,.03,.04]if iteration==0 else[.00125,.0025,.005])
            chosen=origin.copy()
            for direction in directions:
                for fraction in lengths:
                    delta=origin+direction*(fraction*diagonal)
                    if np.linalg.norm(delta)>limit+1e-12:continue
                    trial={k:v.copy()for k,v in offsets.items()};trial[key]=delta;value=assess(trial)
                    if value[0]<best[0]-1e-10:chosen=delta;best=value
            offsets[key]=chosen
    after=assess(offsets)
    return offsets,{'method':'bounded_rigid_search_for_lower_intersection_with_body_contact','before':{'pairs':before[1],'body_gaps':before[2]},
        'after':{'pairs':after[1],'body_gaps':after[2]},'scene_diagonal':diagonal,'maximum_translation_to_diagonal':max_fraction,
        'translations':{key:value.tolist()for key,value in offsets.items()},'evaluations':evaluations,
        'contact_gate_passed':all(p['overlap_fraction_of_smaller_part']<=.002 for p in after[1])and all(gap<=diagonal*.004 for gap in after[2].values()),
        'surface_shape_changed':False,'is_pose_hypothesis':True,'photo_alignment_reverified':False,'physical_structure_verified':False}


def make_pose_guard(meshes,kinds,comparison,evidence):
    import cv2
    from PIL import Image
    from photo_part_evidence import decimate_mesh,rasterize,mask_iou
    data=json.loads((evidence/'observations.json').read_text(encoding='utf-8'));size=tuple(comparison['camera']['image_size'])
    masks={p['kind']:cv2.resize((np.asarray(Image.open(evidence/p['mask_file']).convert('L'))>127).astype('uint8'),size,interpolation=cv2.INTER_NEAREST)>0 for p in data['parts']}
    ordered=sorted(meshes,key=lambda key:kinds[key]);light={key:decimate_mesh(meshes[key],500)for key in ordered};matrix=np.asarray(comparison['camera']['projection_from_world'])
    semantic={key:'back_cushion'if kinds[key]=='pillow'else kinds[key]for key in ordered}
    if set(semantic.values())!=set(masks)or len(set(semantic.values()))!=len(ordered):raise ValueError('Photo guard requires a distinct mask for each part')
    def scores(shifts):
        moved={}
        for key in ordered:
            mesh=light[key].copy();mesh.apply_translation(shifts[key]);moved[key]=mesh
        labels,_=rasterize(moved,matrix,size)
        return {semantic[key]:float(mask_iou(labels==index+1,masks[semantic[key]]))for index,key in enumerate(ordered)}
    baseline=scores({key:np.zeros(3)for key in meshes});facts={'method':'fixed_same_image_camera_visible_mask_regression_guard','baseline_500_face_proxy_iou':baseline,'max_allowed_iou_drop':.03,'evaluated_candidates':0,'rejected_candidates':0,'is_independent_accuracy':False}
    def guard(shifts):
        current=scores(shifts);facts['evaluated_candidates']+=1
        passed=all(current[kind]>=baseline[kind]-.03 for kind in baseline)
        if not passed:facts['rejected_candidates']+=1
        return passed
    return guard,facts,scores


def run(args):
    import trimesh
    from generate_partcrafter import digest,write
    from services.api.glb_document import read_glb,write_glb,parts_catalog,compact_static
    from services.api.geometry import validate_glb
    from furniture_parts import primitive_data
    from mesh_integrity import exact_storage_mesh
    from part_tools import translate_parts,export_parts
    source=Path(args.source);output=Path(args.output)
    if output.exists():raise ValueError('Keep earlier contact trials')
    generation=json.loads((source/'generation.json').read_text(encoding='utf-8'));model=source/generation['object_file']
    if digest(model)!=generation['object_sha256']:raise ValueError('Source candidate changed')
    doc,binary,extra=read_glb(model);groups={};members={};kinds={}
    for p in parts_catalog(doc):
        primitive=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];_,faces,world,*_=primitive_data(doc,binary,p,primitive)
        group=p['logical_group_id']or p['id'];groups.setdefault(group,[]).append(trimesh.Trimesh(world,faces,process=False));members.setdefault(group,[]).append(p['id']);kinds[group]=p['semantic_kind']
    meshes={g:exact_storage_mesh(trimesh.util.concatenate(parts))[0]for g,parts in groups.items()};anchors=[g for g,k in kinds.items()if k=='body']
    if len(anchors)!=1 or any(k not in('body','pillow','bolster','back_cushion')for k in kinds.values()):raise ValueError('This experiment requires one body and pillows only')
    if any(not m.is_watertight or len(m.split(only_watertight=False))!=1 for m in meshes.values()):raise ValueError('All parts must already be complete solids')
    guard=None;photo=None;extra_directions=[]
    if bool(args.photo_comparison)!=bool(args.photo_observations):raise ValueError('Photo comparison and observations must be supplied together')
    if args.photo_comparison:
        comparison=json.loads(Path(args.photo_comparison).read_text(encoding='utf-8'));evidence=Path(args.photo_observations)
        if comparison['before_sha256']!=digest(model)or comparison['observations_sha256']!=digest(evidence/'observations.json'):raise ValueError('Photo constraint belongs to a different source')
        guard,photo,scores=make_pose_guard(meshes,kinds,comparison,evidence)
        ray=np.asarray(comparison['camera']['projection_from_world'])[2,:3];ray/=np.linalg.norm(ray);extra_directions=[ray,-ray]
    started=time.monotonic();offsets,report=solve(meshes,anchors[0],pose_guard=guard,extra_directions=extra_directions);report['elapsed_seconds']=time.monotonic()-started
    if photo is not None:
        photo['final_500_face_proxy_iou']=scores(offsets);report['photo_constraint']=photo;report['photo_alignment_reverified']='proxy_same_image_only_requires_full_final_check'
    output.mkdir(parents=True);write(output/'contact_correction.json',report)
    for group,shift in offsets.items():
        if np.linalg.norm(shift)>0:translate_parts(doc,binary,{'part_ids':members[group],'translation':shift.tolist()})
    binary=compact_static(doc,binary);write_glb(output/'model.glb',doc,binary,extra);validation=validate_glb(output/'model.glb');write(output/'validation.json',validation)
    parts=[]
    for slot,(group,ids)in enumerate(members.items()):
        isolated=copy.deepcopy(doc);ib=bytearray(binary);export_parts(isolated,ib,{'part_ids':ids});ib=compact_static(isolated,ib);file=f'part_{slot:02d}.glb';write_glb(output/file,isolated,ib,extra)
        parts.append({'slot':slot,'id':group,'file':file,'sha256':digest(output/file),'semantic_kind':kinds[group]})
    write(output/'generation.json',{'engine':'bounded_rigid_contact_correction','source_model_sha256':digest(model),'object_file':'model.glb','object_sha256':digest(output/'model.glb'),
        'parts':parts,'is_new_sampling':False,'contact_gate_passed':report['contact_gate_passed'],'complete_assembly_accepted':False})
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--photo-comparison');p.add_argument('--photo-observations');run(p.parse_args())
