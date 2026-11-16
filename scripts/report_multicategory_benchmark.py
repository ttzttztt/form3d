# -*- coding: utf-8 -*-
"""Build an evidence-linked local review report from real run records."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/multicategory_20261111'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
e=html.escape
labels={'usable_candidate':'可作几何候选','needs_correction':'需要修正','failed':'不通过','not_reviewed':'尚未检查'}
mask_labels={'usable':'主体可用','needs_correction':'需要清理','failed':'不通过','not_reviewed':'尚未检查'}

def main():
    protocol=read(OUT/'protocol.json');reviews=read(OUT/'visual_review.json')
    inventory=read(OUT/'inventory.json');source_notes=read(OUT/'source_inspection.json')
    results=[];cards=[];table=[];all_hashes=True
    for case in protocol['cases']:
        folder=OUT/case['id'];detection=read(folder/'detection_record.json')
        execution=read(folder/'hunyuan/execution.json') if (folder/'hunyuan/execution.json').is_file() else {'status':'not_run'}
        review=reviews['cases'].get(case['id'],{})
        summary=execution.get('summary') or {}
        if sha(ROOT/case['path'])!=case['sha256']:raise ValueError('Input changed '+case['id'])
        for filename,expected in execution.get('sha256',{}).items():
            if sha(folder/'hunyuan'/filename)!=expected:raise ValueError('Artifact changed '+case['id']+'/'+filename)
        if summary:
            for key in ['steps','seed','resolution']:
                if summary[key]!=protocol[key]:raise ValueError('Inference protocol changed '+case['id'])
        for evidence_name in ['model_render_evidence.json','extra_render_evidence.json']:
            evidence_path=folder/'renders'/evidence_name
            if evidence_path.is_file() and read(evidence_path)['model_sha256']!=execution['sha256']['model.glb']:
                raise ValueError('Render does not match actual model')
        geometry=review.get('geometry_status','not_reviewed');foreground=review.get('foreground_status','not_reviewed')
        record={'id':case['id'],'name':case['name'],'category':case['category'],
                'source':case['source'],'source_note':source_notes['notes'].get(case['id']),
                'input_path':case['path'],'input_sha256':case['sha256'],
                'intended_category_detected':detection['intended_category_detected'],
                'ui_default_category_matches':detection['ui_default_category_matches'],
                'selection_mode':detection['selection_mode'],
                'selected_bbox_iou_vs_coco_annotation':detection['selected_bbox_iou_vs_coco_annotation'],
                'detection_wall_seconds':detection['detection_wall_seconds'],'cached_analysis':detection['cached_analysis'],
                'execution':execution,'visual_review':review,
                'foreground_status':foreground,'geometry_status':geometry,
                'measured_mask_accuracy':None,'measured_3d_accuracy':None}
        results.append(record)
        ident=case['id'];task=execution.get('url');technical=execution.get('technical_validation') or {}
        valid=execution['status']=='awaiting_review' and technical.get('errors')==0
        observations=''.join('<li>'+e(text)+'</li>' for text in review.get('observations',['尚未查看实际输出，不作质量结论。']))
        preferred=review.get('preferred_view','model_oblique')
        images=[('原图',folder/'original.png'),('检测候选（绿=测试指定目标）',folder/'detection_overlay.png'),
                ('实际前景',folder/'hunyuan/foreground.png'),('实际 GLB 灰模',folder/('renders/'+preferred+'.png'))]
        image_html=''.join('<figure><a href="'+e(path.relative_to(OUT).as_posix())+'"><img loading="lazy" src="'+e(path.relative_to(OUT).as_posix())+'" alt="'+e(case['name']+' '+name)+'"></a><figcaption>'+e(name)+'</figcaption></figure>' for name,path in images if path.is_file())
        additional=''.join('<a href="'+e(path.relative_to(OUT).as_posix())+'"><img loading="lazy" src="'+e(path.relative_to(OUT).as_posix())+'" alt="'+e(ident+' '+path.stem)+'"></a>' for path in sorted((folder/'renders').glob('*.png')))
        sam=summary.get('segmentation',{});timing=f"本地总耗时 {summary.get('total_local_wall_seconds','未记录')} 秒；SAM {sam.get('duration_seconds','未运行')} 秒；3D {summary.get('duration_seconds','未记录')} 秒"
        task_link='<a href="'+e(task)+'">打开真实任务</a>' if task else '未创建任务'
        note=source_notes['notes'].get(ident,'')
        cards.append(f'''<article data-category="{e(case['category'])}" data-result="{e(geometry)}"><h2>{e(case['name'])} <span class="badge {e(geometry)}">{e(labels[geometry])}</span></h2>
<p>{e(ident)} · {task_link} · <a href="{ident}/hunyuan/execution.json">实测记录</a> · <a href="{ident}/detection_record.json">检测依据</a></p>
<p>预期类别候选：{'检出' if detection['intended_category_detected'] else '未检出'}；默认自动选择：{'类别一致' if detection['ui_default_category_matches'] else '类别不一致'}；本次选框方式：{e(detection['selection_mode'])}。GLB 文件检查：{'通过' if valid else e(execution['status'])}；前景：{e(mask_labels[foreground])}。</p>
<div class="images">{image_html}</div><ul>{observations}</ul><p>{e(timing)}；背景处理 {e(summary.get('background_method','未运行'))}；封闭性 {e(str(summary.get('watertight','未记录')))}。</p>
<details><summary>全部固定灰模视角与原始证据</summary><p>模型坐标朝向未必对应照片；六个视角使用相同相机规则和最长轴归一化，未改变网格。不是相机匹配或尺寸验收。</p><div class="views">{additional}</div><p>{e(note)}</p><a href="{ident}/hunyuan/model.glb">实际 GLB</a> · <a href="{ident}/hunyuan/quality_report.json">工作台质量报告</a></details></article>''')
        table.append(f"| {case['name']} | {'有' if detection['intended_category_detected'] else '无'} | {'一致' if detection['ui_default_category_matches'] else '不一致'} | {mask_labels[foreground]} | {labels[geometry]} | {summary.get('total_local_wall_seconds','—')} |")
    completed=[r for r in results if r['execution']['status']=='awaiting_review']
    technical=[r for r in completed if (r['execution'].get('technical_validation') or {}).get('errors')==0]
    geometry_counts=dict(Counter(r['geometry_status'] for r in results))
    stats={'total_cases':len(results),'input_clean':sum(c['background_expected']=='clean' for c in protocol['cases']),
        'input_scene':sum(c['background_expected']=='scene' for c in protocol['cases']),
        'rendered_scene_caveat_cases':['scene_plant_small'],
        'intended_category_candidate_found':sum(r['intended_category_detected'] for r in results),
        'ui_default_category_matches':sum(r['ui_default_category_matches'] for r in results),
        'diagnostic_fallbacks':sum(r['selection_mode']!='category_guided_detection' for r in results),
        'real_models_generated':len(completed),'zero_error_glb_validation':len(technical),
        'assistant_geometry_review_counts':geometry_counts,
        'full_product_accepted_by_assistant':sum(r.get('visual_review',{}).get('full_product_accepted',False) for r in results),
        'all_source_and_artifact_hashes_verified':all_hashes}
    acceptance={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'stats':stats,
                'protocol_sha256':sha(OUT/'protocol.json'),'review_status':reviews['status'],
                'scope':'Purposive 11-case diagnostic run, not general accuracy; no dense mask/true 3D, no textures, no physical dimensions',
                'timing_note':'Real individual runs. Concurrent CPU Blender review renders may affect wall time; not a controlled speed benchmark. Allocator VRAM excludes desktop/driver, stages are serial and not summed.',
                'source_corrections':source_notes,'cases':results}
    save(OUT/'acceptance.json',acceptance)
    head=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>多品类真实测试 · img_to3D</title>
<style>body{{margin:0;background:#f1f3f6;color:#232936;font:16px/1.65 system-ui}}main{{max-width:1450px;margin:auto;padding:24px}}article,.summary{{background:white;padding:22px;border-radius:12px;margin:18px 0}}h1{{margin-bottom:8px}}h2{{font-size:21px}}a{{color:#285ab5}}.images{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}figure{{margin:0}}img{{width:100%;height:260px;object-fit:contain;background:#f5f5f5}}figcaption{{text-align:center;font-size:14px}}.badge{{font-size:14px;padding:4px 10px;border-radius:20px;background:#eee}}.usable_candidate{{background:#d7f2df}}.needs_correction{{background:#fff0c4}}.failed{{background:#ffd8d8}}.views{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}select{{padding:8px;margin-right:10px}}[hidden]{{display:none}}@media(max-width:700px){{main{{padding:12px}}.images,.views{{grid-template-columns:repeat(2,1fr)}}img{{height:180px}}article,.summary{{padding:14px}}h1{{font-size:25px}}}}</style>
<main><h1>多品类真实测试 · 2026-11-11</h1><p>5 张白底商品图 + 6 张场景图，其中浴室小盆栽场景疑似渲染图，单列看待。测试指定类别选择与网页默认选择分别记录。</p>
<section class="summary"><p>预期类别候选 {stats['intended_category_candidate_found']}/{len(results)}；默认选择类别一致 {stats['ui_default_category_matches']}/{len(results)}；真实模型与零错误文件校验 {len(technical)}/{len(results)}。</p>
<p>几何候选可用 {geometry_counts.get('usable_candidate',0)}；需修正 {geometry_counts.get('needs_correction',0)}；不通过 {geometry_counts.get('failed',0)}；尚未检查 {geometry_counts.get('not_reviewed',0)}。完整商品资产通过 {stats['full_product_accepted_by_assistant']}。</p>
<p>这些是本次小样本观察数量，不是准确率。没有运行纹理模型，没有验证背面或尺寸，用户审核保持待确认。首次协议冻结后未替换失败样本；花瓶漏检后的整图诊断明确区分。</p>
<a href="acceptance.json">实测 JSON</a> · <a href="protocol.json">事前协议</a> · <a href="source_inspection.json">来源复核说明</a> · <a href="sources/coco128/provenance.json">公开图片下载记录</a></section>
<a href="examples_overview.png">查看代表样本对比总览</a>
<label>品类 <select id="category"><option value="all">全部</option>{''.join('<option>'+c+'</option>' for c in sorted({r['category'] for r in results}))}</select></label>
<label>几何结论 <select id="result"><option value="all">全部</option>{''.join('<option value="'+k+'">'+v+'</option>' for k,v in labels.items())}</select></label>
'''
    script='''<script>function filter(){const c=document.querySelector('#category').value,r=document.querySelector('#result').value;for(const a of document.querySelectorAll('article'))a.hidden=(c!=='all'&&a.dataset.category!==c)||(r!=='all'&&a.dataset.result!==r)}document.querySelector('#category').onchange=filter;document.querySelector('#result').onchange=filter;</script>'''
    (OUT/'index.html').write_text(head+'\n'.join(cards)+script+'</main></html>',encoding='utf-8')
    doc=f'''# 多品类真实测试 · 2026-11-11

已盘点 `images/` 中 {inventory['count']} 张图片，边缘启发式为白底 {inventory['counts']['white_background']}、透明 {inventory['counts']['provided_alpha']}、其他 {inventory['counts']['scene']}。这是输入背景初筛，不能当作人工真值。

本轮固定 11 例：本地 5 张白底商品图、2 张场景商品图，以及公开 COCO128 的 4 张场景图。浴室小盆栽图疑似渲染图，在来源复核中单列，不能声称 6 张场景都是实拍。公开压缩包约 6.7 MiB，下载地址、日期和 SHA-256 已记录。用户图片仅在本机处理，原图和上轮实验均保留。

[可筛选的本地验收报告](../experiments/multicategory_20261111/index.html) · [机器可读记录](../experiments/multicategory_20261111/acceptance.json) · [事前固定协议](../experiments/multicategory_20261111/protocol.json)

![代表样本的输入与实际 GLB 对照](../experiments/multicategory_20261111/examples_overview.png)

## 本次观察数量

- 预期类别候选检出 {stats['intended_category_candidate_found']}/11；网页默认选择类别一致 {stats['ui_default_category_matches']}/11。类别候选存在并不等于自动选中了想要的实例。
- 实际生成 {len(completed)}/11 个候选，零错误 glTF 校验 {len(technical)}/11。另有 {stats['diagnostic_fallbacks']} 个事前约定的诊断框回退，不计为自动目标识别成功。
- 助手查看实际输出后的几何判断：可作候选 {geometry_counts.get('usable_candidate',0)}，需修正 {geometry_counts.get('needs_correction',0)}，不通过 {geometry_counts.get('failed',0)}，未检查 {geometry_counts.get('not_reviewed',0)}。完整商品资产接受 {stats['full_product_accepted_by_assistant']}；没有修改用户审核状态。

| 样本 | 预期类别候选 | 默认选择类别 | 前景检查 | 几何检查 | 本地总耗时/秒 |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(table)}

## 判定方法与限制

图片、类别、关键特征、回退规则在推理前固定。本轮针对指定类别从检测候选中选最大实例；这与网页优先大件家具的默认选择不同，两者分别记录。花瓶漏检后使用整图仅为诊断，不算全自动成功。COCO 现有框仅用于记录检测框重叠，不是分割真值或 3D 真值；不报告准确率、Chamfer 或不可见面的正确率。

Hunyuan3D-2mini，seed=42、30 步、256 网格、自动分割。保存每例真实任务、前景、模型输入、分割摘要、实际 GLB、日志、计时和哈希。渲染导入实际模型，最长轴统一归一化，材质及相机规则一致，没有重做几何。坐标朝向可能不同，额外查看左侧和对侧斜视，不能将固定“前视”误认为原照片的正面。

所有耗时来自本轮记录；CPU 灰模渲染与部分推理并行，数据不作为受控速度基准。显存是 PyTorch 分配器数值，不是整卡用量。几何候选可用只表示实验预览结构可辨，纹理、材质、真实尺度、背面和内部装配均未通过商品验收。COCO128 是公开常见数据，无法排除预训练数据重合；这些小样本数量不能当成泛化准确率。

## 已定位的问题

1. **检测与目标选择**：彩绘花瓶漏检；多目标场景的默认大件优先策略可能选择桌面或柜子，测试指定的小花瓶/盆栽需要切换目标。两种失败需要分开处理。
2. **语义杂物清理**：SAM 能切外轮廓，不能保证去掉柜内陈列品、猫或其他遮挡物；缺失部分未做修补，保留这类干扰的 3D 不能作为独立商品。
3. **输入文字**：盆栽尺寸标注可能残留并进入几何，需做标注清理；单次观察不能证明因果。
4. **白底分流**：圆桌原图为白底，紧裁剪后被判成场景，实际走 SAM；本图可用但说明自动策略受裁剪影响，应增加有保护的分流规则。
5. **形状模型局限**：正面花瓶成为薄片，玻璃门变成实体；这些问题不能靠文件校验或提高三角形数量解决。

逐件观察、关键缺陷、任务入口与实际图像见可筛选报告和 `visual_review.json`。下一步应优先改善输入清理、目标意图选择与失败分流，再在可用样本上接纹理。
'''
    (ROOT/'docs/MULTICATEGORY_ACCEPTANCE_2026-11-11.md').write_text(doc,encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
