from pathlib import Path
from PIL import Image,ImageDraw
OUT=Path(__file__).resolve().parents[1]/'experiments/multifurniture_20261113'
def sheet(rows,name,size=300):
    result=Image.new('RGB',(size*max(map(len,rows)),(size+30)*len(rows)),'white');draw=ImageDraw.Draw(result)
    for y,row in enumerate(rows):
        for x,(file,label) in enumerate(row):
            result.paste(Image.open(OUT/file).convert('RGB').resize((size,size)),(x*size,y*(size+30)+30));draw.text((x*size+6,y*(size+30)+7),label,fill='black')
    result.save(OUT/name)
sheet([[(f'{name}_{stage}_front.png',name+' '+stage) for stage in ('assembled','moved','part')] for name in ('chair','round_table','bookcase','leather_sofa','corduroy_sofa')],'five_furniture_comparison.png')
sheet([[(f'{name}_part_{view}.png',name+' '+view) for view in ('front','under','side')] for name in ('chair','round_table','leather_sofa','corduroy_sofa')],'parts_under_side.png')
