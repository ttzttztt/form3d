import json,sys
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/complete_cushion_20261112';records=[]
tasks=[('source',ROOT/'.data/jobs/6be16d93f7544ac79c5f09cb3be507fa/model.glb'),*[(name,OUT/(name+'.glb')) for name in ('old_surface','complete_candidate','cushion_export','cushion_inferred_diagnostic','complete_moved')]]
manifest='renders.json'
if '--pilot-contour' in sys.argv:tasks=[(name,OUT/(name+'.glb')) for name in ('contour_pilot_colored','contour_pilot_diagnostic')];manifest='contour_pilot_renders.json'
for name,path in tasks:
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(path));scene=bpy.context.scene;objects=list(scene.objects);meshes=[o for o in objects if o.type=='MESH'];points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices];low=Vector(tuple(min(v[a] for v in points) for a in range(3)));high=Vector(tuple(max(v[a] for v in points) for a in range(3)));scale=1/max(high-low);parent=bpy.data.objects.new('Display normalization only',None);scene.collection.objects.link(parent)
    for o in objects:
        if o.parent is None:o.parent=parent
    parent.scale=(scale,)*3;parent.location=Vector((-(low.x+high.x)/2,-(low.y+high.y)/2,-(low.z+high.z)/2))*scale
    scene.render.engine='CYCLES';scene.cycles.samples=12;scene.cycles.device='CPU';scene.cycles.use_denoising=True;scene.render.threads_mode='FIXED';scene.render.threads=6;scene.render.resolution_x=500;scene.render.resolution_y=500;scene.render.resolution_percentage=100
    world=bpy.data.worlds.new('Neutral world');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Color'].default_value=(.85,.85,.85,1);world.node_tree.nodes['Background'].inputs['Strength'].default_value=.55;scene.world=world
    for label,pos,energy in [('key',(-3,-4,5),400),('fill',(3,1,-1),200)]:
        data=bpy.data.lights.new(label,'AREA');data.energy=energy;data.size=4;obj=bpy.data.objects.new(label,data);scene.collection.objects.link(obj);obj.location=pos;obj.rotation_euler=(-obj.location).to_track_quat('-Z','Y').to_euler()
    data=bpy.data.cameras.new('Inspection camera');camera=bpy.data.objects.new('Inspection camera',data);scene.collection.objects.link(camera);data.type='ORTHO';data.ortho_scale=1.45;scene.camera=camera
    for angle,pos in [('front',(1.7,-3,1.5)),('back',(-1.7,3,1.4)),('under',(-1.7,3,-1.4)),('side',(3,0,.1))]:
        camera.location=pos;camera.rotation_euler=(-camera.location).to_track_quat('-Z','Y').to_euler();filename=f'{name}_{angle}.png';scene.render.filepath=str(OUT/filename);bpy.ops.render.render(write_still=True);records.append({'asset':name,'image':filename,'view':angle,'source':str(path),'display_normalized':True,'source_camera_fitted':False});(OUT/manifest).write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print('CUSHION_RENDER_DONE '+filename,flush=True)
