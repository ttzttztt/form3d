# -*- coding: utf-8 -*-
"""Local example materials, explicitly separate from real product scans."""
import hashlib,io,threading
from pathlib import Path
from PIL import Image
from .asset_editor import ROOT

PRESETS={
 'fabric':{'label':'示例布料','stem':'corduroy','roughness':.9,'uv_scale':3,'normal_gain':.18},
 'leather':{'label':'示例皮革','stem':'leather','roughness':.55,'uv_scale':2,'normal_gain':.25},
 'wood':{'label':'示例木纹','stem':'oak','roughness':.5,'uv_scale':2,'normal_gain':.12},
}
PRESET_LOCK=threading.Lock()


def prepare_preset(store,name):
    # One local API process can receive several first-use requests concurrently.
    # Keep content publication and the image-row existence check in one section.
    with PRESET_LOCK:return _prepare_preset(store,name)


def _prepare_preset(store,name):
    if name not in PRESETS:raise ValueError('材质套装不存在')
    profile=PRESETS[name];textures={}
    for slot,suffix in(('base_color_image','_color.jpg'),('normal_image','_normal.png')):
        source=ROOT/'assets/catalog23_20261110'/(profile['stem']+suffix)
        if not source.is_file():raise ValueError('本地示例材质文件缺失，请上传自有贴图')
        with Image.open(source)as original:image=original.convert('RGB')
        image.thumbnail((2048,2048))
        if slot=='normal_image':
            # Local examples were visually too deep at unit normal strength.
            # Soften only bundled examples; user-supplied maps remain intact.
            red,green,_=image.split();gain=profile['normal_gain']
            lut=[round(127.5+(value-127.5)*gain)for value in range(256)]
            image=Image.merge('RGB',(red.point(lut),green.point(lut),Image.new('L',image.size,255)))
        encoded=io.BytesIO();image.save(encoded,format='PNG');data=encoded.getvalue()
        identity=hashlib.sha256(data).hexdigest()[:32];folder=store.root/'images'/identity;folder.mkdir(parents=True,exist_ok=True)
        path=folder/'normalized.png'
        if path.is_file()and path.read_bytes()!=data:raise ValueError('示例贴图缓存校验失败')
        if not path.exists():path.write_bytes(data)
        if not store.image(identity):
            image.save(folder/'preview.jpg');store.put_image({'id':identity,'name':profile['label']+' · '+slot,'width':image.width,'height':image.height,'normalized_path':str(path.relative_to(store.root)),'material_provenance':'local_example_not_a_measured_product_scan'})
        textures[slot]=identity
    return {'name':name,'label':profile['label'],'textures':textures,'color':'#ffffff','roughness':profile['roughness'],'metalness':0,'opacity':1,'mode':'replace','uvScale':profile['uv_scale'],'uvRotation':0,'provenance':'示例材质，不代表原商品面料；可上传自有扫描或花纹替换。'}
