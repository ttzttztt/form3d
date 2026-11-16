# -*- coding: utf-8 -*-
"""Evidence-derived delivery report; reconstruction and source observations separated."""
import hashlib,html,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/complete_cushion_20261112'
def read(file):return json.loads((OUT/file).read_text(encoding='utf-8'))
run=read('actual_run.json');browser=read('browser_results.json');highlight=read('highlight_browser.json');diag=read('initial_diagnosis.json');exports=read('export_geometry_check.json');validation=read('gltf_validation.json');renders=read('renders.json');e=run['steps'][0]['evidence'];be=browser['completion']
assert not browser.get('failure') and not browser['errors'] and not highlight.get('failure') and not highlight['errors'];assert len(renders)==24;assert len(validation)==5 and all(v['errors']==0 for v in validation)
tests={}
for name in ('api_tests','part_tools','advanced','furniture','solid_unit'):
    file={'api_tests':'api_tests_final.log','solid_unit':'solid_unit_final.log'}.get(name,name+'_final.log');s=(OUT/file).read_text(encoding='utf-8');m=re.search(r'Ran (\d+) tests?',s);assert m and re.search(r'^OK\s*$',s,re.M);tests[name]=int(m[1])
source=ROOT/'.data/jobs/6be16d93f7544ac79c5f09cb3be507fa/model.glb';recorded=json.loads((source.parent/'local_summary.json').read_text(encoding='utf-8'))['model_sha256'];assert hashlib.sha256(source.read_bytes()).hexdigest()==recorded
def mdtable(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n'+'\n'.join('| '+' | '.join(map(str,r))+' |' for r in rows)
metrics=[['三角面',diag['selected_surface']['triangles'],e['part']['triangles'],be['part']['triangles']],['开口边',diag['selected_surface']['boundary_edges'],e['part']['boundary_edges'],exports['browser_cushion_export.glb']['boundary_edges']],['非流形边',diag['selected_surface']['nonmanifold_edges'],e['part']['nonmanifold_edges'],exports['browser_cushion_export.glb']['nonmanifold_edges']],['闭合',False,e['part']['watertight'],exports['browser_cushion_export.glb']['watertight']]]
summary={'acceptance_date':'2026-11-13','started_date':'2026-11-12','python_tests':tests,'python_total':sum(tests.values()),'api_job':run['job'],'demo_job':browser['job'],'part':e['part'],'body':e['remainder'],'browser_part':be['part'],'export_geometry':exports,'gltf_validation':validation,'source_glb_sha256':recorded,'source_unchanged':run['source_unchanged'],'part_moved_without_other_geometry_change':run['part_moved_other_geometry_unchanged'],'external_renders':len(renders),'claim_scope':'One actual chair, static untextured geometry. Closed editing candidates with inferred interfaces; not recovered real product parts.'}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
document=f'''# 坐垫完整拆分、推测接合面与拆装材质验收

验收日期：2026-11-13；工作始于 2026-11-12。[交互图片与原始记录](../experiments/complete_cushion_20261112/index.html)。[打开最终装配副本](http://127.0.0.1:8001/?job={browser['job']})。

## 结论

本轮按要求完成四步：检查原模型、扩展已有表面选取、补出缺失接合面、验证局部换材质和拆装导出。当前这把蓝椅可得到一个独立闭合的坐垫候选，椅身切口也闭合；坐垫能单独移动、换色、导出并重新打开。推测部分在模型元数据、部件清单与橙色高亮中明确标记。

这不是找回了真实坐垫结构。默认 API 候选约 **{e['part']['inferred_area_fraction']*100:.2f}% 的坐垫表面积为推测接合面**，主要在原模型没有独立面的侧部 / 背部。它们由轮廓与范围构造，不能当成实物测量。原始图生 3D 的形变、支撑腿问题仍保留，未训练或更换生成模型。功能性闭合和导出通过；商品还原、制造及真实装配没有验收。

## 1. 原模型诊断

原始生成任务 `6be16d93f7544ac79c5f09cb3be507fa` 有 {diag['source']['triangles']:,} 面，是一个连通网格。坐垫、扶手、靠背没有独立实体边界。原模型没有普通开口边，但有 2 条非流形边，因此不能笼统称为完全闭合。

上轮保存的坐垫表面有 {diag['selected_surface']['triangles']:,} 面、{diag['selected_surface']['boundary_edges']:,} 条开口边。按面积统计，朝后表面占比为 0，朝下约 {diag['selection_normal_area']['bottom']*100:.2f}%；这只是法向方向统计，不是识别准确率。移开后露洞来自选区本身未闭合。

新操作前只焊接重复位置、删除两张索引塌缩 / 重复的零面积面，使本例源网格通过闭合检查；原始 GLB 不改写。未自动填掉输入模型原本缺失的孔洞，单元测试中缺一张面的源模型会被拒绝。

## 2. 如何形成完整候选

1. 用已选表面或已保存的表面部件定位来源，找回同一原始网格的其余表面。
2. 从选区投影构造凸轮廓，并加入顶面支撑约束；绿色三维外框限制最大范围。它不是新的语义识别模型，仍需检查正面、侧面和底面。
3. 沿范围与轮廓精确切分三角面，保留范围内已有底面等表面，给坐垫和椅身各增加一份方向相反的接合面。
4. 检查切口交点，细分共线边以消除 T 形连接；验证坐垫单连通、双方闭合和朝向一致，再检查 GLB 单精度存储后是否仍闭合。
5. 原有表面与推测接合面分别保存为两个网格，共同属于同一个逻辑部件，因此换材质、移动和导出会一起作用。

默认 API 本例使用 {e['cut_planes']} 个切割平面。原有外表面切分的相对面积误差为 {e['source_surface_area_relative_error']:.3g}，两侧体积和相对误差为 {e['volume_partition_relative_error']:.3g}。这些是数值守恒检查，不是照片相似度，也不证明没有所有类型的自相交。

## 3. 实测结果

{mdtable(['指标','旧表面部件','API 默认候选','浏览器移动后导出'],metrics)}

API 椅身：{e['remainder']['triangles']:,} 面，开口边 {e['remainder']['boundary_edges']}、非流形边 {e['remainder']['nonmanifold_edges']}，闭合且单连通。原始坐垫表面在轮廓和外框中保留的面积比例为 {exports['retained_guide_surface_area_fraction']*100:.6f}%；这只说明所测源表面被保留，不衡量语义正确性。

闭合检查按逻辑部件合并原有表面和接合面后进行，使用 8 位小数的位置焊接；两份面组各自不是完整实体。完整 glTF 校验和几何闭合检查是分开执行的。

API 默认副本 `{run['job']}` 与浏览器副本 `{browser['job']}` 独立。浏览器实际编辑并重填过范围数值，浮点边界略有变化，所以三角面数不同；没有把两个副本的数据混成一次测量。默认 API 重建耗时 {run['steps'][0]['seconds']:.3f} 秒，属于本机单次记录，不是性能基准。

## 4. 目测与未通过的试跑

![旧表面、完整候选和推测区域的四向对照](../experiments/complete_cushion_20261112/part_comparison.png)

每行分别为前侧、后侧、底面、侧面；每列为旧表面、完整候选、推测区域诊断（橙色）。图像为独立 Blender 导入后的渲染，做了显示归一化，没有拟合原图相机。

初版矩形外框可以闭合，但会带入不合理的方块边角；**初版外观没有通过**。已保留到 `box_trial/`，其 side / under 渲染不能作为最终效果宣传。最终增加轮廓与顶面约束，减少了这些边角。仍能看见切分痕迹和近似侧背形状，没有恢复真实面料包边、缝线、圆角或内部骨架。用户仍需核对。

![原图、原生成模型、装配与移开检查](../experiments/complete_cushion_20261112/assembly_comparison.png)

## 5. 换材质、移动、导出

- 独立材质测试：只改变坐垫组的原有表面和推测接合面两份网格，椅身材质签名保持不变。
- 移动测试：沿世界 Z 轴移动 1.8 模型单位，椅身三角面坐标不变；坐垫逐面坐标与预期位移相符。没有把该单位解释为实物米数。
- 最初直接位移 float32 顶点，会使本例细面退化；初次浏览器导出有 {exports.get('earlier_vertex_move_trial',{}).get('nonmanifold_edges','未统计')} 条非流形边。该失败文件 `vertex_move_trial_export.glb` 和版本记录保留。
- 修复为独立节点变换，原顶点和其他属性字节保持不变。新的移动后浏览器导出重新加载，开口和非流形边均为 0，闭合与朝向检查通过。
- 最终演示恢复到了完整装配的局部换色版本，移动版本仍在历史中，可继续对照。

可下载：[独立坐垫](../experiments/complete_cushion_20261112/cushion_export.glb)、[浏览器移动后导出的坐垫](../experiments/complete_cushion_20261112/browser_cushion_export.glb)、[整体局部换色](../experiments/complete_cushion_20261112/complete_colored.glb)。

## 6. 界面用法

1. 选择坐垫表面，或者选择已保存的表面部件；切换“拆分部件”，填写部件名称。
2. 展开“完整部件：检查范围与补齐接合面”，点击“检查坐垫与原网格”。
3. 检查绿色外框，可调整 X / Y / Z 起止百分比；框内还会按表面轮廓收紧。旋转检查后点击“生成完整部件候选”。
4. 在“检查部件与拆解展示”中隔离坐垫、看背面和底面；勾选“显示推测接合面”查看橙色区域。
5. 换材质时选择整个坐垫组，移动或单独导出也使用这个范围。清单显示“含推测接合面”。

范围诊断和橙色高亮不创建版本；真正重建会创建独立版本，失败不发布。已有材质编辑、历史恢复和原图均保留。绿色框是外部约束，不意味着整个框内都属于坐垫。

## 7. Review 与验证

Python {sum(tests.values())} 项通过：API {tests['api_tests']}、部件工具 {tests['part_tools']}、高级编辑 {tests['advanced']}、家具工具 {tests['furniture']}、完整部件 {tests['solid_unit']}。覆盖孔洞保留、缺面拒绝、范围边界、推测标记、材质隔离、变换精度和版本保护。

真实浏览器完成范围诊断与编辑、重建、隔离与前底面检查、局部材质、实际移动、下载、恢复装配和 390px 宽度检查。橙色推测面高亮另测：不写版本、不发修改请求、切换原模型后不残留。详细步骤和错误列表见 `browser_results.json` 与 `highlight_browser.json`。

5 份 GLB 通过完整 glTF Validator，错误 {sum(v['errors'] for v in validation)}、警告 {sum(v['warnings'] for v in validation)}；独立 Blender 渲染 {len(renders)} 张。前端类型检查和生产构建通过，仍有主包体积超过 500kB 的提示。

Review 修复了：矩形补面的方块边角、切口共线交点、多个边同时细分、单精度导出闭合保护、旧选区诊断异步返回、移动导致细面退化，以及新依赖声明。早期失败测试日志、矩形试跑、移动失败文件均保留。

## 8. 支持范围与后续工作

本轮真实产品案例只有这一把蓝色扶手椅，几何单元测试使用球体、环形体等夹具，不能称作多家具产品级验收。当前完整重建支持静态、无 UV / 贴图、无顶点颜色且同一来源材质一致的网格；非均匀缩放网格明确拒绝。源模型本身缺面、范围包含多个实体或切口闭合失败时也会拒绝。

凸轮廓不适合任意凹形部件；近似接合面不等于真实隐藏表面。后续应在更多真实家具和视图中检验轮廓，并处理柔和圆角、复杂凹形、带贴图网格和更可靠的语义边界。当前没有制造尺寸、装配公差、自相交全面检测或真实背面照片验证。

原始证据：initial_diagnosis / actual_run / browser_results / export_geometry_check / gltf_validation / highlight_browser / summary.json。原始源 GLB SHA-256：`{recorded}`。旧选区源文件和原图未被改写。
'''
(ROOT/'docs/COMPLETE_CUSHION_REVIEW_2026-11-13.md').write_text(document,encoding='utf-8')
def table(headers,rows):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(h))+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r)+'</tr>' for r in rows)+'</tbody></table></div>'
def fig(file,label):return f'<figure><a href="{file}"><img loading="lazy" src="{file}" alt="{html.escape(label)}"></a><figcaption>{html.escape(label)}</figcaption></figure>'
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>完整坐垫拆分 · 2026-11-13</title><style>*{box-sizing:border-box}body{margin:0;background:#f3f5f9;color:#253249;font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1180px;margin:auto;padding:28px}section{background:#fff;border:1px solid #dde3ef;border-radius:14px;padding:24px;margin:24px 0}h1{font-size:30px}a{color:#5a3ca1}nav{display:flex;flex-wrap:wrap;gap:14px}.notice{background:#fff3d9;padding:18px;border-left:4px solid #d59832}.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:18px}figure{margin:0}img{width:100%;max-height:760px;object-fit:contain;background:#f5f6f9}figcaption{font-size:13px;color:#59667b}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:12px;border-bottom:1px solid #e3e6ef}th{background:#f0eef8}button{border:1px solid #cfc7e2;border-radius:6px;background:white;padding:9px 14px;cursor:pointer;color:#503985}button[aria-pressed=true]{background:#7050b5;color:white}code{overflow-wrap:anywhere}[hidden]{display:none!important}@media(max-width:600px){main{padding:14px}section{padding:16px}h1{font-size:25px}.images{grid-template-columns:1fr}}</style><main><h1>坐垫可以完整拆出了吗？</h1><p>2026-11-13 · 原网格诊断 → 轮廓范围 → 推测接合面 → 换材质与移动导出</p><nav>'''+f'<a href="http://127.0.0.1:8001/?job={browser["job"]}">打开最终装配副本</a><a href="../../docs/COMPLETE_CUSHION_REVIEW_2026-11-13.md">详细验收报告</a><a href="cushion_export.glb">下载独立坐垫</a><a href="summary.json">原始汇总</a></nav>'+f'''<p class="notice">本例的闭合拆装与移动后导出已通过。默认候选约 {e['part']['inferred_area_fraction']*100:.2f}% 表面积为推测接合面，主要在侧部、背部；不能当作恢复了真实零件或实物内部结构。此轮仅验收一把实际椅子。</p>
<section><h2>原来为什么像一层皮？</h2><p>原模型是一块连体网格，旧坐垫选区有 1,512 条开口边，没有独立背面。现在补选范围内原有表面，并为坐垫、椅身分别补接合面。</p>'''+table(['指标','旧表面','API 默认候选','浏览器移动后导出'],metrics)+'''</section><section><h2>看前面，也要看背面和底面</h2><p>橙色诊断区域是推测面。图片可点击放大，使用固定相机和显示归一化，未拟合原图相机。</p><nav><button data-view="front" aria-pressed="true">前侧</button><button data-view="back" aria-pressed="false">背面</button><button data-view="under" aria-pressed="false">底面</button><button data-view="side" aria-pressed="false">侧面</button></nav><div id="views">'''+''.join('<div class="view images" data-name="'+angle+'"'+(' hidden' if angle!='front' else '')+'>'+''.join(fig(f'{asset}_{angle}.png',label) for asset,label in [('old_surface','旧选区：开放表面'),('cushion_export','新候选：闭合部件'),('cushion_inferred_diagnostic','橙色：推测接合面')])+'</div>' for angle in ('front','back','under','side'))+'''</div><p>仍有切分边缘和近似侧背形状。没有还原真实缝线、面料包边和骨架。</p></section><section><h2>装配和移开检查</h2>'''+fig('assembly_comparison.png','原图、原生成模型、完整装配，以及向前移开的前 / 后 / 底面')+'''<p>原图生 3D 的支撑缺陷没有在本轮修复。闭合只说明本例编辑候选可作为独立网格使用。</p></section><section><h2>界面已经接通</h2><p>拆分部件 → 填写坐垫名称 → 完整部件：检查范围与补齐接合面 → 检查原网格。绿色框限制最大范围，内部还沿选区轮廓收紧。生成后可隔离部件、打开“显示推测接合面”检查橙色区域。</p><div class="images">'''+fig('browser_bounds.png','实际范围检查与可编辑百分比')+fig('browser_inferred_back.png','界面内隔离坐垫，橙色高亮推测接合面')+fig('browser_inferred_under.png','界面内底面检查')+'''</div></section><section><h2>换材质和导出</h2><p>仅改变坐垫组的材质，椅身材质不变。移动改为节点变换，保留原顶点数据；移动后下载、重新加载的坐垫仍闭合，开口边和非流形边均为 0。最终演示已恢复装配，移动版本留在历史中。</p><nav><a href="complete_colored.glb">整体局部换色 GLB</a><a href="browser_cushion_export.glb">移动后浏览器导出的坐垫</a></nav></section><section><h2>失败记录与边界</h2><p>初版矩形补面虽然闭合，但边角不合理，未作为最终外观通过。移动时直接改顶点还造成过细面退化。这些失败均保留。</p><details><summary>查看矩形试跑和移动失败</summary><div class="images">'''+fig('box_trial/part_comparison.png','未通过外观的矩形试跑，侧背呈方块')+'''</div><a href="vertex_move_trial_browser.json">早期移动版本记录</a> · <a href="vertex_move_trial_export.glb">早期失败导出</a></details><p>当前限制：只支持无贴图、无顶点颜色、同源材质一致的静态网格；非均匀缩放会拒绝。凹形零件、真实装配尺寸和制造用途尚未验证。</p></section><section><h2>验证依据</h2><p>'''+f"Python {sum(tests.values())} 项通过，5 份 GLB 完整校验，独立 Blender 渲染 24 张；真实浏览器覆盖选择范围、重建、换材质、移动下载、推测高亮与手机宽度。"+'''</p><details><summary>查看原始数据与日志</summary><ul>'''+''.join(f'<li><a href="{name}">{name}</a></li>' for name in ['initial_diagnosis.json','actual_run.json','browser_results.json','highlight_browser.json','export_geometry_check.json','gltf_validation.json','renders.json','summary.json','api_tests_final.log','part_tools_final.log','advanced_final.log','furniture_final.log','solid_unit_final.log','box_trial/actual_run.json','contour_translation_check_initial.log'])+'''</ul></details></section></main><script>for(const button of document.querySelectorAll('[data-view]'))button.addEventListener('click',()=>{for(const other of document.querySelectorAll('[data-view]'))other.setAttribute('aria-pressed',String(other===button));for(const panel of document.querySelectorAll('.view'))panel.hidden=panel.dataset.name!==button.dataset.view;});</script></html>'''
(OUT/'index.html').write_text(page,encoding='utf-8');print(json.dumps({'python_total':sum(tests.values()),'demo_job':browser['job'],'part_inferred_area_fraction':e['part']['inferred_area_fraction'],'renders':len(renders)},ensure_ascii=False))
