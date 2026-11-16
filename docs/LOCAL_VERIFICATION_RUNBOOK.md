# 本机验证执行手册（交给本地 AI 执行）

> **给本地 AI 的一句话指令（可直接粘贴）：**
> 请完整阅读仓库分支 `claude/sharp-davinci-3glv92` 中的 `docs/LOCAL_VERIFICATION_RUNBOOK.md`，严格按顺序执行第 0–7 阶段。每个阶段结束时把结果追加到报告文件。遇到“停止条件”时立即停下并汇报，不要自行修改代码。最后按第 7 阶段的模板交回报告。

---

## 背景（执行者需要知道的）

这个项目把家具照片转换成带独立部件的 3D 模型（GLB）。最近的改动都还没有在真实显卡上验证过，本次的目标就是在这台 Windows + RTX 3060（6 GB）机器上验证以下三点：

1. **部件优先路线（`parts_first`）**：在原图里识别部件 → 用户确认 → 生成 → 审计 → 装配。
2. **规则部件参数化**：
   - 如果识别出的部件全部是桌面、支腿、柜门等规则部件，直接用盒体或圆柱构建，不使用显卡。
   - 如果有软包部件，先用 AI 生成全部部件，再把其中的规则部件替换为拟合后的构件。
3. **显存档位**：PartCrafter 按显存自动选档（standard → reduced → low → minimal），显存不足时自动降档重试，并记录显存峰值。档位阈值目前是估计值，**需要你实测出数据**，再由维护者校准。

相关代码：`services/api/parts_first.py`（编排）、`services/workers/fit_parametric_parts.py`、`services/workers/parametric_parts.py`、`services/workers/vram_profiles.py`、`services/workers/generate_partcrafter.py`。

## 规则（必须遵守）

- **不修改仓库代码**，也不调整阈值。只运行、记录、汇报。发现 bug 时写进报告，附上日志片段。
- **不 push，不合并，不切换或改动用户原来的工作目录。** 所有验证都在第 1 阶段新建的独立 worktree 里进行。
- **使用端口 8001**，不要占用或停止 8000 上的服务。
- **使用独立的数据目录**（`IMG3D_DATA_DIR`，见第 3 阶段），不删除、不覆盖已有的 `.data/`、`library/`、`experiments/`。
- **不调用任何付费或云端服务**，不把图片上传到外部网站。云端路线（meshy）不在本次范围内。
- **安装依赖前**，先在报告里写明要装什么、装到哪个环境；涉及 CUDA / PyTorch 或超过 1 GB 的下载，先征得用户同意。
- **停止条件**：同一步骤连续失败 2 次；需要改代码才能继续；需要用户提供图片或授权。遇到任一情况，就停下并汇报。

## 报告文件

所有输出放在 worktree 内的 `experiments\local_verification_<日期>\`（下文记为 `$OUT`），报告写在 `$OUT\REPORT.md`。这个目录不提交到 git。

---

## 第 0 阶段：记录机器信息

以下命令在 PowerShell 中运行，在用户原来的项目目录（下文记为 `$SRC`）执行：

```powershell
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
systeminfo | findstr /C:"OS Name" /C:"Total Physical Memory"
git -C $SRC status --short | Select-Object -First 20
git -C $SRC remote -v
```

把 GPU 型号、显存、驱动、内存、系统版本记进报告。`git status` 显示的未提交改动**只记录、不处理**。

## 第 1 阶段：准备独立的验证目录

```powershell
cd $SRC
# 如果没有 origin：git remote add origin https://github.com/ttzttztt/form3d.git
git fetch origin claude/sharp-davinci-3glv92
git worktree add ..\form3d-verify origin/claude/sharp-davinci-3glv92
$DST = (Resolve-Path ..\form3d-verify).Path
```

把模型权重、第三方源码和运行环境以目录联接（junction）的方式共享过去。这样不复制、不修改原目录：

```powershell
foreach ($name in '.models','.tools','.venv','.venv-3d','.venv-hunyuan','.venv-sam2','.venv-vision','.venv-preflight','.venv-parts','library','assets','images') {
  if (Test-Path "$SRC\$name") { New-Item -ItemType Junction -Path "$DST\$name" -Target "$SRC\$name" | Out-Null; "linked $name" } else { "missing $name" }
}
cd $DST
git log --oneline -1
```

把 `linked / missing` 列表和提交号写进报告。然后安装前端依赖并构建：

```powershell
npm ci --no-audit --no-fund
npm run build
```

**预期：** 构建成功，输出里有 `✓ built`。失败时把最后 30 行写进报告，并停止。

## 第 2 阶段：环境自检（不需要显卡）

检查几何环境是否具备新 worker 需要的库：

```powershell
.\.venv-hunyuan\Scripts\python.exe -c "import numpy, scipy, trimesh, PIL, pydantic; print('geometry ok', trimesh.__version__)"
.\.venv-hunyuan\Scripts\python.exe -c "import sys; sys.path[:0]=['.tools/geometry_extra']; import igl, manifold3d; print('geometry_extra ok')"
```

运行参数化构件的单元测试。如果几何环境里没有 pytest，可以改用 `python -m unittest`：

```powershell
$env:PYTHONPATH = "$DST;$DST\services\workers"
.\.venv-hunyuan\Scripts\python.exe -m unittest tests.workers.test_parametric_parts tests.workers.test_vram_profiles -v
```

**预期：** 10 项全部 OK。缺少哪个库就写进报告：`scipy`、`trimesh`、`rtree` 属于小依赖，可以装进 `.venv-hunyuan`；`igl` / `manifold3d` 按 README 安装到 `.tools/geometry_extra`。

## 第 3 阶段：启动工作台并检查就绪状态

新开一个 PowerShell 窗口，让服务一直保持运行：

```powershell
cd $DST
$env:IMG3D_DATA_DIR = "$DST\.data-verify"
.\.venv\Scripts\python.exe -m uvicorn services.api.app:app --host 127.0.0.1 --port 8001
```

回到原来的窗口：

```powershell
(Invoke-RestMethod http://127.0.0.1:8001/api/config).providers.parts_first | ConvertTo-Json -Depth 5
```

把输出完整写进报告。重点看下面几项：

| 字段 | 含义 | 为 false 时 |
|---|---|---|
| `available` | 部件识别和几何环境都已就绪，规则部件家具可以跑 | 看 `missing`，按下表处理 |
| `generator_available` | PartCrafter 可用，含软包件的家具可以跑 | 只能测试桌、柜类；写进报告，继续第 4 阶段的桌、柜案例 |

| `missing` 中的项 | 处理方式（先写进报告；涉及大文件下载的先问用户） |
|---|---|
| `planner_runtime` | 缺少 `.venv-sam2`，参见 README“安装本地模型”一节 |
| `detector_weights` | `.\.venv\Scripts\python.exe scripts\setup\setup_detector.py` |
| `segmenter_weights` / `segmenter_source` | `.\.venv\Scripts\python.exe scripts\setup\setup_sam2.py` |
| `generator_runtime` | 缺少 `.venv-parts`（依赖文件为 `requirements-parts.txt`，需要 CUDA PyTorch）——**先问用户** |
| `generator_weights` / `generator_source` | `.\.venv\Scripts\python.exe scripts\setup\setup_partcrafter.py`（下载约数 GB）——**先问用户** |
| `geometry_runtime` / `geometry_extra` | 参见 README 中 `.venv-hunyuan` 和 `requirements-geometry.txt` 的说明 |

`available` 为 false 且无法补齐时，**停止**并汇报。

## 第 4 阶段：逐个案例运行

### 选择图片
优先使用用户指定的图片。用户没有指定时，从 `images\` 目录（如果存在）中选取，**至少覆盖下面 4 类**，每类 1–2 张：

| 编号 | 类型 | 预期走的路线 |
|---|---|---|
| A | 白底桌子（只有桌面和桌腿） | `parametric_only`，不使用显卡 |
| B | 柜子（柜门、抽屉、层板） | `parametric_only` |
| C | 布艺 / 皮质沙发（坐垫、靠枕），优先选此前失败的两款沙发 | `ai_generation`，之后桌腿等被替换 |
| D | 椅子或单人沙发 | `ai_generation` |

在报告里记录每张图的文件名和 SHA-256（`Get-FileHash <文件>`）。

### 运行
每个案例分两步执行：先停在规划阶段查看叠加图，再正式运行。

```powershell
cd $DST
$OUT = "$DST\experiments\local_verification_$(Get-Date -Format yyyyMMdd)"
# 第一步：只做部件识别，查看 parts_overlay.png
.\.venv\Scripts\python.exe scripts\tools\run_parts_first_case.py --image <图片> --category table --name A1 --output "$OUT\A1_plan" --stop-at-plan
```

打开 `$OUT\A1_plan\parts_overlay.png`。图上每个部件都有编号，对应 `summary.json` 中 `parts_plan.parts` 的 `index` 字段。如果有明显错误，比如把桌腿识别成了层板，或者把杂物识别成了部件，就写一个修正文件 `$OUT\A1_edits.json`，**用叠加图上的编号**指定部件。类别必须从 `parts_plan.kind_options` 中选：

```json
{"remove": [5], "kinds": {"2": "leg"}}
```

第二步：在**同一个任务**上确认并继续生成。任务 id 在 `$OUT\A1_plan\summary.json` 的 `job_id` 字段里。不需要修正时，去掉 `--plan-edits` 这一项即可：

```powershell
$JOB = (Get-Content "$OUT\A1_plan\summary.json" | ConvertFrom-Json).job_id
.\.venv\Scripts\python.exe scripts\tools\run_parts_first_case.py --job $JOB --output "$OUT\A1" --plan-edits "$OUT\A1_edits.json"
```

`--category` 可选 `sofa`、`chair`、`table`、`cabinet`。如果家具只占画面的一部分，用 `--target X Y W H` 框选（0–1 的比例坐标）。

**退出码的含义：**
- 0：生成完成，等待审核；
- 2：停在规划确认或“需要处理”，原因见 `summary.json` 的 `error` 或 `plan_confirm_error`；
- 1：失败。

每个案例都要记录这些内容：
- `summary.json` 中的 `status`、`path`、`error`、`timeline`（各阶段用时）、`parts_generation`（档位和显存峰值）、`vram_retries`、`parametric_fit.parts`（每个规则部件是否被替换，以及偏差）。
- 失败时，附上 `$env:IMG3D_DATA_DIR\jobs\<job_id>\parts_first\*.log` 的最后 30 行。

### 看模型
在浏览器打开 `http://127.0.0.1:8001/?job=<job_id>`，从正面、侧面、背面各截一张图，存到 `$OUT\<编号>\`。另外用一两句话描述：部件是否齐全、是否错位、是否有明显的穿插或悬空。**只描述看到的现象，不要下“合格”的结论。**

C 类案例的另一项检查：把 `--no-parametric` 加上，用同一张图再完整跑一次（会新建任务，识别结果可能与第一次略有不同），对比规则部件替换前后的效果。

## 第 5 阶段：显存档位校准（只在 `generator_available` 为 true 时进行）

**先停掉第 3 阶段的服务**（Ctrl+C），并关闭浏览器、游戏等占用显存的程序，保证测量干净。挑两个已经确认过规划的 AI 案例：一个约 3 个部件，一个约 6–8 个部件。

```powershell
$JOB = "<job_id>"
.\.venv\Scripts\python.exe scripts\tools\calibrate_vram.py --plan "$DST\.data-verify\jobs\$JOB\parts_first\plan" --output "$OUT\vram_$JOB"
```

脚本会依次尝试 4 个档位，每个档位用独立的新进程，最后生成 `calibration.md` 表格（包含成功或显存不足、显存峰值、用时）。把表格原样贴进报告。每个档位可能要几分钟到二十分钟，可以中途让用户确认是否继续。

## 第 6 阶段：收尾

- 停止服务。**保留** `.data-verify`、`$OUT` 和 worktree，维护者可能需要查看。
- 不要执行 `git worktree remove`，也不要删除任何文件。

## 第 7 阶段：交回报告

`$OUT\REPORT.md` 按以下模板填写，然后把这个文件，以及 `$OUT` 下所有 `summary.json` 和 `calibration.md`，交给用户：

```markdown
# 本机验证报告 <日期>

## 机器
GPU / 显存 / 驱动 / 内存 / 系统：
验证提交：<git log --oneline -1>
目录联接：linked … / missing …

## 环境自检
- 前端构建：成功 / 失败（附错误）
- 几何环境导入：…
- 单元测试：x/10 通过（附失败项）
- /api/config parts_first：available=…, generator_available=…, missing=[…]

## 案例结果
| 编号 | 图片 | 品类 | 路线 path | 状态 | 部件数（规划 → 最终） | 档位 / 显存峰值 | 显存重试 | 规则部件替换（成功数/总数） | 总用时 |
|---|---|---|---|---|---|---|---|---|---|

每个案例补充：
- 规划是否需要修正，改了什么：
- 外观观察（只写现象）：
- 截图路径：
- 失败时的错误与日志片段：

## 显存校准
（粘贴每个 calibration.md）

## 发现的问题
1. 现象 / 复现步骤 / 相关日志
```

---

## 常见问题

| 现象 | 处理方式 |
|---|---|
| `run_parts_first_case.py` 报连接失败 | 第 3 阶段的服务没在 8001 上运行，或者启动失败；看服务窗口里的报错 |
| `environment_not_ready` | 回到第 3 阶段，按表补齐 |
| 规划报“类别互相冲突” | 用 `--stop-at-plan` 查看后，在修正文件中为 `unknown` 部件指定类别，或者去掉该部件 |
| 规划报“没有识别出部件” | 换一张主体更完整的图，或者用 `--target` 框得更紧；写进报告 |
| “显存不足：最低档位仍无法完成” | 记录部件数，在修正文件里去掉几个次要部件再试一次；仍然失败就写进报告 |
| “含软包或非规则部件…需要 PartCrafter 环境” | 符合预期（缺少生成环境）；只跑 A、B 两类 |
| 审计不通过（“未通过审计”） | 符合预期的保护机制，不是崩溃；写进报告并附 `parts_audit.json` |
| 参数化替换显示“保留 AI 结果” | 符合预期：偏差超过阈值时不替换；把 `parametric_fit.parts` 中的偏差数值写进报告 |
