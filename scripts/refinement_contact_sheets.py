from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/selection_refinement_20261112'
def sheet(rows,filename,size=260):
    result=Image.new('RGB',(size*max(len(r) for r in rows),(size+35)*len(rows)), 'white');draw=ImageDraw.Draw(result)
    for y,row in enumerate(rows):
        for x,(name,path) in enumerate(row):
            if path.exists():result.paste(Image.open(path).convert('RGB').resize((size,size)),(x*size,y*(size+35)+35))
            draw.text((x*size+5,y*(size+35)+8),name,fill='black')
    result.save(OUT/filename)
sheet([[(f'{name} {quality}',OUT/f'{name}_{quality}_shape_{angle}.png') for quality in ('balanced','structure') for angle in ('front','under')] for name in ('chair_triposr','chair_hunyuan','cabinet_hunyuan')],'structure_contact.png',300)
names=('round_table','alien_table','official_chair','accent_chair','leather_sofa','corduroy_sofa','white_cabinet','authored_bookcase')
sheet([[(name+' '+mode,OUT/f'{name}_{mode}_front.png') for mode in ('box','proxy')+ (('cylinder',) if name=='round_table' else ())] for name in names],'uv_contact.png',300)
sheet([[(name+' '+mode,OUT/f'{name}_{mode}_under.png') for mode in ('box','proxy')+ (('cylinder',) if name=='round_table' else ())] for name in ('round_table','accent_chair','corduroy_sofa','white_cabinet')],'uv_under_contact.png',300)
