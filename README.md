# FORM · 家具图片转 3D 工作台

上传一张家具照片，在本机生成 3D 模型（GLB）。模型的部件可以单独选择、隐藏、换材质和导出。单机使用，不需要 API 密钥，图片不会上传到外部服务（云端路线需要显式开启）。

> **现状一句话：** 工作台流程已完整；“部件优先”主路线已接成一键任务，但**尚未在真实 GPU 上完成验收**。生成质量仍未达到商品级。详见下文“现状”和 [路线决策](docs/ROUTE_DECISION.md)。

## 快速开始

需要 Python 3.10+、Node.js 20+，以及支持 WebGL 的浏览器。

macOS / Linux：

```bash
./start.sh --install
```

```bash
./start.sh
```

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Install
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

启动后打开 <http://127.0.0.1:8000>。只装基础依赖时可以使用“手动结构工具”和后期编辑；AI 路线需要按下一节安装模型，否则在界面里显示“待就绪”。

开发模式下前后端分开运行，前端地址为 <http://127.0.0.1:5173>：

```bash
.venv/bin/python -m uvicorn services.api.app:app --reload --port 8000
```

```bash
npm run dev
```

## 生成路线

| 路线 | 做什么 | 依赖 |
|---|---|---|
| **部件优先生成**（`parts_first`，主路线） | 原图识别部件 → PartCrafter 按部件联合生成 → 闭合/对应审计 → 输出带部件身份的 GLB | `.venv-sam2`、`.venv-parts`、`.venv-hunyuan`，权重；建议 ≥12 GB 显存 |
| 本地自动生成（`local`） | TripoSR 或 Hunyuan3D-2mini 生成整体网格，可再在编辑器里拆分 | `.venv-3d` / `.venv-hunyuan` |
| 手动结构工具（`template`） | 按参数搭建置物架、桌、柜 | 无 |
| 对话看图建模（`assistant`） | 等待对话中的助手写 Blender 模型后导入 | Blender |
| 云端（`meshy`） | Meshy 图生 3D，需显式同意上传与计费 | `MESHY_API_KEY` |

每条路线需要的环境是否就绪，可以在 `GET /api/config` 中查看；部件优先路线会列出缺少的具体项目（`providers.parts_first.missing`）。

## 安装本地模型（可选）

每个模型使用独立的 Python 环境，避免 transformers 等依赖版本冲突。各环境需要预先装好与显卡匹配的 CUDA PyTorch，也可以用 `--system-site-packages` 复用已有的 PyTorch。

| 环境 | 依赖文件 | 下载权重 | 用途 |
|---|---|---|---|
| `.venv-vision` | `requirements-vision.txt` | `scripts/setup/setup_detector.py` | Grounding DINO 目标检测 |
| `.venv-sam2` | `requirements-sam2.txt` | `scripts/setup/setup_sam2.py` | SAM 2 分割、部件规划 |
| `.venv-3d` | `requirements-3d.txt` | `services/workers/setup_local3d.py` | TripoSR |
| `.venv-hunyuan` | `requirements-hunyuan.txt` + `requirements-geometry.txt`（安装到 `.tools/geometry_extra`） | `scripts/setup/setup_hunyuan3d.py` | Hunyuan3D-2mini、几何审计 |
| `.venv-parts` | `requirements-parts.txt` | `scripts/setup/setup_partcrafter.py` | PartCrafter 部件生成 |

解释器路径可以用环境变量覆盖，变量名为 `VISION_PYTHON`、`SAM2_PYTHON`、`LOCAL3D_PYTHON`、`HUNYUAN_PYTHON`、`PARTS_PYTHON`、`PREFLIGHT_PYTHON`，完整列表见 `.env.example`。PartCrafter 权重默认从 hf-mirror.com 下载，可以用 `HF_ENDPOINT` 改为其他地址。

## 测试

全部 Python 测试：缺少可选依赖或资产的用例会自动跳过。

```bash
python -m pytest
```

前端模块检查，不需要浏览器：

```bash
npm run test:js
```

浏览器冒烟测试，需要先启动服务。可用 `CHROME_PATH` 指定浏览器：

```bash
npm run test:e2e
```

代码格式化与 lint：

```bash
ruff format services tests scripts && ruff check services tests scripts
```

```bash
npm run format
```

## 现状（2026-11-16）

**已经可用：**

- 上传、框选和擦除、目标检测、SAM 2 分割、TripoSR / Hunyuan 整体生成、GLB 校验、审核、下载、任务恢复和取消。
- 后期编辑：部件分组、换材质、UV、减面、单部件重生成。
- 部件优先一键任务：编排、门槛、取消和界面都已测试，用假 worker 与真实子进程验证。

**尚未完成：**

- **部件优先路线未在真实 GPU 上跑通验收。** 当前开发机是 6 GB 显卡，低于 PartCrafter 官方要求的 8 GB；本次整理所在的环境也没有 GPU。
- 生成结果只有几何，没有纹理；真实尺寸和隐藏结构未经验证。
- 硬质部件参数化拟合、FlexPart 评估、纹理阶段还没开始，见 [路线决策 · 下一步](docs/ROUTE_DECISION.md#下一步)。
- 模型库 `library/`、贴图 `assets/` 和实验记录未入库，见 [docs/ASSETS.md](docs/ASSETS.md)。

## 文档

- [路线决策](docs/ROUTE_DECISION.md)：模型核实、为什么改路线、下一步
- [目标与验收约定](docs/GOAL-parts-first.md)
- [项目目录](docs/PROJECT_STRUCTURE.md)
- [技术设计](docs/TECHNICAL_SPEC.md) · [项目方案](docs/PROJECT_PLAN.md) · [模型选型记录](docs/MODEL_SELECTION.md)
- [迭代历史（原 README）](docs/HISTORY.md) · [历次复测报告](docs/reviews/)
- [未入库资产](docs/ASSETS.md) · [已删除脚本清单](docs/ARCHIVE.md)

## 原则

- 原图、分割、生成结果和最终资产分开保存，后续处理不覆盖原始证据。
- 单张图片无法确定的背面、内部结构和尺寸，一律标为推测或未验证。
- 自动检查通过不等于外观合格；每个候选都要人工审核。
- 使用云端服务需要显式同意，不会自动重复付费提交。
