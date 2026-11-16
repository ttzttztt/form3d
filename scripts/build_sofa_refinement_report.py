# -*- coding: utf-8 -*-
"""Build reports from actual logs and retain negative specimens."""
import hashlib,html,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/sofa_refinement_20261113'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
audit=read('audit.json');cases=read('cases.json');validation=read('gltf_validation.json');ui=read('ui_results.json');brush=read('brush_results.json');commit=read('commit_ui_results.json');renders=read('renders.json');demo=read('demo_browser.json')
counts={}
for label,file in [('api','api_tests.log'),('geometry','geometry_tests.log')]:
    log=(OUT/file).read_text(encoding='utf-8-sig');assert re.search(r'\nOK\s*$',log),file;counts[label]=int(re.findall(r'Ran (\d+) tests?',log)[-1])
assert all(not r.get('error') for r in audit)
assert len(demo['cases'])==4 and not demo['errors']
assert not ui['errors'] and not brush['errors'] and not commit['errors']
assert all(r['errors']==0 and r['warnings']==0 for r in validation)
sources=[]
for c in cases:
    path=ROOT/'.data/jobs'/c['source_job']/'model.glb';digest=hashlib.sha256(path.read_bytes()).hexdigest();assert digest==c['source_sha256'];sources.append({'case':c['case'],'original_source_unchanged':True,'sha256':digest})
# Compact index leaves raw SAM masks/render inputs in the original backend proposal folders.
sam=[]
for item in ui['sam']:
    views=[{k:v for k,v in view.items() if k!='image'} for view in item['request']['views']]
    sam.append({'button':item['button'],'http_status':item['status'],'views':views,'proposal_id':item['body'].get('proposal_id'),'detail':item['body'].get('detail'),'model':item['body'].get('model')})
summary={'date':'2026-11-13','python_tests':counts,'python_total':sum(counts.values()),'validated_glb_files':len(validation),'glb_errors':0,'glb_warnings':0,'blender_renders':len(renders),'furniture_cases':4,'editing_checks_passed':4,'appearance_acceptance':'Two sofas rejected. Chair and round table accepted for editing regression only.','ui_checks':ui['checks']+brush['checks']+commit['checks'],'sam_requests':sam,'source_audit':sources}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
names={'leather_sofa':'皮质沙发','corduroy_sofa':'灯芯绒沙发','accent_chair':'椅子历史软包选区','round_table':'圆桌桌面'}
notes={'leather_sofa':'厚度范围可控制，但靠垫粘连处仍出现明显平顶补面；不属于准确完整坐垫。','corduroy_sofa':'选取贵妃位的局部座面体，前后范围可限制；侧部和背部仍有较大人工平面，不能认定真实独立坐垫。','accent_chair':'复用此前表面引导，验证轮廓方式和编辑操作；本轮不重新判定软包的语义边界或实物还原。','round_table':'验证板件诊断、实际预览和保存，以及局部材质、移动、导出；不验证真实制造接缝。'}
rows=[];cards=[]
for r in audit:
    name=r['case'];is_sofa='sofa' in name;status='外观未通过' if is_sofa else '编辑回归通过';rows.append(f"| {names[name]} | {status} | {notes[name]} |")
    figures=[('source_front','原生成网格'),('part_front','本轮候选 · 蓝色源表面 / 橙色推测面'),('part_side','本轮候选 · 侧面'),('part_bottom','本轮候选 · 底面')]
    if is_sofa:figures.extend([('previous_front','上轮失败候选 · 独立归一化显示'),('trial2_part_front','第二次调低顶部 · 仍未通过'),('trial2_part_side','第二次调低顶部 · 侧面')])
    imgs=''.join(f'<figure><img loading="lazy" src="{name}_{key}.png" alt="{html.escape(label)}"><figcaption>{html.escape(label)}</figcaption></figure>' for key,label in figures)
    links=' · '.join(f'<a href="{name}_{file}">{label}</a>' for file,label in [('export.glb','移动后单件 GLB'),('final_demo.glb','装配示例 GLB'),('request.json','实际切分请求'),('run.json','预览记录')])
    cards.append(f'<article data-result="{"reject" if is_sofa else "pass"}"><h2>{names[name]}：{status}</h2><p>{notes[name]}</p><div class="images">{imgs}</div><p><a href="http://127.0.0.1:8001/?job={r["job"]}">打开工作台</a> · {links}</p></article>')
report=f'''# 沙发坐垫边界、厚度与真实切分预览验收

日期：2026-11-13。[图片与原始证据](../experiments/sofa_refinement_20261113/index.html)。[工作台](http://127.0.0.1:8001)。

## 结论

已实现可明确调整上下和前后边界的切分方式、保存前的真实切分预览，以及预览与保存结果一致性保护。复用原有保留点、排除点、旋转和涂抹，没有更换分割或生成模型。本轮测试 4 个已有图生 3D 网格；两款沙发各做两次显式边界试验。

**沙发“准确完整坐垫拆分”的质量目标仍未达到**。两款沙发的本轮装配演示版本均实际标为 rejected / 需要修改。增加厚度范围、成功闭合、通过导出都不能替代外观验收。椅子与圆桌仅通过编辑流程回归，不是新增的语义准确率或实物还原证明。

| 案例 | 本轮判定 | 依据 |
| --- | --- | --- |
{chr(10).join(rows)}

## 1. 用户现在怎么操作

1. 在模型中进入“AI 辅助选区”，先点击想保留的坐面，再用“保留这里”补选侧面，“不要这里”尝试排除靠垫 / 扶手。拖动仍可旋转；涂抹修正支持增加和擦掉表面。
2. 进入“拆分部件”，填写名称，展开“完整部件：检查范围与补齐接合面”。坐垫方式可选择“沿表面选区轮廓”或“按调整范围（手动确定厚度和前后边界）”。
3. 分析后调整绿色范围。Y 起点 / 终点分别控制下 / 上边界，X 与 Z 控制水平方向范围。它们是源模型坐标的百分比，没有标定真实尺寸。
4. 点击“预览实际切分”。预览运行真实切割和闭合检查；蓝色是源模型表面，橙色是新推测接合面，其余结构半透明。可查看正面、侧面、背面、底面，或仅看拆出的部件。
5. 检查厚度和相邻边界后勾选确认，再生成候选编辑版本。保存的是同一份已预览的模型，仍可继续换材质、移动和单独导出。

**排除点的边界**：排除点只修正表面选区。按显式范围切分时会重新纳入框内源表面，不能保证点击排除的位置在最终实体里消失；需要调整范围并查看真实结果。界面已经直接提示，不能把表面排除当成实体减法。

## 2. 为什么增加显式范围方式

旧坐垫方式从选区的凸轮廓和上部支撑平面切割，适合局部表面引导，但调大外框仍可能受薄顶面或带入的靠垫限制。新方式取消这组轮廓 / 顶部约束，完全按用户明确给出的三维范围切割，并为两侧补齐接合面。

这让厚度和前后边界真正可调，但不会自动找到真实坐垫缝线。框太宽仍会带入扶手，框太低会削掉原坐面，框太高会留下靠垫底部。补出的仍是平面，不是对真实隐藏曲面的恢复。不能只凭这个新方式宣布沙发质量问题已解决。

## 3. 两款沙发的真实结果与第二次试验

皮质沙发：第一轮显式 Y 范围为 38.5%～52.3%，覆盖源模型竖向包围范围的 13.8%；上轮候选竖向跨度约 0.1440，本轮约 0.1811，均为未标定的源模型单位。侧面可以看到体积范围增大，但靠垫粘连位置出现明显抬高平顶。第二轮把顶部降到 51.2%，虽减少部分高处残留，却切到坐面局部凸起，新增橙色顶面。两次都不能通过完整坐垫外观验收。

灯芯绒沙发：第一轮显式范围 X 0～70%、Y 41.5%～57%、Z 64%～93.5%，为人工看图和坐标投影选择的贵妃位局部范围，**不是 SAM 自动识别出的完整坐垫**。竖向跨度从上轮约 0.0610 增至约 0.1170；本轮侧部 / 后部仍有较大的推测平面。第二轮顶部降至 55%，又将更多原上表面截平，没有解决真实边界问题。两次均未通过。

上面的竖向跨度是包围盒统计，不是实物厚度或精度。比较图按各自范围归一化显示，不适合用图中像素长度比较厚度。原始请求、坐标投影和 GLB 均保留。

真实 SAM 交互共记录三次请求：初始保留点 HTTP 200；靠垫排除点 HTTP 409，未得到可用候选并保留旧选区；旋转后的追加保留点 HTTP 200。追加后的候选仍偏宽。这里既不能把 HTTP 200 当准确分割，也不能把未生效的排除点记成成功。

## 4. 验证数据

- Python **{sum(counts.values())} 项通过**：API / 合同 {counts['api']}，几何 / 部件 / 结构 {counts['geometry']}。新增测试覆盖显式范围不被原顶面约束、未指定范围拒绝、预览不发布版本、保存复用原文件、范围 / 名称 / 选区变化、源文件 / 预览篡改，以及预览期间版本变化。
- 四个家具都验证了“保存文件与预览逐字节一致”、只改变选中部件的材质、单件移动后其他组逐三角面不变、单独导出后重开闭合、原模型 SHA-256 未变。它们是编辑检查，不是外观精度。
- **{len(validation)} 份 GLB 文件**通过完整 glTF Validator：0 错误、0 警告。包含多份装配 / 移动 / 导出以及第二轮试验文件，不代表 {len(validation)} 个独立家具样本。
- Blender **{len(renders)} 张诊断渲染**；固定相机与显示归一化，没有做原图相机拟合、照片相似度或人工标注精度评测。
- 真实浏览器完成 SAM 保留 / 失败排除 / 旋转补选、真实预览各方向 / 隔离、人工确认门槛、修改范围后失效、后台拒绝旧预览、390px 无横向溢出；灯芯绒沙发表面涂抹从 {brush['counts']['first']} 面到擦除后 {brush['counts']['second']} 面。另一个独立圆桌副本通过浏览器实际保存，并校验字节与预览一致。
- 最终四任务的编辑版 accepted / rejected 状态已在浏览器读取复核。前端类型检查和生产构建通过，已有主包大于 500kB 提示仍存在。

## 5. Review 与修正

预览放在独立 completion_previews 目录，不写 current_asset_version 或 asset_versions。成功后才写 ready 标记；版本变化或切分失败不会发布。保存时验证请求摘要、源文件 SHA-256、预览文件 SHA-256，并复制该文件；最终发布仍检查当前版本，避免用旧范围覆盖新结果。

界面在任务、版本、选区、部件类型、切分方式、范围或名称变化后清除预览及勾选状态；预览尚未加载成功时不能勾选并保存。异步旧响应不会覆盖新的选区预览。默认轮廓模式保留，结构部件与已有连续拆分回归通过。

测试过程中有两类脚本问题：首次 Python 测试命令引用了不存在的模块，改用实际模块名后通过；Blender 会把多个材质的三角面合入同一个对象，首次隔离脚本删掉了整个对象，已改为按材质删除对应面。初次日志 geometry_tests_initial.log / render_initial.log 保留，最终数据取修正后的完整运行。单元测试中的 subprocess mock 也曾影响校验子进程，修正测试隔离后 API 全套通过。

主要实现见 [完整部件面板](../apps/web/src/CompletePartPanel.tsx)、[三维切分预览](../apps/web/src/CutPreview.tsx)、[预览服务](../services/api/completion_preview.py)、[实体切分](../scripts/complete_part.py)。预览服务、几何和前端没有引入新的识别模型或密钥依赖。

## 6. 当前边界与后续工作

本轮完成了四项工作中的交互、范围控制、真实预览和多家具复测；**两款沙发的完整坐垫外观问题仍然存在**。对于粘连处，继续调整一个盒子不能恢复缺失的独立曲面。下一步需要能表达局部曲面和非矩形边界的重建方式，并在保留干净源表面的前提下约束推测区域；结果仍需逐视角验收，不能提前保证准确。

当前完整切分继续仅支持无贴图、无顶点颜色、静态且同源材质一致的模型，拒绝非均匀缩放；没有新增任意家具语义识别、真实隐藏结构恢复或自相交全面检测。预览在磁盘保留两份 GLB，本轮未增加自动清理策略。

证据目录 experiments/sofa_refinement_20261113：summary / audit / cases / 各模型 run 和 request / trial2_run / ui_results / brush_results / commit_ui_results / demo_browser / gltf_validation / renders，以及各最终日志。历史报告和前轮失败文件保留，本轮只编辑独立副本。
'''
(ROOT/'docs/SOFA_CUSHION_REFINEMENT_REVIEW_2026-11-13.md').write_text(report,encoding='utf-8')
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>坐垫范围与真实切分预览验收</title><style>body{margin:0;background:#f3f5f8;color:#18263b;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1280px;margin:auto;padding:28px}article,.intro{padding:22px;background:white;border:1px solid #d8dfeb;border-radius:12px;margin:22px 0}h1{font-size:28px}h2{font-size:21px}.images{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{margin:0}img{width:100%;border-radius:7px}figcaption{font-size:14px;color:#536174}a{color:#3753a5;overflow-wrap:anywhere}select{font:inherit;padding:7px;max-width:100%}.note{border-left:4px solid #b4701f;padding-left:14px}[hidden]{display:none!important}@media(max-width:650px){main{padding:14px}article,.intro{padding:15px}.images{grid-template-columns:minmax(0,1fr)}}</style><main><h1>坐垫范围与真实切分预览验收</h1>'''+f'''<div class="intro"><p><strong>两款沙发仍未通过完整坐垫外观验收。</strong>已完成范围控制、真实预览与保存一致性保护；椅子和圆桌仅作编辑回归。</p><p>{sum(counts.values())} 项 Python 测试通过，{len(validation)} 份 GLB 完整校验无错误、无警告，{len(renders)} 张诊断渲染。<a href="../../docs/SOFA_CUSHION_REFINEMENT_REVIEW_2026-11-13.md">详细报告</a> · <a href="summary.json">数据摘要</a> · <a href="audit.json">逐家具验收</a></p></div>'''+'''<p class="note">蓝色为源模型表面，橙色为推测接合面。每张图独立归一化，不是实物尺寸、同相机照片对比或分割准确率。</p><label>筛选 <select id="filter"><option value="all">全部 4 个家具</option><option value="reject">外观未通过的 2 款沙发</option><option value="pass">编辑回归通过的 2 个家具</option></select></label>'''+''.join(cards)+'''<article><h2>真实界面与失败提示</h2><div class="images"><figure><img src="ui_exclusion.png"><figcaption>排除点未生效：保留原选区，未记为成功</figcaption></figure><figure><img src="ui_preview_bottom.png"><figcaption>真实预览：隔离部件并查看底面</figcaption></figure><figure><img src="ui_table_preview.png"><figcaption>圆桌预览与保存逐字节一致</figcaption></figure></div><p><a href="ui_results.json">沙发界面记录</a> · <a href="brush_results.json">涂抹记录</a> · <a href="commit_ui_results.json">浏览器保存记录</a> · <a href="gltf_validation.json">GLB 校验</a> · <a href="renders.json">渲染索引</a></p></article></main><script>document.getElementById('filter').onchange=e=>document.querySelectorAll('[data-result]').forEach(c=>c.hidden=e.target.value!=='all'&&c.dataset.result!==e.target.value)</script></html>'''
(OUT/'index.html').write_text(page,encoding='utf-8')
print(json.dumps({'python_tests':sum(counts.values()),'validated_glb_files':len(validation),'renders':len(renders),'report':'docs/SOFA_CUSHION_REFINEMENT_REVIEW_2026-11-13.md'},ensure_ascii=False))
