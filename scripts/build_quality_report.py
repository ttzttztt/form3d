"""Build a review artifact from measured records and explicit visual observations."""
import hashlib
import html
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'experiments'/'quality_20261111'


def font(size):
    return ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)


def photo_panel(path,size):
    image=Image.open(path).convert('RGBA')
    background=Image.new('RGBA',image.size,'white')
    image=Image.alpha_composite(background,image).convert('RGB')
    image=ImageOps.contain(image,size,Image.Resampling.LANCZOS)
    panel=Image.new('RGB',size,'white')
    panel.paste(image,((size[0]-image.width)//2,(size[1]-image.height)//2))
    return panel


def main():
    protocol=json.loads((FOLDER/'protocol.json').read_text(encoding='utf-8'))
    review=json.loads((FOLDER/'visual_review.json').read_text(encoding='utf-8'))
    measured=[]
    failures=[]
    for case in protocol['cases']:
        directory=FOLDER/case['id']
        baseline=json.loads((directory/'triposr'/'execution.json').read_text(encoding='utf-8'))
        success=[]
        for path in sorted((directory/'hunyuan').glob('attempt_*/execution.json')):
            item=json.loads(path.read_text(encoding='utf-8'))
            if item.get('status')=='completed' and item.get('technical_acceptance'):
                success.append((path.parent,item))
            else:
                failure_path=path.parent/'failure.json'
                failure=json.loads(failure_path.read_text(encoding='utf-8')) if failure_path.is_file() else {}
                failures.append({'case':case['id'],'execution':str(path.relative_to(FOLDER)),
                                 'error_type':failure.get('error_type'),'error':failure.get('error'),
                                 'status':item['status']})
        if not success:
            raise ValueError('No completed candidate for '+case['id'])
        chosen,item=success[-1]
        # Verify bytes against the worker's own recorded output hash.
        actual=hashlib.sha256((chosen/'model.glb').read_bytes()).hexdigest()
        if actual!=item['summary']['model_sha256']:
            raise ValueError('Candidate asset changed after measurement: '+case['id'])
        fg_hash=hashlib.sha256((directory/'foreground.png').read_bytes()).hexdigest()
        if fg_hash!=item['input_sha256'] or fg_hash!=item['summary']['foreground_sha256']:
            raise ValueError('Comparison did not use identical foreground pixels: '+case['id'])
        measured.append({'case':case['id'],'name':case['name'],'source_kind':case['source_kind'],
                         'baseline':baseline['summary'],'candidate':item['summary'],
                         'candidate_directory':chosen.relative_to(FOLDER).as_posix(),
                         'validation':item['validation'],'visual_review':review['cases'][case['id']],
                         'shared_foreground_sha256':fg_hash})
    result={'date':protocol['date'],'technical_pass_count':len(measured),
            'product_appearance_pass_count':sum(item['visual_review']['product_accepted'] for item in measured),
            'ground_truth_3d_available':False,'overall':review['overall'],
            'cases':measured,'failed_attempts':failures,
            'workflow_test':'pending','user_final_review':review['user_final_review']}
    web=FOLDER/'web_workflow.json'
    if web.is_file():
        result['workflow_test']=json.loads(web.read_text(encoding='utf-8'))
    (FOLDER/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

    cell=460
    collage=Image.new('RGB',(cell*3+80,100+len(measured)*(cell+82)+75),'#eef0f3')
    draw=ImageDraw.Draw(collage)
    for index,title in enumerate(['原始选区（未补全）','TripoSR · 灰模','Hunyuan3D-2mini · 灰模']):
        draw.text((25+index*(cell+15),25),title,font=font(22),fill='#232b39')
    for row,item in enumerate(measured):
        case=item['case']
        y=90+row*(cell+82)
        paths=[FOLDER/case/'reference.png',FOLDER/case/'renders'/'triposr_oblique.png',FOLDER/case/'renders'/'hunyuan_oblique.png']
        for column,path in enumerate(paths):
            collage.paste(photo_panel(path,(cell,cell)),(20+column*(cell+15),y))
        draw.text((25,y+cell+8),item['name'],font=font(20),fill='#1c2635')
        verdict=item['visual_review']['geometry_verdict']
        # A compact caption; full exact feature-level observations are in report.
        caption={'alien':'嘴部和桌面改善；三眼外观未完整验收','chair':'几何改善；本轮不含商品纹理','armchair':'未通过：抠图丢靠背，模型含杂散杆件'}[case]
        draw.text((520,y+cell+9),caption,font=font(19),fill='#8b2934' if case=='armchair' else '#324158')
        # Preserve a larger per-case comparison, suitable for direct review.
        row_image=collage.crop((0,y,collage.width,y+cell+70))
        row_image.save(FOLDER/case/'comparison.png')
    draw.text((25,collage.height-54),'相同灰模材质和固定视角；未拟合照片相机。文件有效 ≠ 商品外观验收合格。',font=font(19),fill='#576174')
    collage.save(FOLDER/'comparison_overview.png')
    rows=[]
    sections=[]
    for item in measured:
        b,c=item['baseline'],item['candidate']
        rows.append('<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in
            [item['name'],b['duration_seconds'],c['duration_seconds'],c['peak_vram_mb'],c['peak_process_rss_mb'],item['visual_review']['geometry_verdict']])+'</tr>')
        observations=''.join('<li><b>'+html.escape(obs['feature'])+'</b>：'+html.escape(obs['observation'])+'</li>' for obs in item['visual_review']['observations'])
        views=''.join('<figure><img src="'+item['case']+'/renders/'+engine+'_'+view+'.png"><figcaption>'+engine+' / '+view+'</figcaption></figure>'
                      for view in ('front','oblique','side','rear') for engine in ('triposr','hunyuan'))
        sections.append('<section><h2>'+html.escape(item['name'])+'</h2><p>'+html.escape(item['visual_review']['geometry_verdict'])+'</p><ul>'+observations+
            '</ul><p><a href="'+item['case']+'/triposr/model.glb">旧版 GLB</a> · <a href="'+item['candidate_directory']+'/model.glb">新版几何 GLB</a> · <a href="'+item['case']+'/foreground.png">实际共同去背景输入</a></p><div class="views">'+views+'</div></section>')
    document='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>本地模型质量实测验收 · 2026-11-11</title><style>body{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;max-width:1300px;margin:32px auto;padding:0 22px;color:#222b38;background:#f8fafc}h1{font-size:26px}.notice{padding:18px;background:#fff2dc;border-left:4px solid #d58b2c}table{width:100%;border-collapse:collapse;background:white}td,th{padding:10px;border:1px solid #dae0e7;text-align:left;font-size:14px}.scroll{overflow:auto}img{max-width:100%;display:block}section{margin:40px 0}figure{margin:0;background:white}figcaption{padding:8px;font-size:13px}.views{display:grid;grid-template-columns:1fr 1fr;gap:12px}a{color:#315bb7}</style>
<h1>本地模型质量实测验收 · 2026-11-11</h1>
<div class="notice"><b>结论：几何有明显改善，完整商品模型尚未通过验收。</b><br>新方案仅生成形状，没有运行纹理模型。场景扶手椅抠图丢失靠背，本轮判为失败。没有真实 3D 和尺寸真值，不提供虚构相似度或准确率。</div>
<p>同一输入前景分别进入 TripoSR 与 Hunyuan3D-2mini；保留输入哈希、模型版本、实测日志和失败尝试。下图来自实际导出 GLB 的统一灰模渲染，不是 AI 修图。</p>
<img src="comparison_overview.png" alt="原图、旧版和新版实际灰模对比">
<h2>本轮实际运行记录</h2><div class="scroll"><table><tr><th>样本</th><th>TripoSR 秒</th><th>Hunyuan 秒</th><th>Hunyuan 显存 MiB</th><th>Hunyuan RSS MiB</th><th>目视验收</th></tr>'''+''.join(rows)+'''</table></div>
<p>显存为 PyTorch 分配峰值，不含驱动、桌面及其他进程；RSS 是每 100ms 采样的本进程工作集，不是整机内存。耗时为工作脚本内实测，包含依赖导入、权重加载、推理和导出，不含检测排队、下载及离线渲染。小样本、系统负载不同，不据此宣称普遍速度提升。</p>
<p>固定参数：Hunyuan 标准 mini 权重、30 步、seed=42、256³ 网格、CPU 分阶段卸载、完整网格提取；输入编码器 BF16，DiT/VAE FP16。TripoSR 基线使用原有 192³ 配置。</p>'''+''.join(sections)+'''
<h2>审计与边界</h2><p>不可见背面、真实尺寸、内部装配与材质反射均无真值，不能验收。当前观测不能推广为所有商品均可用。</p>
<p><a href="protocol.json">预先固定的验收协议</a> · <a href="acceptance.json">完整实测数据与失败尝试</a> · <a href="visual_review.json">逐项目视判断</a> · <a href="web_workflow.json">网页真实推理验证</a></p>'''
    (FOLDER/'index.html').write_text(document,encoding='utf-8')
    print(json.dumps({'technical_pass_count':len(measured),'product_appearance_pass_count':result['product_appearance_pass_count'],
                      'failed_attempts_preserved':len(failures),'report':str(FOLDER/'index.html')},ensure_ascii=True))


if __name__=='__main__':
    main()
