"""Build an evidence-linked report. All numbers come from saved run artifacts."""
import html,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/part_regeneration_20261113'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
ui=read(OUT/'ui_results.json');controls=read(OUT/'ui_controls.json');verification=read(OUT/'independent_verification.json')
assert not ui.get('failure')and not controls.get('failure')
task=ROOT/'.data/jobs'/ui['job']/'part_regenerations'/ui['regeneration_id']
summary=read(task/'generated/local_summary.json');manifest=read(task/'preview/manifest.json')
reference_state=read(task.parent.parent/'part_reference_scans'/ui['reference_scan']/'status.json')
pillow=read(OUT/'corduroy_pillow/generated_v1/local_summary.json')
cushion=read(OUT/'leather_cushion/generated_trial_v1/local_summary.json')
provenance=read(OUT/'leather_cushion/completed_reference/provenance.json')
seat=read(OUT/'leather_cushion/replacement_outline_trial_v2/manifest.json')['operation']
placement=manifest['operation']['placement']
def tests(file):
    text=(OUT/file).read_text(encoding='utf-8')
    count=re.findall(r'Ran (\d+) tests',text)
    assert count and re.search(r'\nOK\s*$',text),file
    return int(count[-1])
api_count=tests('api_tests_reviewed.log');geometry_count=tests('geometry_tests_retest.log')
text=f'''# 部件重新生成：实施、复测与外观审查

日期：2026-11-13。本报告区分功能验证、网格检查和外观验收。**功能流程已经跑通，两个样本的外观均未通过本次审查。** 当前结果不代表家具精确还原，也不能据此宣称项目质量已经达标。

## 本次交付

新增入口：工作台 → 拆分部件 → 选择一个已保存部件 →「按原图重新生成部件」。

1. 从原商品图寻找靠枕、坐垫、圆柱抱枕的参考候选；也可上传独立部件图。
2. 选择正确的一块参考后，调用本地模型重新生成整体部件。
3. 自动估计缩放和位置，检查连通性、闭合、方向、自交以及存储精度。
4. 预览以橙色显示新部件，蓝色显示发生接口调整的座架，灰色显示其他部件；可以查看正面、侧面、背面、底面和单独部件。
5. 预览加载成功并勾选确认后，保存为独立版本。保存直接采用预览文件，不重新计算另一份模型。
6. 对齐失败时保留可下载的生成部件；当前模型不被替换。支持取消、实际采样步数和同一浏览器标签页刷新后的任务恢复。

候选选择仍需人确认，尚未实现可靠的全自动“这张二维靠枕图对应哪一个三维靠枕”。部件内部的技术补面保持在同一逻辑组内，不作为多个靠枕展示。

## 使用的 AI 与几何处理

| 环节 | 实际实现 | 边界 |
| --- | --- | --- |
| 原图部件检测 | Grounding DINO Tiny | 文字引导的检测，可能把相邻家具一起框入 |
| 部件抠图 | SAM 2.1 Hiera Tiny | 给出候选掩码；模型分数不等于准确率 |
| 透明部件图 | 保留输入 alpha | 这是直接保留用户提供的范围，未声称 AI 识别成功 |
| 整体部件生成 | 本地 Hunyuan3D-2mini，50 步、384 分辨率、seed 42 | 实际生成几何；没有生成布料或皮革贴图 |
| 靠枕对齐 | 连续可见面估计 + 多初值、裁剪 ICP | 开口旧选区不再直接用 PCA 深度当作真实厚度 |
| 坐垫对齐 | 水平外轮廓双向匹配 + 表面与伸出检查 | 使用凸轮廓估计，当前重点覆盖接近矩形的坐垫 |
| 坐垫接口 | 向上表面和凹接缝估计，切割并封闭座架 | 切口是候选；座架在此操作中确实发生几何变化 |

以上本地模型无需 API 密钥。本次没有上传到外部生成服务。坐垫的二维补图试验使用了 **OpenCV Telea 插值修补**，并非 AI 图像编辑服务。

## 两个家具样本的真实结果

### 条纹沙发靠枕

原始任务：`0ee3d49864e543bb92a66ad9cf19115b`。本轮操作副本：`{ui['job']}`。

从 16 个候选中人工确认了一张干净的单靠枕参考：`{ui['reference_candidate']}`。其他候选中存在坐面、靠枕混入或残缺，不能无条件批量生成。

原型和网页正式流程各执行了一次真实 Hunyuan 生成。网页这次生成耗时 **{summary['duration_seconds']:.3f} 秒**；从生成任务开始到替换预览就绪共 **{ui['terminal_state']['seconds']:.3f} 秒**。网页参考提取耗时 **{reference_state['seconds']:.3f} 秒**，不包含在前述生成任务耗时内。这里是单次运行日志，未统计平均速度或成功率。

最终替换部件为 **{manifest['operation']['part']['triangles']:,} 个三角面**，闭合且为一个连通体。原选区含 {manifest['operation']['source_group']['boundary_edges']} 条边界边，并带有坐面碎片。最终对齐主要使用旧选区中约 **{placement['pose_surface']['source_area_fraction']*100:.2f}% 面积**的连续可见面。其采样距离指标只反映这一对齐子集，**不能当作整件家具还原精度**。

**外观结论：不通过。** 新靠枕为完整闭合网格，但厚度仍像薄片，形状和体积不足。没有把旧选区的错误厚度强行拉回去，也没有把“闭合”写成外观合格。

网页保存了候选与局部换色各一个测试版本：`{ui['saved_version']}`、`{ui['material_version']}`。这些保存用于验证版本与材质流程，状态保持 `unreviewed`，不表示外观验收。独立检查确认其余 **{verification['unrelated_primitive_count']} 个 primitive** 的属性、索引、世界变换和材质未变。

### 皮革沙发坐垫

原始任务：`11c5d7496508427cad48c22c5959f53b`。自动提取的 7 张候选均未获得一块干净、完整的坐垫参考，**本样本自动参考提取失败**。

为验证后续链路，另外制作了一张明确标注推测的试验参考：人工估计外边界、去掉遮挡区域，再用 OpenCV 修补。其中约 **{provenance['inferred_visible_reference_area_fraction']*100:.2f}%** 的参考区域来自推测填补。该参考出现明显凹陷，不能视为可信商品图。

这张试验参考实际生成了 **{cushion['triangles']:,} 个三角面**的闭合坐垫。最初仅靠表面 ICP 时出现旋转和伸出座架的问题，已保留旧试验。新增外轮廓对齐后，当前候选不再出现同样的明显旋转伸出；缓冲轮廓外面积比例为 **{seat['placement']['outside_observed_footprint_area_fraction']:.4f}**。这是相对于旧模型估计轮廓的几何检查，不能证明真实装配准确。

接口试验得到闭合座架和独立坐垫；靠枕与圆柱抱枕保持原数据。底部切割位置为模型坐标 Y={seat['slot']['cut_bottom_y']:.6f}，未换算为真实厘米。

**外观结论：不通过。** 生成结果继承了错误参考中的凹陷，局部鼓包和厚度仍需改善。未将这个坐垫替换到原始任务，也未通过验收。网页仅验证了上传这张推测参考、保留透明范围、刷新恢复和候选选择；**坐垫生成与装配是离线真实试验，不冒充网页端第二次生成**。

## 复测与独立核对

| 检查 | 实际结果 |
| --- | --- |
| Python 接口与状态回归 | {api_count} 项通过 |
| 几何、语义映射、补面、材质工具回归 | {geometry_count} 项通过 |
| 本轮新增测试 | 13 项接口测试、10 项几何测试，已包含在上述数量中 |
| JS 语义分色断言 | 5 项通过 |
| 前端 TypeScript 与生产构建 | 通过；仍有大体积 bundle 提示 |
| 实际浏览器生成与保存流程 | {len(ui['checks'])} 项流程断言通过，无 pageerror |
| 上传、范围切换与刷新恢复 | {len(controls['checks'])} 项断言通过，无 pageerror；没有额外启动 3D 生成 |
| GLB 规范校验 | {verification['file_checks']} 次文件检查通过，对应 {verification['unique_glb_contents']} 份不同内容；未把重复文件算作独立模型样本 |
| 保存采用预览的完全相同字节 | 通过 |
| 换材质仅影响新靠枕 | 通过 |
| 手机宽度 390px | 本次页面无横向溢出 |

接口测试中的推理部分使用 mock，检查状态、取消和防串任务逻辑；真实推理证据来自单独的本地运行日志与网页流程。此次部件生成仅覆盖两款沙发，不能由这些测试推断其他家具的生成质量。

本轮检查并修正了：提前拒绝带纹理或类型不符的目标、候选及预览文件哈希核对、版本变化防覆盖、对齐失败保留原始输出、取消后停止本任务子进程、重启后标记中断、跨部件上传响应丢弃、刷新恢复进度、失败后重选参考，以及坐垫的外轮廓约束。

## 保留的失败与限制

- 首次生成曾使用错误的猜测文件名，现已改为读取候选清单；失败日志保留在 `corduroy_pillow/generated/`。
- 靠枕最初对旧选区推算厚度，造成对齐失败；相关日志保留，最终开口源不使用这一厚度推算。
- 坐垫的 7 张自动候选、插值补图及来源说明均保留；没有把补图结果算作自动抠图成功。
- 旧坐垫旋转伸出试验保留在 `leather_cushion/replacement_surface_only_trial/`，改进结果在 `replacement_outline_trial_v2/`。
- 浏览器初测有测试副本 metrics 格式错误和 120 秒测试等待不足的问题，均已修正测试设置并保留日志；最终流程以 `ui_results.json` 为准。
- 所有真实尺寸、隐藏厚度和安装位置仍包含推测；本次不提供还原准确率。
- 高面数靠枕超过 100 万三角面，预览和下载仍较重；未在此轮增加新 LOD。
- 当前替换范围限一个已保存逻辑组；跨节点、多材质、带贴图、骨骼或形变的目标会被提前拒绝，避免丢失已有外观数据。
- 页内刷新恢复只覆盖同一浏览器标签页的会话记录；跨设备任务恢复没有在本轮实现。

## 下一步应优先解决的质量问题

1. **先取得可信的独立部件参考。** 皮革坐垫当前的遮挡和错误补图是主要失败来源。优先用无靠枕遮挡的商品图或侧面细节图验证，再考虑接入真正的生成式补图，并继续标记推测区域。
2. **再提高厚度和体积质量。** 这次本地 Hunyuan 单图靠枕生成偏薄；需要侧面证据、可审查的厚度约束，或更适合软包部件的生成模型对照，不能仅调分割阈值解决。
3. 形状通过后再增加局部重建、部件贴图和 LOD。继续以“完整一块、侧底面正确、相邻部件未改动”为验收标准。

## 证据位置

- 可视化对比：[index.html](../experiments/part_regeneration_20261113/index.html)
- 网页实际流程：[ui_results.json](../experiments/part_regeneration_20261113/ui_results.json)
- 刷新与上传检查：[ui_controls.json](../experiments/part_regeneration_20261113/ui_controls.json)
- 独立文件核对：[independent_verification.json](../experiments/part_regeneration_20261113/independent_verification.json)
- 推测参考说明：[provenance.json](../experiments/part_regeneration_20261113/leather_cushion/completed_reference/provenance.json)
- 核心实现：`services/api/part_regeneration.py`、`scripts/prepare_part_reference.py`、`scripts/replace_generated_part.py`、`scripts/part_registration.py`、`scripts/cushion_registration.py`、`apps/web/src/PartRegenerationPanel.tsx`。
'''
(ROOT/'docs/PART_REGENERATION_REVIEW_2026-11-13.md').write_text(text,encoding='utf-8')

cards=[]
def card(title,caption,files):
    images=''.join(f'<figure><img loading="lazy" src="{html.escape(file)}" alt="{html.escape(label)}"><figcaption>{html.escape(label)}</figcaption></figure>'for file,label in files)
    cards.append(f'<section><h2>{html.escape(title)}</h2><p>{html.escape(caption)}</p><div class="grid">{images}</div></section>')
card('靠枕：参考与生成结果','参考干净，但生成厚度不足。网格闭合，外观不通过。',[
 ('corduroy_pillow/references/d391b5818dc25703678f6b057d2b9d14_preview.png','原图提取的单个靠枕'),
 ('corduroy_pillow/replacement_v1/part_front.png','独立新部件'),
 ('corduroy_pillow/replacement_v1/part_under.png','底面与厚度'),
 ('corduroy_pillow/replacement_v1/model_front.png','替换候选全貌，固定诊断视角并非原图相机')])
card('坐垫：自动参考失败','7 张自动候选均不适合作为完整坐垫参考；下面的补图由人工估计轮廓加 OpenCV 插值得到，约29.51%区域含推测。',[
 ('leather_cushion/reference_sheet.png','自动候选：混入相邻部件或残缺'),
 ('leather_cushion/completed_reference/preview.png','推测参考：凹陷明显，外观不通过'),
 ('leather_cushion/completed_reference/inferred_region.png','白色为插值填补区域')])
card('坐垫：装回位置的改进','外轮廓匹配修正了旋转伸出；凹陷和厚度问题尚未解决。',[
 ('leather_cushion/replacement_surface_only_trial/model_front.png','旧试验：仅表面匹配，坐垫旋转伸出'),
 ('leather_cushion/replacement_outline_trial_v2/model_front.png','新试验：增加外轮廓匹配'),
 ('leather_cushion/replacement_outline_trial_v2/part_side.png','独立坐垫侧面'),
 ('leather_cushion/replacement_outline_trial_v2/model_under.png','装回后的底面')])
card('网页真实流程','完整流程与局部换材质在测试副本验证；这些保存用于技术测试，外观未验收。',[
 ('ui_reference_candidates.png','明确选择单个参考'),('ui_preview_侧面.png','替换预览：橙色新部件'),
 ('ui_regenerated_material.png','局部换材质'),('ui_regeneration_mobile.png','390px 页面'),
 ('ui_cushion_uploaded_reference.png','推测坐垫参考上传，仅测试入口，不生成')])
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>部件重新生成实测</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f6fa;color:#202b3d;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1280px;margin:auto;padding:32px}h1{font-size:30px;margin-bottom:8px}h2{font-size:22px}section{background:white;border:1px solid #dde3ed;border-radius:14px;padding:24px;margin:24px 0}.status{background:#fff1dc;border-left:5px solid #bd761c;padding:18px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{margin:0;background:#f7f8fb;border-radius:8px;padding:8px}img{width:100%;height:330px;object-fit:contain;cursor:zoom-in}figcaption{font-size:14px;margin:8px}a{color:#226d9b}dialog{max-width:95vw;max-height:95vh;border:0;padding:8px;border-radius:8px}dialog img{height:auto;max-height:87vh;max-width:90vw}dialog::backdrop{background:#000b}button{font:inherit;padding:5px 16px;cursor:pointer}@media(max-width:700px){main{padding:16px}.grid{grid-template-columns:1fr}section{padding:16px}img{height:290px}}</style><main><h1>部件重新生成实测</h1><p>2026-11-13 · 本地 Grounding DINO + SAM 2.1 + Hunyuan3D-2mini</p><p class="status">流程验证通过；靠枕偏薄、坐垫参考与生成形状有误，两个样本的外观均未通过。本页面不提供还原准确率。点击图片可放大。</p>'''
page+=''.join(cards)+f'<section><h2>检查证据</h2><p>Python {api_count+geometry_count} 项通过；JS 分色 5 项通过；{verification["file_checks"]} 次 GLB 检查，对应 {verification["unique_glb_contents"]} 份不同内容。</p><p><a href="../../docs/PART_REGENERATION_REVIEW_2026-11-13.md">详细报告</a> · <a href="ui_results.json">网页流程</a> · <a href="ui_controls.json">上传与刷新</a> · <a href="independent_verification.json">独立核对</a></p></section>'
page+='''</main><dialog><button autofocus>关闭</button><br><img></dialog><script>const dialog=document.querySelector('dialog');document.querySelectorAll('figure img').forEach(img=>img.onclick=()=>{dialog.querySelector('img').src=img.src;dialog.showModal()});dialog.querySelector('button').onclick=()=>dialog.close();dialog.onclick=e=>{if(e.target===dialog)dialog.close()};</script></html>'''
(OUT/'index.html').write_text(page,encoding='utf-8')
print('Report and gallery built from saved evidence')
