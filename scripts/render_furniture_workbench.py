"""Independent Blender views; diagnostic colors are explicitly separate files."""
import json
import sys
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/furniture_workbench_20261112';tasks=[];results=[]
for case in json.loads((OUT/'real_runs.json').read_text(encoding='utf-8')):
    name=case['case'];tasks.extend([(name,'source',ROOT/'.data/jobs'/case['source_job']/'model.glb',False),(name,'groups',OUT/(name+'_auto_diagnostic.glb'),True)])
    if case.get('repair_version'):tasks.append((name,'repair',OUT/(name+'_repaired.glb'),False))
tasks.append(('round_table','fine',OUT/'round_table_fine_diagnostic.glb',True))
for case in json.loads((OUT/'new_generation_runs.json').read_text(encoding='utf-8')):
    if case['snapshot'].get('model_url'):tasks.append((case['case'],'new_generation',ROOT/'.data/jobs'/case['job']/'model.glb',False))
comparison=OUT/'engine_comparison.json'
if comparison.exists():
    case=json.loads(comparison.read_text(encoding='utf-8'))
    if case['snapshot'].get('model_url'):tasks.append((case['case'],'new_generation',ROOT/'.data/jobs'/case['job']/'model.glb',False))
for name in ('accent_chair','stone_table','stone_table_hunyuan'):
    path=OUT/(name+'_auto_diagnostic.glb')
    if path.exists():tasks.append((name,'groups',path,True))
if '--refresh-reviewed' in sys.argv:
    tasks=[t for t in tasks if t[1]=='repair' or (t[0] in ('accent_chair','stone_table','stone_table_hunyuan') and t[1]=='groups')]
    results=json.loads((OUT/'external_renders.json').read_text(encoding='utf-8'))
if '--new-groups-only' in sys.argv:
    tasks=[t for t in tasks if t[0] in ('accent_chair','stone_table','stone_table_hunyuan') and t[1]=='groups']
    results=json.loads((OUT/'external_renders.json').read_text(encoding='utf-8'))
for name,stage,path,diagnostic in tasks:
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(path));scene=bpy.context.scene;objects=list(scene.objects);meshes=[o for o in objects if o.type=='MESH'];points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices]
    low=Vector(tuple(min(v[a] for v in points) for a in range(3)));high=Vector(tuple(max(v[a] for v in points) for a in range(3)));scale=1/max(high-low);parent=bpy.data.objects.new('Display normalization only',None);scene.collection.objects.link(parent)
    for obj in objects:
        if obj.parent is None:obj.parent=parent
    parent.scale=(scale,)*3;parent.location=Vector((-(low.x+high.x)/2,-(low.y+high.y)/2,-(low.z+high.z)/2))*scale;target=Vector((0,0,0))
    scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.device='CPU';scene.cycles.use_denoising=True;scene.render.threads_mode='FIXED';scene.render.threads=6
    scene.render.resolution_x=360;scene.render.resolution_y=360;scene.render.resolution_percentage=100
    world=bpy.data.worlds.new('Neutral inspection');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Color'].default_value=(.8,.8,.8,1);world.node_tree.nodes['Background'].inputs['Strength'].default_value=.5;scene.world=world
    for lightname,position,energy in [('key',(-3,-4,5),400),('fill',(3,1,-1),160)]:
        data=bpy.data.lights.new(lightname,'AREA');data.energy=energy;data.size=4;obj=bpy.data.objects.new(lightname,data);scene.collection.objects.link(obj);obj.location=position;obj.rotation_euler=(target-obj.location).to_track_quat('-Z','Y').to_euler()
    data=bpy.data.cameras.new('Inspection camera');camera=bpy.data.objects.new('Inspection camera',data);scene.collection.objects.link(camera);data.type='ORTHO';data.ortho_scale=1.4;scene.camera=camera
    angles=[('front',(1.7,-3,1.5))]
    if diagnostic or stage=='new_generation':angles.append(('under',(-1.7,3,-1.1)))
    for angle,position in angles:
        camera.location=position;camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler();filename=f'{name}_{stage}_{angle}.png';scene.render.filepath=str(OUT/filename);bpy.ops.render.render(write_still=True)
        results=[r for r in results if r['image']!=filename];results.append({'case':name,'stage':stage,'angle':angle,'image':filename,'source':str(path),'diagnostic_color_override':diagnostic,'reference_camera_fitted':False});(OUT/'external_renders.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print('FURNITURE_RENDER_DONE '+filename,flush=True)
