"""Replace one proposed kind using image-bound region classifications, without new sampling."""
import argparse,copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from generate_partcrafter import digest,write
from services.api.assembly_proposals import normalize_proposal


def run(args):
    proposal_path=Path(args.proposal);regions_folder=Path(args.regions);classification_folder=Path(args.classifications);output=Path(args.output)
    if output.exists():raise ValueError('Preserve previous proposal versions')
    proposal=json.loads(proposal_path.read_text(encoding='utf-8'));manifest=json.loads((regions_folder/'observations.json').read_text(encoding='utf-8'))
    classifications=json.loads((classification_folder/'classifications.json').read_text(encoding='utf-8'))
    if proposal['input_sha256']!=manifest['input_sha256']or classifications['source_manifest_sha256']!=digest(regions_folder/'observations.json'):raise ValueError('Region classification provenance differs from the original image')
    if proposal['status']!='proposal_ready'or len(proposal['furniture'])!=1:raise ValueError('Requires one selected furniture proposal')
    replacements=[]
    for row in classifications['regions']:
        if row['kind']!=args.kind or row.get('error'):continue
        region=manifest['parts'][row['source_region']]
        if row['source_mask_sha256']!=region['mask_sha256']or digest(regions_folder/region['mask_file'])!=row['source_mask_sha256']:raise ValueError('Region mask changed')
        t=row['source_target'];replacements.append({'kind':args.kind,'bbox':[t['x']*1000,t['y']*1000,(t['x']+t['width'])*1000,(t['y']+t['height'])*1000],
            'source_region_mask_sha256':row['source_mask_sha256'],'semantic_verified':False})
    if not replacements:raise ValueError('No supported replacement regions')
    result=copy.deepcopy(proposal);furniture=result['furniture'][0]
    furniture['parts']=[p for p in furniture['parts']if p['kind']!=args.kind]+replacements
    normalized,warnings=normalize_proposal({'furniture':result['furniture']});result.update(**normalized,normalization_warnings=warnings,
        is_new_sampling=False,derivation='one_kind_refined_by_contextual_region_classification',
        source_proposal_sha256=digest(proposal_path),source_region_manifest_sha256=digest(regions_folder/'observations.json'),
        source_classifications_sha256=digest(classification_folder/'classifications.json'),semantic_assignment_verified=False)
    output.mkdir(parents=True);write(output/'semantic_proposal.json',result)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--proposal',required=True);p.add_argument('--regions',required=True);p.add_argument('--classifications',required=True);p.add_argument('--kind',required=True,choices=['back_cushion','seat_cushion','armrest','bolster']);p.add_argument('--output',required=True);run(p.parse_args())
