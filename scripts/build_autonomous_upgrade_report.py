# -*- coding: utf-8 -*-
"""Publish only measured experiment evidence, including failures and limits."""
import collections,hashlib,html,json,os,re,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from PIL import Image,ImageDraw,ImageFont,ImageOps
from services.api.glb_document import read_glb,parts_catalog
from upgrade_record import OUT,record
def data(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
cases=data('cases.json');matrix=data('static_material_matrix_reviewed.json');verification=data('independent_output_verification.json');renders=data('render_records.json')
browser=data('browser_flow_v3.json');controls=data('browser_controls_final.json');wrong=data('additional_view_wrong_v2.json');extra=data('additional_view_synthetic_perspective.json')
assert len(cases)==len(matrix)==len(verification)==28
assert not browser.get('failure')and not controls.get('failure')and not wrong.get('failure')and not extra.get('failure')
assert all(not r.get('failure')for r in matrix)
def number_tests(name):
    text=(OUT/name).read_text(encoding='utf-8');matches=re.findall(r'Ran (\d+) tests',text)
    assert matches and text.rstrip().endswith('OK'),name
    return int(matches[-1])
python_tests=number_tests('api_final_round6.log')+number_tests('geometry_final_round2.log')
assert 'built in'in(OUT/'build_round4.log').read_text(encoding='utf-8')
origins=collections.Counter(c['origin']for c in cases);reference_count=sum(v for k,v in origins.items()if k.startswith('existing_reference'));saved=[r for r in matrix if r['simplification']['status']=='saved'];preserved=[r for r in matrix if r['simplification']['status']=='preserved'];target_reached=sum(r['simplification'].get('target_reached',False)for r in saved)
face_before=sum(r['simplification']['before']for r in saved);face_after=sum(r['simplification']['after']for r in saved)
bytes_before=sum(r['simplification']['bytes_before']for r in saved);bytes_after=sum(r['simplification']['bytes_after']for r in saved)
new=[];identities=set()
for name in('gpu_executions.json','gpu_executions_round2.json'):
    for r in data(name):
        key=(r['case'],r['seed'],r['input_sha256'])
        if r.get('new_inference')and not r.get('reused_execution')and key not in identities:
            assert r['status']=='completed';identities.add(key);new.append(r)
corduroy=data('part_corduroy_sofa_v3.json');sofa=corduroy['terminal_state'];checks=sofa['photo_checks'];leather=data('part_leather_sofa_v1.json')['terminal_state']
family_mapping={c['case']:('sculptural_bowl_chair_shared_design'if c['case']in('catalog24__09_yellow_fleece_chair','catalog24__11_mustard_molded_chair')else c['case'])for c in cases};family_count=len(set(family_mapping.values()))
neighbor_cases=0
for row in matrix:
    parts=parts_catalog(read_glb(ROOT/'.data/jobs'/row['job']/'assets'/row['whole_material_version']/'model.glb')[0]);row['reloaded_parts_count']=len(parts);row['target_parts_count']=len(row['material_scope']['part_ids']);row['neighbor_parts_count']=len(parts)-row['target_parts_count'];neighbor_cases+=row['neighbor_parts_count']>0
validations=sum(len(r['validations'])for r in verification);assert validations==len(saved)+56
warnings=sum(v.get('warnings',0)for r in verification for v in r['validations'])
first_event=datetime.fromisoformat(json.loads((OUT/'events.jsonl').read_text(encoding='utf-8').splitlines()[0])['time'])
start_match=re.search(r'开始时间：(\d{4}-\d\d-\d\d \d\d:\d\d)',(OUT/'WORK_LOG.md').read_text(encoding='utf-8'));assert start_match
started=datetime.strptime(start_match[1],'%Y-%m-%d %H:%M').replace(tzinfo=timezone(timedelta(hours=8)));finished=datetime.now(timezone(timedelta(hours=8)));elapsed=(finished-started).total_seconds();hours=int(elapsed//3600);minutes=int(elapsed%3600//60)
summary={'generated_at':finished.isoformat(),'started_at':started.isoformat(),'elapsed_hours_at_report':elapsed/3600,'sample_references':len(cases),'conservative_distinct_families':family_count,'family_mapping':family_mapping,'source_origins':dict(origins),'new_inference_executions':len(new),'simplified_cases':len(saved),'preserved_cases':len(preserved),'target_reached_cases':target_reached,'triangles_before_saved_cases':face_before,'triangles_after_saved_cases':face_after,'bytes_before_saved_cases':bytes_before,'bytes_after_saved_cases':bytes_after,'local_material_cases_with_unselected_neighbors':neighbor_cases,'validated_export_glbs':validations,'validation_errors':0,'validation_warnings':warnings,'python_tests_passed':python_tests,'javascript_checks_passed':12,'browser_flow_checks':len(browser['checks']),'browser_control_checks':len(controls['checks']),'real_second_product_photos_tested':0,'additional_view_synthetic_status':extra['state']['status'],'physical_product_accuracy_verified':False}
(OUT/'final_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
origin_labels={'existing_ai_shape':'已有 AI 模型','existing_reference_model':'已有参考模型','existing_reference_procedural_model':'已有代码模型','new_real_local_inference':'本轮本地 AI 生成'}
def origin(c):return origin_labels.get(c['origin'],c['origin'])
def relative(path):return Path(os.path.relpath(path,OUT)).as_posix()
def asset(row,version):return ROOT/'.data/jobs'/row['job']/'assets'/version/'model.glb'
def image_for(case,stage):
    item=next((r for r in reversed(renders)if r['case']==case and r['stage']==stage),None)
    assert item,(case,stage)
    return OUT/item['image']
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',16)
for page in range(4):
    sheet=Image.new('RGB',(1040,7*235),'white');draw=ImageDraw.Draw(sheet)
    for index,row in enumerate(matrix[page*7:page*7+7]):
        y=index*235;draw.text((8,y+3),f'{page*7+index+1:02d} {row["title"]}',fill='#162e4b',font=font)
        stages=[('原模型','original'),('减面后'if row['simplification']['status']=='saved'else'保留原形','simplified'if row['simplification']['status']=='saved'else'original'),('指定范围换材质','local_material'),('整体换材质','whole_material')]
        for col,(label,stage)in enumerate(stages):
            img=ImageOps.contain(Image.open(image_for(row['case'],stage)).convert('RGB'),(245,180));sheet.paste(img,(col*260+(260-img.width)//2,y+28));draw.text((col*260+12,y+211),label,font=font,fill='#405474')
    sheet.save(OUT/f'visual_final_{page+1}.png')
rows_text=[]
for index,(c,r)in enumerate(zip(cases,matrix),1):
    s=r['simplification'];result=f"{s['before']:,} → {s['after']:,}";target='达到'if s.get('target_reached')else'未达到，保护保留'if s['status']=='saved'else'保留原网格'
    rows_text.append(f"| {index} | {c['title']} | {origin(c)} | {result} | {target} | 通过 | 通过 |")
candidate_text='\n'.join(f"| {r['seed']} | {r['status']} | {r.get('triangles','—')} | {r['photo_iou']:.4f} | {'可作为待审候选'if r['eligible']else'拒绝替换'} |"if r.get('photo_iou')is not None else f"| {r['seed']} | {r['status']} | — | — | {r.get('reason','')} |"for r in sofa['candidate_results'])
extra_pass=extra['state']['status']=='ready'
extra_description=('正向的合成透视图已通过实际 API 路径，主图与补图都写入 before/after 对照。'if extra_pass else'合成透视图仍因对应证据不足而停止，不能写成补充视图端到端成功。')
if extra_pass:extra_description+='该用例走保留原形路线，主图/补图轮廓分别约 0.8938/0.9480；验证补图确实参与检查，不代表两视图重新生成质量已通过真实商品验收。'
report=f'''# 五项自主优化、28 家具复测与 Review

记录时间：{started:%Y-%m-%d %H:%M} 至 {finished:%Y-%m-%d %H:%M}（Asia/Shanghai），截至报告约 {hours} 小时 {minutes} 分钟。用户允许持续 8 小时或更久；这里记录实际经过时间，没有将授权时长写成实际工作时长。

## 结论与边界

本轮实现了多候选筛选、保形减面、补充视图筛选、新部件 UV/材质衔接和分项验收。28 个图片/资产样本完成实际减面尝试、指定范围材质修改和整体材质修改；其中两张雕塑椅属于同一设计家族，合并计数后为 **{family_count} 个不同家具设计家族**。原始输入、失败轮次、缓存来源和测试副本均保留。

**这不是 28 个家具都被准确重建，也不是通用自动拆件已通过商品级验收。** 测试包含 {origins.get('existing_ai_shape',0)} 个已有 AI 模型、{reference_count} 个已有参考/代码模型、{origins.get('new_real_local_inference',0)} 个本轮真实本地 AI 生成模型。完整软部件修复重点验证两款沙发；其他家具验证减面、已有部件边界与材质流程。{neighbor_cases} 个样本存在未选择的相邻 primitive；单网格样本的“指定范围”会覆盖整个网格，不能拿它们证明语义零件识别或相邻部件隔离。

- {len(saved)} 个样本保存了减面结果，{len(preserved)} 个按保护条件保留；{target_reached} 个达到各自测试目标。目标为 min(原面数 × 60%, 10 万) 且不低于 1 万，并非所有家具都承诺降到 10 万面。
- 这 {len(saved)} 个样本合计 {face_before:,} → {face_after:,} 面，GLB 合计 {bytes_before/1048576:.2f} → {bytes_after/1048576:.2f} MiB。未达预算的样本保留原因，不能算作目标达成。
- 重新读取 {validations} 份最终导出 GLB：{0} 个规范错误、{warnings} 个警告；检查了原文件字节、世界几何、法线、目标 UV 和材质范围，并审计减面内部诊断，未将异常吞掉后当作保护成功。
- {python_tests} 项 Python 回归通过；12 项材质/分色 JavaScript 检查通过；主网页流程 {len(browser['checks'])} 项、控制与故障恢复 {len(controls['checks'])} 项通过。生产构建通过，仍有约 966 KB 主包的体积提示。

## 五项具体改动

模型与算法：本地 Grounding DINO Tiny 提出图像目标/部件，SAM 2.1 Hiera Tiny 生成分割掩码，Hunyuan3D-2mini 生成缺失软部件形状；多视角投影归属、相机拟合、几何约束和 QEM 减面不冒充新的语义 AI。本轮未接入能保证任意家具完整拆件的通用 3D 部件模型，也没有使用商业密钥或把图片上传到外部服务。

### 1. 2–3 个候选，先检查再选择

默认对同一部件使用 seed 42、77、123。每个候选独立保存生成、装配、轮廓、自交、邻件穿插和减面证据。优先选允许替换的候选，再按 80% 轮廓、10% 极端折叠面积、10% 抽样邻件净空排序；排序是启发式，不是实物准确率。失败候选保留原因；全部装配失败时保留可下载的原始生成件，当前模型不被替换。

本轮新增 {len(new)} 次真实本地推理，其中 2 次是靠枕新 seed、6 次是新家具整物生成。靠枕 seed 42 使用上轮同参考的已验证原始形状缓存。本轮候选最终复测复用三份原始形状，**没有重复推理冒充新生成**；位置、UV、轮廓和相邻检查全部重新计算。缓存必须同时满足参考字节、seed、worker 版本、50 steps、384 resolution、模型和前景哈希一致。

### 2. 保形减面与文件体积

新增按目标面数的保形减面。检查双向面积采样表面距离、三向轮廓、边界、体积、闭合、连通片、自交和 UV 拉伸。阈值：p99 表面距离 ≤ 对角线 0.25%，最大采样距离 ≤ 0.8%，边界变化 ≤ 0.3%，体积误差 ≤ 1.5%，三向轮廓 IoU ≥ 0.985。它们是抽样/几何检查，不是严格 Hausdorff 保证或实物测量。

保留 primitive 和材质边界；高碎片毛发、同时含 UV 与顶点色、未支持属性或超过处理上限的网格不强行处理。极少量浮点接触只允许最多 16 个接触面、位移不超过对角线 0.05%，并重新检查闭合、方向、体积和自交。未知扩展、动画和骨骼仍走保守路径。

原先已遇到 UV 库兼容异常、浮点接触、无效法线，以及带高级材质的 GLB 减面后变大的问题；本轮均保留失败证据并修复。已支持明确列出的材质扩展纹理回收，避免旧几何 buffer 留在新文件中。

### 3. 补充侧/背面进入筛选

界面可上传最多 3 张补图并标方向。补图经过整件轮廓、相机近似拟合、部件候选和必要的投影提示 SAM 分割；对应不足时停止，不能忽略补图继续。补图相机和参考固定后，每个候选都要参与同视角前后检查；任一视角不通过会阻止采用。后台也检查请求、对应与对照的图像集合是否完整。

完全重复的主图/补图像素（包括重新编码、RGB/RGBA 等）在排队前拒绝。错误家具的实际测试最终停止为 needs_input；第一次较宽松的对应曾让椅子弱匹配沙发坐面，最终轮廓闸门仍阻止采用，因此进一步提高补图对应要求：整件和目标部件 IoU 都至少 0.65，提示精分后仍不足就停止。

{extra_description} 所有合成图均明确标记，包含之前正交图和白色材质失败样本。**本轮没有真实的同一商品侧面/背面照片可验收，不能宣称真实多视图重建已验证。** 当前是单图生成后的补图筛选，不是标定摄影测量或多视图融合；系统也未验证上传图一定同款、一定来自独立拍摄。

### 4. 新部件 UV 与材质编辑

新修复/生成的逻辑部件自动准备 UV；多个技术 patch 共用部件尺度与坐标，仍以整块部件选择。替换后自动进入材质页并选中新部件。支持示例布料、皮革、木纹，先实时预览、可取消、明确保存；纹理重复和角度可调整，导出嵌入贴图。

示例来自本地素材目录，**不代表商品真实扫描面料**。新部件采用六面图表投影 UV，曲面接缝和花纹拉伸仍需检查。高面数床样本因专门 UV 展开超过 75 万面而拒绝，材质编辑采用首次平面 UV 兜底，报告记录该差异；不能称其已完成高质量展开。单独部件和整体换材质不会改变世界顶点、法线或三角面。

### 5. 分开验收和等待状态

展示部件完整性、照片吻合程度、运行性能、待确认区域四张卡。完整性会提示开口邻件未能检查；穿插只是抽样，不是精确碰撞保证。照片指标只表示所用视角轮廓，参与优化的图片也参与比较，不能当独立精度评估。

显示候选编号、生成步数和几何阶段。原形足够时直接保留：隐藏替换确认和采用按钮，只提供当前部件下载。手动参考与修复控件默认折叠。Windows 状态文件被读取时的原子替换增加有限重试，防止第三个候选前失败后一直等待。

## 两款沙发的实际结果

### 灯芯绒沙发中央靠枕

最终任务 `{corduroy['task']}`；source 副本 `{corduroy['job']}`。种子 42 原始生成 761,158 面，最终 100,000 面，单一闭合体、无检测到的自交。原模型同视角 IoU 为 **{checks['part_silhouette_iou_before']:.4f}**，新候选 **{checks['part_silhouette_iou_after']:.4f}**。此前候选为 0.7904，经有界位置/统一缩放调整提升到 0.8335；位移不超过源部件对角线 3%、缩放 ±4%，不会靠无限变形迎合照片。

| seed | 处理状态 | 最终面数 | 当前视角 IoU | 结论 |
|---|---|---:|---:|---|
{candidate_text}

seed 77 虽有形状，也没有通过照片闸门；seed 123 仍是弯曲薄壳且缺乏可靠前后表面支持，被拒绝。没有人为降低阈值让三个候选都通过。最终 42 的部分邻件开口，邻件穿插检查不完整；隐藏形状、厚度与商品实际尺寸仍未实测。

真实浏览器操作验证：四向预览、隔离部件、下载、明确采用同一候选、自动选中完整部件、示例材质预览/取消、保存纹理方向与尺度。采用后的模型与已检查预览逐字节一致，保存版本保持 unreviewed，未伪造人工验收。

### 皮革沙发坐垫

走原表面接缝/遮挡修复路线，无新增 Hunyuan 推理。得到 {leather['photo_checks']['quality_dimensions'][0]['metrics']['triangles']:,} 面闭合坐垫；主图 IoU **{leather['photo_checks']['part_silhouette_iou_before']:.4f} → {leather['photo_checks']['part_silhouette_iou_after']:.4f}**，有小幅下降，界面与报告保留该事实。补出的顶面遮挡区域约 38.8%，这部分是推测，不是从原图恢复出的真实结构。

## 28 个样本明细

“指定范围/整体材质通过”表示实际文件与修改范围检查通过，不表示照片外观一致。测试相机在同一个家具各版本之间固定，未拟合原商品照片；渲染前不替换原材质。两个雕塑椅变体合并只计一个设计家族。

| # | 家具 | 输入模型来源 | 三角面变化 | 测试目标 | 指定范围材质 | 整体材质 |
|---:|---|---|---:|---|---|---|
{chr(10).join(rows_text)}

## Review 中发现的问题与处理

1. **Windows 进度原子重命名失败**：第二轮父任务在读写竞争时失败，增加有限重试；第三轮三个候选都进入终态。失败任务与日志保留，没有把第二轮写成成功。
2. **带 UV 的 MeshLab 构造不兼容**：纹理索引未正确初始化；改为隔离 OBJ/MTL 内部载入。原 GLB 图片、材质和可见几何不借用该内部占位纹理。
3. **原模型两个数值接触面**：两把雕塑椅有接触面；有限位移后重新做全部几何保护，未将大面积重建包装成修复。
4. **减面后 GLB 变大**：材质扩展使旧回收逻辑跳过；支持已知扩展纹理引用，未知扩展保持保守。
5. **材质编号变化导致假阳性**：GLB 回收后未改动的邻件纹理编号变了；API 改为按嵌入图片内容和 sampler 计算签名，并对实际输出独立复核。
6. **退化三角形插值产生 NaN**：新生成桌/椅的无效导出被规范校验挡住；退化投影改用最近原始属性，法线无效则保留原网格，GLB JSON 禁止 NaN。
7. **冷启动并行贴图请求模块尚未初始化**：改为服务启动时加载叶子模块；新服务 16 并发/32 次贴图请求全为 200。另注入一次前端贴图失败，验证取消后重选同一材质可恢复且不会保存版本。
8. **错误家具补图弱匹配**：原本在最终照片检查被挡住，现提前停止，未自动认证同款。
9. **测试脚本问题也保留**：一次使用缺 numpy 的 API Python 跑几何矩阵，改为几何环境并增加前置检查；旧网页定位器仍找“真实 PBR 贴图”，改成实际界面的“上传纹理图片”；一次旧浏览器失败未生成完整 JSON，日志仍保留。UV 独立检查原先误将首次兜底 UV 当作必须保持的已有 UV，改成分别校验首次创建与已有 UV 不变。
10. **首次准备示例材质的并发冲突**：空数据目录缺少 images 父目录；补齐后 32 次/16 并发中仍有 6 次 SQLite 重复插入失败。将本地素材发布与存在检查串行保护，重新在全新 Store 上执行 32 次/16 并发全部成功，只产生 2 个唯一贴图条目，并补充 1 项并发回归。该单进程锁适用于当前本地单用户服务，不宣称多进程部署已验证。
11. **渲染复查发现示例凹凸过强**：原布料法线在默认强度下显得过于鼓起。仅对本地示例预处理法线 XY，布料/皮革/木纹分别使用 0.18/0.25/0.12 的弱化系数与平坦 Z；用户上传的贴图不受此处理影响。重新执行 28 个家具的指定范围与整体材质流程，之后重读实际 GLB 并更新对照图；原强法线版本、导出和图片仍可查。新靠枕也通过真实网页保存和单独导出，未修改几何。

## 仍未解决的产品质量问题

- 新生成形状没有自动恢复真实纹理。透明亚克力、细金属腿、藤编床等即使文件有效，仍会有形状细节、透明度和材质差异。
- 升降茶几输入中的笔记本被整物生成带入模型；这说明清理/目标实例范围仍需更强的证据与检查，本轮没有把它写成准确的纯家具交付。
- 浅蓝椅原图包含脚凳，而已有模型主要是椅体；本轮不宣称补出了脚凳。
- 新家具中的单网格仍不等于已准确拆为门、把手、椅腿等语义部件；跨品类自动语义拆件没有靠这 28 例验证完成。
- 一个靠枕候选仍是薄壳，一个预算回退到 47 万余面；这些失败都应保留。原始模型不存在的真实背面无法凭分割可靠恢复。
- 大型床模型仍有 1,620,296 面；超过保守处理上限而保留。复杂曲面 UV 与真实材质尺度未验收。

## 查阅与复现

- [图片、候选、失败与全部家具对照页](../experiments/autonomous_upgrade_20261113/index.html)
- [最终数字摘要](../experiments/autonomous_upgrade_20261113/final_summary.json)
- [可读时间线](../experiments/autonomous_upgrade_20261113/TIMELINE.md)、[逐条事件](../experiments/autonomous_upgrade_20261113/events.jsonl)、[家具注册表](../experiments/autonomous_upgrade_20261113/cases.json)
- [最终矩阵](../experiments/autonomous_upgrade_20261113/static_material_matrix_reviewed.json)、[重新读取文件的独立验证](../experiments/autonomous_upgrade_20261113/independent_output_verification.json)
- [完整网页流程](../experiments/autonomous_upgrade_20261113/browser_flow_v3.json)、[控制与故障恢复](../experiments/autonomous_upgrade_20261113/browser_controls_final.json)
- [本轮代码 Review 记录](../experiments/autonomous_upgrade_20261113/CODE_REVIEW.md)
- [本地工作台](http://127.0.0.1:8001/)，本轮未操作 8000，未提交 Git、未部署外网、未上传图片到外部服务。

实际脚本：`scripts/test_upgrade_static_matrix.py`（使用 `.venv-hunyuan`）、`scripts/verify_upgrade_outputs.py`、`scripts/test_upgrade_workflow_ui.mjs`、`scripts/test_upgrade_controls_ui.mjs`、`scripts/render_upgrade_matrix.mjs`。测试均在独立副本上执行。重新测试使用新 tag，保留失败轮次；不要覆盖已有证据或将测试副本当成额外家具。
'''
(ROOT/'docs/AUTONOMOUS_OPTIMIZATION_REVIEW_2026-11-14.md').write_text(report,encoding='utf-8')
cards=[]
for c,row in zip(cases,matrix):
    s=row['simplification'];stages=[('原模型','original'),('减面后'if s['status']=='saved'else'保留原网格','simplified'if s['status']=='saved'else'original'),('指定范围换材质','local_material'),('整体换材质','whole_material')]
    pictures=''.join(f'<figure><a href="{html.escape(relative(image_for(c["case"],stage)))}"><img loading="lazy" src="{html.escape(relative(image_for(c["case"],stage)))}" alt="{html.escape(c["title"]+label)}"></a><figcaption>{label}</figcaption></figure>'for label,stage in stages)
    model=relative(asset(row,row['whole_material_version']));cards.append(f'<article data-search="{html.escape(c["title"]+c["case"]+c["category"])}" data-status="{s["status"]}"><h2>{html.escape(c["title"])}</h2><p>{origin(c)} · {s["before"]:,} → {s["after"]:,} 面 · {"已保存减面"if s["status"]=="saved"else"保留原网格"}</p><div class="pictures">{pictures}</div><details><summary>来源、目标与检查范围</summary><p>目标 {s["target"]:,} 面；未选择相邻 primitive {row["neighbor_parts_count"]} 个。{html.escape(row.get("uv_refusal",""))}</p><code>{html.escape(c["case"])}</code><p><a href="{html.escape(relative(ROOT/c["source_model"]))}">源模型</a> · <a href="{html.escape(model)}">整体材质导出 GLB</a> · <a href="http://127.0.0.1:8001/?job={row["job"]}">打开测试副本</a></p></details></article>')
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>28 家具优化实测与失败记录</title><style>body{margin:0;background:#f3f5f8;color:#20314b;font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1250px;margin:auto;padding:24px}h1{font-size:30px}h2{font-size:20px}a{color:#1c5994}article,.intro,section{background:white;border:1px solid #dce3ed;border-radius:12px;padding:20px;margin:18px 0}.note{border-left:5px solid #bc7423;padding:12px 18px;background:#fff5df}input,select{padding:12px;max-width:100%;font-size:16px;border:1px solid #aab9cb;border-radius:6px}.pictures{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}figure{margin:0}img{max-width:100%;height:auto;border-radius:6px}figcaption{color:#52677e;font-size:14px}code{overflow-wrap:anywhere}details{margin-top:12px}.screens{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.screens img{max-height:430px;object-fit:contain}[hidden]{display:none!important}@media(max-width:700px){main{padding:12px}.pictures,.screens{grid-template-columns:repeat(2,1fr)}h1{font-size:24px}article{padding:12px}}</style><main>'''
page+=f'<h1>28 家具优化实测与失败记录</h1><div class="intro"><p>五项改动：多候选筛选、保形减面、补图筛选、新部件 UV/材质、分项验收。</p><p><strong>{family_count} 个不同设计家族 · {len(saved)} 个减面保存 · {len(preserved)} 个保留 · {validations} 份最终 GLB 零规范错误 · {python_tests} 项 Python 回归通过</strong></p><p class="note">这是流程与文件检查结果，商品级外观仍未通过验收。包含已有模型和 6 件本轮 AI 整物生成；不能把全部样本算作本轮 AI 准确生成。侧/背面真实照片尚缺，合成图单独标注。</p><p><a href="../../docs/AUTONOMOUS_OPTIMIZATION_REVIEW_2026-11-14.md">详细报告</a> · <a href="final_summary.json">数字摘要</a> · <a href="events.jsonl">时间记录</a> · <a href="static_material_matrix_reviewed.json">完整矩阵</a> · <a href="independent_output_verification.json">独立文件复核</a></p></div>'
page+='<section><h2>先看靠枕：好坏候选都保留</h2><p>原模型轮廓 0.8040 → 新候选 0.8335；100,000 面。seed 77 未通过照片闸门，seed 123 弯曲薄壳未装回。参与优化的照片同时参与比较，此值不是实物准确率。</p><a href="'+html.escape(relative(ROOT/'.data/jobs'/corduroy['job']/'part_regenerations'/corduroy['task']/'comparison.png'))+'"><img src="'+html.escape(relative(ROOT/'.data/jobs'/corduroy['job']/'part_regenerations'/corduroy['task']/'comparison.png'))+'" alt="靠枕原图与优化前后"></a><div class="screens">'
for name in('正面','侧面','背面','底面'):
    page+=f'<figure><a href="ui/{name}.png"><img src="ui/{name}.png" alt="实际网页预览{name}"></a><figcaption>实际网页预览：{name}</figcaption></figure>'
page+='</div><p><a href="browser_flow_v3.json">主网页检查记录</a> · <a href="browser_controls_final.json">故障与保留原形检查</a> · <a href="ui/cloth_preview_weak.png">新部件布料预览</a> · <a href="ui/keep_controls.png">保留原形时的界面</a></p></section>'
page+='<section><h2>新部件独立检查与示例凹凸调整</h2><p>以下为实际导出的带材质部件，未替换其材质。默认布料凹凸已弱化，几何和已准备的 UV 保持不变；表面缝合与纹理接缝仍需检查。视角名称按模型坐标轴命名，未标定为商品的真实正面。</p><div class="screens">'
for view,label in [('front','轴向一'),('side','轴向二'),('back','反向'),('bottom','底面')]:
    page+=f'<figure><a href="ui/textured_part_{view}_weak.png"><img src="ui/textured_part_{view}_weak.png" alt="新部件独立检查 {label}"></a><figcaption>{label}</figcaption></figure>'
page+='</div><p><a href="ui/optimized_textured_pillow_weak.glb">下载新部件示例材质 GLB</a> · <a href="ui/textured_part_side.png">调整前凹凸效果</a> · <a href="browser_material_tuning.json">实际网页调材质记录</a> · <a href="material_refresh_normal_v1.json">28 家具材质复测</a></p></section>'
page+=f'<section><h2>补充视图</h2><p>{extra_description} 无真实同款第二角度验收，不验证图像独立拍摄或同款身份。</p><p><a href="additional_view_wrong_v2.json">错误家具与重复内容拒绝</a> · <a href="additional_view_synthetic_perspective.json">合成透视图 API 结果</a> · <a href="synthetic_complete_sofa_perspective_provenance.json">合成图来源</a></p></section>'
page+='<p>参考图与原模型：<a href="visual_sources_and_originals_1.png">1–14</a> · <a href="visual_sources_and_originals_2.png">15–28</a>。全部版本接触表：'+ ' · '.join(f'<a href="visual_final_{n}.png">第 {n} 组</a>'for n in range(1,5))+'</p>'
page+='<label>查找家具 <input id="query" placeholder="沙发、椅、桌、柜或样本编号"></label> <label>减面结果 <select id="status"><option value="">全部</option><option value="saved">保存减面结果</option><option value="preserved">保留原网格</option></select></label><p id="count"></p>'+''.join(cards)
page+='<section><h2>失败与剩余限制</h2><p>新生成升降茶几带入了参考图中的笔记本；透明材质、细腿和部分软包仍有偏差。大型床超过保守面数上限而保留，平面 UV 兜底需要检查拉伸。一个商品的技术 primitive、不同 seed 和测试副本不重复计数。</p><p><a href="static_material_matrix_final.json">最终大轮中的失败</a> · <a href="static_material_matrix_final_fixes.json">对应修复复测</a> · <a href="new_table_validation_failure.json">被拒绝的 NaN 导出</a> · <a href="api_final_round6.log">API 回归</a> · <a href="geometry_final_round2.log">几何回归</a> · <a href="build_round4.log">构建日志</a></p></section></main><script>const q=document.getElementById("query"),s=document.getElementById("status"),cards=[...document.querySelectorAll("article")];function filter(){for(const c of cards)c.hidden=!c.dataset.search.toLowerCase().includes(q.value.toLowerCase())||(s.value&&c.dataset.status!==s.value);document.getElementById("count").textContent="显示 "+cards.filter(c=>!c.hidden).length+" / "+cards.length+" 个样本";}q.oninput=s.onchange=filter;filter();</script></html>'
(OUT/'index.html').write_text(page,encoding='utf-8')
record('measured_report_and_gallery_generated',**{k:v for k,v in summary.items()if k not in('family_mapping',)})
events=[json.loads(line)for line in(OUT/'events.jsonl').read_text(encoding='utf-8').splitlines()]
timeline=['# 实际执行时间线','',f'工作记录开始：{started:%Y-%m-%d %H:%M}；结构化事件开始：{first_event:%Y-%m-%d %H:%M}。所有时间为 Asia/Shanghai。完整字段见 events.jsonl。','','| 时间 | 事件 | 摘要 |','|---|---|---|']
for event in events:
    facts={k:v for k,v in event.items()if k not in('time','event')};excerpt=json.dumps(facts,ensure_ascii=False,separators=(',',':')).replace('|','/')
    timeline.append(f'| {event["time"][:19].replace("T"," ")} | {event["event"]} | {excerpt[:330]}{"…"if len(excerpt)>330 else""} |')
(OUT/'TIMELINE.md').write_text('\n'.join(timeline)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
