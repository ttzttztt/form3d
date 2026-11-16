"""Build a review with measured counts and explicitly separated inference/repair."""
import html,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/soft_part_quality_20261113'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
ai=read(OUT/'ui_results.json');seat=read(OUT/'ui_source_result.json');verification=read(OUT/'verification.json');guard=read(OUT/'reference_guard.json')
chair=read(OUT/'additional_guard_case.json')
assert not ai.get('failure')and not seat.get('failure')and not guard.get('failure')
a=ai['terminal_state']['operation'];b=seat['operation']
ai_folder=ROOT/'.data/jobs'/ai['job']/'part_regenerations'/ai['regeneration_id'];seat_folder=ROOT/'.data/jobs'/seat['job']/'part_regenerations'/seat['task']
inference=read(ai_folder/'generated/local_summary.json');cpu=read(seat_folder/'status.json');aux=read(OUT/'mochi_pillow_generated/local_summary.json')
old=read(ROOT/'experiments/part_regeneration_20261113/ui_results.json')['terminal_state']['operation']
def tests(name):
    text=(OUT/name).read_text(encoding='utf-8');matches=re.findall(r'Ran (\d+) tests',text)
    assert matches and re.search(r'\nOK\s*$',text),name
    return int(matches[-1])
api=tests('api_reviewed.log');geometry=tests('geometry_reviewed.log')
review={
 'overall':'improved_editable_candidates; physical product resemblance not accepted',
 'pillow':{'closed_complete_group':True,'paper_shell_problem_improved':True,'fine_shape_and_fabric':'not accepted','hidden_shape':'source-constrained estimate'},
 'seat':{'closed_complete_group':True,'pillow_remnants_and_deep_voids_removed':True,'inferred_roof_area_fraction':b['surface_repair']['occluded_roof_area_fraction'],'tufting_edge_shape_and_material':'not accepted'},
 'unrelated_parts':'byte-level attribute/index/material/world-transform checks passed',
 'review_evidence':['pillow_rebuilt_v3/part_front.png','pillow_rebuilt_v3/part_under.png','pillow_rebuilt_v3/model_back.png','seat_rebuilt_v3/part_front.png','seat_rebuilt_v3/part_side.png','seat_rebuilt_v3/part_under.png','seat_rebuilt_v3/diagnostic_front.png'],
}
(OUT/'visual_review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
report=f'''# 软包部件体积与遮挡修复：本轮实测

日期：2026-11-13。**靠枕薄壳和坐垫残洞已有明显改善，可作为继续编辑的完整部件候选；精细造型和实物还原仍未通过最终验收。** 原始任务未提交替换，本轮保存与换材质均在新测试副本进行。

## 改进结果

| 样本 | 上轮问题 | 本轮结果 | 尚未解决 |
| --- | --- | --- | --- |
| 条纹沙发靠枕 | 整体是一张弯曲薄壳，拉伸只会加大弯曲 | 按旧模型前后表面重建体积，单一闭合实体，{a['part']['triangles']:,} 面 | 轮廓采用凸包估计，折痕和边缘仍不够自然，布料未恢复 |
| 皮革沙发坐垫 | 自动抠图不完整；错误补图导致凹陷；旧几何也带靠枕残洞 | 按已有接缝拆出，排除靠枕/抱枕范围后重建顶面，{b['part']['triangles']:,} 面 | 顶面约 {b['surface_repair']['occluded_roof_area_fraction']*100:.2f}% 为遮挡区推测，皮革拉扣、边缘圆润度尚不准确 |

两块部件在实际导出 GLB 中均为一个闭合连通体，绕序一致，自交检查为 0。坐垫的蓝色、橙色区域和底面虽由不同 primitive 存储，界面仍作为同一个逻辑部件选择、导出与换材质，未拆成多个小坐垫。

## 靠枕：修复弯曲薄壳

本轮确认：Hunyuan 生成的薄壳具有弯曲，PCA 总厚度并不等于实体内部厚度，直接沿法线拉伸仍会得到鼓起的薄片。

现在先从旧模型的连续可见面和相对一侧表面寻找配对，检查覆盖率、空间分布和厚度离散程度。该样本得到 {a['placement']['thickness_constraint']['paired_samples']} 对样本，匹配可见样本占比约 {a['placement']['thickness_constraint']['paired_visible_sample_fraction']*100:.2f}%，旧模型核心间距为 {a['placement']['thickness_constraint']['core_thickness_source_units']:.6f} 个模型坐标单位。**这不是实物厚度测量。**

只有证据满足约束且候选被判定为薄壳时，才使用前后高度场和 AI 候选轮廓重建完整体积。缺少配对证据时不会自动拍定一个厚度；仍为弯曲薄壳的输出会被拒绝，原始生成件保留下载入口。

本轮网页实际再次执行了一次 Hunyuan3D-2mini 推理，耗时 {inference['duration_seconds']:.3f} 秒，之后执行 CPU 对齐与体积重建；从任务开始到替换预览就绪共 {ai['terminal_state']['seconds']:.3f} 秒。**最终 {a['part']['triangles']:,} 面的部件包含几何重建，并非声称 AI 本身直接生成了正确的厚靠枕。**

相对上轮最终 {old['part']['triangles']:,} 面的候选，本轮面数减少约 {(1-a['part']['triangles']/old['part']['triangles'])*100:.2f}%。这是重建带来的简化，也会损失细节；没有测试或宣称帧率提升。

## 坐垫：按原形修复遮挡与接缝

新增入口：工作台 → 拆分部件 → 选择「坐面与主体」→「修复或重新生成部件」→ **沿接缝拆出完整坐垫**。

这条路线不调用 Hunyuan 推理，也不依赖上一轮失败的 OpenCV 补图：

1. 从已有坐面与座架分组估计接缝并切开，补齐接口。
2. 使用已有 AI 逻辑分组中的靠枕、圆柱抱枕投影，自动排除其遮挡范围。
3. 检测到残洞或异常下陷后，用剩余顶面观测重建坐垫；遮挡过多或可用顶面不足时拒绝。
4. 未遮挡区域也会重新采样，蓝色表示“有旧模型支持的重建面”，**不是逐三角面原样保留**。橙色表示遮挡区域与底面的推测补全。

本样本使用 {b['surface_repair']['known_roof_observation_faces']:,} 个有效顶面三角面，未遮挡顶面的高度插值误差 p95 为 {b['surface_repair']['known_roof_height_error_p95_source_units']:.6f} 个模型单位；该指标只衡量重建相对旧模型的偏差，不代表实物精度。遮挡区顶面比例约 {b['surface_repair']['occluded_roof_area_fraction']*100:.2f}%。这次源模型修复任务耗时 {cpu['seconds']:.3f} 秒，仅是单次实测，未统计平均速度。

座架在接缝以下保留，新增切口并封闭。重建坐垫会改变上半部分体积，因此报告中的切分体积守恒仅针对**补洞前的初始切割**，不用于证明最终坐垫与旧形状完全一致。

## 新参考图负例与保护

还实际测试了 `images/0508_Mochi Sofa Pillow.png`，原图仅 150×150。CLI 诊断运行了 Hunyuan 推理，耗时 {aux['duration_seconds']:.3f} 秒，结果后方出现明显体块，细节与真实结构无法确认，**未作为合格部件采用，也未装到原沙发上**。

据此增加参考检查：有效前景任一边不足 96 像素时，网页在启动 3D 推理前拒绝，并提示换高清部件图。不是只检查画布大小；实际 API 测试中，600×600 透明画布里仅 70×80 的主体也被拒绝，当前模型版本不变。该阈值不能保证大图一定合格；上采样也不等于获得真实细节。

## 验证、review 与保存状态

| 检查 | 结果 |
| --- | --- |
| Python 接口与状态回归 | {api} 项通过 |
| 几何、语义映射、补面、材质与结构回归 | {geometry} 项通过 |
| Python 合计 | {api+geometry} 项，新增 11 项包含在内 |
| JS 分色状态 | 5 项通过 |
| 前端构建 | 通过；仍有 bundle 体积提示 |
| 网页靠枕完整生成、预览、保存、换材质 | {len(ai['checks'])} 项流程断言通过，无 pageerror |
| 网页坐垫修复、四向预览、导出、保存、换材质 | {len(seat['checks'])} 项流程断言通过，无 pageerror |
| 小前景拒绝检查 | {len(guard['checks'])} 项实际 API 断言通过 |
| GLB 规范校验 | {verification['file_checks']} 次文件检查，通过；对应 {verification['unique_file_contents']} 份不同文件内容 |
| 保存文件与预览完全相同 | 两个样本均通过 |
| 其他部件属性、索引、变换与材质保持一致 | 靠枕样本 6 个 primitive、坐垫样本 4 个 primitive，通过 |
| 换材质只作用于选中的完整逻辑部件 | 两个样本均通过，坐垫覆盖全部 3 个技术 primitive |
| 390px 手机宽度 | 本次页面无横向溢出 |

接口状态测试中的推理采用 mock；真实推理证据来自单独的网页运行与 CLI 负例。坐垫源模型修复使用真实几何 worker，未冒充 AI 推理。20 次文件检查不等于 20 个家具样本，本轮主要复测两款沙发，另有一个小图诊断负例。

额外对一把实际扶手椅进行只读保护检查：由于“{chair.get('reason','')}”，新修复路线拒绝继续，源文件哈希保持一致。这个结果验证拒绝条件，**不算椅子修复成功**，证据见 `additional_guard_case.json`。

review 还修正了：平面匹配把靠枕薄边当正面而放大的情况、初版高度场三角化造成的绕序/自交问题、修复请求被更改时的拒绝、来源哈希绑定、取消与 CPU 锁释放。失败日志和中间候选保留在本轮目录。

## 验收结论与使用范围

完整部件、闭合、侧底面存在、整件换材质和其他部件不被误改：**本轮通过技术检查，可继续编辑。** 靠枕已经有体积，坐垫不再带着明显的靠枕残洞。

精细外观与实物一致性：**仍未通过最终商品验收。** 靠枕轮廓和折痕、坐垫拉扣与圆润边缘、布料/皮革材质仍需改进。旧三维模型自身的不准会传递到本轮；全模型其他分组中的残片没有在本轮一并修复。当前保守支持静态、无贴图且接近矩形的软包，不能据此推广为任意家具自动精确拆分。

两个网页副本：

- 靠枕：[{ai['job']}](http://127.0.0.1:8001/?job={ai['job']})
- 坐垫：[{seat['job']}](http://127.0.0.1:8001/?job={seat['job']})

保存版本分别为 `{ai['saved_version']}` 和 `{seat['saved_version']}`，均保持 `unreviewed`。这是功能验证保存，不自动替用户完成实物验收。

## 证据文件

- [四向结果与前后对比](../experiments/soft_part_quality_20261113/index.html)
- [网页 AI 流程](../experiments/soft_part_quality_20261113/ui_results.json)
- [网页坐垫修复](../experiments/soft_part_quality_20261113/ui_source_result.json)
- [独立文件与相邻部件检查](../experiments/soft_part_quality_20261113/verification.json)
- [外观审查记录](../experiments/soft_part_quality_20261113/visual_review.json)
- [小前景拦截](../experiments/soft_part_quality_20261113/reference_guard.json)

主要实现：`scripts/observed_thickness.py`、`scripts/soft_part_repair.py`、`scripts/part_registration.py`、`scripts/replace_generated_part.py`、`services/api/part_regeneration.py`、`apps/web/src/PartRegenerationPanel.tsx`。
'''
(ROOT/'docs/SOFT_VOLUME_REVIEW_2026-11-13.md').write_text(report,encoding='utf-8')
sections=[]
def block(title,caption,images):
    figures=''.join(f'<figure><img loading="lazy" src="{html.escape(file)}" alt="{html.escape(label)}"><figcaption>{html.escape(label)}</figcaption></figure>'for file,label in images)
    sections.append(f'<section><h2>{html.escape(title)}</h2><p>{html.escape(caption)}</p><div class="grid">{figures}</div></section>')
block('靠枕：从薄壳到有体积的一块','AI 轮廓 + 旧模型前后表面约束 + 几何重建。完整性改善，折痕与轮廓仍需对照实物。',[
 ('../part_regeneration_20261113/corduroy_pillow/replacement_v1/part_under.png','上轮：弯曲薄壳'),('pillow_rebuilt_v3/part_under.png','本轮：补出完整体积'),
 ('pillow_rebuilt_v3/part_front.png','本轮正面候选'),('pillow_rebuilt_v3/model_back.png','装回原沙发；其余分组的旧残片仍存在')])
block('坐垫：去掉靠枕残洞，遮挡处明确标为推测',f'按已有几何重建，约 {b["surface_repair"]["occluded_roof_area_fraction"]*100:.1f}% 顶面范围缺少可靠观测。蓝色为有旧模型支持的重建面，橙色为推测。',[
 ('leather_seat/part_front.png','中间试验：仅封底，仍有靠枕残洞'),('seat_rebuilt_v3/part_front.png','本轮：顶面修复候选'),
 ('seat_rebuilt_v3/part_side.png','侧面厚度'),('seat_rebuilt_v3/part_under.png','底面'),('seat_rebuilt_v3/diagnostic_front.png','遮挡与底面推测分色'),('seat_rebuilt_v3/model_front.png','装配候选')])
block('网页完整流程','实际生成、修复、保存和整块换材质都在测试副本执行；原任务保留。',[
 ('ui_preview_侧面.png','靠枕四向预览'),('ui_seat_正面.png','坐垫推测区域预览'),('ui_regenerated_material.png','仅新靠枕换色'),('ui_seat_material.png','整块坐垫换色')])
block('额外负例：小图不等于可用的部件参考','150×150 原图，后方体块与真实结构无法确认，本轮未采用。现已增加有效前景不足 96px 的提前拦截。',[
 ('../../images/0508_Mochi Sofa Pillow.png','原始小图：150×150'),('mochi_pillow_generated/model_front.png','实际生成诊断，未验收')])
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>软包体积与遮挡修复实测</title><style>*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#213047;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1280px;margin:auto;padding:32px}h1{font-size:30px}h2{font-size:22px}.status{padding:20px;background:#fff1da;border-left:5px solid #bd7317}section{background:#fff;border:1px solid #dde5ef;border-radius:14px;padding:24px;margin-top:24px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{background:#f7f8fc;margin:0;padding:10px;border-radius:8px}figure img{width:100%;height:330px;object-fit:contain;cursor:zoom-in}figcaption{font-size:14px;margin-top:8px}a{color:#226b91}dialog{border:0;border-radius:8px;max-width:95vw;max-height:95vh}dialog img{max-width:90vw;max-height:86vh}dialog::backdrop{background:#000b}button{font:inherit;padding:6px 16px}@media(max-width:700px){main{padding:16px}.grid{grid-template-columns:1fr}section{padding:16px}figure img{height:280px}}</style><main><h1>软包体积与遮挡修复实测</h1><p>2026-11-13 · 两款沙发复测 + 一个小图负例</p><p class="status">靠枕不再是薄壳，坐垫残洞已修复。完整性与编辑流程通过检查；细节、隐藏形状与实物一致性仍未通过最终验收。点击图片放大。</p>'''
page+=''.join(sections)+f'<section><h2>真实检查记录</h2><p>Python {api+geometry} 项通过；网页流程 {len(ai["checks"])+len(seat["checks"])} 项断言通过；GLB 文件检查 {verification["file_checks"]} 次，对应 {verification["unique_file_contents"]} 份不同内容。</p><p><a href="../../docs/SOFT_VOLUME_REVIEW_2026-11-13.md">详细报告</a> · <a href="verification.json">独立核对</a> · <a href="visual_review.json">外观判断</a></p></section>'
page+='''</main><dialog><button autofocus>关闭</button><br><img></dialog><script>const dialog=document.querySelector('dialog');document.querySelectorAll('figure img').forEach(img=>img.onclick=()=>{dialog.querySelector('img').src=img.src;dialog.showModal()});dialog.querySelector('button').onclick=()=>dialog.close();dialog.onclick=e=>{if(e.target===dialog)dialog.close()};</script></html>'''
(OUT/'index.html').write_text(page,encoding='utf-8');print('Soft-part report and gallery built')
