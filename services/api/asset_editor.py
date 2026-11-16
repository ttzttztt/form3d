"""Immutable local asset revisions. The source generation is never overwritten."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid
import os

from .glb_document import read_glb,parts_catalog
from .geometry import validate_glb
from .local3d import local_python
from .store import now

ROOT=Path(__file__).resolve().parents[2]

def plan_completion(store,job,request):
    if request.operation!='complete_part':raise ValueError('请选择完整部件重建操作')
    if job.get('current_asset_version','original')!=request.base_version:raise ValueError('编辑版本已变化，请刷新后重试')
    source=source_for(store,job,request.base_version);interpreter=local_python('hunyuan-mini') or local_python('triposr')
    if not interpreter:raise ValueError('本地几何环境尚未准备好')
    directory=store.root/'jobs'/job['id']/'completion_plans'/uuid.uuid4().hex;directory.mkdir(parents=True)
    (directory/'request.json').write_text(json.dumps(request.model_dump(),ensure_ascii=False,indent=2),encoding='utf-8')
    with (directory/'worker.log').open('wb') as log:
        result=subprocess.run([interpreter,'-X','utf8',str(ROOT/'services/workers/plan_complete_part.py'),'--input',str(source),'--request',str(directory/'request.json'),'--output',str(directory/'plan.json')],stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        details=(directory/'worker.log').read_text(encoding='utf-8',errors='replace');errors=[line.split('ValueError: ',1)[1] for line in details.splitlines() if line.startswith('ValueError: ')]
        raise ValueError(errors[-1][:200] if errors else '范围诊断未完成，原版本保留')
    return {'version':request.base_version,'plan_id':directory.name,**json.loads((directory/'plan.json').read_text(encoding='utf-8'))}

def inspect_quality(store,job,version=None):
    version=version or job.get('current_asset_version','original');source=source_for(store,job,version);digest=hashlib.sha256(source.read_bytes()).hexdigest()
    directory=store.root/'jobs'/job['id']/'quality_checks';directory.mkdir(exist_ok=True);path=directory/(digest+'.json')
    if not path.exists():
        interpreter=local_python('hunyuan-mini') or local_python('triposr')
        if not interpreter:raise ValueError('本地检查环境未准备好')
        temporary=directory/(uuid.uuid4().hex+'.json')
        result=subprocess.run([interpreter,'-X','utf8',str(ROOT/'services/workers/inspect_edit_quality.py'),'--input',str(source),'--output',str(temporary)],capture_output=True,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise ValueError('几何检查未完成，原模型保留')
        temporary.replace(path)
    return {'version':version,'model_sha256':digest,**json.loads(path.read_text(encoding='utf-8'))}

def source_for(store,job,version):
    if not job.get('model_url'):raise ValueError('只有已完成文件检查的模型才能编辑')
    directory=store.root/'jobs'/job['id']
    if version=='original':return directory/'model.glb'
    if not any(item['id']==version for item in job.get('asset_versions',[])):raise ValueError('编辑版本不存在')
    return directory/'assets'/version/'model.glb'

def catalog(store,job,version=None):
    version=version or job.get('current_asset_version','original')
    path=source_for(store,job,version);doc,binary,_=read_glb(path)
    url=job['model_url'] if version=='original' else f'/api/jobs/{job["id"]}/assets/{version}/model.glb'
    parts=parts_catalog(doc,binary)
    grouped={}
    for part in parts:
        key=part.get('logical_group_id') or part['id']
        group=grouped.setdefault(key,{'id':key,'name':part['name'],'part_ids':[],'triangles':0,'proposal_status':part.get('proposal_status') or 'existing','material_count':0})
        group['part_ids'].append(part['id']);group['triangles']+=part['triangles']
    for group in grouped.values():
        group['material_count']=len({p['material_signature'] for p in parts if p['id'] in group['part_ids']})
        group['has_inferred_interfaces']=any(p.get('completion_role')=='inferred_interface' for p in parts if p['id'] in group['part_ids'])
        first=next(p for p in parts if p['id'] in group['part_ids']);group['semantic_color']=first.get('semantic_color');group['semantic_kind']=first.get('semantic_kind')
    reference_ids=list(dict.fromkeys([job['request']['image_id']]+job.get('reference_image_ids',job['request'].get('reference_image_ids',[]))))
    return {'version':version,'latest_version':job.get('current_asset_version','original'),'model_url':url,'parts':parts,'groups':list(grouped.values()),
            'metrics':{'parts':len(grouped),'mesh_primitives':len(parts),'triangles':sum(part['triangles'] for part in parts),'bytes':path.stat().st_size},
            'versions':job.get('asset_versions',[]),'original_url':job['model_url'],
            'editor_review_status':next((item.get('review_status','unreviewed') for item in job.get('asset_versions',[]) if item['id']==version),'unreviewed') if version!='original' else job.get('review_status','pending'),
            'reference_views':[{'id':identity,'url':f'/api/images/{identity}/preview','role':'generation_primary' if identity==job['request']['image_id'] else 'reference_only'} for identity in reference_ids],
            'reconstruction_strategy':'single_primary_view; optional additional-view screening for part candidates; not fused reconstruction',
            'object_category':job['request'].get('object_category') or 'other',
            'limitations':['几何分组不等于语义部件识别','此版本含推测接合面，闭合不代表真实装配结构' if any(p.get('completion_role') for p in parts) else '区域分组按三角面归属，不切开实体','平面 UV 可能拉伸，贴图需检查接缝','主模型单图重建；部件候选可用补充视图筛选，不等于多视图融合']}


def deduplicate_model(store,job_id,path):
    """Immutable content addressed objects, hard-linked atomically; copies on unsupported disks."""
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    directory=store.root/'jobs'/job_id/'asset_objects';directory.mkdir(exist_ok=True)
    canonical=directory/(digest+'.glb')
    if not canonical.exists():shutil.copyfile(path,canonical)
    if hashlib.sha256(canonical.read_bytes()).hexdigest()!=digest:raise ValueError('内容存储校验失败')
    temporary=path.with_suffix('.link')
    try:
        os.link(canonical,temporary);temporary.replace(path);mode='hardlink'
    except OSError:
        temporary.unlink(missing_ok=True);mode='copy'
    return {'sha256':digest,'storage_mode':mode}

def edit_asset(store,job_id,request):
    job=store.job(job_id)
    if job.get('current_asset_version','original')!=request.base_version:raise ValueError('编辑版本已变化，请刷新后重试')
    if request.operation=='reconstruct_parts' and not request.completion_preview_id:raise ValueError('请先查看独立部件预览，再保存同一候选')
    source_version='original' if request.operation=='restore_original' else request.source_version if request.operation=='restore_version' else request.base_version
    source=source_for(store,job,source_version)
    version=uuid.uuid4().hex;directory=store.root/'jobs'/job_id/'assets'/version;directory.mkdir(parents=True)
    payload=request.model_dump()
    payload['_object_category']=job['request'].get('object_category') or 'other'
    payload['_texture_paths']={}
    for slot in ('base_color_image','normal_image','roughness_image'):
        if payload[slot]:
            image=store.image(payload[slot])
            if not image:raise ValueError('贴图不存在，请重新上传')
            payload['_texture_paths'][slot]=str(store.root/'images'/image['id']/'normalized.png')
    (directory/'request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    if request.operation=='semantic_parts':
        from .semantic_parts import verified_scan
        preview=verified_scan(store,job,request,source)
        shutil.copyfile(preview/'model.glb',directory/'model.glb');manifest=json.loads((preview/'manifest.json').read_text(encoding='utf-8'));manifest['semantic_scan_id']=request.semantic_scan_id
    elif request.operation=='replace_part':
        from .part_regeneration import verified_regeneration
        preview=verified_regeneration(store,job,request,source);shutil.copyfile(preview/'model.glb',directory/'model.glb');manifest=json.loads((preview/'manifest.json').read_text(encoding='utf-8'));manifest['regeneration_preview_id']=request.regeneration_preview_id
    elif request.completion_preview_id:
        from .completion_preview import verified_preview
        preview=verified_preview(store,job,request,source)
        shutil.copyfile(preview/'model.glb',directory/'model.glb')
        manifest=json.loads((preview/'manifest.json').read_text(encoding='utf-8'))
        manifest['completion_preview_id']=request.completion_preview_id
    elif request.operation in {'restore_original','restore_version'}:
        shutil.copyfile(source,directory/'model.glb')
        manifest={'operation':{'operation':request.operation,'restored_version':source_version},'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                  'model_sha256':hashlib.sha256((directory/'model.glb').read_bytes()).hexdigest(),'positions_unchanged':True}
    else:
        interpreter=local_python('hunyuan-mini') or local_python('triposr')
        if not interpreter:raise ValueError('资产编辑的本地 Python 环境未准备好')
        with (directory/'edit.log').open('wb') as log:
            result=subprocess.run([interpreter,'-X','utf8','-u',str(ROOT/'services/workers/edit_asset.py'),'--input',str(source),
                                   '--request',str(directory/'request.json'),'--output',str(directory)],stdout=log,stderr=subprocess.STDOUT,
                                  timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            details=(directory/'edit.log').read_text(encoding='utf-8',errors='replace')
            errors=[line.split('ValueError: ',1)[1] for line in details.splitlines() if line.startswith('ValueError: ')]
            raise ValueError(errors[-1][:200] if errors else '编辑未完成；原模型与旧版本保留，详情见 edit.log')
        manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        if request.operation=='optimize_mesh'and not manifest['operation']['changed_parts']:raise ValueError('当前范围无需减面，或保形检查未允许修改；原版本保留，未创建重复版本')
    validation=validate_glb(directory/'model.glb')
    storage=deduplicate_model(store,job_id,directory/'model.glb')
    manifest.update(validation=validation,version=version,base_version=request.base_version,source_version=source_version,
                    positions_unchanged_relative_to=source_version,review_status='unreviewed',storage=storage,note=request.note)
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    entry={'id':version,'base_version':request.base_version,'operation':request.operation,'created_at':now(),
           'model_url':f'/api/jobs/{job_id}/assets/{version}/model.glb','manifest_url':f'/api/jobs/{job_id}/assets/{version}/manifest.json',
           'review_status':'unreviewed','model_sha256':manifest['model_sha256'],'note':request.note,'archived':False,
           'metrics':{'parts':len({p.get('logical_group_id') or p['id'] for p in parts_catalog(read_glb(directory/'model.glb')[0])}),'bytes':(directory/'model.glb').stat().st_size},'storage_mode':storage['storage_mode']}
    def publish(item):
        if item.get('current_asset_version','original')!=request.base_version:raise ValueError('编辑版本发生冲突，未覆盖其他结果')
        item.setdefault('asset_versions',[]).append(entry);item['current_asset_version']=version
        item['events'].append({'at':now(),'stage':'asset_edit','message':'已保存独立编辑版本，原模型保留；编辑结果尚未验收'})
    updated=store.update(job_id,publish)
    return {**catalog(store,updated,version),'manifest':manifest}
