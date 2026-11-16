# -*- coding: utf-8 -*-
"""Evidence report with editing acceptance separated from appearance acceptance."""
import html,json,re,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/multifurniture_20261113'
def read(file):return json.loads((OUT/file).read_text(encoding='utf-8'))
cases=read('cases.json');runs={c['case']:read(c['case']+'_run.json') for c in cases};audit=read('final_audit.json');ui=read('ui_results.json');demo=read('demo_browser.json');validation=read('gltf_validation.json');renders=read('renders.json')
assert not ui.get('failure') and not ui['errors'] and not demo.get('failure') and not demo['errors'];assert len(audit)==5 and all(a['source_unchanged'] for a in audit);assert len(validation)==23 and all(v['errors']==0 and v['warnings']==0 for v in validation)
tests={}
for name,file in [('api','api_tests_final.log'),('parts','part_tools_final.log'),('advanced','advanced_final.log'),('furniture','furniture_final.log'),('cushion','cushion_tests_final.log'),('structural','structural_tests_final.log')]:
    s=(OUT/file).read_text(encoding='utf-8');count=re.search(r'Ran (\d+) tests?',s);assert count and re.search(r'^OK\s*$',s,re.M);tests[name]=int(count[1])
labels={'chair':'蓝椅底架','round_table':'圆桌','bookcase':'代码书柜','leather_sofa':'皮质沙发','corduroy_sofa':'灯芯绒沙发'}
notes={'chair':'底架作为一件闭合结构拆出；原坐垫几何和材质保留。腿部原有变形没有修复。','round_table':'桌面、公共连接座、两组支撑，共四组；不等于还原了原图真实装配数量。','bookcase':'利用已有 11 个独立网格整理命名，保留几何和 UV；没有新增补面。','leather_sofa':'闭合导出通过，但候选偏薄，并带入靠垫底部；外观未通过。','corduroy_sofa':'闭合导出通过，但仅取到局部偏薄的座面层；外观未通过。'}
rows=[];exports=[]
for c in cases:
    name=c['case'];r=runs[name];checks=r.get('individual_checks',[]);files=checks or r.get('exports',[]);exports.extend({'case':name,**e} for e in files);rows.append([labels[name],len(r['final_groups']),len(files),'操作通过' if r['acceptance']=='editing_checks_passed' else '外观未通过',notes[name]])
    source=ROOT/'.data/jobs'/c['job']/'prepared.png'
    if source.exists():shutil.copyfile(source,OUT/(name+'_reference.png'))
summary={'date':'2026-11-13','cases':rows,'python_tests':tests,'python_total':sum(tests.values()),'validated_glb_files':len(validation),'glb_errors':sum(v['errors'] for v in validation),'glb_warnings':sum(v['warnings'] for v in validation),'external_renders':len(renders),'individual_export_checks':len(exports),'case_sources':'Four image-generated models including the previously edited chair, plus one authored bookcase with existing parts.','acceptance_scope':'Three cases passed editing checks; two sofa candidates rejected for appearance. No measured semantic accuracy or physical reconstruction fidelity.'}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
def mdtable(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n'+'\n'.join('| '+' | '.join(map(str,row))+' |' for row in rows)
chair=runs['chair'];ce=next(s['evidence'] for s in chair['steps'] if s['operation']=='complete_part');table=runs['round_table'];te=[s['evidence'] for s in table['steps'] if s['operation']=='complete_part'];book=runs['bookcase']
sofa_rows=[]
for name in ('leather_sofa','corduroy_sofa'):
    e=next(s['evidence'] for s in runs[name]['steps'] if s['operation']=='complete_part');stats=runs[name]['exports'][0];sofa_rows.append([labels[name],e['part']['triangles'],f"{e['part']['inferred_area_fraction']*100:.2f}%",stats['boundary_edges'],stats['nonmanifold_edges'],'外观拒绝'])
document=f'''# 多家具部件拆分与材质拆装验收

日期：2026-11-13。[图片与原始证据总览](../experiments/multifurniture_20261113/index.html)。服务：[http://127.0.0.1:8001](http://127.0.0.1:8001)。

## 本轮结论

按已约定四项完成实测：椅子底架续拆、圆桌拆装、书柜已有部件整理、两款沙发坐垫方法复测。**椅子、圆桌、书柜通过本轮编辑操作验收；两款沙发未通过完整坐垫外观验收**，其当前编辑版本已标为 rejected，没有因为 GLB 合法或网格闭合而盖章为合格坐垫。

{mdtable(['案例','最终逻辑部件数','独立导出检查数','判定','具体结果'],rows)}

共五个模型：四份图片生成结果（其中椅子输入含此前已拆好并换色的坐垫），以及一个代码制作、已有部件的书柜。没有新训练语义模型，也没有新增杂乱场景数据集。

## 1. 椅子：保留坐垫，继续拆底架

工作副本 `{chair['job']}`，最终版本 `{chair['demo_version']}`。原坐垫未重新生成，几何逐三角面数组保持不变；界面材质测试也验证新底架选中范围不包含旧坐垫。

底架沿源模型下壳底面附近的连接高度提出范围，切分后坐垫、椅身与底架分别保留。底架 {ce['part']['triangles']:,} 面，开口 / 非流形边均为 0，新增接合面面积约 {ce['part']['inferred_area_fraction']*100:.2f}%。它是原生成网格中的一件连续底架，未强行拆成四根腿。此前推测面的 {ce['remainder']['inherited_inferred_triangles']:,} 张三角面继续标记为推测，没有伪装成实拍或原有面。

本轮可独立换材质、移动、导出并重新打开；原图生 3D 的细腿变形、锯齿与近似连接位置仍存在。本轮没有修复或重新生成金属支架。

## 2. 圆桌：桌面、连接座、两组支撑

工作副本 `{table['job']}`。先按观察到的桌面与底座收颈处分出桌面，再保留公共连接座，沿稳定下部分支划分支撑。最终为 **桌面 + 公共连接座 + 两组支撑，共四组**。

早期“3 个区域候选”包含公共连接处，不能解释为三根独立腿。本轮高度扫描和闭合拆分只稳定得到两组支撑，因此按两组记录；没有为凑数量补造第三组。真实装配数量与原图还原仍未验证。

四组均分别做了局部材质、单组位移、其他组逐面坐标不变和移动后导出重开检查，不是把整桌一起移动就算逐件通过。分界和新增接口是几何编辑建议，不是制造接缝。

## 3. 书柜：整理已有 11 件，保留 UV

工作副本 `{book['job']}`。现有代码模型本来就有 11 个闭合网格，整理为左侧板、右侧板、背板、底板、顶板、四块中间层板、前后踢脚板。没有使用坐垫补面方法，没有把已有零件说成 AI 新识别的结果。

重命名前后的各属性数组（含位置、法向和 UV）字节一致；世界坐标三角面逐项一致。十一件逐件换色、移开、导出、重开，其他部件不动。最终演示只对“层板 2”做了材质示例，其余保留原材质。

首次导出检查把 UV 接缝造成的重复顶点误判成开口，已经修正：**只在诊断副本中按几何位置焊接，忽略 UV / 法向差异；没有改动导出的 UV**。原始失败和重测日志保留。

## 4. 两款沙发：闭合通过，外观未通过

{mdtable(['案例','候选三角面','推测面面积比例','导出开口边','导出非流形边','外观结论'],sofa_rows)}

初次 SAM 真实点击中，皮质沙发候选范围过大，包含底座与靠垫；另一款的该次交互未产生有效请求记录，没有作为有效 SAM 分割结果统计。之后改用“坐面高度附近最大朝上连通区域”作为几何引导，不是 SAM 成功识别坐垫，更不是自动语义分割准确率。

几何引导可以生成闭合候选并进行材质、移动和导出，但侧视揭示两个问题：候选偏薄；皮质沙发还带入了靠垫底部。灯芯绒沙发只得到一个局部薄层，不能称为完整单座坐垫。两款当前编辑版本已通过 API 记录为“需要修改”。

已增加厚度约束不足提示：当引导区域主要是顶面、竖向跨度不足时，诊断明确提醒“无法可靠确定坐垫厚度，请补选侧面或明确底部范围”。提示不会补造真实底面，也不意味着调整一个数值就能解决语义串选。本轮结论是：**当前方法还不能直接推广为所有沙发的自动完整坐垫拆分**。

## 5. 已接入的产品改动

- “完整部件类型”增加底架 / 支撑、单根支脚（保留连接座）、桌面 / 板件；坐垫保留轮廓约束，结构部件改用连接高度或分支分界。
- 可以在已重建部件的另一组上继续操作；已有推测面与新范围相交时拒绝，未相交的旧推测面继续保留标记。
- 多个闭合支撑自动成为独立逻辑部件；另提供“按闭合连通体拆成独立部件”，不新增几何、不丢材质属性。
- 修复连续重建后默认选择把旧坐垫一起选中的风险：现在只选本次新建的组。真实浏览器已验证底架换材质不改变原坐垫。
- 结构模式的显式范围不再依赖自动分界成功，且完全位于源模型边缘的无效切割平面不会误标成推测面。
- 开放表面不再报告没有实体含义的体积值；厚度不足的软包选区显示提示。

操作路径：选择目标范围 → 拆分部件 → 填写名称 → 完整部件：检查范围与补齐接合面 → 选择类型 → 检查范围 → 生成候选。若已有多个部件，先选要继续拆的那组。结果仍需查看背面 / 底面，并用橙色高亮检查推测接合面。

## 6. 验证与 Review

Python **{sum(tests.values())} 项通过**：API {tests['api']}、部件工具 {tests['parts']}、高级编辑 {tests['advanced']}、家具工具 {tests['furniture']}、原坐垫 {tests['cushion']}、新增结构 {tests['structural']}。前端类型检查和生产构建通过，主包体积提示仍存在。

{len(exports)} 份独立部件导出检查（椅子 1、圆桌 4、书柜 11、沙发各 1），加五份装配 GLB，共 **{len(validation)} 份完整 glTF Validator 校验，错误和警告均为 0**。这些数据不覆盖任意模型，也不是外观准确率。

真实界面验证了在旧坐垫基础上续拆、结构模式诊断、新部件范围、局部材质、隔离、推测面高亮和 390px 宽度。五个最终任务的 accepted / rejected 状态也在浏览器读取验证。独立 Blender 渲染图记录于 renders.json；使用显示归一化与固定相机，未拟合照片相机。

Review 重点修复：推测面来源保留、后续拆分误选旧部件、共享连接处与独立腿计数混淆、UV 接缝的错误开口判定，以及显式范围被自动分界阻断。保留初次候选、失败请求、早期测试错误、厚度不合格的沙发候选和当前拒绝原因。

## 7. 边界与下一步

本轮完成的是编辑操作能力和这五个模型的实测。没有完成任意家具语义部件识别、真实隐藏表面恢复、装配公差、自相交全面检测或照片材质恢复。完整切割仍主要支持静态、无 UV / 顶点颜色、同源材质一致的网格；书柜用已有部件操作才能保留 UV，不受这个切割限制影响。

下一步应集中修正沙发的侧面约束、坐垫厚度和靠垫串选，保留失败样本作为验收依据。不能用闭合、面数增加或 API 成功替代外观检查。

源文件 SHA-256 已逐项复核，原模型与已验收版本均未覆盖。原始证据：cases / final_audit / ui_results / demo_browser / gltf_validation / summary，以及各模型的 `_run.json`。几何引导与 SAM 试跑分别记录，未混算。
'''
(ROOT/'docs/MULTIFURNITURE_PARTS_REVIEW_2026-11-13.md').write_text(document,encoding='utf-8')
def table(headers,rows):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(h))+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def fig(file,label):return f'<figure><a href="{file}"><img src="{file}" alt="{html.escape(label)}" loading="lazy"></a><figcaption>{html.escape(label)}</figcaption></figure>'
cards=[]
for c in cases:
    name=c['case'];r=runs[name];failed='sofa' in name;cards.append(f'<article class="case" data-outcome="{"failed" if failed else "passed"}"><h2>{labels[name]} · {"外观未通过" if failed else "编辑操作通过"}</h2><p>{notes[name]}</p><p><a href="http://127.0.0.1:8001/?job={c["job"]}">打开对应工作台</a> · 状态 {r["editor_review_status"]}</p><div class="images">'+fig(name+'_assembled_front.png','装配视图')+fig(name+'_moved_front.png','单件移开检查')+fig(name+'_part_side.png','侧视厚度 / 形状检查')+'</div>'+('<p class="warning">候选偏薄，不能当作完整坐垫。几何引导不是自动语义识别；此版本已标记需要修改。</p>' if failed else '<details><summary>逐件导出与检查结果</summary><ul>'+''.join(f'<li><a href="{e["export_file"]}">{html.escape(e["name"])}</a>：{e["triangles"]:,} 面，开口 {e["boundary_edges"]}，非流形 {e["nonmanifold_edges"]}；独立移动后重开通过。</li>' for e in r.get('individual_checks',[]))+'</ul></details>')+'</article>')
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>多家具拆装实测 · 2026-11-13</title><style>*{box-sizing:border-box}body{margin:0;background:#f3f5f9;color:#26334b;font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1200px;margin:auto;padding:28px}h1{font-size:30px}section,article{background:#fff;border:1px solid #dde3ee;border-radius:14px;padding:24px;margin:24px 0}nav{display:flex;flex-wrap:wrap;gap:14px}a{color:#5d3aa2}.warning{background:#fff2d7;border-left:4px solid #d99525;padding:16px}.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}figure{margin:0}img{width:100%;max-height:680px;object-fit:contain;background:#f5f7fa}figcaption{font-size:13px;color:#5e6b80}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:11px;text-align:left;border-bottom:1px solid #e2e6ef}th{background:#efedf8}button{padding:10px 16px;border:1px solid #c9c0df;border-radius:7px;background:white;color:#59388d;cursor:pointer}button[aria-pressed=true]{background:#6b4bb3;color:white}[hidden]{display:none!important}code{overflow-wrap:anywhere}@media(max-width:600px){main{padding:14px}section,article{padding:16px}.images{grid-template-columns:1fr}h1{font-size:25px}}</style><main><h1>其他家具，能稳定拆分了吗？</h1><p>2026-11-13 · 椅子底架、圆桌、书柜、两款沙发的实测与验收</p><nav><a href="http://127.0.0.1:8001">工作台</a><a href="../../docs/MULTIFURNITURE_PARTS_REVIEW_2026-11-13.md">详细报告</a><a href="summary.json">原始汇总</a></nav><p class="warning">三项通过编辑操作验收，两款沙发外观未通过。闭合和 GLB 合法不代表完整坐垫或真实零件还原。圆桌按当前网格稳定分成两组支撑，不补造第三组。</p><section><h2>本轮结果</h2>'''+table(['案例','逻辑部件数','独立导出数','判定','说明'],rows)+'''<p>四份图片生成结果（椅子含之前的编辑）与一个已有独立部件的代码书柜；不能把书柜整理算成 AI 新识别出 11 件。</p></section><nav aria-label="案例筛选"><button data-filter="all" aria-pressed="true">全部 5 件</button><button data-filter="passed" aria-pressed="false">编辑通过</button><button data-filter="failed" aria-pressed="false">外观未通过</button></nav><p id="visible-count" role="status">显示 5 件</p>'''+''.join(cards)+'''<section><h2>完整部件类型与连续编辑</h2><p>新增底架 / 支撑、单根支脚、桌面 / 板件；坐垫保留轮廓收紧。对已有重建模型续拆时保留原坐垫和既有推测标记。新操作只选中新建部件，避免换底架材质时连坐垫一起改变。</p><div class="images">'''+fig('ui_support_plan.png','实际界面：在已有坐垫的模型上检查底架范围')+fig('ui_support_material.png','实际界面：只改变新底架材质')+'''</div></section><section><h2>通过什么、没有通过什么</h2><p>'''+f"Python {sum(tests.values())} 项通过；{len(validation)} 份 GLB 完整校验零错误、零警告；{len(exports)} 份独立导出检查。所有源文件哈希保持不变。"+'''</p><p>两款沙发已经产生闭合候选，但侧视显示厚度不足，皮质沙发还带入了靠垫底部。因此已在工作台标为需要修改。新增顶面选区厚度不足提示，不把这些候选宣传成完整坐垫。</p><details><summary>原始结果与失败记录</summary><ul>'''+''.join(f'<li><a href="{file}">{file}</a></li>' for file in ['final_audit.json','chair_run.json','round_table_run.json','bookcase_run.json','leather_sofa_run.json','corduroy_sofa_run.json','ui_results.json','demo_browser.json','gltf_validation.json','renders.json','sofa_guides.json','sofa_guides_error.txt','sofa_geometry_guides.log','structural_runs.log','bookcase_retest.log','api_tests_final.log','part_tools_final.log','advanced_final.log','furniture_final.log','cushion_tests_final.log','structural_tests_final.log'])+'''</ul></details></section></main><script>for(const button of document.querySelectorAll('[data-filter]'))button.addEventListener('click',()=>{for(const other of document.querySelectorAll('[data-filter]'))other.setAttribute('aria-pressed',String(other===button));let count=0;for(const card of document.querySelectorAll('.case')){card.hidden=button.dataset.filter!=='all'&&card.dataset.outcome!==button.dataset.filter;if(!card.hidden)count++}document.querySelector('#visible-count').textContent='显示 '+count+' 件';});</script></html>'''
(OUT/'index.html').write_text(page,encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
