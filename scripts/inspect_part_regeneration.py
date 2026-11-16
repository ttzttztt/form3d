"""Save measured rejected fits for diagnosis only. Never publishes replacements."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts'), str(ROOT/'.tools/geometry_extra')]
import trimesh
from services.api.glb_document import read_glb, parts_catalog
from replace_generated_part import selected_group, cushion_slot
from solid_partition import prepare_mesh
from part_registration import fit_part, basis, surface_samples

OUT = ROOT/'experiments/part_regeneration_20261113'
for name, source, target_name, kind, generated in [
    ('corduroy_pillow', 'semantic_refinement_20261113/delivery/corduroy_sofa/model.glb', '靠枕 1', 'pillow', 'generated_v1'),
    ('leather_cushion', 'solid_parts_20261113/delivery/leather_sofa/model.glb', '坐面与主体 1', 'cushion', 'generated_trial_v1'),
]:
    folder=OUT/name/'fit_diagnostic';folder.mkdir(exist_ok=True)
    doc,binary,_=read_glb(ROOT/'experiments'/source)
    ids=[p['id'] for p in parts_catalog(doc) if p['name']==target_name]
    if not ids:
        print(name, [p['name']for p in parts_catalog(doc)]);continue
    _,_,target=selected_group(doc,binary,ids)
    target.export(folder/'source.glb')
    candidate,_=prepare_mesh(trimesh.load(OUT/name/generated/'model.glb',force='mesh',process=False))
    slot=None
    if kind=='cushion':
        target,frame,slot=cushion_slot(target);frame.export(folder/'frame.glb');target.export(folder/'upper.glb')
    aligned,fit=fit_part(candidate,target,kind,slot['cut_bottom_y']if slot else None)
    aligned.export(folder/'rejected_fit.glb')
    for mesh,col in [(target,[50,120,210,180]),(aligned,[230,90,20,200])]:mesh.visual.face_colors=col
    trimesh.Scene([target,aligned]).export(folder/'overlay.glb')
    fit['source_pca_span']=basis(surface_samples(target,4000)[0])[2].tolist()
    fit['candidate_pca_span']=basis(surface_samples(candidate,4000)[0])[2].tolist()
    fit['diagnostic_only']=True
    (folder/'fit.json').write_text(json.dumps(fit,indent=2),encoding='utf-8')
    print(name,json.dumps(fit),flush=True)
