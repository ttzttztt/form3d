import json
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/multifurniture_20261113';tasks=[];records=[]
for name in ('chair','round_table','bookcase','leather_sofa','corduroy_sofa'):
    path=OUT/(name+'_verified_final.glb')
    if path.exists():tasks.append((name,'assembled',path))
    moved=OUT/(name+'_individual_1_moved.glb')
    if not moved.exists():moved=OUT/(name+'_verified_moved.glb')
    if moved.exists():tasks.append((name,'moved',moved))
    index=1
    if name=='round_table':
        run=json.loads((OUT/'round_table_run.json').read_text(encoding='utf-8'));index=next((i for i,c in enumerate(run.get('individual_checks',[]),1) if c['name'].startswith('支脚')),1)
    part=OUT/(name+f'_individual_{index}.glb')
    if not part.exists():part=OUT/(name+'_verified_part_1.glb')
    if part.exists():tasks.append((name,'part',part))
    if name=='round_table':
        for i,c in enumerate(run.get('individual_checks',[]),1):tasks.append((name,'component_'+str(i),OUT/c['export_file']))
for name,stage,path in tasks:
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(path));scene=bpy.context.scene;objects=list(scene.objects);meshes=[o for o in objects if o.type=='MESH'];points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices];low=Vector(tuple(min(v[a] for v in points) for a in range(3)));high=Vector(tuple(max(v[a] for v in points) for a in range(3)));scale=1/max(high-low);parent=bpy.data.objects.new('Display normalization only',None);scene.collection.objects.link(parent)
    for o in objects:
        if o.parent is None:o.parent=parent
    parent.scale=(scale,)*3;parent.location=Vector((-(low.x+high.x)/2,-(low.y+high.y)/2,-(low.z+high.z)/2))*scale
    scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.device='CPU';scene.cycles.use_denoising=True;scene.render.threads_mode='FIXED';scene.render.threads=6;scene.render.resolution_x=420;scene.render.resolution_y=420;scene.render.resolution_percentage=100
    world=bpy.data.worlds.new('Neutral inspection');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Color'].default_value=(.85,.85,.85,1);world.node_tree.nodes['Background'].inputs['Strength'].default_value=.6;scene.world=world
    for label,pos,energy in [('key',(-3,-4,5),400),('fill',(3,1,-1),180)]:
        data=bpy.data.lights.new(label,'AREA');data.energy=energy;data.size=4;obj=bpy.data.objects.new(label,data);scene.collection.objects.link(obj);obj.location=pos;obj.rotation_euler=(-obj.location).to_track_quat('-Z','Y').to_euler()
    data=bpy.data.cameras.new('Inspection camera');camera=bpy.data.objects.new('Inspection camera',data);scene.collection.objects.link(camera);data.type='ORTHO';data.ortho_scale=1.45;scene.camera=camera
    for angle,pos in [('front',(1.7,-3,1.5)),('under',(-1.7,3,-1.4)),('side',(3,0,.25))]:
        camera.location=pos;camera.rotation_euler=(-camera.location).to_track_quat('-Z','Y').to_euler();filename=f'{name}_{stage}_{angle}.png';scene.render.filepath=str(OUT/filename);bpy.ops.render.render(write_still=True);records.append({'case':name,'stage':stage,'view':angle,'image':filename,'source':str(path),'reference_camera_fitted':False,'display_normalized':True});(OUT/'renders.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print('FURNITURE_RENDER '+filename,flush=True)
