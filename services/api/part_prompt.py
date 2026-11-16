"""Bounded render payloads and isolated SAM worker under the shared GPU lock."""
import base64,hashlib,io,json,os,subprocess,uuid
from pathlib import Path
from PIL import Image
from .asset_editor import source_for
from .segmentation import segmentation_python,segmentation_status
from .gpu import GPU_LOCK
ROOT=Path(__file__).resolve().parents[2]
def propose_part(store,job,body):
    source=source_for(store,job,body.version)
    if not segmentation_status()['available']:raise ValueError('本地 SAM 2 尚未就绪，请使用几何点选或涂抹')
    folder=store.root/'jobs'/job['id']/'part_proposals'/uuid.uuid4().hex;folder.mkdir(parents=True)
    for i,view in enumerate(body.views):
        try:
            raw=base64.b64decode(view.image.split(',')[-1],validate=True)
            with Image.open(io.BytesIO(raw)) as image:
                if image.width>768 or image.height>768 or min(image.size)<64:raise ValueError()
                image.convert('RGB').save(folder/f'view_{i}.png')
        except Exception:raise ValueError('分割视图需为 64～768 像素的有效图片')
    payload=body.model_dump();payload['model_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    for v in payload['views']:v.pop('image')
    (folder/'request.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    if not GPU_LOCK.acquire(timeout=5):raise ValueError('显卡正在处理其他任务，请稍后重试辅助分割')
    try:
        with (folder/'worker.log').open('wb') as log:
            r=subprocess.run([segmentation_python(),'-X','utf8',str(ROOT/'services/workers/segment_part_views.py'),'--folder',str(folder)],stdout=log,stderr=subprocess.STDOUT,timeout=150,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if r.returncode:raise ValueError('SAM 点击候选未完成，请换个位置或用涂抹；运行日志已保留')
    finally:GPU_LOCK.release()
    result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    def masks(name):return ['data:image/png;base64,'+base64.b64encode((folder/f'mask_{name}_{i}.png').read_bytes()).decode() for i in range(len(body.views))]
    result.update(proposal_id=folder.name,version=body.version,model_sha256=payload['model_sha256'],masks=masks(body.candidate_range),candidates=[{'range':name,'masks':masks(name)} for name in result['ranges']]);return result
