# 项目目录

```text
form3d/
  apps/web/                 网页工作台（React + three.js，Vite 构建）
    src/App.tsx             页面外壳
    src/workbench/          工作台状态 hook（useWorkbench）与各区域组件
    src/Viewer.tsx 等       3D 查看器、资产编辑器与选择工具
  services/
    api/                    FastAPI 后端：任务、存储、路由编排、GLB 检查
      app.py                HTTP 接口
      pipeline.py           任务执行入口，按 route 分派
      parts_first.py        一键“部件优先”流程编排
      assembly_*.py         部件计划 / 装配数据契约与导入
    workers/                由后端以子进程调用的 worker 及其共用库
                            （检测、分割、TripoSR / Hunyuan / PartCrafter 推理、几何处理）
  scripts/
    setup/                  下载权重、准备隔离环境
    tools/                  手工工具（如 attach_assistant_asset.py）
  tests/                    Python 接口与编排测试（pytest）
    workers/                worker 级单元测试
    js/                     前端模块的无浏览器检查（npm run test:js）
    e2e/                    浏览器流程（需先启动服务；npm run test:e2e）
  docs/                     路线、规格、历史记录与复测报告（reviews/）
  modeling/                 Blender 建模说明（源文件未入库，见 ASSETS.md）
  start.sh / start.ps1      启动脚本（macOS/Linux / Windows）
```

未入库的目录（`library/`、`assets/`、`experiments/`、`.models/`、`.tools/`、`.venv-*`、`.data/`）见 [ASSETS.md](ASSETS.md)。

## 约定

- **worker 是独立脚本**：在各自的隔离 Python 环境中运行，通过命令行参数与 JSON 文件通信。它们按裸模块名互相导入（同目录），不要从 API 进程直接 import 需要 GPU 依赖的 worker。
- **新的一次性实验脚本**不要放进 `services/workers/`。需要保留时放在 `experiments/<日期>/`，不入库；被服务调用后再迁入 workers 并补测试。
- **格式**：Python 用 `ruff format`，lint 用 `ruff check`；前端用 `npm run format`。
