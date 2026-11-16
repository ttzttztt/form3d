"""Assemble original masks and real GLB renders; never synthesize evidence."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/segmentation_20261111'
ARM=OUT/'armchair'
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',23)
small=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',18)
sheet=Image.new('RGB',(1600,1230),'#f2f3f5')
draw=ImageDraw.Draw(sheet)

def place(path,box):
    image=Image.open(path).convert('RGBA')
    background=Image.new('RGBA',image.size,'white')
    image=Image.alpha_composite(background,image).convert('RGB')
    fitted=ImageOps.contain(image,(box[2]-box[0],box[3]-box[1]))
    sheet.paste(fitted,(box[0]+(box[2]-box[0]-fitted.width)//2,box[1]+(box[3]-box[1]-fitted.height)//2))

draw.text((20,10),'同一张场景扶手椅：原图 / 旧 U2NetP / SAM 2 / 预测掩码叠加',font=font,fill='#20252c')
top=[ROOT/'experiments/quality_20261111/armchair/reference.png',
     ROOT/'experiments/quality_20261111/armchair/foreground.png',
     ARM/'web_run/segmented.png',ARM/'web_run/segmentation_overlay.png']
for i,(path,label) in enumerate(zip(top,['原图裁剪','旧抠图：靠背丢失','SAM 2：保留可见主体','绿=保留 / 红=丢弃（非真值）'])):
    place(path,(i*400+8,52,(i+1)*400-8,432))
    draw.text((i*400+12,440),label,font=small,fill='#20252c')

for row,(prefix,label) in enumerate([('old_hunyuan','旧 Hunyuan：使用旧抠图'),('sam2_hunyuan','新 Hunyuan：使用 SAM 2 抠图')]):
    y=480+row*355
    draw.text((20,y),label+'；相同种子 / 步数 / 256 网格',font=font,fill='#20252c')
    for i,(view,name) in enumerate([('front','正面'),('oblique','斜视'),('side','侧面'),('rear','背面（无原图验证）')]):
        place(ARM/f'renders/{prefix}_{view}.png',(i*400+5,y+38,(i+1)*400-5,y+322))
        draw.text((i*400+12,y+325),name,font=small,fill='#20252c')
draw.text((20,1195),'实际 GLB 灰模渲染；统一最长轴缩放、相同相机/灯光；不代表尺寸、纹理或隐藏结构已验收。',font=small,fill='#20252c')
sheet.save(OUT/'comparison_overview.png')
print(OUT/'comparison_overview.png')
