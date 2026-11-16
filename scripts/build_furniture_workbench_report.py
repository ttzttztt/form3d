"""Build a reproducible Chinese delivery report from actual run artifacts."""
import hashlib
import html
import json
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/furniture_workbench_20261112'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
runs=read('real_runs.json');geometry=read('geometry_preservation.json');ui=read('browser_checks.json');matrix=read('browser_furniture_matrix.json');guards=read('browser_guards.json');pixels=read('preview_export_pixels.json');new=read('new_generation_runs.json')+[read('engine_comparison.json')];newgroups=read('new_generation_group_checks.json')
assert len(runs)==8 and len(geometry)==8 and len(matrix['cases'])==8 and len(newgroups)==3
assert not any(r.get('failure') or r.get('errors') for r in (ui,matrix,guards))
assert all(c['original_unchanged'] for c in runs);assert all(g['source_unchanged'] and g['exact_triangles_preserved'] for g in newgroups)
NAMES={'round_table':'圆桌','alien_table':'外星人造型边桌','leather_sofa':'皮质沙发','corduroy_sofa':'灯芯绒沙发','white_cabinet':'白底拱形柜','scene_cabinet':'场景图拱形柜','official_chair':'官方示例餐椅','authored_bookcase':'代码建模书柜','accent_chair':'蓝色扶手椅','stone_table':'石材茶几 · TripoSR','stone_table_hunyuan':'同图石材茶几 · Hunyuan-mini'}
NOTES={'round_table':'桌面已包含外圆边、凸出底环和底面；中心连接处仍属于底座。底座可再提出支撑候选。','alien_table':'桌面与造型底座可分开编辑；造型底座没有进一步识别成真实装配零件。','leather_sofa':'按座部高度与上部位置生成区域，边界会跨过软包和靠垫；不能当作准确坐垫分割。','corduroy_sofa':'可覆盖各侧面的区域，但扶手、坐垫、靠背边界仍有混杂，需要涂抹修正。','white_cabinet':'目前是上中下区域，柜门、层板没有逐一识别；不能按真实柜门直接拆装。','scene_cabinet':'场景里的摆件仍已融入源网格；重新分组不能自动清除这些杂物。','official_chair':'区域覆盖全表面，但上部区域包含一部分坐面，不是准确椅背分割。输入为 TripoSR 官方示例。','authored_bookcase':'利用原有独立网格生成部件候选，比较清楚；源资产为已有代码模型，并非本轮图片推理结果。'}
VERDICTS={'accent_chair':'主体、坐垫和扶手大体可辨；细金属腿不完整、连接有扭曲，且只有灰色几何。未达到商品外观验收。','stone_table':'顶板与两个支撑可辨，但表面噪声和错误颜色明显，顶板厚度与支撑形状有偏差。未达到商品外观验收。','stone_table_hunyuan':'相较本轮 TripoSR，顶板轮廓和两个方形支撑更规整，可作几何草稿；石材纹理缺失，尺寸与隐藏面未核实，未达到完整商品外观验收。'}
review={'scope':'本轮人工查看固定前斜视角、背面/底部视角；没有实物或尺寸标定，没有照片相似度分数。','existing':[{'case':c['case'],'observation':NOTES[c['case']],'semantic_parts_accepted':False} for c in runs],'new':[{'case':c['case'],'job':c['job'],'observation':VERDICTS[c['case']],'product_appearance_accepted':False,'workflow_status':c['snapshot']['status'],'note':'工作台保留待审核；本轮报告不把可读 GLB 当作外观合格。'} for c in new]}
(OUT/'visual_acceptance.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
# Recreate contact sheets from the reviewed final outputs.
sheet=Image.new('RGB',(1440,390*8),'white');draw=ImageDraw.Draw(sheet)
for row,c in enumerate(runs):
    for col,stage in enumerate(('source_front','groups_front','groups_under','repair_front')):
        path=OUT/(c['case']+'_'+stage+'.png')
        if path.exists():sheet.paste(Image.open(path).convert('RGB'),(col*360,row*390+30))
        draw.text((col*360+8,row*390+8),c['case']+' / '+stage,fill='black')
sheet.save(OUT/'all_furniture_contact.jpg')
sheet=Image.new('RGB',(1080,390*len(new)),'white');draw=ImageDraw.Draw(sheet)
for row,c in enumerate(new):
    sheet.paste(Image.open(ROOT/'images'/c['filename']).convert('RGB').resize((360,360)),(0,row*390+30))
    draw.text((8,row*390+8),c['case']+' / reference',fill='black')
    for col,angle in enumerate(('front','under'),1):
        sheet.paste(Image.open(OUT/(c['case']+'_new_generation_'+angle+'.png')).convert('RGB'),(col*360,row*390+30));draw.text((col*360+8,row*390+8),'Actual output / '+angle,fill='black')
sheet.save(OUT/'new_generation_contact.jpg')
top=geometry[0]['top_surface_evidence'];repairs=[c for c in runs if c.get('repair_version')];assert len(repairs)==7
assert all(c['quality_after_repair']['whole_model']['watertight'] and c['quality_after_repair']['whole_model']['boundary_edges']==0 and c['quality_after_repair']['whole_model']['nonmanifold_edges']==0 for c in repairs)
table=[];repairtable=[]
for c in runs:
    groups=c['steps'][0]['groups'];table.append(f"| {NAMES[c['case']]} | {c['quality_before']['whole_model']['triangles']:,} | {len(groups)} | 保留 | {NOTES[c['case']]} |")
    before=c['quality_before']['whole_model'];step=next(s for s in c['steps'] if s['operation']=='repair_geometry')
    if step['status']==201:
        after=c['quality_after_repair']['whole_model'];ratio=max(p['max_displacement_ratio'] for p in step['manifest']['operation']['parts']);repairtable.append(f"| {NAMES[c['case']]} | {before['degenerate_faces']} → {after['degenerate_faces']} | {before['boundary_edges']} → {after['boundary_edges']} | {ratio*100:.4f}% | 新版本；闭合 |")
    else:repairtable.append(f"| {NAMES[c['case']]} | {before['degenerate_faces']} | 0 | 0 | 409：无安全变化，未发布 |")
generation=[]
for c in new:
    inf=c['snapshot']['report']['local_inference'];generation.append(f"| {NAMES[c['case']]} | {c['snapshot']['actual_engine']} | {c['snapshot']['metrics']['triangles']:,} | {inf['total_local_wall_seconds']:.3f} 秒 | {VERDICTS[c['case']]} |")
report=f'''# 家具部件与材质工作台：交付、复测与验收

日期：2026-11-12。运行环境：本机 Windows / FastAPI / React / Three.js / Blender 5.1.2；本轮不使用商业 API 密钥或云建模服务。

## 交付结论

五项已接通：完整表面的分组候选、部件清单与 3D 联动、合并与选区归属修改、即时材质预览与显式保存、质量检查与保守修复。新增两张用户图片的三次本地推理也已完成，并进行了同图引擎对照。

功能流程验收通过，商品级外观验收未全部通过。自动分组是几何编辑建议，沙发与柜子的边界仍较粗；修复只能小幅处理现有网格。薄腿、隐藏结构、真实尺寸、石材或布料纹理都不能据此宣称已还原。

入口：[可视化证据总览](../experiments/furniture_workbench_20261112/index.html) · [圆桌完整部件示例](http://127.0.0.1:8000/?job={runs[0]['test_job']})。

## 五项改动与使用方法

1. **完整分组候选**：在“拆分部件”中选家具品类，点击“生成完整分组候选”。已有独立网格优先保留；融合网格按几何结构或空间区域提出分组。每个三角面有且只有一个归属，包含背面、侧面和底面；“包含全表面”不等于“边界完全符合真实零件”。圆桌可选底座后再“尝试细分选中底座 / 支撑”。
2. **部件清单联动**：点击清单高亮整个逻辑部件；已有部件可在 3D 中点选，右侧同步编辑范围。尚未分组的模型仍可提出连续平面或连通片选区，遇到不明确的边界会拒绝，保留涂抹修正。
3. **修正归属**：勾选多个部件可合并；在 3D 上涂抹后，可命名“保存选区为新部件”，或选择“选区接收部件”再“移入接收部件”。默认只选看得到的表面，旋转后补选背面。操作不丢弃其余三角面。
4. **材质预览**：先选部件，再改颜色、表面参数或上传色彩/法线/粗糙度图；立即预览，支持撤销、重做和取消。只有“保存当前材质效果”才创建模型版本。切换范围或版本会取消未保存预览。原模型和旧版本保留；未保存预览不属于下载 GLB。
5. **检查与修复**：在“更多操作 → 检查与保守修复模型”检查当前版本。可清理不破坏拓扑的重复/退化面，或轻微平滑；原有开口可能是设计结构。带 UV/切线部件只允许安全清理。无法安全处理或无变化时拒绝发布，不伪造“修复成功”。

合并采用逻辑分组，保留多种原材质与节点变换，不执行焊接。忽略自定义分组信息的外部软件可能仍显示多个子网格。拆出或移动以完整三角面为单位，不新造封口或可制造实体。

## 测试样本与范围

八份已有家具模型来自四类家具；其中白底柜和场景柜是同产品不同来源，餐椅是官方示例，书柜是已有代码模型。本轮没有把这八份全部重新推理。另使用两张新的用户图片做三次推理，其中石材茶几做了两种引擎对照，不应算成三个新产品。

| 样本 | 原始三角面 | 初次候选组数 | 原面与坐标 | 实际观察与限制 |
| --- | ---: | ---: | --- | --- |
{chr(10).join(table)}

八个样本均经真实 API 执行分组、合并、拆出和移动选区。独立脚本将导出结果还原为世界坐标三角面多重集，比对 SHA：分组前后完全相同，原 GLB 哈希也不变；这项验证不包含有意移动顶点的修复操作。

圆桌专项：桌面共 {top['triangle_count']:,} 面；包含朝上面 {top['upward_faces']:,}、朝下面 {top['downward_faces']:,}、近竖直圆边面 {top['rim_faces_abs_y_below_0_5']:,}。针对本样本已观察到的外圈区域，误留底座的圆环面为 {top['outer_rim_faces_in_base']}。另以底部渲染检查了圆环完整性；中心安装连接仍属于底座。

![完整表面候选与底面](../experiments/furniture_workbench_20261112/round_table_groups_under.png)

分组图使用人工指定的诊断颜色，仅帮助看边界，不是从照片恢复的材质；源模型和修复渲染保留原材质。相机为固定检查视角，没有拟合原照片。

## 自动化与浏览器验收

- Python：API/合同与原流程 34 项、资产操作回归 9 项、家具分组与修复 12 项，均通过，共 55 项。日志分别为 `api_tests_final.log`、`advanced_tests.log`、`furniture_tests.log`。
- 材质预览状态：7 项断言通过，覆盖替换、染色、透明、局部范围、原材质不可变及取消恢复。见 `material_preview_unit.json`。
- 原有选面算法复测：点选 6 个合成用例与实际模型探测、可见表面选择 9 个用例完成；不明确的软体或花瓶点选仍会拒绝。见 `point_algorithm.log`、`visibility_algorithm.log`。
- 浏览器主流程 {len(ui['checks'])} 项通过：真实画面变化与撤销/重做/取消、清单和点选联动、仅选中部件保存、三种 PBR 图、合并后多材质恢复、涂抹拆出和移动、质量检查、390px 窄屏无横向溢出。见 `browser_checks.json`。
- 八个家具的清单选择、局部换色预览、取消后像素恢复、预览不新增版本均通过；这些页面未出现未捕获 JS 异常。见 `browser_furniture_matrix.json`。
- 上传中锁定编辑范围、选面工具和材质参数；非法 UV 参数禁止保存；带 UV 的轻微平滑请求返回 409，当前版本与版本数不变。见 `browser_guards.json`。
- 前端生产构建通过。仍有约 900kB 主 JS 包的体积提示，不能据此宣称已完成前端性能优化。

三张合成 PBR 贴图（包含非平坦法线图）、2 倍重复、37° 旋转的预览/重载导出对照：8 位 RGB 全画面平均绝对差 {pixels['mean_absolute_rgb_difference_8bit']:.6f}，固定模型区域平均差 {pixels['roi_mean_absolute_rgb_difference_8bit']:.6f}；任一通道差值大于 10 的像素占比为 {pixels['fraction_pixels_with_any_channel_over_10']:.6f}。这是同浏览器、同相机的一组渲染一致性测试，不是照片相似度，也不是全部材质效果证明。

## 保守修复结果

复测后七份修复模型均保持闭合、边界边为 0、非流形边为 0；没有丢面，部分极小面通过轻微移动脱离退化阈值，部分仍保留。顶点移动上限为部件局部包围盒对角线的 0.2%，下表是各样本实测最大移动比例。该阈值不是实物误差。

| 样本 | 退化面：前 → 后 | 边界边：前 → 后 | 最大移动比例 | 发布结果 |
| --- | --- | --- | --- | --- |
{chr(10).join(repairtable)}

平滑后的外观差异较小，不能当作更接近原商品的证据。模型没有新长出柜门、桌腿或靠垫，也没有自动补洞。安全修复用了独立测试任务，`real_runs.json` 的 `repair_test_job` 记录其任务号。

## 新图片生成与真实外观验收

两张图片为 `images/0012_Accent Chair.png` 和 `images/0043_Aristea Travertine Geometric Coffee Table.jpg`。实际记录如下；耗时是本机这一轮的全流程测量，不承诺其他机器或图片的速度。

| 输出 | 实际引擎 | 三角面 | 本地处理总耗时 | 看图验收 |
| --- | --- | ---: | ---: | --- |
{chr(10).join(generation)}

三次推理均到达 `awaiting_review`，文件结构和启发式几何筛查通过；工作台没有被自动标成外观合格。三份输出另在隔离副本上试了完整分组，均成功且世界三角面不变；椅子 3 组，两种茶几各 2 组。分组成功不能抵消源几何或纹理缺陷。

![新图片与两种引擎实际输出](../experiments/furniture_workbench_20261112/new_generation_contact.jpg)

本轮支持的结论是：这张石材茶几可以优先使用 Hunyuan-mini 的几何草稿，再补真实石材贴图。不能仅凭这一张图，宣称某个引擎对所有桌子更好。蓝色扶手椅的细腿还需要更好的重建或人工处理。

## Review 发现与处理

1. **圆桌底环遗漏**：最初用最大平坦底面覆盖了更低的桌面/底座收缩分界，凸出圆环误归底座。保留较低的可信分界，重新跑八样本、独立世界三角面核对、圆桌圆环检查与浏览器验收。旧记录为 `real_runs_before_rim_fix.json`。
2. **清理引入新开口**：初版删除极小面使六个闭合样本出现边界。现先检查删除的拓扑后果，有风险便保留原面，只尝试安全平滑；发布前再次检查边界、闭合性、非流形与退化面。增加闭合曲面退化面回归用例，重跑八份修复。旧结果以 `*_before_topology_fix*` 与旧版本保留，不属于最终推荐输出。
3. **材质替换与预览差异**：复查后，替换模式使用新的标准 PBR 材质，清除原发光、额外物理材质效果与旧贴图；染色模式保留原效果。上传法线图重置 normal scale，贴图栅格转换在预览与导出间共用。补测非平坦法线后发现切线基差异，预览现与导出一致生成顶点切线，并经非平坦法线、37° 旋转对照检查。旧差异记录见 `preview_export_nonflat_before_tangent_fix.json`，最终看 `preview_export_pixels.json`。
4. **异步误操作**：上传/保存时禁用范围和选面；保存前校验纹理载入与 UV 参数。多材质取消逐项恢复，不把第一种材质覆盖整个合并组。
5. 首次浏览器主测因测试脚本的旧文案定位失败，防护测试也曾因测试路由释放顺序失败；修正脚本后复测通过。失败日志保留，没有把失败的那一轮计为通过。
6. **倾斜模型的桌面分界**：TripoSR 新茶几的上表面相对模型 Y 轴约倾斜 17°，原高度分界切过桌面。现对有足够平面证据的轻度倾斜桌面，沿其法线分类，实际网格坐标不变。增加倾斜桌面回归，并核对八份已有模型的逐分组世界三角面保持原结果，见 `current_proposals_regression.json`。表面噪声和真实零件边界仍需人工检查。

## 当前边界与后续重点

几何分组没有使用新的语义 3D 部件识别模型。2D Grounding DINO/SAM 用于图片目标检测/分割，不能自动证明某一片 3D 网格就是柜门或坐垫。当前空间候选在柜子、软体家具上仍不够精细。

接下来最有价值的是提升软体/柜门的语义部件边界、保留细腿和真实结构、为曲面做正确 UV 展开，以及接入真实材质素材。当前平面 UV 只是可用回退，曲面会拉伸；单图隐藏面与尺寸仍有推测。

## 文件、日志与复现

完整证据目录：`experiments/furniture_workbench_20261112/`。当前结果看 `real_runs.json`、`geometry_preservation.json`、`visual_acceptance.json`、`new_generation_runs.json`、`engine_comparison.json`、`external_renders.json` 和各浏览器结果。历史失败、原图、原始 GLB 均保留。

主要实现：`scripts/furniture_parts.py`、`scripts/mesh_quality.py`、`services/api/asset_editor.py`、`services/api/textures.py`、`apps/web/src/AssetEditor.tsx`、`apps/web/src/Viewer.tsx`、`apps/web/src/materialPreview.ts`。本轮未提交 Git、未推送、未部署外网。

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests
.venv-hunyuan/Scripts/python.exe scripts/test_asset_advanced.py
.venv-hunyuan/Scripts/python.exe scripts/test_furniture_workbench.py
node scripts/test_material_preview.mjs
npm run build
node scripts/test_furniture_workbench_ui.mjs
node scripts/test_furniture_guards.mjs
```

浏览器脚本依赖运行中的 `http://127.0.0.1:8000` 和记录的隔离任务；脚本会在测试任务内创建新版本。重新运行推理脚本会创建新的 GPU 任务，不是只读检查。
'''
(ROOT/'docs/FURNITURE_WORKBENCH_REVIEW_2026-11-12.md').write_text(report,encoding='utf-8')
# Local report: no CDN, no generated fidelity scores.
cards=[]
for c in runs:
    name=c['case'];cards.append(f'''<article data-category="{c['category']}"><h3>{html.escape(NAMES[name])}</h3><p>{html.escape(NOTES[name])}</p><div class="pictures"><figure><img src="{name}_source_front.png"><figcaption>源模型 · 原材质</figcaption></figure><figure><img class="group-image" src="{name}_groups_front.png" data-front="{name}_groups_front.png" data-under="{name}_groups_under.png"><figcaption>候选分组 · 诊断色</figcaption></figure><figure><img src="{name}_repair_front.png" onerror="this.parentElement.innerHTML='未发布修复版本'" ><figcaption>最终安全修复 · 原材质</figcaption></figure></div><button class="angle">切换分组的正面 / 底部</button> <a href="http://127.0.0.1:8000/?job={c['test_job']}">打开 3D 工作台</a> · <a href="{name}_auto.glb">下载分组 GLB</a></article>''')
newcards=[]
for c in new:
    name=c['case'];newcards.append(f'''<article><h3>{NAMES[name]}</h3><p>{VERDICTS[name]}</p><div class="pictures"><figure><img src="../../images/{html.escape(c['filename'],quote=True)}"><figcaption>输入原图</figcaption></figure><figure><img src="{name}_new_generation_front.png"><figcaption>真实输出 · 前斜视角</figcaption></figure><figure><img src="{name}_new_generation_under.png"><figcaption>真实输出 · 底部 / 背面</figcaption></figure></div><a href="http://127.0.0.1:8000/?job={c['job']}">打开待审核模型</a></article>''')
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>家具工作台：实测与验收</title><style>body{margin:0;background:#f4f6fa;color:#192236;font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1240px;margin:auto;padding:30px}h1{font-size:32px}h2{margin-top:42px}article,.summary{background:white;border:1px solid #dbe0e8;border-radius:14px;padding:24px;margin:20px 0}p{max-width:1000px}.pictures{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}figure{margin:0}img{width:100%;object-fit:contain;background:#eef1f6;border-radius:8px}figcaption{font-size:14px;color:#596477}button,select,a{font:inherit}button,select{padding:8px 12px;border:1px solid #cbd2df;border-radius:8px;background:#fff;cursor:pointer}a{color:#5143b8}code{font-size:13px;overflow-wrap:anywhere}.warning{border-left:4px solid #b87322;padding-left:18px}[hidden]{display:none!important}@media(max-width:700px){main{padding:15px}.pictures{grid-template-columns:1fr}h1{font-size:26px}}</style><main><h1>家具部件与材质工作台</h1><p>2026-11-12 · 五项功能交付与真实测试</p><div class="summary"><strong>流程验收通过；自动部件边界和源模型外观仍有限制。</strong><p>8 份已有家具编辑实测，2 张新图片、3 次本地推理。55 项 Python 测试通过，8 份家具的浏览器预览/取消通过。源 GLB 保留；这里没有照片相似度分数。</p><p><a href="../../docs/FURNITURE_WORKBENCH_REVIEW_2026-11-12.md">阅读详细报告、缺陷与验证方法</a></p></div><p class="warning">彩色分组图用于看边界；全表面覆盖不等于准确语义分割。修复不会补出缺失零件。源模型与修复使用原材质，检查相机未拟合照片。</p><h2>八份已有家具：源模型、候选边界、安全修复</h2><label>筛选品类 <select id="filter"><option value="all">全部</option><option value="table">桌子</option><option value="chair">椅子</option><option value="sofa">沙发</option><option value="cabinet">柜子 / 架子</option></select></label>'''+''.join(cards)+'''<h2>新图片与实际生成结果</h2><p>三个输出均保留待审核；未标成商品外观合格。石材茶几的两次输出来自同一张照片。</p>'''+''.join(newcards)+'''<h2>即时材质预览与导出</h2><div class="pictures"><figure><img src="ui_texture_preview.png"><figcaption>保存前的三贴图预览</figcaption></figure><figure><img src="ui_texture_saved.png"><figcaption>保存后重新载入 GLB</figcaption></figure><figure><img src="ui_texture_difference_x4.png"><figcaption>像素差 ×4，仅作一致性检查</figcaption></figure></div><h2>可追溯的原始记录</h2><p><a href="real_runs.json">编辑与安全修复</a> · <a href="geometry_preservation.json">世界三角面核对</a> · <a href="browser_checks.json">浏览器主流程</a> · <a href="browser_furniture_matrix.json">八家具预览</a> · <a href="browser_guards.json">错误防护</a> · <a href="visual_acceptance.json">看图验收</a> · <a href="preview_export_pixels.json">预览 / 导出像素</a></p></main><script>document.getElementById('filter').onchange=e=>document.querySelectorAll('[data-category]').forEach(c=>c.hidden=e.target.value!=='all'&&c.dataset.category!==e.target.value);document.querySelectorAll('.angle').forEach(b=>b.onclick=()=>{const im=b.closest('article').querySelector('.group-image');im.dataset.underView=im.dataset.underView==='1'?'0':'1';im.src=im.dataset.underView==='1'?im.dataset.under:im.dataset.front})</script></html>'''
# Bookcase deliberately has no repair; render a plain truthful placeholder.
page=page.replace('<img src="authored_bookcase_repair_front.png" onerror="this.parentElement.innerHTML=\'未发布修复版本\'" >','<p>无安全变化，未发布修复版本</p>')
(OUT/'index.html').write_text(page,encoding='utf-8')
files=['scripts/furniture_parts.py','scripts/mesh_quality.py','apps/web/src/materialPreview.ts','apps/web/src/AssetEditor.tsx','services/api/asset_editor.py','services/api/textures.py']
(OUT/'delivery_manifest.json').write_text(json.dumps({'date':'2026-11-12','source_models_preserved':True,'existing_furniture_samples':8,'new_input_images':2,'new_inference_runs':3,'python_tests_passed':55,'semantic_parts_guaranteed':False,'files':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}},ensure_ascii=False,indent=2),encoding='utf-8')
print('Report and dashboard written from actual run records.')
