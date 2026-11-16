"""Same viewport/camera PBR preview versus reloaded saved GLB, 8-bit RGB pixels."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
folder=Path(__file__).resolve().parents[1]/'experiments/furniture_workbench_20261112'
a=np.array(Image.open(folder/'ui_texture_preview.png').convert('RGB')).astype(float);b=np.array(Image.open(folder/'ui_texture_saved.png').convert('RGB')).astype(float)
assert a.shape==b.shape
diff=abs(a-b);roi=diff[140:550,280:700]
result={'image_shape':list(a.shape),'mean_absolute_rgb_difference_8bit':float(diff.mean()),'fraction_pixels_with_any_channel_over_10':float((diff.max(2)>10).mean()),'fixed_model_roi':[280,140,700,550],'roi_mean_absolute_rgb_difference_8bit':float(roi.mean()),'note':'Same local browser/GPU/camera and synthetic three-map sample only; not photo resemblance or all material coverage.'}
result['normal_map_fixture']='normal_image_nonflat.png'
result['normal_map_unique_rgb_values']=int(len(np.unique(np.array(Image.open(folder/'normal_image_nonflat.png')).reshape(-1,3),axis=0)))
assert result['normal_map_unique_rgb_values']>100
assert result['mean_absolute_rgb_difference_8bit']<.1
assert result['fraction_pixels_with_any_channel_over_10']<.001
(folder/'preview_export_pixels.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
Image.fromarray(np.uint8(np.minimum(diff*4,255))).save(folder/'ui_texture_difference_x4.png')
