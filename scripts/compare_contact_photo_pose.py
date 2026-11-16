"""Same-image fixed-camera diagnostics for rigid contact correction, not physical accuracy."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'.tools/geometry_extra')]


def run(args):
    import cv2,numpy as np,trimesh
    from PIL import Image
    from services.api.glb_document import read_glb,parts_catalog
    from furniture_parts import primitive_data
    from photo_part_evidence import decimate_mesh,fit_camera,rasterize,mask_iou
    from generate_partcrafter import digest,write
    evidence=Path(args.observations);output=Path(args.output)
    if output.exists():raise ValueError('Preserve previous photo checks')
    data=json.loads((evidence/'observations.json').read_text(encoding='utf-8'));whole=np.asarray(Image.open(evidence/'whole_mask.png').convert('L'))>127
    factor=min(256/whole.shape[1],256/whole.shape[0]);size=tuple(max(1,round(v*factor))for v in whole.shape[::-1]);whole=cv2.resize(whole.astype('uint8'),size,interpolation=cv2.INTER_NEAREST)>0
    masks={p['kind']:cv2.resize((np.asarray(Image.open(evidence/p['mask_file']).convert('L'))>127).astype('uint8'),size,interpolation=cv2.INTER_NEAREST)>0 for p in data['parts']}
    if len(masks)!=len(data['parts']):raise ValueError('This diagnostic requires one instance of each semantic kind')
    def meshes(path):
        doc,binary,_=read_glb(path);groups={}
        for p in parts_catalog(doc):
            primitive=doc['meshes'][doc['nodes'][p['node']]['mesh']]['primitives'][p['primitive']];_,f,w,*_=primitive_data(doc,binary,p,primitive)
            kind='back_cushion'if p['semantic_kind']=='pillow'else p['semantic_kind'];groups.setdefault(kind,[]).append(trimesh.Trimesh(w,f,process=False))
        return {kind:decimate_mesh(trimesh.util.concatenate(parts),1500)for kind,parts in sorted(groups.items())}
    before=meshes(args.before);after=meshes(args.after)
    if list(before)!=list(after)or set(before)!=set(masks):raise ValueError('Part inventory does not agree with photo masks')
    camera=fit_camera(before,whole);matrix=np.asarray(camera['projection_from_world'])
    labels_a,image_a=rasterize(before,matrix,size);labels_b,image_b=rasterize(after,matrix,size)
    rows=[]
    for index,kind in enumerate(before):
        a=float(mask_iou(labels_a==index+1,masks[kind]));b=float(mask_iou(labels_b==index+1,masks[kind]));rows.append({'kind':kind,'before_visible_mask_iou':a,'after_visible_mask_iou':b,'difference':b-a,'declined_more_than_003':b<a-.03})
    output.mkdir(parents=True);Image.fromarray(image_a).save(output/'before.png');Image.fromarray(image_b).save(output/'after.png')
    report={'before_sha256':digest(args.before),'after_sha256':digest(args.after),'observations_sha256':digest(evidence/'observations.json'),
        'camera':camera,'camera_fixed_for_both_versions':True,'fitted_to_same_image':True,'is_independent_accuracy_measurement':False,
        'parts':rows,'visible_pose_guard_passed':not any(row['declined_more_than_003']for row in rows),
        'whole_before_iou':float(mask_iou(labels_a>0,whole)),'whole_after_iou':float(mask_iou(labels_b>0,whole)),
        'appearance_accepted':False,'threshold_note':'0.03 IoU drop is an experimental regression guard, not a product accuracy standard'}
    write(output/'comparison.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--before',required=True);p.add_argument('--after',required=True);p.add_argument('--observations',required=True);p.add_argument('--output',required=True);run(p.parse_args())
