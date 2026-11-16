"""Non-flat OpenGL normal map for saved-versus-live material acceptance."""
from pathlib import Path
import numpy as np
from PIL import Image
folder=Path(__file__).resolve().parents[1]/'experiments/furniture_workbench_20261112'
y,x=np.mgrid[0:128,0:128];nx=.5*np.sin(x/128*np.pi*8);ny=.4*np.cos(y/128*np.pi*6);nz=np.sqrt(1-nx*nx-ny*ny);pixels=np.stack((nx,ny,nz),axis=-1)
Image.fromarray(np.uint8(np.clip((pixels*.5+.5)*255,0,255))).save(folder/'normal_image_nonflat.png')
