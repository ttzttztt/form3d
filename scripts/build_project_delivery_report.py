# -*- coding: utf-8 -*-
"""Detailed delivery report built from executed evidence, not estimated scores."""
from datetime import datetime,timezone
import hashlib
import html
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/project_delivery_20261111';OUT.mkdir(exist_ok=True)
ASSETS=ROOT/'experiments/asset_editor_20261111';QUALITY=ROOT/'experiments/output_quality_20261111'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
web=read(ASSETS/'web_validation.json');preserved=read(ASSETS/'geometry_preservation.json');selection=read(ASSETS/'selection_validation.json')
vertex=read(ASSETS/'triposr_vertex_color_validation.json');external=read(ASSETS/'external_viewer_validation.json')
cases={folder.name:read(folder/'job.json') for folder in (QUALITY/'real_runs').iterdir() if (folder/'job.json').exists()}
baseline=read(QUALITY/'baseline_geometry_results.json')
assert all(item['status']=='PASS' for item in [web,preserved,selection,vertex,external])
assert sha(ASSETS/'final_edited_plant.glb')==external['model_sha256']
flat=cases['flat_vase'];table=cases['table_control'];blocked=cases['blocked_cat'];disabled=cases['flat_vase_no_retry']
assert len(flat['output_attempts'])==2 and flat['actual_engine']=='triposr'
assert len(table['output_attempts'])==1
assert not blocked.get('output_attempts') and blocked['attention_kind']=='local_input'
assert disabled['attention_kind']=='local_output' and len(disabled['output_attempts'])==1
evidence={'generated_at_utc':datetime.now(timezone.utc).isoformat(),
 'scope':'Local single-user workbench delivery; no claim of general image-to-3D product fidelity or production deployment',
 'tests':{'api_and_contract':30,'input_rules':11,'legacy_preprocessing':4,'output_geometry_rules':6,'asset_grouping':3,'total':54,'frontend_build':'pass'},
 'real_generation_jobs':{key:{'id':value['id'],'status':value['status'],'actual_engine':value.get('actual_engine'),
                            'attempts':len(value.get('output_attempts',[]))} for key,value in cases.items()},
 'historical_glb_screening':baseline,'asset_browser':web,'geometry_preservation':preserved,'part_selection':selection,
 'vertex_color_editing':vertex,'external_viewer':external,'full_product_assets_accepted':0,
 'acceptance_scope':'New automated reconstruction samples in this evaluation; historical authored/accepted library assets are outside this count',
 'final_browser_validation':read(OUT/'final_validation.json') if (OUT/'final_validation.json').exists() else None,
 'frozen_export':{'path':'experiments/asset_editor_20261111/final_edited_plant.glb','sha256':sha(ASSETS/'final_edited_plant.glb')},
 'limitations':['Geometry heuristics do not prove image similarity or openings','Grouping is geometric, not semantic CAD disassembly','Parameter materials are not real texture scans','Hidden geometry and physical scale remain unverified']}
save(OUT/'acceptance.json',evidence)

font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',22);small=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',17)
canvas=Image.new('RGB',(1240,940),'#eef0f2');draw=ImageDraw.Draw(canvas)
draw.text((16,12),'实际交付：区域材质编辑与几何异常的有限返工',font=font,fill='black')
panels=[('原始 GLB · 同相机灯光',ASSETS/'same_lighting_original.png'),('两个区域 · 整体和局部材质',ASSETS/'same_lighting_edited.png'),
        ('首次 Hunyuan · 几何检查拦截',QUALITY/'real_runs/flat_vase/renders/hunyuan_rejected_oblique.png'),
        ('TripoSR 重试 · 厚度增加，瓶口仍需修',QUALITY/'real_runs/flat_vase/renders/triposr_retry_oblique.png')]
for index,(name,path) in enumerate(panels):
    x=(index%2)*620;y=55+(index//2)*420;draw.text((x+12,y),name,font=small,fill='black')
    image=ImageOps.contain(Image.open(path).convert('RGB'),(598,368));canvas.paste(image,(x+(620-image.width)//2,y+36+(368-image.height)//2))
draw.text((16,907),'图片来自真实浏览器或真实 GLB 渲染。通过几何规则不代表商品还原成功，完整商品资产仍未验收。',font=small,fill='black')
canvas.save(OUT/'delivery_overview.png')

def job_link(key):return 'http://127.0.0.1:8000/?job='+cases[key]['id']
local_seconds=flat['report']['local_inference']['total_local_wall_seconds'];table_seconds=table['report']['local_inference']['total_local_wall_seconds']
group_seconds=read(ASSETS/'plane_group.json')['manifest']['duration_seconds'];material_seconds=read(ASSETS/'local_material.json')['manifest']['duration_seconds']
doc=f'''# img_to3D 项目阶段交付与详细验收报告

日期：2026-11-11。工作目录：`D:\\Documents\\MiniLab\\img_to3D`。

本次完成的是可运行的本地单人工作台：图片选择、主体处理、输入拦截、本地生成、输出几何检查、有限返工、人工审核、版本化分组与材质编辑、GLB 导出。已经运行真实图片和真实模型，并保存失败结果。**本次自动重建测试仍没有通过完整商品还原验收的样本；不改变历史手工作品和用户审核记录。**

[打开工作台](http://127.0.0.1:8000) · [图像与证据总览](../experiments/project_delivery_20261111/index.html) · [机器可读验收](../experiments/project_delivery_20261111/acceptance.json)

![真实编辑与返工对照](../experiments/project_delivery_20261111/delivery_overview.png)

## 1. 本次新增交付

沿用的前序工作：已盘点 `images/` 中 884 张图片；之前固定 11 例（5 张白底、6 张场景，含 1 张疑似渲染场景）完成图像与建模检查。输入清理阶段的结果为 5 例拦截、6 例继续生成。上述记录保存在旧报告中，本轮没有把它们重复宣称为 11 次新的神经生成。本轮新增的是 11 个历史 GLB 的离线输出检查、4 个真实工作台流程案例，以及实际模型上的编辑/导出验证。

| 能力 | 已实现的行为 | 边界 |
| --- | --- | --- |
| 输出几何检查 | 检查非有限/空网格、可疑薄片/低秩体积、特定品类方块退化、连通片及封闭性 | 启发式规则，不证明原图相似度、瓶口或实物尺寸 |
| 有限返工 | 异常时最多改用另一本地模型一次；保存两次模型、参数和日志 | 不重试输入遮挡问题，不调用付费服务，不无限循环 |
| 品类意图 | 可手动指定花瓶、桌子等，用于质检规则；保留不确定/其他选项 | 不改变图片选框，不调用该品类参数模板强行造型 |
| 已有部件选择 | 按当前 GLB 节点/primitive 列表选择，也支持点击模型拾取及选区外框 | 一张连续网格不会自动变成语义部件 |
| 连通片分组 | 保留所有面，把几何相连的部分归组，小片集中保留 | 连通片不是桌腿/坐垫等语义标签 |
| 空间区域分组 | 按 X/Y/Z 与百分比分界对面中心分组 | 不切割三角面，不封口，不是装配级实体拆分 |
| 整体/局部换材质 | 颜色、粗糙度、金属度、不透明度；支持替换与保留纹理染色 | 哑光/金属/塑料/织物/透明均为参数材质或近似效果 |
| 版本与恢复 | 每次编辑生成独立 GLB，支持查看历史、恢复原始和恢复历史为新版本 | 原始生成文件不覆盖；当前分组 ID 绑定版本 |
| 独立编辑审核 | 编辑版本可接受或退回，新编辑与恢复版本不继承旧审核 | 演示编辑版本保持未验收，没有伪造用户通过 |
| 导出 | 编辑 GLB 与编辑记录分别下载，原生成记录包继续保留 | 当前没有将编辑版自动发布到统一模型库 |

## 2. 当前流程和状态

```mermaid
flowchart TD
  A[上传图片与目标品类] --> B[检测候选并选择目标]
  B --> C[分割 / OCR 清理 / 遮挡检查]
  C --> D{{输入是否可继续}}
  D -->|需要修正| E[需要处理：保存原因和处理图]
  D -->|可继续| F[本地形状生成]
  F --> G{{输出几何检查}}
  G -->|异常且有重试预算| H[另一本地模型，最多一次]
  H --> G
  G -->|仍异常| I[需要处理：保留诊断候选]
  G -->|通过| J[glTF 校验与待审核候选]
  J --> K[分组 / 换材质 / 独立版本]
  K --> L[编辑版本单独审核与导出]
```

`awaiting_input/local_input` 表示图片需要修改，尚未启动 3D。`awaiting_input/local_output` 表示生成过候选但输出异常，主模型下载不开放，可查看诊断候选。`awaiting_review` 只表示已得到通过技术规则的候选。编辑版本另存 `unreviewed/accepted/rejected`，与原任务审核分离。

## 3. 本轮真实生成与返工

| 案例 | 实际执行 | 最终状态 | 结论 |
| --- | --- | --- | --- |
| 彩绘花瓶，开启重试 | Hunyuan 被标记为横向厚度异常；重试 TripoSR 一次 | 待审核，实际来源为 TripoSR | 厚度增加，但表面粗糙、瓶口封闭，**未达到商品还原验收** |
| 圆桌对照 | Hunyuan 一次，几何检查通过 | 待审核 | 正常薄桌面与分离支撑没有被整体薄片规则误拦 |
| 猫遮挡沙发 | 在输入检查处停止 | 需要处理，0 次形状尝试 | 输入问题未浪费重试，也未把方块作为新资产发布 |
| 彩绘花瓶，关闭重试 | Hunyuan 一次后被几何规则拦截 | 需要处理，主 GLB 返回 409 | 诊断候选仍可访问，未作为可用资产发布 |

任务入口：[花瓶有限返工]({job_link('flat_vase')})、[圆桌对照]({job_link('table_control')})、[输入拦截]({job_link('blocked_cat')})、[输出拦截]({job_link('flat_vase_no_retry')})。

额外对首轮 11 个历史 GLB 做了离线规则筛查：本次标记彩绘花瓶、猫遮挡沙发方块及小盆栽剪影片 3 例。陈列柜粘连物品、玻璃桌楔块和插花瓶缺口并不能全部由当前几何规则发现，因此输入检查和人工外观核对仍保留。**这些是已知难例回归，不是独立测试集准确率。**

本机单次记录：花瓶两次生成及本地处理共 {local_seconds:.3f} 秒；圆桌本地处理 {table_seconds:.3f} 秒。数据含模型启动与检查等开销，不含全部排队/浏览器加载；CPU 渲染和编辑可能并行，不作为速度基准。各模型显存数字仍以 PyTorch 分配器为口径，不代表整卡占用。

## 4. 真实编辑验收

在实际生成的琴叶榕盆栽上完成测试，原始模型不是用于替代生成质量的合成夹具。

- 原模型有 1 个可编辑 primitive、338,358 个三角面。按高度分成 2 个区域后，整体换成绿色，再将下部区域改成棕色。两个区域材质保持独立。
- 恢复原始版本后，导出字节与原始 GLB 一致；恢复历史材质版本后，导出字节与该历史文件一致。
- 对最终编辑 GLB 核验了顶点位置、节点世界变换、三角面索引多重集合，均与原始模型一致。不是仅比较三角面数量。
- 实际连通片操作得到 6 个几何组，未将它们命名成语义部件；最终展示恢复到两个空间区域的材质版本。
- 已验证 3D 点击拾取、选区外框、刷新恢复、移动端无横向溢出、GLB 下载和编辑记录。
- 真实 TripoSR 彩色模型也做了验证：替换模式移除旧顶点色影响，染色模式保留顶点色，避免用户换色却仍被原预测颜色覆盖。
- 最终编辑 GLB 在 Blender 中再次导入并用自身材质渲染，未覆盖成灰模；glTF Validator 为 0 错误、0 警告。

[打开当前盆栽编辑示例]({web['final_url']}) · [固定导出 GLB](../experiments/asset_editor_20261111/final_edited_plant.glb) · [外部查看器渲染](../experiments/asset_editor_20261111/edited_materials_blender.png) · [几何保持证据](../experiments/asset_editor_20261111/geometry_preservation.json)

固定导出 SHA-256：`{sha(ASSETS/'final_edited_plant.glb')}`。原始 GLB 为 8,115,916 字节，固定导出为 {(ASSETS/'final_edited_plant.glb').stat().st_size:,} 字节。分组增加索引，版本当前按完整文件保存，没有宣称轻量化。

编辑 Worker 的一次记录：区域分组 {group_seconds:.3f} 秒、局部换材质 {material_seconds:.3f} 秒，均不包含 API 文件校验和浏览器加载，不可当作端到端耗时保证。

## 5. 使用步骤

1. 在项目目录运行 `powershell -ExecutionPolicy Bypass -File .\\start.ps1`，打开本地工作台。
2. 上传图片、选择目标。检查识别框；若品类错误，可手动指定目标品类用于几何检查。
3. 选择本地模型。默认允许几何异常时最多换一个本地模型重试；图片遮挡/低像素问题会先停下。
4. 得到候选后旋转查看。若要局部换材质，先选择已有部件；连续网格可展开“几何分组与拆分”，设置方向和分界位置。
5. 在编辑范围选择整个模型或一个分组，选颜色与材质参数，保存独立版本。版本列表可查看与恢复历史。
6. 审核当前编辑版本，下载该编辑 GLB 和编辑记录。页面的原始生成记录包对应原始模型，不会暗中替换成编辑版。

## 6. 软件验证

| 检查 | 结果 | 性质 |
| --- | ---: | --- |
| API 与状态/契约测试 | 30 通过 | 包括输出拦截、诊断访问、版本冲突、独立审核与恢复 |
| 输入清理规则 | 11 通过 | 包括尺寸引线、文字保护与正常孔洞 |
| 原预处理回归 | 4 通过 | 浅色部件、透明通道、顶点色、Windows 原子写入 |
| 输出几何规则 | 6 通过 | 旋转薄片、正常薄桌面、柜子与沙发方块区别等 |
| 资产分组保持 | 3 通过 | 顶点/面数保持、共享节点不串色、正常立方体不拆成六个假部件 |
| 合计 | **54 通过** | 合成夹具只证明软件契约，不证明照片还原能力 |
| 前端构建 | 通过 | 仍有约 810 kB 主包的体积提示，未做生产级性能承诺 |
| 真实浏览器及文件 | 通过 | 全局/局部材质、历史恢复、刷新、移动端、点击拾取、外部 GLB 查看 |

## 7. 本次修正的工程问题

复现软件检查可使用下列命令；真实浏览器脚本会在测试任务上创建独立编辑版本，不是只读检查：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v
.\\.venv-preflight\\Scripts\\python.exe scripts/test_input_preflight.py
.\\.venv-3d\\Scripts\\python.exe scripts/test_local3d_preprocess.py
.\\.venv-hunyuan\\Scripts\\python.exe scripts/test_output_geometry.py
.\\.venv-hunyuan\\Scripts\\python.exe scripts/test_asset_grouping.py
npm run build
node scripts/test_asset_editor_workflow.mjs
```

1. 避免把格式合法当成几何可用；失败候选与主模型下载分开。
2. 返工次数有限，输入拦截不进入重试；实际成功模型与纹理来源如实记录。
3. 修改共享 mesh 的一个节点前先隔离，避免其他实例被一起改色。
4. 按世界坐标处理空间分界，保留原三角面和节点变换；未被分开的已有部件保留其名称。
5. 替换材质时处理 TripoSR 的顶点色，染色时则保留，避免两种意图混淆。
6. 当前预览、下载链接和显示的部件/面数/文件大小对应当前编辑版本。
7. 原模型审核与编辑审核分开，恢复为新版本不继承旧批准；并发编辑使用版本冲突保护。
8. 原模型、前次失败、返工候选和历史编辑文件分别保存。

## 8. 仍未解决的质量边界

- 单图无法证明背面、内部结构和真实尺寸；本轮没有制造准确率或尺寸误差数据。
- 当前规则无法识别所有商品结构错误，尤其瓶口、玻璃、反射、精细文字和软包结构。
- 遮挡处理仍是识别与拦截，没有自动补全真实产品结构；需要无遮挡图或额外视图。
- 区域/连通片分组不是语义拆分、实体切割、装配件或可打印封闭零件。
- 参数材质与透明近似不等于真实布料、木纹、石材扫描贴图或折射玻璃。改变材质不会补出缺失柜内几何。
- 编辑版本的独立审核已实现；没有替用户把当前演示资产标成已接受。
- 多目标场景仍须检查所选实例，单纯指定“花瓶”不会自动把选框从桌子移过去。

## 9. 后续部件与材质功能的实现顺序

| 顺序 | 工作 | 前置条件与验收门槛 |
| --- | --- | --- |
| 1 | 连体网格的精细面选、刷选及分组重命名 | 稳定部件 UUID、父子关系；选择/撤销可复现，面集合无丢失 |
| 2 | 语义部件拆分 | 先建立真实标注样本，区分桌腿、桌面、靠背等；自动结果允许人工纠正，不拿连通片数量当语义准确率 |
| 3 | 真实 PBR 材质库与纹理上传 | 来源、单位、颜色空间、UV/三平面映射/烘焙方案；导出到 Blender 后比例与方向一致 |
| 4 | 局部纹理和整体材质替换完善 | 部件边界、UV 接缝、贴图平铺、粗糙度/法线通道独立管理；保留原纹理与版本 |
| 5 | 部件替换与装配 | 独立节点变换、锚点、尺度与朝向；替换后不漂移，材质槽和附件关联可恢复 |
| 6 | 输出轻量化与 LOD | 在几何可用后减少面数和文件大小；细腿、孔洞、材质边界与 UV 不被损坏 |
| 7 | 多用户与批量服务 | 独立任务队列、GPU Worker、对象存储、权限、配额和版本保留；当前单机演示不宣称已经具备 |

这些是后续工作清单，不是已完成能力，也没有编造开发工期或未执行的测试结果。

## 10. 代码、数据与运行维护

- 输出检查：`scripts/analyze_geometry.py`、`services/api/output_quality.py`、`services/api/local3d.py`、`services/api/pipeline.py`。
- 编辑：`services/api/glb_document.py`、`services/api/asset_editor.py`、`scripts/edit_asset.py`、`apps/web/src/AssetEditor.tsx`、`apps/web/src/Viewer.tsx`。
- 几何诊断：`.data/jobs/<id>/attempts/`；编辑版本：`.data/jobs/<id>/assets/<version>/`，附请求、manifest 和操作日志。
- 真实验证：`experiments/output_quality_20261111/`、`experiments/asset_editor_20261111/`；本报告证据索引：`experiments/project_delivery_20261111/acceptance.json`。
- 核心接口：`GET /api/jobs/<id>/asset`、`POST /api/jobs/<id>/asset/versions`、`POST /api/jobs/<id>/assets/<version>/review`、`GET /api/jobs/<id>/assets/<version>/model.glb`。
- 运行依赖沿用独立 venv：API、目标检测、SAM、输入清理、TripoSR、Hunyuan 分开；商品图片和推理保留在本机。
- 当前是 localhost、SQLite、单 Uvicorn、共享 GPU 锁的单人工作台；未部署公网、多租户或商业云账号联调。
- 每个编辑版本当前保存完整 GLB，会增加磁盘占用；128 MiB 编辑文件上限明确报错，版本压缩/归档与保留策略待后续实现。

本轮所有结果以实际任务、哈希、模型与截图为依据。可继续开发和试用，但完整商品级重建仍需要进一步改善与验证。
'''
(ROOT/'docs/PROJECT_DELIVERY_REPORT_2026-11-11.md').write_text(doc,encoding='utf-8')

rows=''.join('<tr><td>'+html.escape(item['id'])+'</td><td>'+html.escape(item['status'])+'</td><td>'+html.escape(', '.join(item['reasons']) or '无阻断项，仍需外观审核')+'</td></tr>' for item in baseline)
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>img_to3D 项目交付报告</title><style>body{{max-width:1300px;margin:24px auto;padding:0 18px;background:#f1f3f6;color:#252b36;font:16px/1.75 system-ui}}section{{padding:22px;background:white;border-radius:12px;margin:20px 0}}img{{max-width:100%;height:auto}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}a{{color:#2757b6}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:left;overflow-wrap:anywhere}}@media(max-width:700px){{.pair{{grid-template-columns:1fr}}h1{{font-size:25px}}section{{padding:14px}}}}</style>
<h1>img_to3D 项目阶段交付</h1><p>真实执行、失败留档、有限返工、版本化编辑。54 项自动测试与前端构建通过。本轮自动重建样本尚未通过完整商品还原验收；历史作品与用户审核不受影响。</p>
<p><a href="../../docs/PROJECT_DELIVERY_REPORT_2026-11-11.md">详细 Markdown 报告</a> · <a href="acceptance.json">机器可读证据索引</a> · <a href="{web['final_url']}">打开材质编辑示例</a> · <a href="{job_link('flat_vase')}">打开实际返工任务</a></p>
<img src="delivery_overview.png" alt="真实区域材质与几何有限返工对照">
<section><h2>当前可用</h2><p>已有部件选择、3D 点击拾取、连通片分组、X/Y/Z 区域分组、整体与局部参数材质、替换/染色、GLB 导出、原始/历史恢复、独立版本审核。</p><p>每次编辑保留原始文件。实际盆栽核验顶点、变换与三角面多重集合一致。不是语义 CAD 拆分，没有把区域自动命名成花盆/树干/叶子。</p><div class="pair"><img src="../asset_editor_20261111/same_lighting_original.png" alt="相同灯光下的原始模型"><img src="../asset_editor_20261111/same_lighting_edited.png" alt="相同灯光下的区域材质版本"></div><p><a href="../asset_editor_20261111/final_edited_plant.glb">固定编辑 GLB</a> · <a href="../asset_editor_20261111/geometry_preservation.json">几何保持证据</a> · <a href="../asset_editor_20261111/web_validation.json">浏览器验证</a></p></section>
<section><h2>外部查看器验证</h2><p>实际导出的编辑 GLB 在 Blender 中按自身材质渲染，没有改成灰模。</p><img src="../asset_editor_20261111/edited_materials_blender.png" alt="Blender 中实际 GLB 材质"><p><a href="../asset_editor_20261111/edited_materials_review.blend">导入复核的 Blender 文件</a> · <a href="../asset_editor_20261111/external_viewer_validation.json">渲染依据</a></p></section>
<section><h2>四个真实流程验证</h2><ul><li>花瓶：Hunyuan 检查异常后只重试 TripoSR 一次，实际来源记录正确；新模型厚度增加但瓶口仍封闭，未通过商品还原。</li><li>圆桌：一次生成并通过规则，保留正常薄桌面和支撑。</li><li>猫遮挡：输入拦截，0 次形状尝试。</li><li>关闭重试的花瓶：停在输出检查，主 GLB 不开放，诊断候选仍可查看。</li></ul><p>本机花瓶本地流程 {local_seconds:.3f} 秒，圆桌 {table_seconds:.3f} 秒；单次运行不是速度基准。</p></section>
<section><h2>11 个历史 GLB 的规则筛查</h2><p>这是已知难例回归数量，不是准确率。规则不能识别所有结构错误，输入检查与人工审核保留。</p><table><thead><tr><th>案例</th><th>规则状态</th><th>依据</th></tr></thead><tbody>{rows}</tbody></table></section>
<section><h2>后续优先级</h2><ol><li>精细面选/刷选、稳定部件 ID 与分组重命名。</li><li>带标注验证与人工纠错的语义部件拆分。</li><li>真实 PBR 材质库、UV 与纹理比例/方向。</li><li>局部贴图、部件替换与装配锚点。</li><li>轻量化、版本归档和批量服务。</li></ol><p>这些能力尚未全部实现。当前参数材质不是实拍纹理，分组不会补出缺失几何，单图不证明背面与尺寸。</p></section></html>'''
(OUT/'index.html').write_text(page,encoding='utf-8')
print(json.dumps({'report':'docs/PROJECT_DELIVERY_REPORT_2026-11-11.md','tests':54,'real_jobs':len(cases),'fixed_export_sha256':evidence['frozen_export']['sha256']},ensure_ascii=True),flush=True)
