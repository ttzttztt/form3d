"""Bind a native inference input to actual image-first planning artifacts."""
import hashlib
import json
from pathlib import Path
from .assembly_models import AssemblyPlan


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_generation_binding(plan_path, input_path):
    from PIL import Image
    plan_path=Path(plan_path).resolve();folder=plan_path.parent
    plan=AssemblyPlan.model_validate_json(plan_path.read_text(encoding='utf-8'))
    manifest_path=folder/'observations.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    physical=[part for part in plan.parts if part.geometry_role=='physical_part']
    if plan.status!='planned' or not 1<=len(physical)<=16:
        raise ValueError('Native generation requires an unresolved-free plan of 1 to 16 parts')
    if manifest.get('planning_phase')!='before_3d_generation' or manifest.get('input_sha256')!=plan.primary_image_sha256:
        raise ValueError('The image provenance does not match the assembly plan')
    if file_hash(input_path)!=manifest.get('generation_input_sha256'):
        raise ValueError('The generator input differs from the planned foreground image')
    with Image.open(input_path)as foreground:
        image_size=foreground.size
        if foreground.convert('RGBA').getchannel('A').getextrema()[1]==0:
            raise ValueError('The planned foreground is entirely transparent')
    observations={row['mask_sha256']:row for row in manifest.get('parts',[])}
    verified_masks={}
    for part in plan.parts:
        if part.geometry_role=='structural_group':continue
        if part.status!='planned' or part.geometry_method!='native_joint' or part.kind=='unknown':
            raise ValueError('Every requested slot must be a resolved native-joint proposal')
        for observed in part.observations:
            row=observations.get(observed.mask_sha256)
            if row is None or row.get('kind')!=part.kind or row.get('target')!=observed.target.model_dump():
                raise ValueError('The part observations differ from the planning manifest')
            candidate=(folder/row['mask_file']).resolve()
            if candidate.parent!=folder or file_hash(candidate)!=observed.mask_sha256:
                raise ValueError('A part mask is missing, changed or outside the planning folder')
            with Image.open(candidate)as mask:
                if mask.size!=image_size or mask.convert('L').getextrema()[1]==0:
                    raise ValueError('A part mask is empty or in a different image coordinate frame')
            if observed.image_id!=plan.primary_image_id or observed.image_sha256!=plan.primary_image_sha256:
                raise ValueError('The native primary-image observation has inconsistent provenance')
            verified_masks[part.id]=observed.mask_sha256
    if not verified_masks or set(verified_masks.values())!=set(observations):
        raise ValueError('The plan must bind every observed image part without silently dropping one')
    return {'plan_id':plan.id,'plan_sha256':file_hash(plan_path),'observations_sha256':file_hash(manifest_path),
            'num_parts':len(physical),'part_ids':[p.id for p in physical],
            'structural_group_ids':[p.id for p in plan.parts if p.geometry_role=='structural_group'],
            'observation_masks':verified_masks,'semantic_assignment_verified':False}
