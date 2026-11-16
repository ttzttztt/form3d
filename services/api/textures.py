"""The same raster conversion for live material preview and embedded GLB maps."""
from PIL import Image

def texture_image(path,slot):
    with Image.open(path) as source:image=source.convert('RGB')
    if max(image.size)>4096:image.thumbnail((4096,4096))
    if slot=='roughness_image':
        gray=image.convert('L');image=Image.merge('RGB',(Image.new('L',image.size,255),gray,Image.new('L',image.size,255)))
    return image
