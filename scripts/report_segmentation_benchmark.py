# -*- coding: utf-8 -*-
"""Report measured run data plus explicitly attributed visual review."""
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/segmentation_20261111'
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

protocol=read(OUT/'protocol.json')
job=read(OUT/'armchair/web_run/job.json')
new=read(OUT/'armchair/web_run/local_summary.json')
old=read(ROOT/'experiments/quality_20261111/armchair/hunyuan/attempt_001/local_summary.json')
segment=read(OUT/'armchair/web_run/segmentation_summary.json')
visual=read(OUT/'visual_review.json')
workflow=read(OUT/'web_workflow.json')
points=read(OUT/'point_checks.json')
assert workflow['status']=='PASS'
assert old['worker_revision']==new['worker_revision']
for name in ['steps','seed','resolution','guidance_scale','precision','volume_decoder','provenance']:
    assert old[name]==new[name],name
assert list(job['request']['target'].values())==protocol['target']
assert sha(OUT/'armchair/web_run/model.glb')==new['model_sha256']
assert sha(ROOT/protocol['source'])==segment['source_sha256']
assert sha(ROOT/protocol['prepared_reference'])==segment['prepared_sha256']
assert sha(OUT/'armchair/web_run/segmentation_mask.png')==segment['mask_sha256']
assert segment['mask_sha256']==read(OUT/'armchair/sam2_box/segmentation_summary.json')['mask_sha256']
assert points['results']['sam2']['mask_sha256']==segment['mask_sha256']
created=datetime.fromisoformat(job['created_at'])
review=datetime.fromisoformat(next(event['at'] for event in job['events'] if event['stage']=='review'))
task_seconds=(review-created).total_seconds()
result={
    'job_id':job['id'],'url':workflow['url'],'workflow':'pass','user_review_status':job['review_status'],
    'actual_glb_validation':job['report']['gltf_validation'],
    'same_input_box_and_geometry_parameters_verified':True,
    'sam_mask_repeat_hash_equal':True,
    'sam_seconds':segment['duration_seconds'],
    'sam_prediction_seconds':segment['inference_seconds'],
    'hunyuan_worker_seconds':new['duration_seconds'],
    'local_pipeline_wall_seconds':new['total_local_wall_seconds'],
    'task_creation_to_review_seconds':round(task_seconds,3),
    'old_hunyuan_worker_seconds':old['duration_seconds'],
    'timing_note':'Single executions at different times; not a controlled speed benchmark. Worker includes startup and loading. Local wall excludes GPU waiting and final GLB validation.',
    'sam_allocator_peak_mib':segment['peak_vram_allocated_mib'],
    'hunyuan_allocator_peak_mib':new['peak_vram_mb'],
    'memory_note':'Stages run serially. PyTorch allocator only; not total GPU use and not summed.',
    'hunyuan_sampled_process_rss_mib':new['peak_process_rss_mb'],
    'sam_model_predicted_iou':segment['model_predicted_iou'],
    'measured_segmentation_accuracy':None,'measured_dense_mask_iou':None,
    'old_sparse_checks':points['results']['u2netp'],'sam_sparse_checks':points['results']['sam2'],
    'vertices':new['vertices'],'triangles':new['triangles'],'watertight':new['watertight'],
    'hashes':{name:new[name] for name in ['input_sha256','foreground_sha256','model_sha256','worker_revision']},
    'sam_source_sha256':segment['source_sha256'],'sam_mask_sha256':segment['mask_sha256'],
    'visual_review':visual,
    'browser_test_note':'Initial test used an incorrect image alt selector and timed out. Corrected selector; resumed same running task, observed masks during generation, then completed downloads/refresh/mobile checks. No inference rerun or failure deletion.',
    'cancellation':read(OUT/'cancellation.json'),
}
(OUT/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

doc=f'''# SAM 2 分割与同图 3D 验收 · 2026-11-11

已完成 Grounding DINO 候选框 → SAM 2.1 Hiera Tiny → 本地 3D 的接入，并对之前失败的同一张场景扶手椅完成真实网页推理。这个样本的主体分割及几何候选有明显改善；完整商品资产仍未通过，用户审核保持 `{job['review_status']}`。

[打开真实任务]({workflow['url']}) · [本地交互报告](../experiments/segmentation_20261111/index.html) · [机器可读实测](../experiments/segmentation_20261111/acceptance.json)

![原图、旧新分割及实际 GLB 对照](../experiments/segmentation_20261111/comparison_overview.png)

## 固定条件

- 复用原先选定的检测框，本轮没有重新挑框，没有补充 SAM 点提示。原图 1279×1706，ROI 像素 `[167,475,1075,1514]`，原图和旧失败资产不变。
- Hunyuan3D-2mini 同一权重、同一生成脚本哈希、seed 42、30 步、256 网格、guidance 5、同一精度及全网格解码。比较脚本逐项检查一致性。
- 新掩码来自原始完整图片与目标框，再裁剪、与准备图的 alpha 相乘。分割结束不再执行 U2NetP，未做修补或隐藏结构补全。
- 旧模型使用旧 U2NetP 前景，新模型使用 SAM 前景；旧新实际 GLB 由同一 Blender 函数渲染，统一最长轴比例、相同材质/相机/灯光。这不是原照片相机拟合，模型没有为展示重新建造或修形。

## 实际观察

SAM 保留了旧方案丢失的灰色靠背，以及双扶手和可见前腿，背景架、墙与地板被剔除。新灰模的靠背轮廓完整，靠背凹点可见，旧模型下方明显的杂杆在新模型四个检查视角中未见。

仍有问题：分割边缘有锯齿及扶手/坐垫接缝小缺口；模型扶手边缘薄且不平，侧板简化并有凹痕，软包接缝和凹点仅近似。网格 `watertight={str(new['watertight']).lower()}`，不能当作已封闭实体。纹理模型未运行，黑色扶手和面料色彩没有还原；背面和遮挡部分无法用原图验证，尺寸没有校准。

上述为助手查看实际图片与渲染后的判断，不替代用户确认。分割可供本样本继续建模、几何可供试验预览；完整商品资产不通过。没有将任务改成用户已接受。

## 实测数据

| 项目 | 本次网页任务实测 |
| --- | --- |
| SAM 子进程耗时，含启动和加载 | {segment['duration_seconds']:.3f} 秒 |
| SAM 图像编码及预测 | {segment['inference_seconds']:.3f} 秒 |
| Hunyuan 子进程耗时，含启动和加载 | {new['duration_seconds']:.3f} 秒 |
| 分割 + 3D 桥接总耗时 | {new['total_local_wall_seconds']:.3f} 秒 |
| 任务创建至待审核 | {task_seconds:.3f} 秒 |
| SAM PyTorch 显存分配峰值 | {segment['peak_vram_allocated_mib']:.1f} MiB |
| Hunyuan PyTorch 显存分配峰值 | {new['peak_vram_mb']:.1f} MiB |
| Hunyuan 进程工作集采样峰值 | {new['peak_process_rss_mb']:.1f} MiB |
| 网格 | {new['vertices']:,} 顶点 / {new['triangles']:,} 三角形 |
| 完整 glTF Validator | {job['report']['gltf_validation']['errors']} 错误 / {job['report']['gltf_validation']['warnings']} 警告 |

显存是各阶段 PyTorch 分配器峰值，分割和 3D 串行运行，不相加，也不代表整卡用量。桥接总耗时包含进程退出等开销，不含排队与最终 GLB 校验；分阶段计时不能直接相加当成任务总耗时。旧 Hunyuan 单次耗时 {old['duration_seconds']:.3f} 秒，本轮不是速度对比，不能据此宣称提速。更早的独立 SAM 检查为 36.562 秒，与本次网页任务分开保存；两次实际掩码哈希相同。

## 分割检查的限制

预先选定的 9 个前景诊断点，旧方案保留 4 个，SAM 保留 8 个；5 个背景点两者均剔除。不是密集真值，不换算准确率。未通过的点为右前腿 ROI `[501,975]`；复看原图疑似位于腿轮廓边界外，点的标注存疑。原协议和 8/9 原始结果保留，未挪点或改标签。详见 `point_checks.json`、`armchair/diagnostic_points.png` 及 `visual_review.json`。

SAM 内部预测 IoU {segment['model_predicted_iou']} 只是模型自估分数，不是实测 IoU 或准确率。没有人工密集掩码，没有泛化到其他品类的质量结论。

## 软件与流程验收

- 25 个 API/路由/契约测试通过，合成测试夹具只验证契约，不证明模型效果；前端构建通过。
- 真实网页自动策略识别本图为场景并选择 SAM，生成期间可查看/下载分割图；实际 3D 推理、GLB 下载、刷新恢复、移动端无横向溢出通过，浏览器无页面错误。
- 显式 SAM 未就绪会拒绝；运行失败不回退。自动策略在 SAM 未就绪时允许基础处理，实际选择写入报告；白底和透明输入保留基础处理。
- 真实取消测试在 SAM 阶段取消，任务停在 cancelled，没有发布 GLB；进程检查另存。未伪造完成进度。
- 首次浏览器测试因测试脚本中的图片 alt 选择器写错而超时，修正后续接同一运行任务完成检查。初始失败记录保留，不是模型推理失败。

## 复现与证据

真实任务 ID：`{job['id']}`。本次模型 SHA-256：`{new['model_sha256']}`；掩码 SHA-256：`{segment['mask_sha256']}`。原图、准备图、权重和脚本哈希均保存在实测 JSON。

SAM 源码固定 `2b90b9f5ceec907a1c18123530e92e794ad901a4`，模型 `facebook/sam2.1-hiera-tiny` 固定 `de431c4043854a71d8101e17995dfe596bf101a5`，156,008,466 字节，Apache-2.0，未使用 CUDA 扩展。独立 `.venv-sam2` 复用现有 CUDA torch，没有修改原 ML 环境。

```powershell
node scripts/test_sam2_workflow.mjs
node scripts/test_sam2_cancel.mjs
& 'D:\\Blender 5.1\\blender.exe' -b --python scripts/render_segmentation_benchmark.py
.\\.venv\\Scripts\\python.exe scripts/assemble_segmentation_comparison.py
.\\.venv\\Scripts\\python.exe scripts/report_segmentation_benchmark.py
```

实验目录 `experiments/segmentation_20261111/` 保存协议、检查点、两次分割、网页任务快照、实际模型、四视图、截图和验收 JSON。上轮 `experiments/quality_20261111/` 保持原样。

下一步先用已有真实商品图扩充分割验证，再决定是否接纹理。当前只证明这一张失败样本得到改善，尚不足以认定复杂场景稳定可用。
'''
(ROOT/'docs/SEGMENTATION_ACCEPTANCE_2026-11-11.md').write_text(doc,encoding='utf-8')

e=html.escape
improvements=''.join('<li>'+e(item)+'</li>' for item in visual['improvements'])
defects=''.join('<li>'+e(item)+'</li>' for item in visual['remaining_defects'])
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SAM 2 同图复测</title><style>body{{max-width:1400px;margin:30px auto;padding:0 20px;background:#f2f3f5;color:#20252c;font:16px/1.65 system-ui}}img{{width:100%;height:auto}}a{{color:#2457ba}}section{{padding:18px 24px;background:white;border-radius:12px;margin:16px 0}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}pre{{overflow:auto}}@media(max-width:700px){{.grid{{display:block}}}}</style>
<h1>SAM 2 → Hunyuan 同图复测</h1><p>本样本分割和几何候选改善；完整商品资产未通过。保留用户待审核状态。</p>
<p><a href="{e(workflow['url'])}">打开真实任务</a> · <a href="../../docs/SEGMENTATION_ACCEPTANCE_2026-11-11.md">完整验收记录</a> · <a href="acceptance.json">实测 JSON</a> · <a href="armchair/web_run/model.glb">实际 GLB</a></p>
<img src="comparison_overview.png" alt="原图、旧新抠图与实际 GLB 四视图对比">
<div class="grid"><section><h2>查看实际输出后确认的改善</h2><ul>{improvements}</ul></section><section><h2>剩余缺陷与未验证项</h2><ul>{defects}</ul></section></div>
<section><h2>实际耗时与显存</h2><p>SAM {segment['duration_seconds']:.3f} 秒；Hunyuan {new['duration_seconds']:.3f} 秒；本地桥接总耗时 {new['total_local_wall_seconds']:.3f} 秒；任务创建至待审核 {task_seconds:.3f} 秒。</p>
<p>PyTorch 分配器峰值：SAM {segment['peak_vram_allocated_mib']} MiB，Hunyuan {new['peak_vram_mb']} MiB。串行阶段不相加，不是整卡用量。单次计时不构成速度基准。</p></section>
<section><h2>稀疏点不是准确率</h2><p>前景诊断点：旧 4/9，新 8/9；背景均 5/5 排除。右前腿点标注位置存疑，原结果未修改。模型自估 IoU {segment['model_predicted_iou']} 不是实测准确率。</p><p><a href="armchair/diagnostic_points.png">查看预先选定的诊断点</a> · <a href="point_checks.json">原始检查结果</a> · <a href="visual_review.json">助手视觉检查及限制</a></p></section>
<section><h2>验证记录</h2><p>25 项 API/契约测试通过；真实网页推理、生成期间分割预览、下载、刷新与移动端通过。模型 {new['triangles']:,} 三角形，glTF 校验无错误/警告，网格非完全封闭；未运行纹理模型。</p><p><a href="web_workflow.json">网页结果</a> · <a href="web_workflow_last_failure.json">保留的首次测试选择器错误</a> · <a href="cancellation.json">真实取消测试</a> · <a href="cancellation_process_check.json">取消后进程检查</a></p></section>
<p>此结论仅适用于这一张场景扶手椅；隐藏结构与真实尺寸未验证。旧失败文件不变。</p></html>'''
(OUT/'index.html').write_text(page,encoding='utf-8')
print(json.dumps({key:result[key] for key in ['job_id','workflow','local_pipeline_wall_seconds','task_creation_to_review_seconds','watertight']},ensure_ascii=False))
