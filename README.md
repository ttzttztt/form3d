# img_to3D

本轮完成 **多候选筛选、保形减面、补图参与部件检查、新部件 UV/示例材质、分项验收**，并对 28 个样本复测（合并同设计变体后为 27 个家具家族）。19 个保存减面结果、9 个保护保留；223 项 Python 回归通过，75 份最终矩阵 GLB 校验零错误、零警告。另检查真实网页替换/换材质、故障恢复和首次并发准备材质；默认示例凹凸过强的问题已通过渲染复查修正。**真实侧背面商品照片尚未验收，部分形状、UV 接缝与隐藏结构仍有偏差，不能视作通用准确拆件完成。** 详见 [详细报告与 Review](docs/AUTONOMOUS_OPTIMIZATION_REVIEW_2026-11-14.md)、[28 家具对照与失败记录](experiments/autonomous_upgrade_20261113/index.html)、[可读时间线](experiments/autonomous_upgrade_20261113/TIMELINE.md)。当前服务为 [8001](http://127.0.0.1:8001/)。

上一轮新增 **原图轮廓约束、自动选择保留/修复/重生成、照片与三维部件对应、保守软包细节恢复、同视角前后验收**。203 项 Python 测试通过。两条真实网页流程得到可继续编辑的完整候选，右侧靠枕因对应不可靠而停止；换材质和相邻部件保留检查通过。轮廓 IoU 略有下降，隐藏结构和细节仍有推测，**商品级外观尚未通过验收**。详见 [五项优化与详细 review](docs/PHOTO_GUIDED_PARTS_REVIEW_2026-11-13.md) 和 [实测图片、四向检查与拒绝样本](experiments/photo_guided_parts_20261113/index.html)。

上一轮新增 **靠枕薄壳体积重建、坐垫接缝与遮挡区修复**。靠枕得到约 4 万面的完整实体，坐垫得到约 4.7 万面的完整部件；推测区域会标色，支持整块换材质。详见 [实测与限制](docs/SOFT_VOLUME_REVIEW_2026-11-13.md) 和 [前后对比](experiments/soft_part_quality_20261113/index.html)。当时 179 项 Python 测试通过，两条网页流程和相邻部件保留检查通过。完整性已改善，细节与实物一致性仍未通过最终验收。

上轮接入 **按原图重新生成整体部件 → 自动对齐 → 四面预览 → 保存替换候选**，使用本地 Grounding DINO、SAM 2.1 和 Hunyuan3D-2mini，无需密钥。支持任务取消、刷新恢复、失败后下载生成部件，并保留原模型。历史实测见 [部件重生成报告](docs/PART_REGENERATION_REVIEW_2026-11-13.md) 和 [实际结果对比](experiments/part_regeneration_20261113/index.html)。当时 168 项 Python 测试与 5 项分色检查通过，但靠枕偏薄、坐垫参考补全失真。以下为此前迭代记录。

最新实测见 **[AI 整体部件识别与分色验收](docs/AI_SEMANTIC_PARTS_REVIEW_2026-11-13.md)** 和 [分色图片、独立部件与失败证据](experiments/semantic_parts_20261113/index.html)。已接入本地 Grounding DINO + SAM 2 的六视角自动实例归组，合并同一靠枕正反面，并用圆柱几何证据纠正混组；无需逐件涂选。皮质沙发得到 3 组，灯芯绒沙发为 5 个靠枕和主体；坐面与扶手 / 底座仍未分清，圆桌无效候选被拒绝。123 项 Python 测试与 5 项分色状态检查通过，32 份 GLB 校验零错误、零警告。11 个表面组可分别编辑导出，但均未形成独立闭合实体，通用准确拆分尚未验收。

最新实测见 **[沙发坐垫边界、厚度与真实预览验收](docs/SOFA_CUSHION_REFINEMENT_REVIEW_2026-11-13.md)** 和 [前后对比与失败证据](experiments/sofa_refinement_20261113/index.html)。新增显式厚度 / 前后范围切分、保存前真实预览、源表面与推测面区分，以及预览失效和保存一致性保护；保留原有旋转补选、正负点与涂抹。108 项 Python 测试通过，30 份 GLB 校验零错误、零警告；四个家具的编辑操作通过，但两款沙发经两轮边界试验仍未通过完整坐垫外观验收，已标为需要修改。不能把可调厚度或闭合导出当成准确还原。

最新实测见 **[多家具拆分与材质拆装验收](docs/MULTIFURNITURE_PARTS_REVIEW_2026-11-13.md)** 和 [五模型图片与失败记录](experiments/multifurniture_20261113/index.html)。椅子底架、圆桌和书柜通过本轮编辑操作验收；圆桌稳定分出桌面、连接座及两组支撑，书柜已有 11 件逐件验证且保留 UV。两款沙发虽闭合导出成功，但坐垫偏薄，外观未通过并已标为需要修改。新增结构类型、连续拆分与旧推测面保留、厚度不足提示。101 项 Python 测试通过，23 份 GLB 完整校验零错误、零警告；不代表任意家具均可准确自动拆分。

最新一轮见 **[完整坐垫拆分、推测接合面与拆装验收](docs/COMPLETE_CUSHION_REVIEW_2026-11-13.md)** 和 [四向图片及失败记录](experiments/complete_cushion_20261112/index.html)。本轮聚焦一把实际蓝椅：坐垫、椅身切口与移动后导出均通过闭合检查，支持局部换材质；推测接合面可橙色高亮。默认候选约 44.14% 表面积为推测接合面，不等于真实零件还原。91 项 Python 测试通过，5 份 GLB 完整校验通过。可直接 [打开最终装配副本](http://127.0.0.1:8001/?job=58218e68edfd42889d295436a8e1ed42)。

最新一轮见 **[多点修正、候选范围、边界、结构细节与 UV 验收](docs/SELECTION_REFINEMENT_REVIEW_2026-11-12.md)** 和 [八家具图片与失败证据](experiments/selection_refinement_20261112/index.html)。已接通正负点击修正、缓存范围切换、橙色选区边界与蓝色 UV 接缝、结构细节生成档位、代理与圆形 UV 展开。77 项 Python 测试通过；八个固定家具样本中六个得到非空初始候选，三个高细节任务完成但未证明细腿或孔洞明显改善。高面数 UV 自动对照后才采用代理；失败与退步样本均保留。当前服务仍为 [http://127.0.0.1:8001](http://127.0.0.1:8001)。

上一轮见 **[点击辅助、部件检查、生成对照、UV 与拆装验收](docs/PART_TOOLS_REVIEW_2026-11-12.md)** 和 [实测对比页](experiments/part_tools_20261112/index.html)。新版当前运行在 [http://127.0.0.1:8001](http://127.0.0.1:8001)，旧服务保留。已增加本地 SAM 多视角点击候选、隔离/隐藏与底面检查、同图双引擎对照、精细/快速 UV 展开、拆解展示、实际移动与部件单独导出。八家具测试及失败重测记录均保留；自动候选仍需修正，不保证完整语义零件。

部件与材质工作台最新验收见 **[五项改动、多家具测试与已知限制](docs/FURNITURE_WORKBENCH_REVIEW_2026-11-12.md)**，或打开 [实测图片与交互证据总览](experiments/furniture_workbench_20261112/index.html)。已接通完整表面分组候选、部件清单联动、合并/拆出/移动选区、材质即时预览与显式保存、质量检查与保守修复。自动候选不等于准确语义零件；八份已有家具和两张新图片的实测结果、失败及修正均在报告中。

最新阶段交付见 **[详细汇报与操作说明](docs/PROJECT_DELIVERY_REPORT_2026-11-11.md)**，或打开 [图像与实测证据总览](experiments/project_delivery_20261111/index.html)。现已具备输入检查、输出几何检查、最多一次本地返工，以及版本化几何分组和整体/局部参数材质编辑；这些不等于任意图片的商品级还原。

所有最终 GLB 已集中到 **[library/models/](library/models/)** 一个目录，共 68 件。打开 [可搜索模型库](library/index.html) 查找和下载；整体布局见 [项目目录说明](docs/PROJECT_STRUCTURE.md)，生成与维护见 [建模代码说明](modeling/README.md)。

面向家具与家居商品的图片转 3D 项目。输入至少一张图片，经过目标选择、图片准备、建模、材质处理和审核，输出可预览的 GLB 资产及质量报告。

现已接入本地自动目标识别、TripoSR 自动图生 3D 和对话看图建模。默认选择“本地自动生成”：提交选中的商品后，在本机自动去背景、推理形状和颜色、导出并校验 GLB，结果回到工作台，不需要商业 API 密钥。对话看图建模作为独立协作路线保留。

已根据实际上传图片独立制作了 [三眼外星人床头桌](http://127.0.0.1:8000/?job=6b42f4e4a12f4954837b22cad0b660e0) 和 [五层木书柜](http://127.0.0.1:8000/?job=de3c04312fdd4a99993e29e29bccb388)。最终文件位于 `library/models/assistant__*.glb`，预览在 `library/previews/`，可编辑源文件在 `modeling/scenes/assistant/`。它们没有使用默认书柜模板。背面与尺寸仍包含推测。

## 启动工作台

要求 Python 3.9+、Node.js 20.19+ 和支持 WebGL 的现代浏览器。在项目目录执行：

```powershell
# 第一次安装依赖并构建前端
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Install

# 以后启动
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

打开 [本地工作台](http://127.0.0.1:8000)。本机已配置本地识别环境与模型。手动结构工具无需 Blender；对话协助建模使用本机 Blender。

开发时分别运行后端与前端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.api.app:app --host 127.0.0.1 --port 8000 --reload
npm run dev
```

开发前端地址为 `http://127.0.0.1:5173`。生产构建由同一个 FastAPI 服务提供，无需同时启动两个服务。

## 当前能力

| 能力 | 状态 |
| --- | --- |
| 上传、EXIF 纠正、原图保留 | 已实现，JPG/PNG/WebP，最大 12 MB / 2400 万像素 |
| 选商品、裁剪、手工背景擦除、撤销与重置 | 已实现；不会补全遮挡结构 |
| 自动物件识别与点击选框 | 已接入本地 Grounding DINO Tiny，不需要密钥；检测结果是候选，需要检查 |
| 按目标框精细分割 | 已接入本地 SAM 2.1 Hiera Tiny；自动模式对场景图启用，保留手工擦除，生成期间可查看主体和掩码叠加图 |
| 尺寸标注清理与输入质量检查 | 本地 OCR 保守清除独立尺寸文字/双端引线；破碎掩码、低原生像素及遮挡候选会停在建模前，处理图与原因可查看 |
| 输出几何检查与有限返工 | 按目标品类筛查薄片、方块退化及连通片；可最多换另一本地模型一次，失败候选与可用下载分开 |
| 分组与整体/局部材质 | 完整表面候选与清单联动、逻辑合并、拆出/移动面归属；保留点选、涂抹、可见表面框选与撤销。材质与 PBR 贴图即时预览、取消恢复、显式保存、自包含 GLB 导出 |
| 质量检查与保守修复 | 统计整体重复/退化面、边界与非流形；安全清理和小幅平滑，不新增开口、不自动填洞，不补出缺失零件 |
| 参考视角与补充图片 | 轮廓驱动的近似相机拟合、参考图叠加、参数/IoU 记录；最多 8 张补充参考图，当前不参与多视图融合 |
| LOD 与版本管理 | 静态无 UV 部件减面与偏差保护；独立版本、历史恢复、备注、归档、双模型比较、完全相同内容的硬链接存储 |
| 编辑版本审核 | 原模型和编辑版本分别审核，恢复与再编辑不继承旧审核；原始 GLB 保留 |
| 本地自动图生 3D | TripoSR，独立 Python 环境及 CUDA 推理，支持自动去背景、阶段进度、取消和 GLB 校验 |
| 对话看图建模 | 已实现任务提交、等待、模型导入和结果回显；由当前对话查看图片并编写 Blender 模型 |
| 开放架、桌/边几、双门柜模板 | 已实现；依据人工选择的结构与参数生成自包含 GLB |
| Three.js 旋转、缩放、平移、网格、全屏 | 已实现 |
| 图片对照、质量报告、审核、GLB/ZIP 下载 | 已实现；近似参考角度叠加可用，尚未完成真实相机标定；记录包作为可选下载 |
| 持久化任务、幂等创建、取消、重启恢复 | 已实现本地版本 |
| Meshy AI 图生 3D | 协议适配器已实现；需要密钥、用户允许第三方处理和真实账号验证 |
| 自动识别模板/参数、遮挡补全、实物尺寸自动提取 | 待实现；现有 OCR 只用于尺寸标注清理 |
| 真实照片材质恢复、相机标定、多图几何融合、语义 3D 部件识别 | 待实现；上传自有贴图与近似视角拟合已可用 |

本地版使用 SQLite、本地文件与两线程 Worker，供单人试验。目标生产架构中的 PostgreSQL、对象存储、持久队列与多用户隔离尚未部署。详细范围见 [MVP 运行与限制](docs/MVP_STATUS.md)。

## 无密钥使用方式

1. 上传图片，等待本地检测；单件/主要家具会提出选框，多件物品可以点击标签切换。
2. 默认选择“本地自动生成”，分割策略默认“自动选择”：场景图在 SAM 2 就绪时按目标框分割；白底通常走基础处理，主体贴紧裁剪边缘时可用 SAM 细分；已有透明通道保留。之后自动检查输入风险，也可明确选择分割策略。
3. 点击“开始生成”，等待本机推理和 GLB 校验，网页自动显示候选模型。该路线不会进入等待对话状态。
4. 直接下载 GLB；需要复查依据时再下载处理记录包。记录包不是另一个更精细的模型。

“手动结构工具”只按人工参数构建，保留用于规则结构编辑，已不作为默认图片生成方式。

“对话看图建模”仍需在本对话触发制作，适合需要针对结构单独处理的物件；不会自动调用聊天能力。

## 本地图生 3D 安装与使用

2026-11-11 新增 Hunyuan3D-2mini **几何实验**，可在本地模型下拉框中选择；当前没有运行纹理模型。首轮三张实际图片对比中，两张干净输入的几何有改善，场景扶手椅因抠图丢失靠背未通过，见 [首轮质量验收记录](docs/QUALITY_ACCEPTANCE_2026-11-11.md)。后续 SAM 2 同图复测恢复了靠背并改善灰模，仍有粗糙表面、未封闭网格及未验证的背面/纹理，见 [分割验收](docs/SEGMENTATION_ACCEPTANCE_2026-11-11.md)。完整商品外观尚未通过验收，不将“文件生成成功”当作“商品还原成功”。

模型为 [stabilityai/TripoSR](https://huggingface.co/stabilityai/TripoSR)，主权重约 1.6 GiB，采用公开 MIT 许可。安装脚本下载固定版本源码和权重，验证 Git blob/SHA-256；本机文件保存在 `.tools/TripoSR/` 和 `.models/triposr/`。商品图不发送到模型供应商。

使用 Python 3.10 和 CUDA 版 PyTorch；本机 3D 环境复用现有 `claude` 环境的 torch，通过单独 venv 安装其余依赖，不修改目标识别使用的原环境：

```powershell
& 'D:\Miniconda3\envs\claude\python.exe' -m venv --system-site-packages .venv-3d
.\.venv-3d\Scripts\python.exe -m pip install -r requirements-3d.txt --index-url https://pypi.tuna.tsinghua.edu.cn/simple
.\.venv\Scripts\python.exe scripts/setup_local3d.py
.\.venv-3d\Scripts\python.exe scripts/generate_local3d.py --check
```

迁移电脑时将第一行替换为已有的 Python 3.10/CUDA PyTorch 环境。也可创建完全独立的环境，先安装与显卡匹配的 CUDA PyTorch，再安装 `requirements-3d.txt`。`LOCAL3D_PYTHON` 可指定解释器，默认自动查找项目的 `.venv-3d`。环境检查通过后，网页“服务状态”显示本地模型就绪。

直接推理检查：

```powershell
.\.venv-3d\Scripts\python.exe scripts/generate_local3d.py --input path/to/product.png --output .data/modeling/local-test
node scripts/check_asset.cjs .data/modeling/local-test/model.glb
```

TripoSR 默认使用 192³ 网格采样、半精度形状推理和分块网格查询，CPU 提取等值面，避免在 Windows 上编译 `torchmcubes`。自动去背景优先保留已有透明通道；纯白背景使用边缘连通分离以保留浅色部件。其他背景在 SAM 2 就绪时按选中目标框分割；基础策略使用本地 CPU U2NetP。SAM 分割后不会重复执行 U2NetP，也不会补全遮挡部分。TripoSR 输出使用模型预测的顶点颜色，尚无独立 PBR 纹理图。单位为未校准比例，填写的模板尺寸不会拉伸 AI 模型。

## 本地 SAM 2 精细分割

采用 Grounding DINO 候选框 → SAM 2.1 Hiera Tiny 像素掩码 → 本地 3D。模型与图片处理均在本机，下载公开权重无需 API 密钥。独立环境复用已有 CUDA PyTorch，其余依赖单独安装：

```powershell
& 'D:\Miniconda3\envs\claude\python.exe' -m venv --system-site-packages .venv-sam2
.\.venv-sam2\Scripts\python.exe -m pip install -r requirements-sam2.txt
.\.venv\Scripts\python.exe scripts/setup_sam2.py
# 用实际图片/目标框运行一次；只有成功推理后才标为就绪
.\.venv-sam2\Scripts\python.exe scripts/segment_target.py --input path/to/photo.png --target 0 0 1 1 --output .data/sam2-check
```

迁移时替换第一行的 CUDA PyTorch 环境路径；可用 `SAM2_PYTHON` 指定独立解释器。源码和权重固定版本并校验哈希；不编译 CUDA 扩展。网页可选择自动、SAM 2 或基础策略。自动模式在 SAM 尚未就绪时走基础处理；明确选择 SAM 后，未就绪或运行失败会报错，不会悄悄替换策略。关闭自动去背景会跳过分割。

每次保存 `segmented.png`、`segmentation_mask.png`、`segmentation_overlay.png`、`segmentation_summary.json` 和 `segmentation.log`，记录原图/掩码哈希、实际耗时及分阶段显存。绿色/红色只是预测保留/丢弃区域；模型预测分数不是实测准确率。原图、手工擦除和历史模型分别保留。对同一场景扶手椅的真实复测见 [分割与几何验收](docs/SEGMENTATION_ACCEPTANCE_2026-11-11.md)。

后续已盘点 `images/` 的 884 张图片，并固定 11 个跨品类样本完成真实检测、分割和 Hunyuan 推理。首轮助手查看实际输出后，3 个可作几何预览候选、3 个需修正、5 个不通过；11 个 GLB 文件校验均通过，但完整商品资产接受为 0。见 [首轮逐件验收记录](docs/MULTICATEGORY_ACCEPTANCE_2026-11-11.md) 与 [可筛选的图像报告](experiments/multicategory_20261111/index.html)。首轮暴露了彩绘花瓶漏检、默认大件目标优先、杂物/反射未清理、尺寸标注残留及薄片/方块退化等问题；后续输入清理修正见下节，不将小样本数量当作泛化准确率。

## 本地输入清理与质量拦截

工作台现在在形状推理前运行独立输入准备 Worker：分割/去背景 → RapidOCR 检查 → 清除与主体分离的尺寸文字及独立双端引线 → 遮挡候选与掩码检查 → 可用输入继续 3D，不合适的输入停在“需要处理”。清理只改变 alpha，不修补原图 RGB。普通文字、与主体相连的结构及未确认的细部保留。

```powershell
& 'D:\Miniconda3\envs\claude\python.exe' -m venv --system-site-packages .venv-preflight
.\.venv-preflight\Scripts\python.exe -m pip install -r requirements-preflight.txt
.\.venv-preflight\Scripts\python.exe scripts/test_input_preflight.py
```

迁移时替换为已有 CUDA PyTorch/Transformers 环境路径；`PREFLIGHT_PYTHON` 可指定解释器。OCR 使用随包的本地 ONNX 模型并记录哈希，遮挡筛查复用现有 Grounding DINO 权重。检测、分割、输入检查和 3D 共用显卡锁，串行运行；商品图片不上传外部服务。

每个任务保存 `foreground_before_cleanup.png`、`cleaned.png`、`cleanup_mask.png`、`input_overlay.png`、`input_quality.json` 与日志。拦截任务不启动 3D、不提供 GLB，可查看原因并修改图片后新建任务。规则是启发式判断，可能漏检或误拦；遮挡处理目前是识别并提示修正来源图，没有运行自动对象擦除或不可见结构补全。命令行直接调用旧生成脚本属于独立推理入口，不包含工作台的输入检查。

同批 11 例复测：5 例在建模前拦截，6 例继续生成；完成两例修正后，4 个可作几何候选、1 个需修正、1 个仍生成失败。盆栽清除了尺寸文字和引线；圆桌首轮策略造成的多余薄片已在独立重验中消除。完整商品资产接受仍为 0，彩绘花瓶薄片等问题未解决。详见 [输入清理与质量拦截验收](docs/INPUT_GUARD_ACCEPTANCE_2026-11-11.md)，首轮回归和旧失败全部保留。

## 输出检查、分组与换材质

工作台在本地生成之后运行独立几何检查。可明确指定目标品类，并开关“几何异常时最多换一个本地模型重试”。失败候选保存于任务的 `attempts/`，只作为诊断查看；最终来源记录实际通过检查的模型。检查是启发式筛查，不能证明瓶口、纹理、背面或尺寸正确。

已有候选模型下方提供“部件与材质编辑”。选择已有部件或点击模型，可局部/整体换色、粗糙度、金属度与透明近似；需要连续网格局部改材质时，可先按空间区域分组。连通片/区域只表示几何分组，不会自动识别桌腿或坐垫，也不切开实体。每次操作生成独立 GLB 与编辑记录，可查看历史、恢复原始/历史版本，并单独审核编辑版本。参数材质不是实拍 PBR 纹理。

2026-11-12 扩展：模型下方可画笔/框选三角面、加减选、撤销重做并保存为稳定 ID 的部件；支持色彩 / OpenGL 法线 / 灰度粗糙度贴图及纹理缩放旋转。缺少 UV 时使用平面投影，需检查拉伸。参考视角拟合是低分辨率轮廓近似，不代表商品准确率；补充图片仅用于对照，不做多图融合。LOD 对带 UV 的部件保守拦截。版本支持备注、归档、比较与重复内容存储整理，历史不删除。详见 [本轮审查与验收报告](docs/ASSET_UPGRADE_REVIEW_2026-11-12.md) 和 [实测看板](experiments/asset_upgrade_20261112/index.html)。

同日交互修订：模型生成后进入独立编辑阶段，图片准备栏默认隐藏，点击“对照原图”或“修改图片 / 重新生成”按需打开。编辑分为“换材质 / 拆分部件 / 更多操作”。涂抹与框选默认只选可见表面，使用 BVH 加速射线检查遮挡，穿透选择在“选择设置”中单独开启。保存选区后自动把材质修改范围设为新部件，防止误改整个模型。详见 [表面选择与界面简化验收](docs/SELECTION_UX_REVIEW_2026-11-12.md)。

点选辅助：默认提供“查看 / 转动”“点选部件”“涂抹修正”。点选已有部件可直接换材质；连体网格可尝试按独立连通区域或连续平面自动扩选，不能保证识别完整语义部件。桌面平面测试可用，沙发/曲面花瓶存在拒绝案例，提示改用涂抹；平面结果不保证包含侧边和底面。点选范围可调，框选保留在涂抹的选择设置中。详见 [点选部件试用验收](docs/POINT_SELECTION_REVIEW_2026-11-12.md)。

真实示例：[带两个区域材质的盆栽](http://127.0.0.1:8000/?job=6eab9c5a4a9545febbfc0835fd89ee4e)。分组及材质编辑已验证顶点、节点变换与三角面多重集合不变；固定导出和外部 Blender 查看见最新详细报告。编辑 Worker 当前使用已有 Hunyuan/TripoSR 环境，支持静态自包含 GLB，不超过 128 MiB。

检测与 3D 生成在服务内共用显卡锁；取消会终止对应推理进程并释放显存。推理期间保存 `foreground.png`、`model_input.png`、`local_summary.json` 和 `local3d.log`，报告记录输入哈希、模型版本、耗时及显存峰值。模型只有完整校验通过后才开放下载，失败不会回退到模板或其他付费路线。

## 本地目标检测

当前使用 `Grounding DINO Tiny`，权重约 657 MB，保存在被 Git 忽略的 `.models/grounding-dino-tiny/`。商品图片只在本机处理，模型文件下载不需要账号密钥。

当前机器已在 `.env` 配置现有的 ML Python 环境，未修改该环境的软件。迁移机器时用 Python 3.10+ 创建独立环境并安装 `requirements-vision.txt`，将 `VISION_PYTHON` 指向该解释器，再运行：

```powershell
.\.venv\Scripts\python.exe scripts/setup_detector.py
```

检测按图片哈希和检测代码版本缓存。候选包括书柜/柜子、沙发/扶手椅、椅子、桌子、花瓶、盆栽和落地灯。奇特造型、遮挡和画面边缘仍可能识别不全，手工框选保留作为修正手段。自动检测框不等于像素级抠图或遮挡补全。

本机书柜场景实测识别出书柜、花瓶、盆栽和扶手椅；一次检测约 22 秒，首次约 79 秒，均包含启动开销，仅作本机实测参考。

## 配置云端生成

复制 `.env.example` 为 `.env`，设置服务端 `MESHY_API_KEY` 后重启。可以使用 `MESHY_AI_MODEL` 固定账号支持的模型。

云端仅在选择 AI 路线且勾选第三方处理说明后提交；模板不会偷偷回退到云服务。每次只提交一个候选，提交结果不确定时暂停，不自动重新付费提交。实际费用以供应商账单为准；本版尚无严格金额预算控制。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm run build
# 先启动本地服务，再运行浏览器流程测试（默认使用本机 Chrome）
npm run test:e2e
# 验证真实图片中的检测结果、切换目标及两个看图建模资产
node scripts/test_detection_workflow.mjs
# 使用真实 CUDA 推理，验证不同图片、网页生成、取消、下载和移动端
node scripts/test_local3d_workflow.mjs
# 浅色部件/透明通道保留的回归检查（在 3D 环境中运行）
.\.venv-3d\Scripts\python.exe scripts/test_local3d_preprocess.py
# 稳定部件、PBR 嵌入、资源回收、LOD 与失败保护
.\.venv-hunyuan\Scripts\python.exe scripts/test_asset_advanced.py
# 同一真实场景图：网页 SAM 2 → Hunyuan 推理、证据下载、刷新和移动端
node scripts/test_sam2_workflow.mjs
```

浏览器测试会创建一条真实的本地模板任务，并将截图和测试交付包写入 `.data/checks/workbench/`。可通过 `CHROME_PATH` 和 `WORKBENCH_URL` 修改浏览器与测试地址。

## 项目文档

- [完整项目方案](docs/PROJECT_PLAN.md)：产品边界、处理流程、人工参与、MVP、验收和推进顺序。
- [技术设计](docs/TECHNICAL_SPEC.md)：系统架构、数据契约、任务状态、接口、版本与成本控制。
- [模型选型与核验记录](docs/MODEL_SELECTION.md)：候选方案、已核验的官方资料和需要实测的事项。
- [资产编辑扩展、审查与验收](docs/ASSET_UPGRADE_REVIEW_2026-11-12.md)：六个方向、65 项回归、6 个真实模型及未完成能力。
- [独立部件重建与真实复测](docs/SOLID_PARTS_REVIEW_2026-11-13.md)：完整圆柱抱枕、重建预览、三件家具逐组验证，以及未通过的坐垫与语义拆分问题。
- [多视角部件边界改进](docs/SEMANTIC_BOUNDARY_REVIEW_2026-11-13.md)：可见视角排除约束、灰色未确认区域、四件家具复测及未采用的试验。

## 已分组部件的独立实体预览

先采用 AI 整体分组，在“拆分部件 → 生成独立部件预览”中自动补齐当前范围。蓝色为重建外表面，橙色为附近缺少源表面支持的推测区域；保存复用预览文件，原版本保留。未通过闭合、自交和偏差保护的组保留原样。闭合不能证明部件边界或实物形状正确，当前坐垫与主体的准确自动拆分仍未通过验收。

此功能需要已有的 Hunyuan 几何环境，以及隔离的 CPU 依赖：

```powershell
.\.venv-hunyuan\Scripts\python.exe -m pip install --target .tools/geometry_extra --no-deps -r requirements-geometry.txt
```

当前只重建无 UV、无顶点颜色及普通参数材质的静态部件。识别仍使用 Grounding DINO Tiny + SAM 2.1 Hiera Tiny；补齐使用几何重建及有观测证据的圆柱曲面拟合，不需要商业密钥。细节和失败记录见上述复测报告。

## 建议先做的闭环

```text
上传一张图 → 选择一件商品 → 调整抠图 → 生成一个候选模型
          → 统一尺寸和材质 → 原图对比与旋转查看 → 审核 → 下载
```

第一版覆盖白底图和轻度杂乱的场景图，优先支持桌/几、开放架和简单柜体。复杂遮挡、镜面/玻璃、软包与混合结构应分别评估，逐步开放。

## 现有可复用内容

| 路径 | 当前作用 | 下一步 |
| --- | --- | --- |
| `modeling/build/` | 按批次维护的最终 Blender 建模、GLB 导出与渲染入口 | 根据参考图修改具体产品 |
| `modeling/lib/` | 共用几何、短绒、材质映射和构件库 | 保持跨批次依赖集中 |
| `modeling/materials/` | 材质与贴图准备 | 保留已归档的取样参考图 |
| `modeling/run.py` | 统一生成、校验、目录和按需打包命令 | 详见 `modeling/README.md` |
| `assets/` | 现有材质资源 | 补充来源、比例尺和使用范围 |
| `library/models/` | 全部最终 GLB，集中在单个目录 | 通过模型索引搜索和批量导入 |
| `library/previews/` | 所有模型预览与细节图 | 对照参考图检查 |
| `modeling/scenes/` | 可编辑 Blender 源文件 | 后续修改与生成 |
| `.data/` | 工作台任务、草稿和测试记录 | 与最终交付模型分开 |

现有具体商品脚本与工作台的三类参数模板分别维护；均尚未实现从任意图片自动识别参数。原型中的尺寸和不可见结构需要单独确认，不能作为实物依据。

## 项目原则

1. 单张图片能够生成展示模型，但不能保证恢复不可见结构和真实尺寸。
2. 原图、分割结果、修补结果和最终资产分别保存；AI 修补不能覆盖原始证据。
3. 未提供可靠尺度时，模型标记为“比例预览”；完成尺寸确认后再启用真实尺寸展示。
4. 自动检查通过后仍需人工确认外观；技术成功、外观合格和尺寸已核准分别记录。
5. 商业服务和本地模型通过适配器接入，按真实商品评测结果选择。

## 六件家居模型的最终文件

这组六件物品的最终 GLB、预览和校验报告集中在 [统一模型库](library/index.html?batch=studio6)。纸巾盒采用最后确认的不对称波浪空盒，茶几为单张，扶手椅包含短绒毛几何。

相关代码位于 [modeling/build/studio6](modeling/build/studio6/README.md)，提供统一生成、预览、格式校验和可选打包入口。
