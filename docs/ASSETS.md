# 未入库的资产与数据

当前仓库只有代码和文档。以下目录在原作者机器上存在，但**没有提交**，因此文档里的部分链接会失效，相关功能也会降级：

| 目录 | 内容 | 缺失时的表现 |
|---|---|---|
| `library/` | 最终 GLB 模型库、预览、元数据、`catalog.json` | 首页“示例”为空（`/api/samples` 返回空列表）；`tests/e2e/test_workbench.mjs` 无法运行；对应测试自动跳过 |
| `assets/` | 材质贴图，如 `assets/catalog23_20261110/{corduroy,leather,oak}_{color.jpg,normal.png}` | “示例布料 / 皮革 / 木纹”材质报“本地示例材质文件缺失”，用户自传贴图不受影响 |
| `modeling/`（README 以外的部分） | Blender 建模脚本、场景、`run.py` | `modeling/README.md` 中的命令不可用；工作台不依赖它 |
| `experiments/` | 历次复测图片、报告、`parts_first_*` 实验记录 | 文档中的 `experiments/...` 链接失效 |
| `.models/`、`.tools/`、`.venv-*` | 模型权重、第三方源码、隔离运行环境 | 由 `scripts/setup/` 下载或安装，本来就不该入库 |

## 方案 A：用 Git LFS 入库（推荐，用于 `library/` 和 `assets/`）

仓库已带 `.gitattributes`，GLB、贴图、`.blend` 会自动走 LFS。在有原始文件的机器上执行：

```bash
git lfs install
git add .gitattributes library assets modeling
git commit -m "Add model library and texture assets via LFS"
git push
```

GitHub 免费账户的 LFS 额度有限，超过时需要购买数据包。

## 方案 B：放在仓库外

把 `library/`、`assets/` 放到对象存储或网盘，按原相对路径解压到仓库根目录即可，代码只按这些路径读取。`experiments/` 体积大、只用于追溯，建议用这种方式归档，不进 Git。

## 已删除的一次性脚本

整理时删除了约 250 个一次性的 probe / prepare / benchmark / report / 复测脚本。完整清单见 [ARCHIVE.md](ARCHIVE.md)，需要时可以从初始提交恢复：

```bash
git checkout 03851c0 -- scripts/<文件名>
```
