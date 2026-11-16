"""Inspect opposing-surface evidence before changing any generated geometry."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import numpy as np
from services.api.glb_document import read_glb,parts_catalog
from replace_generated_part import selected_group
from part_registration import observed_pose_surface,surface_samples,basis

out=ROOT/'experiments/soft_part_quality_20261113';out.mkdir(exist_ok=True);rows=[]
for label,snapshot in [('corduroy','semantic_refinement_20261113/delivery/corduroy_sofa/model.glb'),('leather','solid_parts_20261113/delivery/leather_sofa/model.glb')]:
    doc,binary,_=read_glb(ROOT/'experiments'/snapshot)
    for group in dict.fromkeys(p.get('logical_group_id')for p in parts_catalog(doc)if p.get('semantic_kind')=='pillow'):
        p=next(p for p in parts_catalog(doc)if p.get('logical_group_id')==group)
        _,_,source=selected_group(doc,binary,[p['id']]);patch,evidence=observed_pose_surface(source,'pillow')
        points,normals=surface_samples(source,16000);visible,vn=surface_samples(patch,5000)
        center,axes,spans=basis(visible);normal=np.average(vn,axis=0);normal/=np.linalg.norm(normal)
        if axes[:,2]@normal<0:axes[:,2]*=-1
        xy=(visible-center)@axes[:,:2];lo,hi=np.quantile(xy,[.1,.9],axis=0)
        projected=(points-center)@axes;core=np.all((projected[:,:2]>=lo)&(projected[:,:2]<=hi),axis=1)
        front=core&(normals@normal>.72);back=core&(normals@normal<-.72)
        record={'case':label,'part':p['name'],'front_samples':int(front.sum()),'back_samples':int(back.sum()),'core_samples':int(core.sum()),'pose_surface':evidence}
        if front.sum()>20 and back.sum()>20:
            depths=np.quantile(projected[front,2],[.1,.25,.5,.75,.9]);bd=np.quantile(projected[back,2],[.1,.25,.5,.75,.9])
            record.update(front_depth=depths.tolist(),back_depth=bd.tolist(),median_gap=float(depths[2]-bd[2]),planar_span=spans[:2].tolist())
        rows.append(record)
(out/'observed_thickness_probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(rows,ensure_ascii=False))
