import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import cv2
from services.api.store import Store
from services.api.glb_document import read_glb,parts_catalog
from photo_part_evidence import product_mask,scene_meshes,fit_camera,associate
store=Store(ROOT/'.data');out=ROOT/'experiments/photo_guided_parts_20261113';out.mkdir(exist_ok=True)
for name,source_job,snapshot,part_name in [
 ('corduroy','0ee3d49864e543bb92a66ad9cf19115b','semantic_refinement_20261113/delivery/corduroy_sofa/model.glb','靠枕 1'),
 ('leather','11c5d7496508427cad48c22c5959f53b','solid_parts_20261113/delivery/leather_sofa/model.glb','坐面与主体 1')]:
    started=time.monotonic();folder=out/name;folder.mkdir(exist_ok=True)
    ref_folder=ROOT/'experiments/part_regeneration_20261113'/('corduroy_pillow'if name=='corduroy'else'leather_cushion')/'references'
    refs=json.loads((ref_folder/'references.json').read_text(encoding='utf-8'));job=store.job(source_job);image=store.image(job['request']['image_id'])
    mask=product_mask(store.root/image['normalized_path'],refs,store.root/'jobs'/source_job,job['request'])
    doc,binary,_=read_glb(ROOT/'experiments'/snapshot);meshes=scene_meshes(doc,binary)
    camera=fit_camera(meshes,mask);group=next(p['logical_group_id']for p in parts_catalog(doc)if p['name']==part_name)
    association,visible=associate(meshes,camera,refs,ref_folder,group)
    cv2.imwrite(str(folder/'product_mask.png'),mask.astype('uint8')*255);cv2.imwrite(str(folder/'projected_part.png'),visible.astype('uint8')*255)
    result={'camera':camera,'association':association,'seconds':time.monotonic()-started}
    (folder/'association.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(name,json.dumps(result,ensure_ascii=False),flush=True)
