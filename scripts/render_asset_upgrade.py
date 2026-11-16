"""External Blender render of actual source/LOD/textured exports; materials retained."""
import json
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/asset_upgrade_20261112';cases=json.loads((OUT/'real_edits.json').read_text(encoding='utf-8'));results=[]
for case in cases:
    lod=next((s for s in case['steps'] if s['operation']=='decimate' and s['status']==201),None)
    stages=[('original',ROOT/'.data/jobs'/case['source_job']/'model.glb'),('textured',OUT/(case['case']+'_edited.glb'))]
    if lod:stages.insert(1,('lod',ROOT/'.data/jobs'/case['test_job']/'assets'/lod['version']/'model.glb'))
    normalization=None
    for stage,path in stages:
        bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(path))
        scene=bpy.context.scene;objects=list(scene.objects);meshes=[o for o in objects if o.type=='MESH']
        if normalization is None:
            points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices]
            low=Vector(tuple(min(v[a] for v in points) for a in range(3)));high=Vector(tuple(max(v[a] for v in points) for a in range(3)));normalization=(low,high)
        low,high=normalization;scale=1/max(high-low);parent=bpy.data.objects.new('Display normalization only',None);scene.collection.objects.link(parent)
        for obj in objects:
            if obj.parent is None:obj.parent=parent
        parent.scale=(scale,)*3;parent.location=Vector((-(low.x+high.x)/2,-(low.y+high.y)/2,-low.z))*scale
        height=(high.z-low.z)*scale;target=Vector((0,0,height*.5))
        scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.device='CPU';scene.cycles.use_denoising=True;scene.render.threads_mode='FIXED';scene.render.threads=6
        scene.render.resolution_x=400;scene.render.resolution_y=400;scene.render.resolution_percentage=100
        world=bpy.data.worlds.new('Neutral inspection');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Color'].default_value=(.8,.8,.8,1);world.node_tree.nodes['Background'].inputs['Strength'].default_value=.5;scene.world=world
        for name,position,energy in [('key',(-3,-4,5),400),('fill',(3,1,3),160)]:
            data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.size=4;obj=bpy.data.objects.new(name,data);scene.collection.objects.link(obj);obj.location=position;obj.rotation_euler=(target-obj.location).to_track_quat('-Z','Y').to_euler()
        data=bpy.data.cameras.new('Review camera');camera=bpy.data.objects.new('Review camera',data);scene.collection.objects.link(camera);camera.location=target+Vector((1.7,-3,1.5));camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler();data.type='ORTHO';data.ortho_scale=1.4;scene.camera=camera
        filename=case['case']+'_'+stage+'_blender.png';scene.render.filepath=str(OUT/filename);bpy.ops.render.render(write_still=True)
        texture_nodes=sum(1 for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE')
        results.append({'case':case['case'],'stage':stage,'file':filename,'source':str(path),'material_override':False,'texture_image_nodes':texture_nodes,'camera':'shared fixed review angle per case, not reference-photo fit'})
        if case['case']=='table' and stage=='textured':bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'textured_table_review.blend'))
        (OUT/'external_renders.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print('UPGRADE_RENDER_DONE '+filename,flush=True)
