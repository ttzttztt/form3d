# 生成路线决策（2026-11-16）

## 结论

1. **停止“整体网格 → 事后切分 → 几何补洞”路线的继续投入。** 整体网格里本来就没有部件之间的接触面和被遮挡的表面，切出来的部件必然缺面或粘连。之前用圆柱拟合、膨胀、winding 曲面等补丁，没能稳定解决这个问题（见 [reviews/](reviews/) 中的多份复测）。现有功能保留，作为“已有模型的后期编辑”工具，不再作为主生成路线。
2. **主路线改为“原图部件规划 → 原生按部件生成 → 审计 → 装配”**，已接入工作台，路线名 `parts_first`，见下文“当前实现”。生成器先用 **PartCrafter**，下一步优先评估 **FlexPart**。
3. **硬质部件走参数化拟合，软包部件走 AI 生成**（待实现，见“下一步”）。
4. **6 GB 显卡不够用。** 目前没有一个原生部件模型官方支持 6 GB，需要 ≥12 GB，最好 24 GB 的卡或云 GPU。

## 候选模型核实结果

核实日期为 2026-11-16，来源是各项目 GitHub README / LICENSE。**Hugging Face 与 arXiv 在核实环境中无法访问**，因此权重卡上的许可证、论文中的部件上限和耗时都没有核实，表中标为“未核实”。

| 模型 | 能否直接从图生成独立部件 | 输入要求 | 纹理 | 代码许可 | 商用 | 显存（官方） | 适用性 |
|---|---|---|---|---|---|---|---|
| **PartCrafter** | 能，一次联合生成 N 个部件网格 | 图片和部件数 | 无 | MIT（基于 TripoSG，MIT） | 代码可以；权重许可未核实 | ≥8 GB | **当前生成器**，已接入 |
| **FlexPart**（PartCrafter 改进版） | 能，按点/框/掩码提示生成指定部件 | 图片和部件提示 | 无 | MIT，权重沿用 TripoSG 等来源 | 代码可以；权重未核实 | 未说明 | **首选评估对象**：本项目已有 DINO+SAM 部件掩码，可以直接作为提示 |
| HoloPart | 不能，补全已分割网格中的完整部件 | 网格和逐面部件标签 | 无 | MIT | 可以 | 未说明 | 可作为“已有整件模型 → 补全部件”的后期工具 |
| OmniPart | 能（基于 TRELLIS） | 需要 2D 部件掩码 | 未核实 | MIT，但 NOTICE 含 NVIDIA 非商用代码（PartField）和 RMBG-2.0 | **实际上不可商用** | 未说明（TRELLIS 基础需 ≥16 GB） | 仅研究对照 |
| PartPacker（NVIDIA） | 能 | 图片 | 无 | NVIDIA Source Code License，非商用 | **不可商用** | 约 10 GB | 排除 |
| Hunyuan3D-Part（P3-SAM + X-Part） | 不能，分割/补全已有网格 | 网格 | 无 | 腾讯社区许可 | 月活 100 万以内可商用；**欧盟、英国、韩国不适用** | 未说明 | 视目标市场而定；X-Part 开源版为精简版 |
| Hunyuan3D-2.1 | 不能，生成整体网格 | 图片 | **有 PBR** | 腾讯社区许可（同上限制） | 同上 | 形状 10 GB，纹理 21 GB | 纹理阶段候选，需要大显存 |
| Hunyuan3D-2mini（现用） | 不能 | 图片 | 需 2.0 纹理模型 | 腾讯社区许可（同上限制） | 同上 | 形状 6 GB | 保留为整体生成的备选 |
| TRELLIS / TRELLIS.2 | 不能 | 图片 | **有，TRELLIS.2 为 PBR** | MIT（nvdiffrast 等子模块另有许可） | MIT 部分可以 | ≥16 GB / ≥24 GB | 纹理阶段候选 |
| TripoSR（现用默认） | 不能 | 图片 | 顶点色 | MIT | 可以 | 约 6 GB | 仅快速预览 |
| PartField | 不能，在已有网格上做部件特征聚类 | 网格 | — | NVIDIA 非商用 | 不可 | — | 排除 |
| SAMPart3D | 不能，逐物体优化分割 | 网格 | — | MIT | 可以 | — | 后期工具候选 |
| CoPart / PartGen / BANG / KaiNinja | 论文称可以 | — | — | 代码未发布或推理代码缺失 | — | — | 关注，暂不可用 |

参考链接：
- 主要候选：<https://github.com/wgsxm/PartCrafter>、<https://github.com/Gucci233/FlexPart>、<https://github.com/VAST-AI-Research/HoloPart>、<https://github.com/HKU-MMLab/OmniPart>、<https://github.com/NVlabs/PartPacker>
- 腾讯 Hunyuan 系列：<https://github.com/Tencent-Hunyuan/Hunyuan3D-Part>、<https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1>、<https://github.com/Tencent-Hunyuan/Hunyuan3D-2>
- 整体生成与纹理：<https://github.com/microsoft/TRELLIS>、<https://github.com/microsoft/TRELLIS.2>、<https://github.com/VAST-AI-Research/TripoSR>
- 部件分割：<https://github.com/nv-tlabs/PartField>、<https://github.com/Pointcept/SAMPart3D>

**上线前必须补核：** PartCrafter / TripoSG / FlexPart 在 Hugging Face 上的权重许可证。

## 当前实现（`parts_first` 路线）

工作台里选“部件优先生成”并选择家具类别后，一次提交，后台依次运行：

| 阶段 | Worker | 运行环境 | 门槛 |
|---|---|---|---|
| 1. 原图部件规划 | `services/workers/plan_assembly_from_photo.py`（Grounding DINO Tiny + SAM 2.1 Tiny） | `.venv-sam2`，占用 GPU | 计划状态必须为 `planned`，即没有类别冲突且不超过 16 个部件；否则停在 `awaiting_input` 并说明原因 |
| 1b. 用户确认（默认开启） | 界面显示带编号的叠加图，可以修正类别、去掉部件；`POST /api/jobs/{id}/parts-plan/confirm` | — | 修正后用规划器同一个构建函数重建计划，仍须满足上面的门槛；原始计划保存为 `plan.original.json` |
| 2. 按部件生成 | `generate_partcrafter.py`（部件数来自第 1 步的计划） | `.venv-parts`，占用 GPU | 每个槽位都要解码出有限网格 |
| 3. 审计 | `audit_parts_first.py` | `.venv-hunyuan` + `.tools/geometry_extra` | 每个部件闭合、无自交，且与原图部件掩码一一对应；否则停在 `awaiting_input` |
| 4. 装配导出 | `export_planned_assembly.py` | 同上 | 生成带部件身份、UV、层级的 GLB，并做完整 glTF 校验 |
| 5. 发布 | `attach_assembly_candidate` | API 进程 | 哈希与身份一致后才进入 `awaiting_review` |

编排代码在 `services/api/parts_first.py`，测试在 `tests/test_parts_first.py`。环境是否就绪可以看 `/api/config` 中 `providers.parts_first.missing`。

**未验证：** 本次整理所在的环境没有 GPU 和模型权重，所以只验证了编排、门槛、取消和前端流程（用假 worker 和真实子进程），**没有跑真实推理**。各阶段 worker 是原有代码，原作者曾单独跑过，见 [HISTORY.md](HISTORY.md) 和 `experiments/parts_first_*`（未入库）。

## 下一步

1. **硬件。** 用 24 GB 卡（本地 3090/4090，或云上 A10G/L4）跑通 `parts_first`，并记录每阶段耗时和显存峰值。6 GB 卡上 PartCrafter 只能减部件数、减 token 勉强尝试，不作为默认方案。
2. **固定评测集。** 按 [GOAL-parts-first.md](GOAL-parts-first.md) 的要求，≥10 个不同家具设计，覆盖白底、杂乱背景和一图多件。对比三种方案：现有整体路线、PartCrafter、FlexPart。指标如下：
   - 部件召回率和误拆、误合，以人工部件清单为准；
   - 逐部件闭合率；
   - 原图对应率（仅作诊断，不是精度）；
   - 人工外观评分。
3. **FlexPart 接入。** 把第 1 步的 SAM 部件掩码直接作为 FlexPart 的提示，替换 PartCrafter 的“只给部件数”。这一步只需改第 2 阶段的 worker，编排不用动。
4. **硬质部件参数化。** 桌面、桌腿、柜门、层板、抽屉面板改为拟合参数化基元，用部件掩码加生成网格的包围盒和朝向做约束，AI 只负责坐垫、靠枕、抱枕等软包部件。可以复用 `services/api/geometry.py` 里的 GLBBuilder 与模板构件。
5. **纹理。** 几何验收通过后再单独评估 TRELLIS.2 或 Hunyuan3D-2.1 纹理，两者都需 ≥21–24 GB 显存。按部件烘焙材质时，要保持部件身份不变。
