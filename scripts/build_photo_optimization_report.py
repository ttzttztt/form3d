# -*- coding: utf-8 -*-
"""Publish measured evidence, including refused and superseded trials."""
import html,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/photo_guided_parts_20261113'
read=lambda path:json.loads(path.read_text(encoding='utf-8'))
cases=read(OUT/'cases.json');verification=read(OUT/'verification.json');uis={c['case']:read(OUT/(c['case']+'_ui.json'))for c in cases}
center=uis['corduroy_center'];seat=uis['leather_seat'];side=uis['corduroy_side']
detail=seat['terminal_state']['operation']['surface_repair']['photo_supported_details']if'photo_supported_details'in seat['terminal_state']['operation']['surface_repair']else seat['terminal_state']['operation']['surface_repair'].get('detail_evidence',{})
# Read the owning metadata key rather than assuming a result count.
repair=seat['terminal_state']['operation']['surface_repair']
detail=next((v for v in repair.values()if isinstance(v,dict)and'dimple_candidates'in v),{})
assert detail
api_log=(OUT/'full_api_final.log').read_text(encoding='utf-8');geo_log=(OUT/'full_geometry_final.log').read_text(encoding='utf-8')
assert re.search(r'\nOK\s*$',api_log)and re.search(r'\nOK\s*$',geo_log)
api=int(re.search(r'Ran (\d+) tests',api_log)[1]);geo=int(re.search(r'Ran (\d+) tests',geo_log)[1])
generation=read(ROOT/'.data/jobs'/center['job']/'part_regenerations/d28da45342a242ed9558f2f2df91da2a/generated/local_summary.json')
percent=lambda value:f'{value*100:.2f}%'
table=[]
for c in cases:
    row=next(r for r in verification['cases']if r['case']==c['case']);ui=uis[c['case']]
    check=row.get('checks');score=f"{percent(check['part_silhouette_iou_before'])} → {percent(check['part_silhouette_iou_after'])}"if check else'对应不确定，未生成替换'
    table.append(f"| {c['part_name']} · {c['case']} | {'完整可编辑候选'if check else'需要确认'} | {score} | {format(row['part_triangles'],',') if check else'—'} |")
keep=read(OUT/'keep_result.json')if(OUT/'keep_result.json').exists()else None
if keep:assert not keep.get('failure'),keep
keep_note='实际 API 复测已闭合的坐垫，自动选择 keep；不运行新 Hunyuan 推理，直接保存请求返回 409，版本保持不变。'if keep else'保留路线已实现并通过几何与接口测试；本轮未新增整条保留路线的真实 API 记录。'
report=f'''# 原图约束与自动部件优化：本轮实现、review 与实测

日期：2026-11-13。服务：[本地工作台](http://127.0.0.1:8001)。

五项功能已经接入。两条真实网页流程得到完整、可继续编辑的部件候选；侧面靠枕因照片对应证据不足被拒绝，另有一把扶手椅通过只读拒绝检查。**这些结果没有通过最终商品外观验收。**

## 1. 五项分别做了什么

| 项目 | 实现与边界 |
| --- | --- |
| 原图约束轮廓 | 将当前三维逻辑组投影到原图，结合真实分割参考，保留非凸边界；在旧模型有成对深度证据时，使用照片轮廓与前后高度场重建。强侧向、碎散或缺少厚度证据时不强行拉伸。 |
| 自动选择方式 | 选择一个已保存逻辑部件后，一键分析，分流到保留、已有接缝局部修复、原图轮廓重建、Hunyuan 重生成或需要补充信息。保留也检查单体、闭合、绕序、正体积与自交。 |
| 自动对应照片与部件 | 近似整件相机拟合 + 每像素深度可见性 + 原图部件候选位置/轮廓对应；必要时以投影正点和邻件负点驱动 SAM 精分。相近实例和脏掩码会降低或拒绝对应。不是只按名称、候选序号或检测分数选参考。 |
| 软包细节 | 支持前后表面体积、软边；坐垫边缘弧度要有足够旧表面支持，凹点需同时有旧几何下陷与照片暗点支持。当前坐垫没有可靠圆角半径，未补造缝线或纽扣。 |
| 同视角验收 | 原图 / 优化前 / 优化后使用同一投影，显示对应叠图、四面预览及推测区域；前后轮廓检查失败时，页面和直接 API 均不允许采用。原图、分割、模型、范围或预览证据变化后需要重做。 |

局部轮廓重建算法已接入并有几何回归覆盖，但本轮真实靠枕样本缺少可靠的成对旧表面，正式成功案例走的是 Hunyuan 路线，**不能把它报告成照片轮廓局部重建已在这些靠枕上成功**。

{keep_note}

## 2. 实际用了哪些 AI

- 部件检测：本地 **Grounding DINO Tiny**。
- 图片分割与投影辅助精分：本地 **SAM 2.1 Hiera Tiny**。
- 缺失部件形状生成：本地 **Hunyuan3D-2mini**，仅形状，无生成纹理。
- 原图与三维对应、厚度、接缝、补面和检查：几何与图像计算，不是新增的语义大模型。

无需商业 API 密钥。中间靠枕本轮真实运行一次 Hunyuan：50 步、384 分辨率、seed 42，worker 单次耗时 {generation['duration_seconds']:.3f} 秒；不是平均性能数据。修正投影后复测时，复用这一次相同参考字节生成并校验过的原始形状，重新做装配与照片检查，未冒称第二次推理。缓存只复用已校验的二维提案或原始几何，不复用三维对应、姿态或验收结论。

皮革坐垫没有运行 Hunyuan；它按旧模型接缝和剩余顶面修复，分割使用真实本地模型。

## 3. 正式结果

| 样本 | 结果 | 当前视角轮廓 IoU | 拆出部件三角面 |
| --- | --- | --- | --- |
{chr(10).join(table)}

中间靠枕旧分组有 13 个连通片，且未闭合；新候选是 1 个闭合、正体积实体，自交面为 0。细边仍有起伏，隐藏面由模型推测，不能认定真实厚度或折痕已恢复。当前靠枕有约 76 万面，网页预览明显较重；高面数不代表更接近实物。

皮革坐垫拆为一个完整逻辑部件，内部仍有 3 个技术 primitive，换材质覆盖全部 3 个。约 {percent(repair['occluded_roof_area_fraction'])} 的顶面范围属于遮挡区推测；底面也是推测接口。{len(detail['dimple_candidates'])} 个凹点候选得到旧几何与照片的共同支持，但**没有被认定为真实纽扣**。可靠圆角半径为 null，缝线未恢复。底面已补齐，但弧度与真皮拉扣细节仍未达到原图质量。

两条成功流程的 IoU 都略有下降，**没有轮廓准确率提升的证据**。当前采用门槛为 `优化后 IoU ≥ max(0.65, 优化前 IoU − 0.03)`，允许最多 3 个百分点的小幅下降，因此它们只被允许作为人工待审候选保存。该门槛没有为本轮结果临时放宽。

整件相机拟合 IoU：灯芯绒 {percent(center['terminal_state']['photo_checks']['camera_silhouette_iou'])}，皮革 {percent(seat['terminal_state']['photo_checks']['camera_silhouette_iou'])}。这些都是近似单视角轮廓拟合；未做相机标定、实物测量或独立多视角验证。照片同时参与约束与比较，所有分数都不能解释为实物还原准确率。

右侧“靠枕 1”的投影与原图对应仍不足，自动停止在 needs_input。系统没有错误采用左侧靠枕参考，也没有替换模型。另测真实扶手椅时，因坐面与座架分组未闭合而拒绝，文件哈希不变；该椅子不算修复成功。

## 4. Review 发现并修正的问题

1. 历史选图曾把左侧靠枕参考用于右侧“靠枕 1”。现用原图坐标和投影自动对应，不再仅凭干净候选外观选图。
2. 原来的多三角轮廓填充使用偶奇规则，重叠的正背面可能互相抵消。已改为三角面并集，并增加闭合盒子的回归；相机拟合重新计算，旧拟合分数作废。
3. 原先按三角中心深度绘制会把底面错误画到顶面前面。已改为逐像素、透视正确的深度缓冲，并测试绘制顺序不影响可见性。
4. 分割参考有邻件残片、孔洞或重复变体时，不能把检测分数当对应准确率；现检查主连通片、孔洞、边界复杂度和不同实例间隔。部件不可见时直接拒绝。
5. 未闭合坐垫或圆柱抱枕不能默认视为健康部件；强侧向或缺少源表面的靠枕会重新生成或停止，不降低原有面积/厚度保护。
6. 原图、整件分割和所有照片对照文件绑定到候选；取消、GPU 等待、请求变化及异常 worker 退出都有终态，避免一直等待。无可靠整件轮廓的杂乱背景不会悄悄下载 rembg 权重。
7. 有透明背景的整件图片不再直接被当成“已经独立的一个部件”；自动入口仍执行部件检测。

首轮靠枕生成期间发现投影问题，该试验被取消；生成的原始文件保留，未用于旧分数验收。首轮坐垫任务在更新服务时中断，随后重新跑完整流程。相关日志在 `superseded_v1/` 与原任务目录中保留。早期 `*_auto_v1`、`additional_pillows.json` 等诊断结果不计入正式验收，最终数据以本报告链接的 JSON 为准。

## 5. 测试与独立文件检查

| 检查 | 本轮结果 |
| --- | --- |
| Python API / 状态 / 来源保护回归 | {api} 项通过 |
| Python 几何 / 分组 / 材质 / 照片计算回归 | {geo} 项通过 |
| Python 合计 | {api+geo} 项通过 |
| JS 逻辑分色 | 5 项通过 |
| TypeScript + 生产构建 | 通过，仍有 bundle 体积提示 |
| 两条真实网页成功流程 | 各 8 类断言通过，四方向预览、导出、显式保存、换材质、390px 宽度均测试 |
| 右侧靠枕保护流程 | 5 类断言通过，直接保存被拒绝，源版本未变 |
| 浏览器 pageerror | 三条正式网页流程均为 0 |
| 独立 GLB 规范检查 | {verification['file_checks']} 次文件检查，{verification['unique_file_contents']} 份不同字节内容；零错误、零警告 |
| 无关部件 | 靠枕 6 个 primitive、坐垫 4 个 primitive 的属性、索引、世界变换、材质一致 |
| 采用文件 | 两个样本保存字节与预览完全一致，编辑状态仍为 unreviewed |
| 材质范围 | 仅目标完整逻辑组变化，相邻部件材质不变 |

单元测试中的 AI worker 使用 mock；真实推理与真实分割记录单独保留，不能用测试数量代替真实家具数量。14 次文件校验也不等于 14 款家具。网页自动化勾选确认框只为测试保存流程，不代表用户已认可实物外观。四向 Blender 图是斜前、侧向、斜后、底部；与网页四方向检查一并用于检查残缺。

## 6. 如何使用与下一步边界

打开模型，在“拆分部件”里点选一个已保存的完整逻辑组，展开“修复或重新生成部件”，点击“自动分析并优化部件”。先查看照片对应和前后对照，再旋转检查侧面、背面、底面。只有允许采用的候选才能勾选确认并保存，旧版本保留。

- [中间靠枕副本](http://127.0.0.1:8001/?job={center['job']})：已保存几何与局部换色测试版本，仍为待审。
- [坐垫副本](http://127.0.0.1:8001/?job={seat['job']})：已保存完整坐垫与局部换色测试版本，仍为待审。
- [右侧靠枕拒绝副本](http://127.0.0.1:8001/?job={side['job']})：原版本保留。

目前只保守支持已有逻辑归组的静态、无贴图软包。带贴图、顶点颜色、动画、镜像节点或跨节点等情况会拒绝自动替换，避免损坏原资产。原图看不见的厚度、背面与连接结构无法从单图验证；其他分组已有的残片也没有在本轮自动消失。高面数靠枕需要后续保形简化；更准确的厚度与圆角需要侧面/背面图或更可靠的局部三维生成。**本轮完成的是五项功能接入和保守验收流程，项目整体的商品级自动还原尚未完成。**

## 证据与实现

- [可放大图片与完整结果页](../experiments/photo_guided_parts_20261113/index.html)
- [独立核验 JSON](../experiments/photo_guided_parts_20261113/verification.json)
- [靠枕网页记录](../experiments/photo_guided_parts_20261113/corduroy_center_ui.json)、[坐垫网页记录](../experiments/photo_guided_parts_20261113/leather_seat_ui.json)、[拒绝记录](../experiments/photo_guided_parts_20261113/corduroy_side_ui.json)
- [额外扶手椅保护](../experiments/photo_guided_parts_20261113/additional_chair_guard.json)
- [API 回归日志](../experiments/photo_guided_parts_20261113/full_api_final.log)、[几何回归日志](../experiments/photo_guided_parts_20261113/full_geometry_final.log)
- 主要实现：`services/api/part_optimization.py`、`services/api/part_regeneration.py`、`scripts/photo_part_evidence.py`、`scripts/auto_part_optimization.py`、`scripts/refine_photo_part.py`、`scripts/soft_surface_details.py`、`apps/web/src/PartRegenerationPanel.tsx`。
'''
(ROOT/'docs/PHOTO_GUIDED_PARTS_REVIEW_2026-11-13.md').write_text(report,encoding='utf-8')

cards=[]
names={'corduroy_center':'中间靠枕 · 完整候选','leather_seat':'皮革坐垫 · 局部修复','corduroy_side':'右侧靠枕 · 拒绝替换'}
for c in cases:
    name=c['case'];ui=uis[name];images=[]
    if name!='corduroy_side':
        images.append(f'<img class="wide zoom" src="{name}_comparison.png" alt="原图、优化前、优化后同投影对比">')
        images.append('<div class="views">'+''.join(f'<figure><img class="zoom" src="delivery/{name}/part_{v}.png" alt="独立部件{label}"><figcaption>{label}</figcaption></figure>'for v,label in [('front','斜前'),('side','侧向'),('back','斜后'),('under','底部')])+'</div>')
        images.append(f'<p><a href="delivery/{name}/part.glb" download>下载独立部件</a> · <a href="delivery/{name}/model.glb" download>下载装配候选</a></p>')
    images.append(f'<details><summary>查看照片对应与网页</summary><img class="zoom wide" src="{name}_association.png" alt="照片对应，蓝线投影、绿线参考"><img class="zoom wide" src="{name}_desktop.png" alt="真实网页测试截图"></details>')
    reason=ui['terminal_state'].get('photo_checks',{}).get('reason',ui['terminal_state']['automatic_plan']['reason'])
    cards.append(f'<section data-case="{name}"><h2>{names[name]}</h2><p>{html.escape(reason)}；实物外观未最终验收。</p>'+''.join(images)+f'<p><a href="http://127.0.0.1:8001/?job={c["job"]}">打开工作台副本</a> · <a href="{name}_ui.json">流程证据</a></p></section>')
gallery='''<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>原图约束与自动部件优化 · 实测</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f5f8;color:#203047;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1240px;margin:auto;padding:26px 18px}h1{font-size:28px;line-height:1.4}h2{font-size:22px}section,.notice{background:white;border:1px solid #dfe6ee;border-radius:14px;padding:22px;margin:20px 0}.notice{border-left:5px solid #b77920}a{color:#155e91;overflow-wrap:anywhere}button{padding:8px 14px;margin:5px;border:1px solid #b9c7d7;border-radius:20px;background:white;color:#203047;cursor:pointer}button[aria-pressed=true]{background:#174a73;color:white}img{max-width:100%;height:auto;border-radius:8px}.wide{display:block;width:100%;margin:14px 0}.views{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}figure{margin:0}figcaption{text-align:center;color:#526176}.zoom{cursor:zoom-in}dialog{border:0;border-radius:12px;padding:8px;max-width:96vw;max-height:95vh;background:#f8fafc}dialog::backdrop{background:#101b2cc7}dialog img{display:block;max-width:92vw;max-height:84vh;object-fit:contain}dialog button{display:block;margin-left:auto}details{margin:16px 0}summary{cursor:pointer}section[hidden]{display:none}@media(max-width:650px){h1{font-size:23px}section,.notice{padding:14px}.views{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style><main><h1>原图约束与自动部件优化 · 2026-11-13</h1><div class="notice"><strong>两个完整可编辑候选，一个对应不确定而停止的靠枕。</strong><p>几何与换材质检查通过；当前轮廓 IoU 均略下降，细节和实物一致性尚未最终验收。隐藏面仍有推测。这里没有商品准确率数据。</p><a href="../../docs/PHOTO_GUIDED_PARTS_REVIEW_2026-11-13.md">详细报告</a> · <a href="verification.json">独立核验</a></div><nav aria-label="筛选样本"><button data-filter="all" aria-pressed="true">全部</button><button data-filter="corduroy_center" aria-pressed="false">中间靠枕</button><button data-filter="leather_seat" aria-pressed="false">皮革坐垫</button><button data-filter="corduroy_side" aria-pressed="false">拒绝样本</button></nav>'''+''.join(cards)+'''<section><h2>四向检查合图</h2><img class="zoom wide" src="four_view_contact_sheet.png" alt="两个独立部件的四方向实拍渲染合图"><p>Blender 中性材质渲染，材质纹理未生成。高面数靠枕仍有边缘起伏；坐垫圆角与拉扣细节未充分恢复。</p></section></main><dialog aria-label="放大证据图片"><button autofocus>关闭</button><img alt="放大的证据图片"></dialog><script>
const dialog=document.querySelector('dialog');document.querySelectorAll('.zoom').forEach(img=>img.addEventListener('click',()=>{dialog.querySelector('img').src=img.src;dialog.showModal()}));dialog.querySelector('button').onclick=()=>dialog.close();document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));document.querySelectorAll('[data-case]').forEach(s=>s.hidden=button.dataset.filter!=='all'&&s.dataset.case!==button.dataset.filter)});
</script></html>'''
(OUT/'index.html').write_text(gallery,encoding='utf-8')
visual={'physical_appearance_accepted':False,'reviewed_files':['four_view_contact_sheet.png','corduroy_center_comparison.png','leather_seat_comparison.png'],'findings':{'corduroy_center':'完整闭合候选，有厚度；边缘起伏，隐藏形状未验证；照片布纹未恢复。','leather_seat':'遮挡区和底面补齐；底面为推测面，圆角半径无可靠证据，拉扣与缝线未充分恢复。','corduroy_side':'对应不确定，保持原模型。'},'all_iou_are_image_metrics_not_physical_accuracy':True}
(OUT/'visual_review.json').write_text(json.dumps(visual,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'api_tests':api,'geometry_tests':geo,'total':api+geo,'files':verification['file_checks'],'unique_contents':verification['unique_file_contents'],'keep_actual_api':bool(keep)},ensure_ascii=False))
