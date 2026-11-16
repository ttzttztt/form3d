# 最终模型归档状态

6 个批次、68 个最终 GLB 已统一放在 `library/models/` 的同一层目录，用批次前缀区分同名编号。完整列表与文件哈希见 [library/catalog.json](../library/catalog.json)，浏览与搜索见 [library/index.html](../library/index.html)。

- 已保留每件模型的最后修订版，包括花纹修正后的花卉椅和最终不对称纸巾盒。
- 移动前后所有最终 GLB 的 SHA-256 一致，没有重新生成或改变模型内容。
- 预览、参数和检查报告分别在 `library/previews/`、`library/metadata/`、`library/reports/`。
- 生成代码位于 `modeling/build/`，共用代码在 `modeling/lib/`，统一入口为 `modeling/run.py`。
- 已有的可编辑 Blender 场景集中在 `modeling/scenes/`，外部贴图引用已检查和修复。
- 工作台任务、草稿及浏览器检查记录留在 `.data/`，不混入最终交付目录。
- 原批次输出目录不再用于生成；ZIP 仅按需写入 `library/packages/`。

各目录用途和维护命令见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) 与 [modeling/README.md](../modeling/README.md)。
