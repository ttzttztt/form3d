from pathlib import Path
import shutil
folder=Path(__file__).resolve().parents[1]/'experiments/complete_cushion_20261112';target=folder/'box_trial';target.mkdir(exist_ok=True)
for p in folder.iterdir():
    if p.is_file() and p.name not in {'source_selection.npz','contour_pilot.npz'}:shutil.copyfile(p,target/p.name)
print('Initial box trial preserved, including renders, API versions and browser results')
