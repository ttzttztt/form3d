"""Render measured geometry candidates from four directions, without accepting them."""
import argparse,json,sys
from pathlib import Path
import bpy
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--folder',required=True);p.add_argument('--files',nargs='+',required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);folder=Path(a.folder).resolve();records=[]
for filename in a.files:
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(folder/filename));scene=bpy.context.scene
    objects=list(scene.objects);points=[o.matrix_world@v.co for o in objects if o.type=='MESH' for v in o.data.vertices];low=Vector(tuple(min(v[k] for v in points) for k in range(3)));high=Vector(tuple(max(v[k] for v in points) for k in range(3)));scale=1/max(high-low);parent=bpy.data.objects.new('Display normalization',None);scene.collection.objects.link(parent)
    for o in objects:
        if o.parent is None:o.parent=parent
    parent.scale=(scale,)*3;parent.location=-(low+high)*.5*scale
    scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.use_denoising=True;scene.render.threads_mode='FIXED';scene.render.threads=6;scene.render.resolution_x=520;scene.render.resolution_y=440;scene.render.resolution_percentage=100
    world=bpy.data.worlds.new('Neutral');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Color'].default_value=(.8,.85,.9,1);world.node_tree.nodes['Background'].inputs['Strength'].default_value=.7;scene.world=world
    for label,pos,power in [('key',(-3,-4,5),450),('fill',(3,2,2),200)]:
        data=bpy.data.lights.new(label,'AREA');data.energy=power;data.size=4;o=bpy.data.objects.new(label,data);scene.collection.objects.link(o);o.location=pos
    data=bpy.data.cameras.new('Diagnostic');camera=bpy.data.objects.new('Diagnostic',data);scene.collection.objects.link(camera);data.type='ORTHO';data.ortho_scale=1.4;scene.camera=camera
    for angle,pos in [('front',(2.5,-3,1.8)),('side',(0,-3,.15)),('back',(-2.5,3,1.8)),('under',(-1,2,-2.5))]:
        camera.location=pos;camera.rotation_euler=(-camera.location).to_track_quat('-Z','Y').to_euler();file=Path(filename).stem+'_'+angle+'.png';scene.render.filepath=str(folder/file);bpy.ops.render.render(write_still=True);records.append({'model':filename,'view':angle,'file':file,'appearance_review':'unreviewed'});(folder/'trial_renders.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print('SOLID_TRIAL_RENDER',file,flush=True)
