# 项目目录与文件去向

## 找模型

所有最终 GLB 集中在 **[library/models/](../library/models/)**，共 6 批、68 件。直接打开 [library/index.html](../library/index.html) 可以搜索名称、筛选批次和下载模型。

```text
img_to3D/
  library/                  最终交付物
    models/                 所有最终 GLB 都在这一层
    previews/               预览、背面和细节图
    metadata/               按批次保存的参数和建模说明
    reports/                格式及几何校验报告
    catalog.json            模型清单和 SHA-256
    index.html              模型库入口
  modeling/                 建模相关源文件
    build/                  各批次生成脚本
    lib/                    共用几何、绒毛和材质映射
    materials/              贴图准备脚本
    references/             贴图取样需要的归档原图
    scenes/                 可编辑 Blender 场景
    tools/                  索引、校验、打包和路径检查
    config.json             批次、文件前缀与脚本注册表
    run.py                  统一维护命令
  assets/                   建模用纹理资源
  apps/web/                 网页工作台
  services/api/             后端接口与生成流程
  scripts/                  启动、环境安装、任务集成与浏览器检查
  tests/                    应用测试
  docs/                     架构、操作与模型说明
  .data/                    本地任务、草稿、缓存及检查记录
  .models/                  本地 AI 模型权重，不是交付 GLB
```

## 日常操作

| 需求 | 位置或命令 |
| --- | --- |
| 找到全部最终模型 | `library/models/` |
| 搜索或按批次查看 | `library/index.html` |
| 修改某件模型 | `modeling/build/` |
| 编辑已有 Blender 场景 | `modeling/scenes/` |
| 更新模型库索引 | `python modeling/run.py catalog` |
| 检查集中目录、链接和文件哈希 | `python modeling/run.py layout` |
| 校验最终 GLB | `python modeling/run.py validate` |
| 检查生成代码依赖 | `python modeling/run.py check` |
| 检查源场景贴图 | `python modeling/run.py scenes` |
| 打包全部最终 GLB | `python modeling/run.py package all` |
| 打包某批次 | `python modeling/run.py package catalog24` |
| 启动工作台 | `powershell -ExecutionPolicy Bypass -File start.ps1` |

默认生成文件带有批次前缀，并直接进入 `library/models/`；预览和参数进入各自目录。使用显式 `--output` 生成的临时任务结果属于草稿，应留在 `.data/`，确认后再发布到模型库。

## 工作台数据与依赖

网页任务通过 `.data/jobs/` 管理自己的输入、进度和草稿模型，避免整理模型库时破坏已有任务。浏览器测试和本地推理检查输出统一位于 `.data/checks/`。这些运行数据不作为最终模型库中的额外交付版本。

`.models/`、`.venv/`、`.venv-3d/`、`.tools/` 和 `node_modules/` 是权重、运行环境或依赖，不与最终模型混放。保留现有启动方式，不需要因本次目录调整重新安装依赖。
