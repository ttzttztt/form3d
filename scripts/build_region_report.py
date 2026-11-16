# -*- coding: utf-8 -*-
"""Honest boundary report: supported observations are not semantic ground truth."""
import html,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/semantic_refinement_20261113'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
audit=read('verification.json');ui=read('ui_results.json');validation=read('gltf_validation.json');runs=read('api_runs_validated.json');assert not ui.get('failure') and not ui['errors'];assert all(r['errors']==r['warnings']==0 for r in validation);assert runs[-1]['validated_result']['status']=='failed'
counts={}
for name,file in [('api','api_tests_delivery.log'),('geometry','geometry_tests_final.log')]:
    log=(OUT/file).read_text(encoding='utf-8-sig');assert re.search(r'\nOK\s*$',log),file;counts[name]=int(re.findall(r'Ran (\d+) tests?',log)[-1])
colours=json.loads((OUT/'colour_tests.log').read_text(encoding='utf-8-sig'));assert colours['passed']==5;assert 'built in' in(OUT/'build.log').read_text(encoding='utf-8-sig')
names={'leather_sofa':'皮革沙发','corduroy_sofa':'灯芯绒沙发','accent_chair':'休闲椅'}
notes={'leather_sofa':'保留靠枕、坐面与主体、圆柱抱枕三组，另设一组灰色未确认区域。靠枕包边和接触处仍有残留，坐垫与底座仍合在一起。','corduroy_sofa':'仍为五个靠枕和一组坐面与主体，未把每个碎片算成零件。长条外扩减少，部分短小残片仍在；灰色区域保留原始表面。','accent_chair':'仍有两个已命名候选和一组灰色未确认区域。靠枕标签及座面范围仍不可靠，不能作为准确椅子部件验收。'}
parts=[p for c in audit for p in c['groups']];rows=[];cards=[];metrics=[]
for case in audit:
    comp=case['same_saved_masks_comparison'];old=sum(g['old_visible_conflict_area']for g in comp);new=sum(g['new_visible_conflict_area']for g in comp);metrics.append({'case':case['case'],'old_conflicting_source_area':old,'new_conflicting_source_area':new,'not_semantic_accuracy':True})
    rows.append(f"| {names[case['case']]} | {case['recognized_groups']} + 1 组未确认 | {case['unconfirmed_area_fraction']:.1%} | {notes[case['case']]} |")
    images=[('all_front.png','整体分色 · 正面'),('all_back.png','整体分色 · 背面')]+[(f'group_{i}_front.png',g['name']+' · 单独观察')for i,g in enumerate(case['groups'])]+[(f'group_{i}_under.png',g['name']+' · 底面')for i,g in enumerate(case['groups'])]
    figures=''.join(f'<figure><img loading="lazy" src="delivery/{case["case"]}/{file}" alt="{html.escape(label)}"><figcaption>{html.escape(label)}</figcaption></figure>'for file,label in images)
    links=' · '.join(f'<a href="{g["export"]}">{html.escape(g["name"])}</a>'for g in case['groups'])
    cards.append(f'<article><h2>{names[case["case"]]}</h2><p>{notes[case["case"]]}</p><div class="images">{figures}</div><p>{links}</p></article>')
summary={'date':'2026-11-13','unique_real_furniture_cases':4,'ready_soft_furniture_cases':3,'rejected_table_case':True,'recognized_candidate_groups':sum(c['recognized_groups']for c in audit),'unknown_groups':sum(g['kind']=='unknown'for g in parts),'python_tests':counts,'python_total':sum(counts.values()),'colour_checks':5,'group_material_move_export_checks':len(parts),'glb_files':len(validation),'glb_errors':0,'glb_warnings':0,'browser_errors':[],'source_invariants_preserved':True,'semantic_accuracy_measured':False,'generic_semantic_split_accepted':False,'demo_job':ui['job'],'same_saved_masks_conflict_comparison':metrics}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
metric_rows='\n'.join(f"| {names[r['case']]} | {r['old_conflicting_source_area']:.6f} | {r['new_conflicting_source_area']:.6f} |"for r in metrics)
link_checks=read('completion_links.json')if(OUT/'completion_links.json').exists()else[]
link_lines=[]
for r in link_checks:
    group=(r.get('operation',{}).get('groups')or[{}])[0]
    outcome='重建候选通过几何保护，外观仍待确认。'if group.get('status')=='reconstructed'else'重建拒绝，保留源网格；'+r.get('rejected_reason',group.get('reason',''))
    link_lines.append(f"- {names[r['case']]} / {r['name']}："+outcome)
report=f'''# 多视角部件边界约束、失败复测与审查报告

日期：2026-11-13。[图像与证据](../experiments/semantic_refinement_20261113/index.html)。[灯芯绒沙发演示](http://127.0.0.1:8001/?job={ui['job']})。

## 实际完成的改善

本轮处理“靠枕分组带着长条杂片”的归属问题。旧逻辑把未知表面沿网格传播到最近的已有部件，没有充分使用其他可见视角的排除证据，且允许传播到源模型对角线 35% 的距离。小片误归属可能进一步充当传播起点。

现已接入：

1. **可见视角的排除约束**：只被一个视角支持、却被更多可见视角排除的面，不再作为这个部件的种子，也不能被自动补入。
2. **传播起点需要多视角锚点**：没有稳定锚点的孤立片不继续扩张；允许的推测传播距离缩短到源模型对角线的 10%，并受部件观察范围限制。
3. **合并后继续遵守排除约束**：同一靠枕正反面合并时同时合并观察证据，避免把真实背面误判为“其他视角没支持”；圆柱/平面归属调整后再次检查，避免把已排除的面加回来。
4. **不强行填满所有区域**：缺少一致证据的表面集中显示为一组灰色“主体与未确认区域”。这组可能包含源模型的底部、隐藏接触处和暂不确定的面，不是一个已识别的真实装配零件。
5. **桌面误识别保护**：当“桌面”候选覆盖大部分表面、几何又呈明显立体体积时，拒绝将它当作可靠桌面分组。此保护同样检查旧的 ready 缓存和采用请求，不能靠新增灰色组绕过。

原图生 3D 引擎没有更换；识别仍为本地 **Grounding DINO Tiny + SAM 2.1 Hiera Tiny**。本轮主改进来自归属约束与证据记录，不是新训练的 3D 语义模型。无需商业密钥，没有将图片上传第三方。

## 四件家具的真实复测

本轮重新运行了四件家具的本地渲染、GPU 识别和三维归组。网页操作还触发并验证了一次自动品类识别的灯芯绒沙发任务，不是用假检测结果代替实际 AI 流程。

| 家具 | 分组结果 | 未确认源表面积占比 | 真实结果与限制 |
| --- | --- | --- | --- |
{chr(10).join(rows)}
| 圆桌 | 拒绝采用 | 不作为成功结果统计 | 初次复测暴露“桌面 + 未确认区域”绕过原整件检查的回归。新增保护后状态为 failed，采用请求返回 409，旧预览地址返回 404，当前模型仍为原版本。 |

**不能据此宣布准确的全自动部件拆分已经完成。** 五个靠枕没有被继续碎分，但部分短小残片仍存在；沙发坐垫与底座、椅子的语义边界均未通过完整验收。

新的保守分组也有覆盖范围的代价：**这次皮革沙发的新圆柱抱枕选区，未通过已有补全流程的外形偏差保护**。本轮没有降低阈值强行通过，也没有替换上轮保留的完整圆柱抱枕候选；新分组与重建之间仍有未解决的联动问题。

## 可复核的变化，而非虚构准确率

为公平比较算法，本轮另外复用同一批保存的检测掩码、同一源网格，比较旧传播和新传播。下表是分给某部件、却违反其可见视角支持条件的源表面积，单位为模型坐标单位的平方，**不是实物平方米**。

| 家具 | 旧传播的冲突表面积 | 新传播的冲突表面积 |
| --- | --- | --- |
{metric_rows}

“冲突降为零”是新规则保证的内部一致性结果，**不是语义识别准确率 100%**。多个视角也可能一致地分错。测试没有真实人工部件标注，不能给出 precision、recall、mIoU 或商品级通过率。

比较时已合并靠枕正反面的观察计数，避免把来自另一个已合并视角的真实背面误记为冲突。逐部件数据及多视角观察区域保留比例见 `verification.json` 的 `same_saved_masks_comparison`；原始和最终面归属、支持计数另存为 NPZ，方便复查。

## 没有采用的试验

- **按投影轮廓形态学裁剪**：虽然可去掉细长分支，也会裁掉真实靠枕边缘和部分背面，未接入产品。
- **自动座面正点与底座/扶手负点的 SAM 再分割**：真实本地推理有部分有效掩码，但两款沙发及椅子的跨视角稳定性不一致，尚未作为默认坐垫识别流程。
- **给靠枕掩码增加自动座架排除点**：对部分皮革样本有变化，对灯芯绒剩余短小残片改善有限，未加入默认识别步骤。
- **靠枕上部与低位座架间的最小割**：可以缩短某些残片，但仍留下短桩，不能称为完整靠枕边界修复；未接入产品。

试验结果保留在 `footprint_trial*`、`seat_mask_trial`、`pillow_mask_trial`、`neck_trial` 目录及对应日志中，没有删除失败样本或把它们算作通过。

## 验证与 review

- API {counts['api']} 项、几何 {counts['geometry']} 项，共 {sum(counts.values())} 项 Python 测试通过；另有 5 项分色/材质状态检查通过。TypeScript 和生产构建通过，主包体积提示仍存在。
- 三件成功生成候选的家具共 {len(parts)} 个逻辑组逐组验证换材质、移动和独立导出，确认相邻组没有被这些操作修改。这里包含 3 组灰色未确认区域，不能把 {len(parts)} 当作识别出的真实零件数。
- {len(validation)} 个 GLB 文件格式检查，0 错误、0 警告。格式合格不代表外观或结构准确。
- 网页真实验证：AI 候选预览不修改版本；仍有五个靠枕；灰色区域解释可见；采用确切预览；整组换材质不影响相邻靠枕；浏览器下载；桌面和 390 px 移动端无横向溢出、无页面脚本异常。
- 分组前后所有源顶点属性、三角面多重集合和材质均保留；源任务文件哈希保持不变。采用后的模型与预览模型字节一致。
- review 发现并修复了“新增未确认区域导致整桌误识别检查失效”的回归，也补充了缓存失效和采用保护测试。

本轮交付文件是**表面归属候选，均未闭合**。没有把它们伪装成完整实体，也没有覆盖上轮已保存的闭合重建测试任务。与已有重建 Worker 的小范围联动检查：

{chr(10).join(link_lines)or'联动检查未作为本轮完成项统计。'}

## 仍未完成的工作

1. **完整坐垫拆分**：座面、厚度、底面与座架还没有稳定识别，不能依赖统一高度硬切。
2. **短小接触残片**：多视角一致性只能处理互相矛盾的归属，对多个视角一致分错、或原始网格已经粘连的区域能力有限。
3. **独立真实部件形状**：源 3D 的变形或缺失结构仍需局部重建，并标出推测部分；仅改变选区不能恢复真实形状。
4. **不同家具的语义可靠性**：椅子“靠枕”标签仍需复核，圆桌被保护拒绝；没有扩展到“所有家具已支持”的承诺。

本轮改善的是长条误归属、自动传播的失败保护和结果的可解释性。完整坐垫与通用家具自动部件识别仍未达到项目最终验收标准。
'''
(ROOT/'docs/SEMANTIC_BOUNDARY_REVIEW_2026-11-13.md').write_text(report,encoding='utf-8')
comparisons='''<article><h2>同一靠枕，前后对照</h2><p>长条外扩减少，短桩和包边残片仍未完全去掉。以下两张显示同一源模型、同一相机方向。</p><div class="images"><figure><img src="../semantic_parts_20261113/corduroy_sofa/group_2_front.png" alt="改进前靠枕带长条"><figcaption>改进前</figcaption></figure><figure><img src="delivery/corduroy_sofa/group_3_front.png" alt="改进后靠枕仍有短小残片"><figcaption>改进后，仍待修正</figcaption></figure></div></article>'''
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>部件边界改进与真实复测</title><style>body{{font:16px/1.7 system-ui,sans-serif;margin:0;background:#f4f5f9;color:#24283a}}main{{max-width:1200px;margin:auto;padding:28px}}article,.intro{{margin:24px 0;padding:24px;background:white;border:1px solid #e1e3ee;border-radius:14px}}h1{{font-size:30px;line-height:1.3}}h2{{font-size:22px}}.images{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}figure{{margin:0}}img{{max-width:100%;height:auto;border-radius:8px}}figcaption{{font-size:13px}}a{{color:#6541bc;overflow-wrap:anywhere}}.badge{{background:#ede7ff;padding:12px;border-radius:8px}}.bad{{border-left:4px solid #b45309;padding-left:14px}}@media(max-width:700px){{main{{padding:14px}}article,.intro{{padding:16px}}.images{{grid-template-columns:1fr 1fr}}h1{{font-size:24px}}}}@media(max-width:420px){{.images{{grid-template-columns:1fr}}}}</style><main><h1>部件边界改进：减少误归属，保留不确定区域</h1><div class="intro"><p class="badge">4 件家具真实识别 · {sum(counts.values())} 项 Python 测试通过 · {len(validation)} 个 GLB 零错误/零警告</p><p class="bad">仍未完成准确的全自动部件拆分。坐垫与座架尚未分开，短小残片仍在；灰色区域表示未确认。</p><p><a href="http://127.0.0.1:8001/?job={ui['job']}">打开灯芯绒沙发演示</a> · <a href="../../docs/SEMANTIC_BOUNDARY_REVIEW_2026-11-13.md">详细报告</a> · <a href="verification.json">可复核的数据</a></p></div>{comparisons}{''.join(cards)}<article><h2>真实网页复测</h2><img src="ui_boundary_desktop.png" alt="AI 分组结果与未确认区域说明"><img src="ui_boundary_material.png" alt="整组换材质复测"><p><a href="ui_results.json">浏览器结果</a></p></article><article><h2>圆桌：错误候选已拒绝</h2><p>原始候选把大块支撑结构也叫作桌面。保护检查拒绝采用；原版本保留。</p><a href="api_runs_validated.json">查看实际状态、409 拒绝及 404 隐藏预览记录</a></article></main></html>'''
(OUT/'index.html').write_text(page,encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
