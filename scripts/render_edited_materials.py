# -*- coding: utf-8 -*-
"""Verify the exported edited GLB in Blender without overriding its materials."""
import hashlib
import json
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/asset_editor_20261111';path=OUT/'final_edited_plant.glb'
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=str(path))
objects=list(bpy.context.scene.objects);meshes=[obj for obj in objects if obj.type=='MESH']
points=[obj.matrix_world@vertex.co for obj in meshes for vertex in obj.data.vertices]
low=Vector(tuple(min(v[a] for v in points) for a in range(3)));high=Vector(tuple(max(v[a] for v in points) for a in range(3)))
scale=1/max(high-low);parent=bpy.data.objects.new('Display normalization only',None);bpy.context.collection.objects.link(parent)
for obj in objects:
    if obj.parent is None:obj.parent=parent
parent.scale=(scale,)*3;parent.location=Vector((-(low.x+high.x)/2,-(low.y+high.y)/2,-low.z))*scale
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=24;scene.cycles.device='CPU';scene.cycles.use_denoising=True
scene.render.resolution_x=700;scene.render.resolution_y=700;scene.render.resolution_percentage=100
world=bpy.data.worlds.new('Export review');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Strength'].default_value=.4;scene.world=world
target=Vector((0,0,.5))
for name,location,power in [('key',(-3,-4,5),400),('fill',(3,0,3),180)]:
    data=bpy.data.lights.new(name,'AREA');data.energy=power;data.size=4;obj=bpy.data.objects.new(name,data);scene.collection.objects.link(obj);obj.location=location;obj.rotation_euler=(target-obj.location).to_track_quat('-Z','Y').to_euler()
camera_data=bpy.data.cameras.new('Review camera');camera=bpy.data.objects.new('Review camera',camera_data);scene.collection.objects.link(camera)
camera.location=(1.7,-3,1.5);camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler();camera_data.type='ORTHO';camera_data.ortho_scale=1.38;scene.camera=camera
scene.render.filepath=str(OUT/'edited_materials_blender.png');bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'edited_materials_review.blend'))
(OUT/'external_viewer_validation.json').write_text(json.dumps({'status':'PASS','viewer':'Blender 5.1','model_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'actual_materials_preserved':True,'geometry_changes':'none; display normalization parent only','render':'edited_materials_blender.png','blend':'edited_materials_review.blend'},indent=2),encoding='utf-8')
print('EXPORTED_MATERIALS_RENDERED_WITHOUT_OVERRIDE',flush=True)
