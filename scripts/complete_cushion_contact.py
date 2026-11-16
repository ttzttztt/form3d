from pathlib import Path
from PIL import Image,ImageDraw
OUT=Path(__file__).resolve().parents[1]/'experiments/complete_cushion_20261112'
def sheet(rows,name,size=330):
    canvas=Image.new('RGB',(size*max(len(row) for row in rows),(size+32)*len(rows)),'white');draw=ImageDraw.Draw(canvas)
    for y,row in enumerate(rows):
        for x,(file,title) in enumerate(row):
            canvas.paste(Image.open(OUT/file).convert('RGB').resize((size,size)),(size*x,(size+32)*y+32));draw.text((size*x+6,(size+32)*y+8),title,fill='black')
    canvas.save(OUT/name)
sheet([[(f'{asset}_{angle}.png',asset+' '+angle) for asset in ('old_surface','cushion_export','cushion_inferred_diagnostic')] for angle in ('front','back','under','side')],'part_comparison.png')
sheet([[('reference.png','Source photo'),('source_front.png','Source generated mesh'),('complete_candidate_front.png','Completed candidate assembled')],[('complete_moved_front.png','Translated candidate front'),('complete_moved_back.png','Translated candidate back'),('complete_moved_under.png','Translated candidate underside')]],'assembly_comparison.png')
