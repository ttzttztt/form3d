"""Build an honest stage-scoped report from actual artifacts; never invent missing runs."""
import argparse,html,json,os,sys
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from generate_partcrafter import digest,write

NOTES={
'corduroy_sofa':'本表为首轮全图清单的掩码检查，漏两个小靠枕。后续用保留上下文的单区域分类补到 5 个靠枕、3 块坐面、2 个扶手，见后续进展；新生成沙发仍失败。',
'leather_sofa':'方靠枕和圆柱抱枕可定位；坐垫框把整件家具包住，已在掩码阶段拒绝。圆柱只见端部，不能把端部掩码当成完整圆柱。',
'accent_chair':'弯曲软包和支撑体存在交叠清单，完整部件归属仍不可靠。管状支撑不能直接按固定四条腿处理。',
'catalog24__01_pattern_armchair':'四个可见支撑有框；靠背被标为 back_cushion，和参考的 backrest 不同。部分细长部件掩码仍不支持完整归属。',
'round_table':'桌面与连续支撑底座得到两个掩码；后续已真实采样、导出两个闭合部件，并完成工作台局部编辑实测。外观与真实结构仍未验收，见后续进展。',
'catalog24__05_lift_top_kitchen_cart':'模型能定位顶部和储物区；书、餐具、细杆及轮子造成混淆，未达到完整部件选区。',
'catalog24__06_curved_wood_side_table':'识别了顶部与多个层面；弯曲连续侧架的归属仍不稳定，不能当作两条普通直腿。',
'bookcase':'把整柜区域当作一块 shelf，内部层板没有识别齐。该候选被计数复核拦截，不能生成成一个实心柜子。',
'catalog24__02_cherry_sideboard':'12 个抽屉正面和 1 个柜门被列出；topbox 是未明确的标签，保留为 unknown，没有擅自猜成柜体。抽屉内部深度未验证。',
'catalog24__15_orange_mesh_cabinet':'输出含同类别同坐标的重复部件，归一化时拒绝；没有删除重复项后冒充清单正确。网门厚度与内部结构仍未验证。'}


def run(args):
    root=ROOT/'experiments/parts_first_20261116';evaluation=Path(args.evaluation)
    out=Path(args.output)
    if out.exists():raise ValueError('Preserve prior reports; use a new folder')
    out.mkdir(parents=True);assets=out/'assets';assets.mkdir()
    data=json.loads((evaluation/'evaluation.json').read_text(encoding='utf-8'));rows=data['cases']
    cases={r['case']:r for r in json.loads((ROOT/'experiments/parts_first_20261114/cases.json').read_text(encoding='utf-8'))}
    def rel(path):return Path(os.path.relpath(path,out)).as_posix()
    table=[];cards=[]
    for row in rows:
        case=row['case'];objects=row.get('objects',[]);accepted=sum(o.get('segmented_parts',0)for o in objects);proposed=sum(row.get('proposed_counts',{}).values())
        stage=' / '.join(o.get('plan_status',o.get('status','unknown'))for o in objects)or row.get('reason',row['status'])
        table.append(f'| {cases[case]["title"]} | {proposed if row.get("proposed_counts")is not None else "清单被拒绝"} | {accepted} | {stage} |')
        pictures=[]
        for label,path in [('部件框建议',root/'vlm_4b_ten_01'/case/'boxes.png'),('掩码建议',evaluation/case/'masks/object_00/observations.png')]:
            if path.is_file():
                image=Image.open(path).convert('RGB');image.thumbnail((720,600));file=assets/(case+('_boxes.jpg'if label=='部件框建议'else'_masks.jpg'));image.save(file,quality=88)
                pictures.append(f'<figure><img src="assets/{file.name}" alt="{html.escape(label)}"><figcaption>{label}</figcaption></figure>')
        cards.append('<article><h2>'+html.escape(cases[case]['title'])+'</h2><p>'+html.escape(NOTES[case])+'</p><p>清单数量 '+str(proposed)+'；保留掩码 '+str(accepted)+'；'+html.escape(stage)+'</p><div class="pictures">'+''.join(pictures)+'</div><a href="'+rel(evaluation/case/'evaluation.json')+'">实际逐例数据</a></article>')
    text='''# 按完整部件生成家具：2026-11-16 阶段报告

本轮完成了 10 个不同家具输入的本地部件清单推理和掩码检查，**没有完成 10 个完整家具的新生成与装配验收**。圆桌已作为独立待审候选导入工作台；失败沙发没有发布为完整模型，用户原始模型没有被替换。最终 Goal 仍未达到。

文中的外观判断来自助手对实际渲染图的检查，不代表用户验收或独立实物真值。最新检查：API 128 项通过、几何 157 项通过，前端构建及浏览器操作检查通过；这些测试数量不代表家具数量。

## 本轮实际使用的 AI

本地 Qwen3-VL-4B-Instruct（ebb281ec70b05090aa6165b016eac8ec08e71b17），NF4 量化，提出语义部件和框；SAM 2.1 Hiera Tiny 提取掩码。补查单款沙发还使用 Grounding DINO Tiny。独立靠枕使用 Hunyuan3D-2mini 进行了一次真实图生 3D，圆桌和十部件沙发分别实际调用 PartCrafter。没有使用付费服务，也没有向外部服务上传图片。

## 实测范围与结果

10 款输入固定于 11 月 14 日的 cases.json。本次部件推理使用既有目标框裁图后回映原图坐标，因此覆盖的是目标内的部件识别，不能冒充本轮全场景家具实例检测验收。单图多家具和整场景自动生成仍未达到最终要求。

标签计数对照来自助手对输入图的视觉观察，不是独立人工真值。标签不足可能是漏件或误分类，不能当成准确率。planned 也只表示可以形成下一步的建议，不代表模型或实物结构验收。

| 家具 | 回传清单项 | 保留掩码项 | 建议状态 |
| --- | ---: | ---: | --- |
'''+ '\n'.join(table)+'''

## 发现并改正的问题

- 字段别名：模型使用 top 表示桌面；现在只归一明确同义词，并保存 raw_kind。topbox 等含糊标签保留为 unknown。
- 重复部件：同类别同框会被拒绝，不能靠简单去重掩盖模型循环或误拆分。
- 选区过大：坐垫框若实际上覆盖带靠枕的整件沙发，会被拦截。加入邻件排除点、交叠检查和大缺口检查，不能把破洞掩码当完整坐垫。
- 层级与支撑：识别出框架时也建立层级；靠枕的支撑关系依据附近坐垫提出假设，仍标为 inferred。
- 证据绑定：部件生成绑定实际输入图、掩码、计划和哈希；不能手填部件数就称为 image_plan。
- 回归入口：旧 CLI 的导入副作用已加入口保护。此前误触发检查覆盖两份旧报告的事实和原文件无法精确恢复的限制均已保留记录，没有声称恢复历史字节。

## 独立靠枕重建

真实 Hunyuan3D 推理约 78 秒，原始结果 508,996 面，闭合但含 22 个连通分量，外观偏薄，未通过整体部件几何检查。该结果只是一个新生成的局部部件，不是新生成整件沙发。

另保留两种推测修复：高度场补厚与 3D 距离场偏移。高度场候选虽能形成单闭合体、带 UV 并通过 GLB 规范，但可见形状失真，外观未接受。距离场候选可形成单闭合体并通过 GLB 规范，但边缘仍有不自然鼓包，且尚无 UV 和真实厚度证据；不自动采用。以上派生候选不是新的 AI 采样，也不计为更多家具设计。

“闭合、能打开”不能替代外观、真实背面、装配、换材质邻件隔离等验收。当前没有把这些部件装回原沙发，也没有宣称已恢复实物隐藏结构。

## 当前限制与后续工作

小靠枕的上下文分类已改善；下一步重点是让几何生成受分区、共同坐标与邻件约束，改善浮空和变形。皮革沙发还要区分连续软包主体与可拆坐垫，避免凭类别强行拆出不存在的坐垫/座架。圆桌的姿态修正与部件操作继续单独记录，不能由编辑功能通过推导外观通过。

部件规划、生成、装配、UV/材质、图片对照、实际浏览器操作分别记录；任何阶段未完成就保持未完成，不使用旧材质测试或重复视角替代新的生成验收。

## 证据入口

'''
    text+='- [逐例图像检查页](index.html)\n- [实际检查数据]('+rel(evaluation/'evaluation.json')+')\n- [真实 VLM 执行数据]('+rel(root/'vlm_4b_ten_01/run.json')+')\n- [本轮执行记录]('+rel(root/'WORK_LOG.md')+')\n- [原始靠枕生成结果]('+rel(root/'leather_pillow_hunyuan_01/local_summary.json')+')\n'
    text+='''
## 后续真实进展（不计作新增家具设计）

- 灯芯绒沙发：Grounding DINO/SAM 候选区域保留原图上下文，用 Qwen 对单个高亮目标分类，补齐两个小靠枕。融合后为 5 个靠枕、3 块坐面、2 个扶手，10 个掩码均保留；可拆结构仍未验证。独立白底裁图曾把靠枕误判成扶手，失败输出保留。
- 未观察到的内部框架现在只作为无网格装配组；不再额外生成一层重复座架。观察到的物理主体仍保留实体身份。
- 灯芯绒十实体部件实际联合采样约 354 秒，存在漂浮靠枕和形状错位，且多数部件未过完整性检查；未发布完整沙发。
- 圆桌实际联合采样约 87 秒；两个部件均为单连通闭合体，自交面为 0。旧检查把坐标舍入到 1e-7，曾制造错误破洞；现在只合并完全相同的 float32 位置，移除精确零面积面，不移动顶点、不删除正面积表面。
- 圆桌与原照片的轮廓拟合为同图优化，不能称为独立准确率。最新姿态修正后须重新拟合，不能继承原始候选的数值。
- 圆桌 _05：仅对桌面做最短旋转调平约 16.01°，再沿法线移动约 0.1422 个归一化单位接触支撑。保留原网格和原候选，姿态、接合与尺度均含推测。体积重叠约 2.22e-11（归一化单位立方），属于数值量级；不代表真实榫接或制造精度。
- 圆桌桌面、支撑有独立 UV、材质、稳定 ID 和单独 GLB。六面投影仍有接缝，真实纹理尺度未验证。
- 工作台实际验证：单部件选择、隔离/隐藏/恢复、正背底面、桌面换色不改支撑、两个部件分别下载。原始和实验模型文件哈希未变；保存出的编辑版本保持未验收。
- 导入增加整体哈希、逐部件哈希、身份清单及语义归属一致性检查。导入使用 normalized 单位和真实生成来源，不能误标为 Blender 手工模型或真实米制。
- HoloPart 为“已有分区几何 + 全局上下文 → 补全整体部件”的实验，公开 MIT 模型；已真实试跑，详见下表。它不直接消费图片，也不自动修正错误的原始分区。SAM 3 仍需手动许可授权，本轮没有绕过下载限制。

'''
    for label,path in [
        ('10 部件掩码',root/'corduroy_sam_fused_02/object_00/observations.json'),
        ('失败沙发生成',root/'corduroy_native_01/generation.json'),
        ('失败沙发几何检查',root/'corduroy_native_01/audit_01/audit.json'),
        ('圆桌最新装配与姿态证据',root/'round_table_assembly_05/assembly.json'),
        ('圆桌部件浏览器操作',root/'round_table_operations_05/review.json'),
        ('API 回归日志',root/'api_regression_04.log'),('几何回归日志',root/'geometry_regression_04.log'),
        ('导入契约测试',root/'assembly_import_tests_02.log'),('HoloPart 下载',root/'holopart_download_02.log'),
        ('原始十款图像与模型哈希核对',root/'source_preservation_01.json'),
        ('工作台简化浏览器检查',root/'planned_parts_ui_01/review.json'),
        ('新提示回归后的默认策略',root/'prompt_policy_verification.json'),('代码与输出复核记录',root/'REVIEW.md')]:
        if path.exists():text+='- ['+label+']('+rel(path)+')\n'
    imported=root/'round_table_assembly_05/workbench_import.json'
    if imported.is_file():text+='\n[打开圆桌待审候选]('+json.loads(imported.read_text(encoding='utf-8'))['url']+')。此链接是本机工作台，未表示已验收。\n'
    text+='''
## 皮革沙发：识别、重建和装配约束的新实测

“整体软包主体 + 方靠枕 + 圆柱抱枕”的新清单得到 3/3 可见掩码。坐面和底座作为连续主体保留，不凭类别强行拆出一块可拆坐垫。圆柱仅露出端部，长度仍未知。

同一新提示在灯芯绒沙发发生重复输出，直接判失败。现将该提示保留为 `--continuous-body` 显式实验；默认提示已恢复到十款基线原文，并用哈希确认一致。没有把皮革单例改善直接推广到所有沙发。

HoloPart 使用冻结旧模型的几何分区和全局上下文，4 次完成的采样来自同一款皮革沙发，不是 4 款新家具。另有一次在采样前因参数名错误退出，不计入完成采样。原始输出、潜变量、条件点和标量场均保留。

| 实验 | 完成耗时（秒） | 原始闭合分量 | 原始几何关卡 | 外观/装配结论 |
| --- | ---: | ---: | --- | --- |
'''
    for name,label,note in [
        ('leather_bolster_holo_02','圆柱抱枕','侧面仍有不自然纹路，隐藏长度未验证'),
        ('leather_pillow_holo_01','方靠枕','边缘拖尾；副分量面积约 0.0015%，原始输出未通过单整体要求'),
        ('leather_body_holo_01','整体软包主体','表面有凸起和旧缺口影响，外观未通过'),
        ('leather_pillow_holo_02','靠枕：排除旧推测接合面','仍有拖尾与微小分量，未采用')]:
        file=root/name/'generation.json';audit=root/name/'audit_01/audit.json'
        if file.is_file():
            g=json.loads(file.read_text(encoding='utf-8'));a=json.loads(audit.read_text(encoding='utf-8'))if audit.is_file()else{}
            if g['status']=='raw_candidate_ready':text+='| '+label+' | '+str(g['elapsed_seconds'])+' | '+str(a.get('slots',[{}])[0].get('components','未测'))+' | '+a.get('geometry_gate','未测')+' | '+note+' |\n'
    text+='''
三个部件按旧模型共同坐标装回，靠枕的极小漂浮分量按既有阈值清理，删除面积与体积占比记录在 assembly.json；不能将这种清理算作新的 AI 生成。_03 的三个实体均闭合、单连通、无自交，但两两体积重叠约 2.19%、4.23%、6.33%，因此不能交付。

进一步增加有限范围的刚体接触校正：固定软包主体，只平移靠枕和圆柱抱枕，保持表面形状、材质和部件身份。单件位移上限为场景对角线 4%，并检查它们仍接触主体。这个阈值是实验工程约束，不是实物容差。

'''
    contact=root/'leather_holo_contacts_01/contact_correction.json'
    if contact.is_file():
        c=json.loads(contact.read_text(encoding='utf-8'))
        values=[p['overlap_fraction_of_smaller_part']*100 for p in c['after']['pairs']]
        text+='实际约束求解 '+str(c['evaluations'])+' 次评估、约 '+str(round(c['elapsed_seconds'],2))+' 秒；重叠降至 '+ '、'.join(f'{v:.4f}%'for v in values)+'，主体固定，两个软部件仍与主体接触。存储复核确认：扣除记录的平移后，三角面与材质保持一致。\n\n'
    text+='''
**这仍未通过外观验收。** 靠枕边缘拖尾和主体表面凸起仍在。后续固定相机对照证实，单纯减少穿插会破坏照片对应。最小间隙为零也不能证明承托面积足够；该沙发修复候选没有导入正常任务，更没有替换用户原件。

## 同时约束照片对应和碰撞：拒绝数值上的假改善

'''
    photo_a=root/'leather_contact_photo_01/comparison.json'
    if photo_a.is_file():
        p=json.loads(photo_a.read_text(encoding='utf-8'))
        text+='固定同一个由原图拟合的相机，第一轮接触校正的可见区域对照为：\n\n| 部件 | 校正前同图 IoU | 校正后同图 IoU |\n| --- | ---: | ---: |\n'
        for row in p['parts']:text+='| '+row['kind']+' | '+f'{row["before_visible_mask_iou"]:.4f} | {row["after_visible_mask_iou"]:.4f}'+' |\n'
        text+='\n靠枕和圆柱抱枕明显偏离照片，照片姿态保护未通过，第一轮结果拒绝采用。这是同图近似拟合诊断，不是独立产品准确率。\n\n'
    constrained=root/'leather_holo_contacts_02/contact_correction.json'
    if constrained.is_file():
        c=json.loads(constrained.read_text(encoding='utf-8'));text+='第二轮求解加入固定相机的逐部件可见轮廓保护：500 面代理用来搜索，额外保留更完整网格的独立最终复查，拒绝超过 0.03 IoU 回退的候选。加入沿相机视线的移动方向，避免仅按坐标轴抬高物体。\n\n'
        text+='实际 '+str(c['evaluations'])+' 次候选评估中，'+str(c['photo_constraint']['rejected_candidates'])+' 次被照片约束挡住；搜索约 '+str(round(c['elapsed_seconds'],2))+' 秒。最后两两重叠仍为 '+ '、'.join(f'{p["overlap_fraction_of_smaller_part"]*100:.4f}%'for p in c['after']['pairs'])+'，**接触关卡未通过，保持未采用**。这说明当前错误形状无法仅靠有限平移同时满足照片与装配约束，需要回到可信表面筛选及局部形状重建。\n\n'
    photo_b=root/'leather_contact_photo_02/comparison.json'
    if photo_b.is_file():
        p=json.loads(photo_b.read_text(encoding='utf-8'));text+='第二轮更完整网格的同相机复查：照片姿态保护'+('通过'if p['visible_pose_guard_passed']else'未通过')+'；这个结论不覆盖几何接触和外观。\n\n'
    text+='''
工程保护回归包含“即使移动能减小碰撞，只要违反照片姿态约束也不能采用”。初始姿态本身不满足保护条件时直接失败，不允许空检查误报通过。

## 仍待解决的目标

- 一图多家具和杂乱场景的全流程检测、生成、装配尚未完成端到端验收。
- 十款实测目前覆盖规划/掩码；不能称为十款新模型生成成功。
- 新 Qwen/SAM 规划、HoloPart 补全和接触校正主要是保留证据的本地实验脚本，尚未全部接入工作台的一键任务流程。
- 柜子层板、细腿、抽屉和网门仍有漏识别/归属问题。两款沙发仍没有达到最终外观与完整结构验收。
- 隐藏结构和真实尺寸无独立实物证据。最终完整新装配验收数仍为 0。

后续先用照片约束筛选可信表面，避免把旧模型的推测接合面和错误凸起再次喂给补全模型；把图像对应、表面偏差、碰撞和支撑接触同时纳入候选筛选，再做任务化集成与跨家具复测。
'''
    for label,path in [('皮革三部件掩码',root/'leather_body_sam_01/object_00/observations.json'),
        ('三部件重建装配及失败检查',root/'leather_holo_assembly_03/assembly.json'),
        ('有限范围接触校正',contact),('校正后形状与材质保留复核',root/'leather_holo_contacts_01/storage_verification.json'),
        ('第一轮照片姿态回归',photo_a),('第二轮照片与接触共同约束',constrained),('第二轮最终照片姿态复查',photo_b)]:
        if path.is_file():text+='\n- ['+label+']('+rel(path)+')'
    text+='\n'
    extra=[]
    for label,path in [('灯芯绒沙发：补齐五个靠枕后的十部件选区',root/'corduroy_sam_fused_02/object_00/observations.png'),
                       ('圆桌：姿态修正候选',root/'round_table_assembly_05/renders/object_orbit.png'),
                       ('圆桌：底面',root/'round_table_assembly_05/renders/object_bottom.png'),
                       ('沙发生成失败证据：漂浮与错位',root/'corduroy_native_01/renders/object_orbit.png'),
                       ('皮革沙发：整体软包主体与两类靠枕',root/'leather_body_sam_01/object_00/observations.png'),
                       ('HoloPart 圆柱抱枕：单闭合候选，外观未验收',root/'leather_bolster_holo_02/renders/object_orbit.png'),
                       ('HoloPart 沙发修复：仍有表面伪影',root/'leather_holo_assembly_03/renders_stable_01/object_orbit.png'),
                       ('照片约束下的接触校正：接触仍失败，未采用',root/'leather_holo_contacts_02/renders_stable_01/object_orbit.png')]:
        if path.is_file():
            file=assets/(path.parent.parent.name+'_'+path.name);Image.open(path).convert('RGB').save(file)
            extra.append('<figure><img src="assets/'+file.name+'"><figcaption>'+html.escape(label)+'</figcaption></figure>')
    cards.insert(0,'<article><h2>后续生成与诊断</h2><p>圆桌为独立候选；沙发仍失败。图中颜色用于区分部件，不是恢复的真实材质。</p><div class="pictures">'+''.join(extra)+'</div></article>')
    (out/'REPORT.md').write_text(text,encoding='utf-8')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>完整部件生成·实际测试</title><style>body{font:16px/1.65 system-ui;background:#edf1f6;color:#182338;margin:0 auto;max-width:1160px;padding:28px}h1{font-size:28px}article{background:white;border-radius:12px;padding:22px;margin:24px 0}.pictures{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0}img{width:100%;max-height:550px;object-fit:contain;background:#f5f7fa}a{color:#275bbd}.notice{padding:18px;background:#fff1d4;border-radius:8px}@media(max-width:750px){.pictures{grid-template-columns:1fr}}</style><h1>10 款家具：部件规划与掩码实测</h1><p class="notice">覆盖的是部件规划与掩码检查。没有完成 10 个整件家具的新生成验收，也没有发布完整沙发装配。框和颜色是诊断建议；计数参考不是独立人工真值。</p><p><a href="REPORT.md">详细中文报告</a></p>'+''.join(cards)+'</html>'
    (out/'index.html').write_text(page,encoding='utf-8');write(out/'provenance.json',{'evaluation_sha256':digest(evaluation/'evaluation.json'),'scope':'stage_report_not_goal_completion','complete_assemblies_accepted':0,'distinct_test_designs':len({r['case']for r in rows})})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evaluation',required=True);p.add_argument('--output',required=True);run(p.parse_args())
