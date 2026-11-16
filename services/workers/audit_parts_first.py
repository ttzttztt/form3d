"""Measure raw native slots without treating valid GLBs as complete parts."""
import argparse,hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'services/workers'),str(ROOT/'.tools/geometry_extra')]


def run(args):
    import cv2,numpy as np,trimesh
    from PIL import Image
    from reconstruct_parts import intersections
    from photo_part_evidence import decimate_mesh,fit_camera,rasterize,mask_iou
    from scipy.optimize import linear_sum_assignment
    from mesh_integrity import exact_storage_mesh
    folder=Path(args.folder);generation=json.loads((folder/'generation.json').read_text(encoding='utf-8'));started=time.monotonic()
    destination=folder/args.name
    if destination.exists():raise ValueError('Keep prior audit evidence; use another --name')
    destination.mkdir();rows=[];meshes={};geometry_pass=True
    for part in generation['parts']:
        if not part.get('file'):rows.append({'slot':part['slot'],'geometry_gate':'failed','reason':'missing_output'});geometry_pass=False;continue
        scene=trimesh.load(folder/part['file'],force='scene',process=False)
        mesh,cleanup=exact_storage_mesh(scene.to_geometry())
        components=sorted(mesh.split(only_watertight=False),key=lambda m:m.area,reverse=True)
        self_intersections=None if args.skip_intersections else intersections(mesh)
        row={'slot':part['slot'],'sha256':hashlib.sha256((folder/part['file']).read_bytes()).hexdigest(),
             'storage_topology_cleanup':cleanup,
             'triangles':len(mesh.faces),'finite':bool(np.isfinite(mesh.vertices).all()),'closed':bool(mesh.is_watertight),
             'consistent_winding':bool(mesh.is_winding_consistent),'volume':float(mesh.volume),'components':len(components),
             'secondary_area_fraction':float(sum(p.area for p in components[1:])/max(mesh.area,1e-15)),
             'self_intersection_faces':self_intersections}
        failed=[]
        if not row['finite']:failed.append('nonfinite')
        if not row['closed']:failed.append('open_surface')
        if not row['consistent_winding']or row['volume']<=0:failed.append('invalid_volume_or_winding')
        if row['components']!=1:failed.append('not_one_coherent_solid')
        if self_intersections is None:failed.append('self_intersections_not_checked')
        elif self_intersections:failed.append('self_intersections')
        row.update(geometry_gate='failed'if failed else'passed',failed_checks=failed);geometry_pass &= not failed
        rows.append(row);meshes[str(part['slot'])]=mesh
        print('AUDITED_SLOT',part['slot'],row['geometry_gate'],flush=True)
    report={'generation_sha256':hashlib.sha256((folder/'generation.json').read_bytes()).hexdigest(),'slots':rows,
            'geometry_gate':'passed'if geometry_pass else'failed','semantic_assignment_verified':False,
            'physical_structure_verified':False,'photo_evidence':{'status':'not_checked'},'hidden_surface_accuracy':'unverified',
            'publish_complete_assembly':False,'pair_contact_and_penetration':'not_checked'}
    if args.observations:
        evidence=Path(args.observations);observations=json.loads((evidence/'observations.json').read_text(encoding='utf-8'));plan=json.loads((evidence/'plan.json').read_text(encoding='utf-8'))
        masks=[np.asarray(Image.open(evidence/p['mask_file']).convert('L'))>127 for p in observations['parts']]
        silhouette=np.asarray(Image.open(evidence/'whole_mask.png').convert('L'))>127
        factor=min(256/silhouette.shape[1],256/silhouette.shape[0]);size=tuple(max(1,round(v*factor))for v in silhouette.shape[::-1])
        silhouette=cv2.resize(silhouette.astype('uint8'),size,interpolation=cv2.INTER_NEAREST)>0
        masks=[cv2.resize(mask.astype('uint8'),size,interpolation=cv2.INTER_NEAREST)>0 for mask in masks]
        light={k:decimate_mesh(mesh,1500)for k,mesh in meshes.items()};camera=fit_camera(light,silhouette)
        labels,rendered=rasterize(light,np.asarray(camera['projection_from_world']),size)
        Image.fromarray(rendered).save(destination/'photo_fitted_geometry.png')
        scores=np.asarray([[mask_iou(labels==i+1,mask)for mask in masks]for i in range(len(light))])
        matches=[]
        if scores.size:
            selected_slots,selected_images=linear_sum_assignment(-scores)
            for slot,part_index in zip(selected_slots,selected_images):
                iou=float(scores[slot,part_index]);others=np.delete(scores[:,part_index],slot)
                margin=iou-float(others.max(initial=0))
                matches.append({'raw_slot':int(list(light)[slot]),'mask_sha256':observations['parts'][part_index]['mask_sha256'],
                    'proposed_kind':observations['parts'][part_index]['kind'],'visible_mask_iou':iou,'alternative_slot_margin':margin,
                    'link_status':'photo_linked_hypothesis'if iou>=.6 and margin>=.1 and camera['silhouette_iou']>=.65 else'ambiguous'})
        report['photo_evidence']={'status':'diagnostic_only','observations_sha256':hashlib.sha256((evidence/'observations.json').read_bytes()).hexdigest(),
                                  'planning_status':plan['status'],'camera':camera,'matches':matches,'slot_mask_ious':scores.tolist(),
                                  'is_independent_accuracy_measurement':False,'fitted_to_same_photo':True}
    report['elapsed_seconds']=round(time.monotonic()-started,3)
    (destination/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('RAW_ASSEMBLY_GATE',report['geometry_gate'],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder');parser.add_argument('--observations');parser.add_argument('--name',default='audit_01');parser.add_argument('--skip-intersections',action='store_true');run(parser.parse_args())
