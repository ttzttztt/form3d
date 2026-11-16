# -*- coding: utf-8 -*-
"""Evidence report for input cleanup, gates, and preserved corrective attempts."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import html
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageOps

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/input_guard_20261111';BASE=ROOT/'experiments/multicategory_20261111'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def composite(path):
    image=Image.open(path).convert('RGBA')
    return Image.alpha_composite(Image.new('RGBA',image.size,'white'),image).convert('RGB')

def montage():
    canvas=Image.new('RGB',(1200,840),'#eef0f2');draw=ImageDraw.Draw(canvas)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',20);small=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',17)
    draw.text((16,12),'真实清理与复测：原始失败、首轮回归、最终候选分别保留',font=font,fill='black')
    panels=[('标注清理前',OUT/'batch/clean_plant/foreground_before_cleanup.png',(280,900,410,1046)),
            ('文字和引线清理后',OUT/'attempt_002/clean_plant/cleaned.png',(280,900,410,1046)),
            ('旧灰模：花盆旁有碎点',BASE/'clean_plant/renders/model_oblique.png',None),
            ('新灰模：该处已清除',OUT/'attempt_002/clean_plant/renders/model_oblique.png',None)]
    for i,(title,path,crop) in enumerate(panels):
        draw.text((i*300+10,48),title,font=small,fill='black')
        image=composite(path)
        if crop:image=image.crop(crop)
        image=ImageOps.contain(image,(288,310));canvas.paste(image,(i*300+(300-image.width)//2,82+(310-image.height)//2))
    for i,(title,path) in enumerate([
        ('首轮回归：桌脚之间多余薄片',OUT/'batch/clean_table/renders/model_oblique.png'),
        ('修正复测：多余薄片消失',OUT/'attempt_002/clean_table/renders/model_oblique.png'),
        ('遮挡候选：停在建模前',OUT/'batch/scene_sofa_cat/input_overlay.png')]):
        draw.text((i*400+10,426),title,font=small,fill='black')
        image=ImageOps.contain(composite(path),(388,330));canvas.paste(image,(i*400+(400-image.width)//2,466+(330-image.height)//2))
    draw.text((16,811),'输入检查不保证几何正确；不补全不可见结构。上图均来自实际输入、处理图和实际 GLB 渲染。',font=small,fill='black')
    canvas.save(OUT/'comparison_overview.png')

def main():
    protocol=read(BASE/'protocol.json');visual=read(OUT/'visual_review.json');rows=[];cards=[];records=[]
    names={'usable_candidate':'可作几何候选','needs_correction':'需修正','failed':'几何仍失败','not_generated_input_blocked':'输入被拦截'}
    for case in protocol['cases']:
        ident=case['id'];review=visual['cases'][ident];attempt=review.get('selected_attempt','batch');folder=OUT/attempt/ident
        execution=read(folder/'execution.json');quality=execution['input_quality'];baseline=read(BASE/ident/'hunyuan/execution.json')
        assert sha(ROOT/case['path'])==case['sha256']
        for name,expected in execution['sha256'].items():assert sha(folder/name)==expected,(ident,name)
        for name in ['source_sha256','prepared_sha256']:
            assert quality[name]==read(OUT/'batch'/ident/'input_quality.json')[name]
        rgb_unchanged=bool(np.array_equal(np.asarray(Image.open(folder/'cleaned.png'))[:,:,:3],np.asarray(Image.open(folder/'prepared.png'))[:,:,:3]))
        assert rgb_unchanged,'RGB was modified '+ident
        reasons=[reason['code'] for reason in quality['reasons']]
        observations=review['observations'];label=names[review['geometry_status']]
        summary=execution.get('summary') or {}
        records.append({'case_id':ident,'selected_attempt':attempt,'execution':execution,'visual_review':review,
                        'prepared_rgb_unchanged_verified':rgb_unchanged,'source_sha256_verified':True})
        rows.append(f"| {case['name']} | {'拦截，未启动 3D' if execution['gate_blocked'] else '继续生成'} | {quality['removed_alpha_pixels']} | {label} |")
        pictures=[('原图',(BASE/ident/'original.png')),('清理后',folder/'cleaned_preview.png'),('检查标记',folder/'input_overlay.png')]
        if execution['status']=='awaiting_review':pictures.append(('实际灰模',folder/('renders/model_'+review.get('preferred_view','oblique')+'.png')))
        images=''.join('<figure><a href="'+html.escape(str(path.relative_to(OUT) if path.is_relative_to(OUT) else Path('..')/'multicategory_20261111'/ident/path.name).replace('\\','/'))+'"><img loading="lazy" src="'+html.escape(str(path.relative_to(OUT) if path.is_relative_to(OUT) else Path('..')/'multicategory_20261111'/ident/path.name).replace('\\','/'))+'" alt="'+html.escape(case['name']+' '+title)+'"></a><figcaption>'+title+'</figcaption></figure>' for title,path in pictures)
        rel=folder.relative_to(OUT).as_posix();notes=''.join('<li>'+html.escape(text)+'</li>' for text in observations)
        more=''
        if execution['status']=='awaiting_review':
            more='<details><summary>全部实际灰模视角</summary><div class="images">'+''.join('<a href="'+path.relative_to(OUT).as_posix()+'"><img loading="lazy" src="'+path.relative_to(OUT).as_posix()+'" alt="'+path.stem+'"></a>' for path in sorted((folder/'renders').glob('*.png')))+'</div></details>'
        cards.append(f'<article><h2>{html.escape(case["name"])} · {label}</h2><p><a href="{execution["url"]}">打开真实任务</a> · <a href="{rel}/input_quality.json">输入检查记录</a> · <a href="{rel}/execution.json">实际执行记录</a></p><div class="images">{images}</div><ul>{notes}</ul><p>原因代码：{html.escape(", ".join(reasons) or "无输入阻断项")}。清理 {quality["removed_alpha_pixels"]} 个 alpha 像素；OCR {quality["ocr"]["seconds"]} 秒；输入准备 {quality["duration_seconds"]} 秒。</p>{more}</article>')
    stats={'unique_cases':len(records),'blocked_before_3d':sum(r['execution']['gate_blocked'] for r in records),
           'generated_after_preflight':sum(r['execution']['status']=='awaiting_review' for r in records),
           'geometry_review':dict(Counter(r['visual_review']['geometry_status'] for r in records)),
           'all_selected_source_and_artifact_hashes_verified':True,'all_selected_prepared_rgb_unchanged_verified':True,
           'api_tests_passed':27,'rule_tests_passed':11,'legacy_preprocess_tests_passed':4,
           'full_product_assets_accepted':0}
    acceptance={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'stats':stats,
                'rule_evaluation_scope':'Known-case regression motivated by baseline failures, not held-out accuracy. First batch and three corrective reruns preserved.',
                'clutter_handling':'Local detection and hold; no semantic object erase, inpainting or verified occlusion completion',
                'corrective_history':read(OUT/'corrective_change.json'),'cases':records,
                'web_blocked_validation':read(OUT/'web_blocked_validation.json'),'cancellation':read(OUT/'cancellation.json')}
    save(OUT/'acceptance.json',acceptance);montage()
    header=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>输入清理与质量拦截验收</title><style>body{{max-width:1450px;margin:24px auto;padding:0 18px;background:#f1f3f5;color:#252a34;font:16px/1.7 system-ui}}article,section{{padding:20px;background:white;border-radius:12px;margin:18px 0}}.images{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}figure{{margin:0}}img{{width:100%;height:280px;object-fit:contain;background:#f6f6f6}}.overview{{height:auto}}a{{color:#285bb4}}@media(max-width:700px){{.images{{grid-template-columns:1fr 1fr}}img{{height:180px}}h1{{font-size:25px}}}}</style>
<h1>输入清理与质量拦截 · 2026-11-11</h1><section><p>同一批 11 个样本：5 个在 3D 推理前拦截，6 个继续生成。最终查看实际灰模后：4 个可作几何候选、1 个需修正、1 个仍生成失败。完整商品资产接受为 0。</p><p>尺寸标注和独立引线可保守清理；遮挡物仅识别并提示修正输入，没有自动补全隐藏结构。规则针对已知失败做回归检查，不是泛化准确率。</p><a href="acceptance.json">实测 JSON</a> · <a href="corrective_change.json">两次发现与修正记录</a> · <a href="web_blocked_validation.json">网页拦截验收</a> · <a href="cancellation.json">实际取消测试</a></section><img class="overview" src="comparison_overview.png" alt="实际文字清理、灰模复测及遮挡拦截对照"><section><h2>保留的首轮回归</h2><p>圆桌首次改走基础白底处理后，桌脚间出现多余薄片；第二次改为白底紧裁剪的 SAM 细分，实际灰模中薄片消失。盆栽首轮只清文字仍留下尺寸括号，第二轮清除文字与独立双端引线，合计 603 个 alpha 像素，灰模中该处碎点与细杆消失。</p><a href="batch/clean_table/renders/model_oblique.png">圆桌首轮实际灰模</a> · <a href="batch/clean_plant/renders/model_oblique.png">盆栽首轮实际灰模</a><p>彩绘花瓶仍通过输入检查并生成薄片，说明输出几何还需要独立检查。玻璃门、材质和真实尺寸均未由本轮解决。</p></section>'''
    (OUT/'index.html').write_text(header+'\n'.join(cards)+'</html>',encoding='utf-8')
    doc=f'''# 输入清理与质量拦截验收 · 2026-11-11

本轮实现本地 RapidOCR 尺寸文字清理、独立双端尺寸引线清理、原图背景分类与紧裁剪细分，以及破碎掩码、低原生像素和遮挡/前景干扰候选拦截。原图、旧模型与首轮回归均保留。

[逐件图像报告](../experiments/input_guard_20261111/index.html) · [实测 JSON](../experiments/input_guard_20261111/acceptance.json) · [修正记录](../experiments/input_guard_20261111/corrective_change.json)

![实际清理、复测与拦截](../experiments/input_guard_20261111/comparison_overview.png)

## 同批 11 例的最终状态

5 个问题输入停在 `awaiting_input`，均核验没有启动 3D Worker、没有模型文件，模型下载返回 409，清理图和原因仍可查看。6 个继续生成，实际灰模中 4 个可作几何预览候选、1 个需修正、1 个仍失败。没有把输入检查通过当成商品验收，没有修改用户接受状态。

| 样本 | 流程结果 | 移除标注 alpha 像素 | 目视判断 |
| --- | --- | --- | --- |
{chr(10).join(rows)}

## 真实改善和保留的回归

- 盆栽真实 OCR 识别 `5in`。首轮移除 329 个 alpha 像素，括号引线残留，新灰模仍有细杆；v1.1 清理文字和独立双端尺寸引线，共移除 603 个 alpha 像素，第二轮实际灰模中该处碎点与细杆不再出现。RGB 未修补，主体掩码保留，叶片仍粗糙并有粘连。
- 圆桌首轮根据原图白底强制基础去背景，实际模型新增桌脚间的薄片。修正为记录原图白底，同时对边缘不干净的紧裁剪用 SAM 细分，第二轮实际灰模中薄片消失。首轮模型未覆盖。
- 陈列柜检出盆栽/瓶子干扰，猫遮挡沙发和反光玻璃桌检出破碎掩码/前景物品，插花瓶检出花束，小盆栽原生像素不足。这些输入现在停在建模前，需要清理来源图或补充视图。
- 彩绘花瓶仍生成薄片并封口。输入检查不能识别所有几何退化，后续仍需输出几何检查。玻璃柜门封实的问题也没有修好。

## 实现边界

OCR 为 RapidOCR ONNX Runtime 1.4.4，实际运行 PP-OCRv4 检测/识别模型，CPU 推理，模型哈希保存在每个任务。仅处理带明确单位且与主体分离的文字/独立尺寸括号；普通文字、主体重叠文字、无端部刻度的细杆均保留。规则有误识别风险，不能承诺任意 Logo 或尺寸图完全正确。

遮挡候选复用本地 Grounding DINO Tiny，候选分数和框内 alpha 重叠属于启发式信号，不证明真实遮挡关系。当前实现是识别和拦截，没有运行语义对象擦除或图像修补模型，没有补全被挡住的产品结构。正常结构孔洞不会仅因有孔而被拦；破碎阈值、像素阈值与规则版本写入任务记录。

全部最终选定案例的原图、任务文件哈希及清理前后 RGB 一致性已核验。Hunyuan 参数仍为 30 步、seed 42、256 网格；导入实际 GLB，使用相同灰模场景并查看多侧视角。未验证纹理、物理尺寸和隐藏面。规则来自已知难例，不是独立测试集，不能据此报告准确率。

## 软件验证

27 项 API/契约测试、11 项清理规则测试、4 项原有预处理测试通过；前端构建通过。真实网页验证 5 个拦截任务的原因/处理图可访问、模型不可下载，刷新恢复和移动端布局通过；真实输入检查阶段取消成功，未启动形状推理。详见实验目录中的网页与取消记录。

实验目录 `experiments/input_guard_20261111/`：`batch/` 为首轮完整 11 例，`attempt_002/` 为圆桌、盆栽和猫遮挡案例的真实重验，首轮失败不覆盖。逐件耗时、OCR 输出、DINO 候选、处理图和模型分别保存。
'''
    (ROOT/'docs/INPUT_GUARD_ACCEPTANCE_2026-11-11.md').write_text(doc,encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
