"""Bind actual image-part inference to its planned identity, without claiming assembly."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'services/workers')]
from generate_partcrafter import digest,write
from services.api.assembly_models import AssemblyPlan


def run(args):
    folder=Path(args.geometry);evidence=Path(args.observations)
    if(folder/'generation.json').exists():raise ValueError('Preserve existing inference binding')
    summary=json.loads((folder/'local_summary.json').read_text(encoding='utf-8'))
    manifest=json.loads((evidence/'observations.json').read_text(encoding='utf-8'))
    plan=AssemblyPlan.model_validate_json((evidence/'plan.json').read_text(encoding='utf-8'))
    matches=[p for p in manifest['parts']if p.get('part_image_sha256')==summary['input_sha256']]
    if len(matches)!=1:raise ValueError('The generated input must match one actual planned part image')
    row=matches[0]
    if digest(evidence/row['part_image_file'])!=summary['input_sha256']or digest(evidence/row['mask_file'])!=row['mask_sha256']:raise ValueError('Image part evidence changed')
    parts=[p for p in plan.parts if any(o.mask_sha256==row['mask_sha256']for o in p.observations)]
    if len(parts)!=1 or parts[0].kind in('unknown','other'):raise ValueError('No unique semantic proposal identity')
    if digest(folder/'model.glb')!=summary['model_sha256']:raise ValueError('The actual generated model changed')
    part=parts[0]
    write(folder/'generation.json',{'engine':summary['model'],'mode':'image_part_reconstruction','is_new_sampling':True,
        'input_sha256':summary['input_sha256'],'model_revision':summary['provenance']['model_revision'],
        'source_summary_sha256':digest(folder/'local_summary.json'),'object_file':'model.glb','object_sha256':summary['model_sha256'],
        'status':'raw_candidates_ready','coordinate_frame':'local_part_unregistered','shared_coordinate_frame':False,
        'semantic_assignment_verified':False,'physical_structure_verified':False,'complete_assembly':False,
        'source_plan_id':plan.id,'source_plan_sha256':digest(evidence/'plan.json'),'source_mask_sha256':row['mask_sha256'],
        'whole_plan_status':plan.status,'external_image_requests':False,'hidden_surface_status':'ai_inferred',
        'parts':[{'slot':0,'id':part.id,'semantic_kind':part.kind,'semantic_assignment_verified':False,
                  'image_region_bound':True,'file':'model.glb','sha256':summary['model_sha256'],'status':'raw_candidate'}]})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--geometry',required=True);parser.add_argument('--observations',required=True);run(parser.parse_args())
