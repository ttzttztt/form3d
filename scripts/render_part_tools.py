import json
import sys
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/part_tools_20261112';records=json.loads((OUT/'real_edits.json').read_text(encoding='utf-8'));tasks=[];renders=[]
for c in records:
    for stage in ('planar','unwrapped'):tasks.append((c['case'],stage,OUT/(c['case']+'_'+stage+'_checker.glb')))
    tasks.append((c['case'],'exported_part',OUT/(c['case']+'_part.glb')))
comparison=json.loads((OUT/'generation_compare_ui.json').read_text(encoding='utf-8'))
for name,job in [('chair_hunyuan',comparison['source']),('chair_triposr',comparison['alternative'])]:tasks.append((name,'generation',ROOT/'.data/jobs'/job/'model.glb'))
if '--only-exports' in sys.argv:
    tasks=[t for t in tasks if t[1]=='exported_part'];renders=json.loads((OUT/'external_renders.json').read_text(encoding='utf-8'))
for name,stage,path in tasks:
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(path));scene=bpy.context.scene;objects=list(scene.objects);meshes=[o for o in objects if o.type=='MESH'];points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices];low=Vector(tuple(min(v[a] for v in points) for a in range(3)));high=Vector(tuple(max(v[a] for v in points) for a in range(3)));scale=1/max(high-low);parent=bpy.data.objects.new('Display normalization only',None);scene.collection.objects.link(parent)
    for obj in objects:
        if obj.parent is None:obj.parent=parent
    parent.scale=(scale,)*3;parent.location=Vector((-(low.x+high.x)/2,-(low.y+high.y)/2,-(low.z+high.z)/2))*scale
    scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.device='CPU';scene.cycles.use_denoising=True;scene.render.threads_mode='FIXED';scene.render.threads=6;scene.render.resolution_x=360;scene.render.resolution_y=360;scene.render.resolution_percentage=100
    world=bpy.data.worlds.new('Neutral inspection');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Color'].default_value=(.8,.8,.8,1);world.node_tree.nodes['Background'].inputs['Strength'].default_value=.5;scene.world=world
    for lightname,position,energy in [('key',(-3,-4,5),400),('fill',(3,1,-1),160)]:
        data=bpy.data.lights.new(lightname,'AREA');data.energy=energy;data.size=4;obj=bpy.data.objects.new(lightname,data);scene.collection.objects.link(obj);obj.location=position;obj.rotation_euler=(-obj.location).to_track_quat('-Z','Y').to_euler()
    data=bpy.data.cameras.new('Inspection camera');camera=bpy.data.objects.new('Inspection camera',data);scene.collection.objects.link(camera);data.type='ORTHO';data.ortho_scale=1.4;scene.camera=camera
    angles=[('front',(1.7,-3,1.5))]+([('under',(-1.7,3,-1.1))] if stage in ('unwrapped','generation') else [])
    for angle,position in angles:
        camera.location=position;camera.rotation_euler=(-camera.location).to_track_quat('-Z','Y').to_euler();filename=f'{name}_{stage}_{angle}.png';scene.render.filepath=str(OUT/filename);bpy.ops.render.render(write_still=True);renders=[r for r in renders if r['image']!=filename];renders.append({'case':name,'stage':stage,'angle':angle,'image':filename,'source':str(path),'diagnostic_checker':stage in ('planar','unwrapped'),'reference_camera_fitted':False});(OUT/'external_renders.json').write_text(json.dumps(renders,ensure_ascii=False,indent=2),encoding='utf-8');print('PART_RENDER_DONE '+filename,flush=True)
