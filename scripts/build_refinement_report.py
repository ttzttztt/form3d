# -*- coding: utf-8 -*-
"""Build this round's report from raw evidence, with explicit visual review limits."""
import html,json,re,shutil
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/selection_refinement_20261112'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
sam=read('sam_matrix.json');uv=read('uv_metrics.json');auto=read('auto_uv_runs.json');runs=read('structure_runs.json');delivery=read('delivery_browser.json');controls=read('controls.json');renders=read('external_renders.json')
assert len(sam['cases'])==8 and not sam.get('failure') and not delivery.get('failure') and not delivery['errors']
assert len(auto)==8 and all(c['status']==201 and c['exact_world_triangles'] and c['original_unchanged'] for c in auto)
assert all(c['snapshot']['status']=='awaiting_review' for c in runs)
labels={'round_table':'圆桌','alien_table':'外星人床头桌','official_chair':'官方椅子示例','accent_chair':'蓝色扶手椅','leather_sofa':'皮质沙发','corduroy_sofa':'灯芯绒沙发','white_cabinet':'拱顶展示柜','authored_bookcase':'代码书柜'}
notes={'round_table':'得到桌面可见区域候选；排除点可改变边界，未补齐桌面隐藏部分。','alien_table':'得到候选且有两个不同范围；未验证每个范围均对应独立语义部件。','official_chair':'本次固定点击得到 HTTP 409，未发布新选区；已有部件仍可直接选。','accent_chair':'保留、排除、再保留均得到非空结果；目测选中了坐垫附近的可见表面，仍有小缺口。','leather_sofa':'得到候选；追加排除点的实际状态与面数见下表及原始记录。','corduroy_sofa':'三个范围不同；范围增大不代表部件更完整或更准确。','white_cabinet':'初始候选覆盖了大部分柜体，分部件效果不足；追加排除点失败，原选区保留。','authored_bookcase':'二维掩码请求成功，但多视角三维一致性未通过，未发布选区。'}
samrows=[]
for c in sam['cases']:
    queries='；'.join(f"{q['label']}: HTTP {q.get('status','未提交')}, {q.get('faces',0):,} 面" for q in c['queries'])
    ranges=' / '.join(f"{r['range']} {r['faces']:,}" for r in c['range_faces']) or '无可用范围'
    samrows.append([labels[c['case']],f"{c['initial_faces']:,}",queries,ranges])
uvrows=[]
for c in uv:
    a=next(a for a in auto if a['case']==c['case']);p=a['operation']['parts'][0]
    uvrows.append([labels[c['case']],f"{c['box']['normalized_seam_length']:.3f}",f"{c['proxy']['normalized_seam_length']:.3f}",f"{c['box']['geometric_mean_anisotropy']:.3f} → {c['proxy']['geometric_mean_anisotropy']:.3f}",p['algorithm']])
generation=[]
balanced={'chair_triposr_structure':'95ef2dd6c99d4cacac90a6cf61ef8994','chair_hunyuan_structure':'6be16d93f7544ac79c5f09cb3be507fa','cabinet_hunyuan_structure':'212518024ebe4a4b9e4bd3543ee4a13c'}
for c in runs:
    b=balanced[c['case']];old=json.loads((ROOT/'.data/jobs'/b/'local_summary.json').read_text(encoding='utf-8'));new=json.loads((ROOT/'.data/jobs'/c['job']/'local_summary.json').read_text(encoding='utf-8'))
    assert old['input_sha256']==new['input_sha256']
    generation.append({'case':c['case'],'balanced_job':b,'structure_job':c['job'],'balanced_faces':old['triangles'],'structure_faces':new['triangles'],'balanced_worker_seconds':old['duration_seconds'],'structure_worker_seconds':new['duration_seconds'],'balanced_resolution':old['resolution'],'structure_resolution':new['resolution'],'same_processed_input_sha256':new['input_sha256'],'structure_steps':new.get('steps'),'status':c['snapshot']['status']})
def mdtable(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n'+'\n'.join('| '+' | '.join(map(str,row))+' |' for row in rows)
genrows=[[r['case'],f"{r['balanced_resolution']} → {r['structure_resolution']}",f"{r['balanced_faces']:,} → {r['structure_faces']:,}",f"{r['balanced_worker_seconds']:.2f} → {r['structure_worker_seconds']:.2f}",r['structure_job']] for r in generation]
tests={}
for name,file in [('api','api_final.log'),('part_tools','part_tools_final.log'),('advanced','advanced_final.log'),('furniture','furniture_final.log')]:
    content=(OUT/file).read_text(encoding='utf-8');count=re.search(r'Ran (\d+) tests?',content);assert count and re.search(r'^OK\s*$',content,re.M);tests[name]=int(count[1])
validation=read('gltf_validation.json');saved=read('saved_geometry_check.json');qa=read('report_qa.json')
assert len(validation)==12 and all(v['errors']==0 and v['warnings']==0 for v in validation)
summary={'generated_at':datetime.now().isoformat(timespec='seconds'),'python_tests':tests,'python_total':sum(tests.values()),'sam_initial_nonempty':sum(c['initial_faces']>0 for c in sam['cases']),'sam_cases':8,'uv_explicit_versions':17,'uv_auto_versions':len(auto),'external_renders':len(renders),'gltf_files_validated':len(validation),'saved_geometry_check':saved,'report_qa':qa,'generation':generation,'delivery_job':delivery['job'],'limits':'No measured semantic accuracy, photo resemblance, manufacturing fit or hidden-surface ground truth.'}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
for c in read('cases.json'):
    source=ROOT/'.data/jobs'/c['source_job']/'prepared.png'
    if source.exists():shutil.copyfile(source,OUT/('reference_'+c['case']+'.png'))
document=f'''# 多点选区、候选范围、边界检查、结构细节与 UV 验收

日期：2026-11-12。当前工作台：[http://127.0.0.1:8001](http://127.0.0.1:8001)。[图片与原始证据总览](../experiments/selection_refinement_20261112/index.html)。本轮不覆盖前两轮报告。

## 结论与验收边界

五项均已实现并完成本轮功能验收。部件选择可以继续用保留点、排除点和涂抹修正；范围切换复用候选；边界和 UV 接缝可显示；生成支持结构细节档位；UV 新增代理回传、圆形环绕及高面数自动保护。

外观质量只部分改善，不能标为任意家具商品级还原。八个固定家具样本中 {summary['sam_initial_nonempty']} 个得到非空初始候选；官方椅子示例和代码书柜本轮未得到可发布的一致选区。非空候选数不是语义分割准确率。柜子初始范围仍过大，排除点失败；失败记录已保留。

三次高细节实际推理均完成，状态为待审核，未自动验收。固定视角目测未见足以确认的细腿、孔洞显著改善。代理 UV 在四个样本上减少接缝长度、另四个增加；代码书柜虽略减接缝却明显拉伸。已加入高面数默认保护，不能一律推荐代理展开。

## 1. 实际改动与用法

| 功能 | 现在如何使用 | 保护与限制 |
| --- | --- | --- |
| 保留 / 排除点 | AI 辅助选区 → 点一个目标 → 不要这里排除串选 → 保留这里补选 | 每轮最多 24 点；多视角必须看见提示点；失败保留原提示与选区 |
| 小 / 中 / 大候选 | 在候选范围切换 | 同轮缓存，不重复请求 SAM；重复或无效范围禁用；不足三个很正常 |
| 边界检查与贴合 | 橙线检查范围；按需关闭贴合几何边界 | 只清理局部突出碎面、用已观察证据补单面平面缺口；可能误删细突起，不补不可见背面 |
| 结构细节档位 | 更多操作 → 同图本地引擎对照 → 结构细节 | 更慢、面数更高；不保证找回缺腿。Hunyuan 仍只生成灰色几何 |
| UV 连续性 | 换材质 → 曲面贴图与 UV 展开 | 支持精细图集、快速分区、代理和圆形环绕；蓝线显示接缝或开口边界 |

保存选区会创建新部件版本，换材质仍需显式保存。新增版本会清空旧提示点和缓存，避免旧面号进入新模型。涂抹、面选择撤销会终止旧 SAM 会话；清空提示点本身保留当前选区。

## 2. 模型和判断依据

仍使用本地 SAM 2.1 Hiera Tiny。对当前模型最多渲染三个可见视角，将正负点击投影到二维后调用真实模型，再把掩码投票回原三角面，保留首个正点所在连通区。两个或三个视角观察到的面至少要获两票；只观察到一次的面要获一票。提示点的面号保持，正点必须留在同一连通区。

每个视角可用掩码按面积分成小、中、大；不同视角相同档位未必代表相同语义层级，因此允许拒绝不一致结果。掩码 predicted IoU 是模型预测置信信息，没有人工真值标注，不能当作实测准确率。现有几何分组、已有网格直选仍保留。

## 3. 八个家具的真实选区结果

样本复用已有资产：六份商品图片生成结果、一个官方椅子示例、一个代码书柜。它们不是八张本轮新生成图片，也没有新增杂乱场景数据集。固定点击仅覆盖这些交互，不能推断任意角度或任意家具效果。

{mdtable(['家具','初始非空面数','实际请求与后续结果','缓存范围面数'],samrows)}

所有范围切换均验证没有增加 SAM 请求；候选操作未自动写模型版本。柜子追加排除点失败时仍保留 125,683 面及原提示。代码书柜 HTTP 200 只说明二维掩码产生，前端未发布不一致的三维候选。蓝椅可见坐垫选区仍有小缺口，不能称作完整坐垫实体。

最终端到端副本 `{delivery['job']}` 实测保留、排除、再保留 → 保存部件 → 局部换色；只改变目标部件材质，三角面总数不变。新版本清空提示点与候选缓存；生成对照同时显示常规与结构细节，并复用已有任务。详见 `delivery_browser.json`。

## 4. 结构细节实际生成

TripoSR：提取分辨率 192 → 256。Hunyuan：提取分辨率 256 → 384，采样步数 30 → 50，seed 42 保持。两种档位的已处理输入 SHA-256 逐对相同。单次 worker 计时包含不同热启动条件，不是标准速度基准，也不含队列等待。

{mdtable(['比较项','分辨率','三角面数：常规 → 细节','worker 秒：常规 → 细节','细节任务'],genrows)}

![常规与结构细节的固定视角对照](../experiments/selection_refinement_20261112/structure_contact.png)

每行依次为常规前侧、常规背面下视、细节前侧、细节背面下视。使用相同相机、显示归一化、统一中性材质；没有拟合原图相机，不能直接计算照片还原分数。

- TripoSR 蓝椅：细节档位仍将支撑腿生成成粗短突起，椅背和坐垫表面仍粗糙，不推荐仅凭提高分辨率替换 Hunyuan 结果。
- Hunyuan 蓝椅：两档均有细支撑结构，但底部仍出现开放、扭曲或不连续的形状；本组图片未证明缺陷被细节档位修复。
- Hunyuan 柜子：两档均能看见上部层板与下部门面；细节档位没有明显改正背面凹洞或恢复未观察结构。柜门装饰仍是近似。

蓝椅细节输出 1,507,468 面，超过 UV 单部件 750,000 面限制，实际编辑可能要先减面。三个输出均通过现有几何 / 文件检查，但外观验收状态仍待检查；未自动盖章为合格。

## 5. UV 量化、视觉与默认选择

正式矩阵包含 17 个显式 UV 版本（八样本各跑快速分区和代理，圆桌再跑环绕）与 8 个最终自动模式版本，共 25 个结果。额外试跑和重测版本保留，不计入这 25 个结果。均保持原始世界坐标三角面多重集合，原文件 SHA-256 保持不变。UV 接缝允许复制顶点，不等于增添几何面。

下表接缝值是“几何接缝长度 / 所选范围包围盒对角线”，不是接缝条数。拉伸为按几何面积加权的各向异性几何平均值，1 较好。指标使用位置焊接容差 1e-7、UV 连续性容差 1e-5，不检测所有图集重叠或保证花纹主观美观。

{mdtable(['家具','分区接缝值','代理接缝值','平均拉伸：分区 → 代理','最终自动算法'],uvrows)}

高面数（超过 60,000 面）自动策略先尝试 12,000 面代理 xatlas，再回传原面；使用附近三角形候选的近似投影，并非精确最近表面求解。代理面上限 25,000、图块上限 256、回传距离 / 包围盒对角线 ≤ 0.03。显式代理还限制塌缩面积 ≤ 1%。

自动策略额外与快速分区对照：接缝减少超过 5%；面积平均拉伸不超过基线的 110%；各向异性 >4 的面积不超过 0.5%；塌缩面积不超过 0.1%。通过才采用代理，否则回退并记录原因。这些是启发式保护，不是产品外观承诺。≤60,000 面自动仍使用既有 xatlas 图集，不进行这项代理对照。

本轮五个高面数样本中，蓝椅、灯芯绒沙发、柜子采用代理；圆桌、皮质沙发回退分区。低面数三个样本使用 xatlas。显式代理失败 / 不理想证据均保留。圆形环绕用于围绕局部轴的圆形部件，必须选对轴，不适用于所有家具。

圆桌环绕接缝值 {uv[0]['cylinder']['normalized_seam_length']:.3f}，分区 {uv[0]['box']['normalized_seam_length']:.3f}；连续域从 {uv[0]['box']['uv_continuity_components']} 减为 {uv[0]['cylinder']['uv_continuity_components']}，但桌面边沿和底面仍有接缝。代理圆桌反而增加接缝，因此默认拒绝。代码书柜显式代理平均拉伸约 2.85，也不应推荐。

![八家具的诊断棋盘格对照](../experiments/selection_refinement_20261112/uv_contact.png)

棋盘图是诊断材质，不是商品材质恢复。各算法图集利用率不同，即使重复次数相同，物理格子大小也不同；比较密度和颜色不能得出还原提升。背面下视另见 `uv_under_contact.png`。蓝椅代理仍有花纹方向跳变；自动保护只能控制所测指标，不能消除所有接缝。

## 6. Review 发现并修复

1. 严格锚点协议不接受多出的 label：锚点只发 x/y，正负信息放在 points，422 试跑证据保留。
2. 视角只有排除点却被跳过时，不能把该点算作已提交：仅统计实际有保留点且已提交的视角。
3. 旧 SAM 缓存可能覆盖手工修正：手动选面 / 涂抹及面撤销清空会话，首次正点撤销恢复之前的选区。
4. 保存版本后旧提示计数残留：随模型 URL 更新重置提示、模式与范围缓存，端到端已验证。
5. 代理不是普遍优于分区：八家具量化后增加高面数接缝 / 拉伸保护，保留显式入口与原失败版本。
6. UV 回退元数据可能被代理字段覆盖：最终算法与代理尝试分别记录；新增回归测试，并重跑八个自动版本。
7. 测试脚本两个预览遮罩触发 strict locator 错误：逐个等待两侧加载；原失败日志保留，不算成产品失败。

## 7. 验证结果与可复查证据

- Python：{sum(tests.values())} 项通过，包含 API {tests['api']}、部件工具 {tests['part_tools']}、高级编辑 {tests['advanced']}、家具工具 {tests['furniture']}；日志分别为 api_final / part_tools_final / advanced_final / furniture_final.log。
- JS 几何单元：8 项通过，含不填未观察孔、正负点锁定、UV 不连续检测和面序保持。
- 真实浏览器：八家具 SAM 矩阵、范围缓存、橙线切换、几何贴合缓存、单提示撤销、UV 蓝线、390px 宽度、选区保存 / 局部材质、双档位任务复用。
- 前端 TypeScript 和生产构建通过；仍有主包超过 500kB 的体积提示。
- Blender 独立导入并渲染 {len(renders)} 张固定视角图；输出与图片逐项记录在 external_renders.json。人工目测范围是本报告所示视角，不是所有面或所有材质。
- 完整 glTF Validator 校验 12 份输出（8 份自动 UV、3 份新生成、1 份保存后局部换色）：错误和警告均为 0。另比较保存后完整三角面多重集合，确认与源模型相同。
- 交互报告的图片全部加载，本地链接存在，失败筛选与手机宽度检查通过；具体计数见 report_qa.json。

第一次 Python unittest 模块方式调用未加入 scripts 路径而导入失败，改为直接执行测试脚本后通过；geometry_final.log 仍保留。自动 UV 验证最初选错缺 numpy 的环境，随后改用几何环境，失败日志保留。鼠标未击中网格、早期严格协议失败、测试定位器失败均保留，不能删掉后只报成功次数。

原始 JSON：sam_matrix、controls、delivery_browser、uv_runs、uv_metrics、auto_uv_runs、structure_runs、gltf_validation、saved_geometry_check、report_qa、summary。各 mask / request / subprocess 日志在 `.data/jobs/<job>/part_proposals/<proposal>/`；sam_matrix.json 记录具体 proposal ID。生成参数、输入 SHA、耗时和阶段在对应 local_summary.json 与 structure_runs.json。

## 8. 仍未解决与下一步

当前分离仍是表面三角面归属调整，不是带封口的实体切割或制造零件分解。SAM 基于渲染可见表面，不会看透模型；柜子等复杂结构仍可能整块被选中。没有人工真值数据集，不能提供准确率。隐藏部位、真实尺寸和材质均需更多实拍或人工校正。

下一轮建议先解决柜子、官方椅子与代码书柜的失败案例，并给局部选区提供更可靠的跨视角语义约束；对细腿可考虑局部人工结构修复或更合适的重建模型。UV 后续应增加花纹方向、物理纹理密度和重叠检查。高细节模型需形成保形减面流程。当前未完成多图几何融合、训练语义部件模型或材质扫描恢复。
'''
(ROOT/'docs/SELECTION_REFINEMENT_REVIEW_2026-11-12.md').write_text(document,encoding='utf-8')
def table(headers,rows):return '<div class="table-scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def figure(filename,label):return f'<figure><a href="{filename}"><img src="{filename}" alt="{html.escape(label)}" loading="lazy"></a><figcaption>{html.escape(label)}</figcaption></figure>'
cards=[]
for c in sam['cases']:
    name=c['case'];u=next(u for u in uv if u['case']==name);failure=c['initial_faces']==0 or any(q.get('status',200)!=200 for q in c['queries']);regression=u['proxy']['normalized_seam_length']>=u['box']['normalized_seam_length'] or u['proxy']['geometric_mean_anisotropy']>u['box']['geometric_mean_anisotropy']*1.1
    images=figure(name+'_final.png','最终交互候选 / 失败后保留状态')
    if (OUT/('reference_'+name+'.png')).exists():images=figure('reference_'+name+'.png','该家具的已裁剪生成参考图')+images
    for mode in ('box','proxy')+ (('cylinder',) if name=='round_table' else ()):
        images+=figure(name+'_'+mode+'_front.png',{'box':'快速分区棋盘诊断','proxy':'代理回传棋盘诊断','cylinder':'圆形环绕棋盘诊断'}[mode])
    evidence=''.join(f'<li>{html.escape(q["label"])}：HTTP {q.get("status","未提交")}，{q.get("faces",0):,} 面；proposal {html.escape(q.get("proposal", "无"))}</li>' for q in c['queries'])
    cards.append(f'<article class="case" data-samfail="{int(failure)}" data-uvregression="{int(regression)}"><h3>{labels[name]}</h3><p>{notes[name]}</p><ul>{evidence}</ul><div class="images">{images}</div><p><a href="http://127.0.0.1:8001/?job={c["job"]}">打开本轮测试副本</a></p></article>')
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>五项优化实测 · 2026-11-12</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f9;color:#26324a;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1240px;margin:auto;padding:28px}h1{font-size:30px}h2{margin-top:38px}p{max-width:1050px}a{color:#6142b1}section,article{background:white;padding:24px;border:1px solid #dee3ee;border-radius:14px;margin:20px 0}.notice{background:#fff6df;border-left:4px solid #d69720;padding:18px}nav{display:flex;gap:12px;flex-wrap:wrap}.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}figure{margin:0}figure img{width:100%;height:240px;object-fit:contain;background:#f6f7fa;border-radius:8px}figcaption{font-size:13px;color:#59667a}.wide img{height:auto;max-height:800px}.table-scroll{max-width:100%;overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:12px;border-bottom:1px solid #e4e7ed;vertical-align:top}th{background:#f1f0fa}button{padding:10px 16px;background:white;border:1px solid #c7bfdc;border-radius:7px;color:#50348e;cursor:pointer}button[aria-pressed=true]{background:#704fc2;color:white}[hidden]{display:none!important}code{overflow-wrap:anywhere}@media(max-width:600px){main{padding:14px}section,article{padding:16px}h1{font-size:24px}.images{grid-template-columns:1fr}}
</style><main><h1>五项优化的实际验收</h1><p>多点修正 · 候选范围 · 边界检查 · 结构细节 · UV 连续性 | 2026-11-12</p><nav><a href="http://127.0.0.1:8001">工作台</a><a href="../../docs/SELECTION_REFINEMENT_REVIEW_2026-11-12.md">详细报告</a><a href="summary.json">汇总 JSON</a></nav>
<div class="notice">功能已接通；外观仅部分改善。八个样本有六个得到非空初始候选，不能视为准确率。高细节增加了面数，本组未证明细腿和孔洞明显变好。UV 代理在部分样本更差，已加入高面数自动回退。</div>
<section><h2>如何操作</h2><p>AI 辅助选区中，先点目标，再用“不要这里”排除串选、“保留这里”补选；小 / 中 / 大复用本轮缓存。检查橙色边界，必要时涂抹，保存为新部件后再换材质。结构细节在“更多操作 → 同图本地引擎对照”中。曲面 UV 在“换材质”页。</p><p>所有选区都是待检查表面；不会自动生成隐藏表面或封闭制造零件。</p></section>
<section><h2>八家具候选记录</h2>'''+table(['家具','初始面数','请求结果','范围面数'],samrows)+'''<p>范围切换不增加 SAM 请求。柜子排除失败保留原选区；书柜二维 HTTP 200 后三维一致性仍失败。已保存完整负例。</p></section>
<section><h2>实际高细节生成</h2>'''+table(['对象','分辨率','面数','单次 worker 秒','细节任务'],genrows)+'''<div class="wide">'''+figure('structure_contact.png','每行：常规前侧 / 常规背面下视 / 结构细节前侧 / 结构细节背面下视')+'''</div><p>统一中性材质、固定相机、各自显示归一化；未拟合原图相机。TripoSR 细腿仍粗短，Hunyuan 支撑仍有缺陷，柜子开口没有确认的显著改善。三个任务均待审核。</p></section>
<section><h2>UV 对照与保护</h2>'''+table(['家具','分区接缝','代理接缝','平均拉伸变化','自动算法'],uvrows)+'''<p>接缝值为接缝长度 / 包围盒对角线；拉伸 1 较好。不是语义准确率或照片相似度。图集密度不同，棋盘格物理大小并不一致。</p><p>高面数自动仅在接缝减少 >5%、平均拉伸 ≤基线 110%、严重拉伸面积 ≤0.5%、塌缩面积 ≤0.1% 时采用代理；否则保留快速分区。小部件继续用 xatlas。回传采用近似投影，仍需检查花纹方向和接缝。</p><details><summary>查看四个家具的背面 / 底面棋盘格</summary><div class="wide">'''+figure('uv_under_contact.png','背面和底面诊断；保留全部原几何面')+'''</div></details></section>
<h2>逐件图片与失败证据</h2><p>六份商品图结果、一个官方示例、一个代码模型；全部复用已有输入。切换筛选可只看需要继续处理的样本。</p><nav aria-label="样本筛选"><button data-filter="all" aria-pressed="true">全部 8 件</button><button data-filter="samfail" aria-pressed="false">选区有失败</button><button data-filter="uvregression" aria-pressed="false">代理有退步</button></nav><p id="case-count" role="status">显示 8 件</p>'''+''.join(cards)+f'''<section><h2>最终选区保存与局部材质</h2><p>验收副本：<a href="http://127.0.0.1:8001/?job={delivery['job']}">打开已保存的蓝椅部件</a>。正负点修正后保存部件，仅局部材质变化；新版本清空旧提示和缓存。</p><div class="images">'''+figure('multipoint_saved_material.png','正负点修正 → 保存新部件 → 局部换色')+figure('structure_comparison_desktop.png','常规与结构细节在同一对照中，已有候选复用')+'''</div></section>
<section><h2>验证与仍未解决</h2><p>'''+f"Python {sum(tests.values())} 项、JS 几何 8 项通过；真实八家具交互、17 个显式 UV +8 个自动 UV 版本，独立 Blender 渲染 {len(renders)} 张。前端构建通过，主包体积提示仍存在。"+'''</p><p>仍未完成：精确语义部件识别、实体切割封口、任意图片高精度还原、隐藏面恢复、真实尺寸验证、真实照片材质恢复。蓝椅高细节超过 150 万面，后续编辑可能需要减面。</p><details><summary>原始结果与失败日志</summary><ul>'''+''.join(f'<li><a href="{file}">{file}</a></li>' for file in ['sam_matrix.json','controls.json','delivery_browser.json','uv_runs.json','uv_metrics.json','auto_uv_runs.json','structure_runs.json','external_renders.json','api_final.log','part_tools_final.log','advanced_final.log','furniture_final.log','selection_review_unit.json','geometry_final.log','auto_uv_failed_missing_numpy.log','auto_uv_runs_initial.json','delivery_browser_initial_locator_failure.json','pilot_first_failed.json','pilot_missed_click.json'])+'''</ul></details></section></main><script>
for(const button of document.querySelectorAll('[data-filter]'))button.addEventListener('click',()=>{for(const other of document.querySelectorAll('[data-filter]'))other.setAttribute('aria-pressed',String(other===button));let visible=0;for(const card of document.querySelectorAll('.case')){card.hidden=button.dataset.filter!=='all'&&card.dataset[button.dataset.filter]!=='1';if(!card.hidden)visible++}document.querySelector('#case-count').textContent='显示 '+visible+' 件'});
</script></html>'''
(OUT/'index.html').write_text(page,encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
