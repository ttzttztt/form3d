"""Background local semantic-instance scans; proposals never publish themselves."""
import hashlib,json,os,re,shutil,subprocess,threading,time,uuid
from pathlib import Path
from .asset_editor import ROOT,source_for
from .local3d import local_python
from .segmentation import segmentation_python,segmentation_status
from .detection import detector_status
from .geometry import validate_glb
from .glb_document import read_glb,parts_catalog
from .gpu import GPU_LOCK
from .semantic_validation import validate_semantic_proposal
SCAN_LOCK=threading.Lock()

def blender_path():
    candidates=[os.getenv('BLENDER_EXE',''),shutil.which('blender') or '',r'D:\Blender 5.1\blender.exe',r'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe','/Applications/Blender.app/Contents/MacOS/Blender','/usr/bin/blender','/snap/bin/blender']
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()),None)

def semantic_status():
    return {'available':bool(blender_path() and local_python('hunyuan-mini') and segmentation_status()['available'] and detector_status()['weights_ready']),'detector':'Grounding DINO Tiny','segmenter':'SAM 2.1 Hiera Tiny','mode':'local_multiview_instances','requires_key':False}

def revision():
    files=['render_semantic_views.py','detect_semantic_views.py','semantic_mapping.py','semantic_asset.py','supported_regions.py','cylinder_evidence.py','build_semantic_asset.py']
    return hashlib.sha256(b''.join((ROOT/'services/workers'/p).read_bytes() for p in files)).hexdigest()

def write_json(path,data):
    temporary=path.with_suffix('.writing');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)

def start_scan(store,job,body,executor):
    if not semantic_status()['available']:raise ValueError('本地 AI 整体识别环境尚未准备好')
    if job.get('current_asset_version','original')!=body.version:raise ValueError('编辑版本已变化，请刷新后重试')
    source=source_for(store,job,body.version);digest=hashlib.sha256(source.read_bytes()).hexdigest();category=body.category
    if category=='auto':category=job['request'].get('object_category') or 'auto'
    if category not in ('sofa','chair','table','cabinet'):category='auto'
    key={'source_sha256':digest,'version':body.version,'category':category,'worker_revision':revision()};root=store.root/'jobs'/job['id']/'semantic_scans'
    with SCAN_LOCK:
        root.mkdir(exist_ok=True)
        if not body.force:
            for folder in root.iterdir():
                path=folder/'status.json'
                if not path.is_file():continue
                data=json.loads(path.read_text(encoding='utf-8'))
                if data.get('key')==key and data.get('status') in ('queued','running','ready'):return scan_result(store,job,folder.name)
        identity=uuid.uuid4().hex;folder=root/identity;folder.mkdir();write_json(folder/'status.json',{'scan_id':identity,'status':'queued','stage':'queued','key':key,'created_at':time.time()})
        try:executor.submit(run_scan,store,job['id'],identity,str(source))
        except Exception:write_json(folder/'status.json',{'scan_id':identity,'status':'failed','stage':'failed','key':key,'error':'后台任务未能启动，请重试'});raise
        return scan_result(store,job,identity)

def scan_folder(store,job,identity):
    if not re.fullmatch(r'[a-f0-9]{32}',identity):raise ValueError('识别结果不存在')
    folder=store.root/'jobs'/job['id']/'semantic_scans'/identity
    if not (folder/'status.json').is_file():raise ValueError('识别结果不存在')
    return folder

def scan_result(store,job,identity):
    folder=scan_folder(store,job,identity);state=json.loads((folder/'status.json').read_text(encoding='utf-8'));result={k:v for k,v in state.items() if k!='key'};result['version']=state['key']['version'];result['published']=False
    if state['status']=='ready':
        try:validate_semantic_proposal(json.loads((folder/'manifest.json').read_text(encoding='utf-8')))
        except ValueError as exc:
            state.update(status='failed',stage='failed',error=str(exc));write_json(folder/'status.json',state);result.update(status='failed',stage='failed',error=str(exc));return result
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));doc,_,_=read_glb(folder/'model.glb');result.update(groups=manifest['operation']['groups'],parts=parts_catalog(doc),preview_url=f'/api/jobs/{job["id"]}/asset/semantic-scans/{identity}/style.glb',warnings=['灰色为主体与未确认区域，不会强行归入靠枕。分色仍需检查，不能保证是独立闭合部件。'],limits=manifest['operation']['limits'])
    return result

def run_scan(store,job_id,identity,source):
    job=store.job(job_id);folder=scan_folder(store,job,identity);state=json.loads((folder/'status.json').read_text(encoding='utf-8'));started=time.monotonic()
    def stage(name):state.update(status='running',stage=name);write_json(folder/'status.json',state)
    def run(name,command,timeout):
        with (folder/(name+'.log')).open('wb') as log:
            value=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if value.returncode:
            lines=(folder/(name+'.log')).read_text(encoding='utf-8',errors='replace').splitlines();errors=[line.split('ValueError: ',1)[1] for line in lines if line.startswith('ValueError: ')]
            raise ValueError(errors[-1][:220] if errors else 'AI 整体识别未完成，原模型保留；运行日志已保存')
    try:
        stage('rendering');run('render',[blender_path(),'-b','-t','6','--python-exit-code','1','--python',str(ROOT/'services/workers/render_semantic_views.py'),'--','--input',source,'--output',str(folder)],240)
        stage('waiting_gpu')
        if not GPU_LOCK.acquire(timeout=300):raise ValueError('显卡忙，请稍后重新识别')
        try:stage('recognizing');run('recognize',[segmentation_python(),'-X','utf8',str(ROOT/'services/workers/detect_semantic_views.py'),'--folder',str(folder),'--category',state['key']['category']],360)
        finally:GPU_LOCK.release()
        stage('grouping');run('group',[local_python('hunyuan-mini'),'-X','utf8',str(ROOT/'services/workers/build_semantic_asset.py'),'--input',source,'--folder',str(folder)],240)
        validate_glb(folder/'model.glb');validate_glb(folder/'style.glb')
        if store.job(job_id).get('current_asset_version','original')!=state['key']['version'] or hashlib.sha256(Path(source).read_bytes()).hexdigest()!=state['key']['source_sha256']:raise ValueError('识别期间编辑版本发生变化，请重新识别')
        if revision()!=state['key']['worker_revision']:raise ValueError('识别算法已更新，请重新识别，当前模型保留')
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));validate_semantic_proposal(manifest);write_json(folder/'ready.json',{'source_sha256':state['key']['source_sha256'],'model_sha256':manifest['model_sha256'],'version':state['key']['version']})
        state.update(status='ready',stage='ready',seconds=round(time.monotonic()-started,3));write_json(folder/'status.json',state)
    except Exception as exc:
        state.update(status='failed',stage='failed',error=str(exc)[:220] if isinstance(exc,ValueError) else 'AI 整体识别未完成，原模型保留，请重试',seconds=round(time.monotonic()-started,3));write_json(folder/'status.json',state)

def verified_scan(store,job,request,source):
    folder=scan_folder(store,job,request.semantic_scan_id);state=json.loads((folder/'status.json').read_text(encoding='utf-8'))
    if state['status']!='ready' or not (folder/'ready.json').is_file():raise ValueError('AI 识别结果尚未完成，请等待或重试')
    record=json.loads((folder/'ready.json').read_text(encoding='utf-8'))
    if record['version']!=request.base_version or record['source_sha256']!=hashlib.sha256(source.read_bytes()).hexdigest():raise ValueError('源版本已变化，请重新识别后保存')
    if record['model_sha256']!=hashlib.sha256((folder/'model.glb').read_bytes()).hexdigest():raise ValueError('识别文件校验失败，请重新识别')
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    validate_semantic_proposal(manifest)
    if len(manifest['operation']['groups'])<2:raise ValueError('AI 未识别出多个整体部件，不能采用该候选')
    return folder

def recover_interrupted_scans(store):
    for path in store.root.glob('jobs/*/semantic_scans/*/status.json'):
        try:state=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if state.get('status') in ('queued','running'):
            state.update(status='failed',stage='failed',error='上次 AI 识别因服务重启而中断，请重新识别');write_json(path,state)
