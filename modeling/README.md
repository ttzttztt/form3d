# 建模代码与维护命令

最终 GLB 统一放在 [library/models/](../library/models/)，可通过 [模型库索引](../library/index.html) 搜索。这里仅维护生成代码、参考原图和可编辑源场景。

```text
modeling/
  build/        各批次的最终建模入口
    studio6/    六件金属与软包家具的独立模块
    assistant.py
    folded_rack.py
  lib/          共用几何、绒毛、材质映射和 GLB 处理
  materials/    纹理准备脚本
  references/   已归档的取样原图
  scenes/       可编辑 Blender 源文件
  tools/        索引、校验、打包和依赖检查
  config.json   批次与文件前缀配置
  run.py        统一命令入口
```

## 查看与检查

在项目根目录运行：

```powershell
python modeling/run.py list
python modeling/run.py catalog
python modeling/run.py layout
python modeling/run.py validate
python modeling/run.py check
python modeling/run.py scenes
```

唯一交付清单为 `library/catalog.json`。`catalog` 会按注册的批次前缀扫描同一个 `library/models/`，刷新清单、网页索引和 `docs/MODEL_CATALOG.md`。`validate` 校验模型格式和自包含资源，报告写入 `library/reports/validation.json`。

## 修改与重新生成

```powershell
python modeling/run.py prepare collection21
python modeling/run.py build collection21 -- --only 1
python modeling/run.py build reference7 -- --only 4 --no-render
python modeling/run.py build studio6 -- --only 2
python modeling/run.py build furniture6 -- 03
python modeling/run.py build catalog24 -- 07
python modeling/run.py build assistant -- --product bookcase

# 生成后刷新索引并校验
python modeling/run.py catalog
python modeling/run.py validate
```

这些命令默认直接更新集中模型库；文件名带批次前缀，例如 `catalog24__07_tulip_side_table.glb`。参数记录在 `library/metadata/<批次>/`，预览在 `library/previews/`，源场景在 `modeling/scenes/`。

工作台对话建模可用显式 `--output .data/modeling/某任务` 指定草稿位置。单图产品的具体生成逻辑仍以相应脚本为准；这些脚本不是任意图片自动建模算法。

## 导出 ZIP

```powershell
python modeling/run.py package catalog24
python modeling/run.py package all
```

ZIP 按需写入 `library/packages/`，不会常驻维护多份 GLB。每个包的 `models/` 都是单层目录，可批量导入。

## 依赖与源场景

本机 Blender 为 `D:/Blender 5.1/blender.exe`，可通过 `BLENDER_EXECUTABLE` 环境变量覆盖。贴图脚本使用 NumPy、Pillow 和 OpenCV；GLB 校验使用根目录 npm 依赖 `gltf-validator`。现有 Python、Node 和 Blender 环境继续使用。

`python modeling/run.py scenes` 检查归档 `.blend` 的外部贴图。迁移后可用 `python modeling/run.py scenes all -- --repair` 修复项目资产的相对路径。交付 GLB 自带贴图，不依赖这些源资源。

模型尺寸及不可见结构包含估算；格式校验不等同于外观或实物尺寸验收。
