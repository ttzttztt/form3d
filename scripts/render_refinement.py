"""Fixed diagnostic cameras, no camera fitting and no photo resemblance score."""
import json, sys
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/selection_refinement_20261112';tasks=[];renders=[]
for c in json.loads((OUT/'uv_runs.json').read_text(encoding='utf-8')):
    for mode in ('box','proxy','cylinder'):
        path=OUT/(c['case']+'_'+mode+'_checker.glb')
        if path.exists():tasks.append((c['case'],mode,path,True))
for name,job in [('chair_triposr_balanced','95ef2dd6c99d4cacac90a6cf61ef8994'),('chair_hunyuan_balanced','6be16d93f7544ac79c5f09cb3be507fa'),('cabinet_hunyuan_balanced','212518024ebe4a4b9e4bd3543ee4a13c')]:
    tasks.append((name,'shape',ROOT/'.data/jobs'/job/'model.glb',False))
for c in json.loads((OUT/'structure_runs.json').read_text(encoding='utf-8')):
    path=ROOT/'.data/jobs'/c['job']/'model.glb'
    if path.exists():tasks.append((c['case'],'shape',path,False))
for name,stage,path,checker in tasks:
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(path));scene=bpy.context.scene;objects=list(scene.objects);meshes=[o for o in objects if o.type=='MESH']
    points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices];low=Vector(tuple(min(v[a] for v in points) for a in range(3)));high=Vector(tuple(max(v[a] for v in points) for a in range(3)));scale=1/max(high-low);parent=bpy.data.objects.new('Display normalization only',None);scene.collection.objects.link(parent)
    for obj in objects:
        if obj.parent is None:obj.parent=parent
    parent.scale=(scale,)*3;parent.location=Vector((-(low.x+high.x)/2,-(low.y+high.y)/2,-(low.z+high.z)/2))*scale
    if not checker:
        mat=bpy.data.materials.new('Neutral geometry comparison');mat.diffuse_color=(.55,.59,.63,1);mat.use_nodes=True;bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=(.55,.59,.63,1);bsdf.inputs['Roughness'].default_value=.8
        for mesh in meshes:
            mesh.data.materials.clear();mesh.data.materials.append(mat)
            for polygon in mesh.data.polygons:polygon.material_index=0
    scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.device='CPU';scene.cycles.use_denoising=True;scene.render.threads_mode='FIXED';scene.render.threads=6;scene.render.resolution_x=420;scene.render.resolution_y=420;scene.render.resolution_percentage=100
    world=bpy.data.worlds.new('Neutral inspection');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Color'].default_value=(.8,.8,.8,1);world.node_tree.nodes['Background'].inputs['Strength'].default_value=.5;scene.world=world
    for lightname,position,energy in [('key',(-3,-4,5),400),('fill',(3,1,-1),160)]:
        data=bpy.data.lights.new(lightname,'AREA');data.energy=energy;data.size=4;obj=bpy.data.objects.new(lightname,data);scene.collection.objects.link(obj);obj.location=position;obj.rotation_euler=(-obj.location).to_track_quat('-Z','Y').to_euler()
    data=bpy.data.cameras.new('Inspection camera');camera=bpy.data.objects.new('Inspection camera',data);scene.collection.objects.link(camera);data.type='ORTHO';data.ortho_scale=1.4;scene.camera=camera
    angles=[('front',(1.7,-3,1.5))]+([('under',(-1.7,3,-1.1))] if not checker or name in ('round_table','accent_chair','corduroy_sofa','white_cabinet') else [])
    for angle,position in angles:
        camera.location=position;camera.rotation_euler=(-camera.location).to_track_quat('-Z','Y').to_euler();filename=f'{name}_{stage}_{angle}.png';scene.render.filepath=str(OUT/filename);bpy.ops.render.render(write_still=True)
        renders.append({'case':name,'stage':stage,'angle':angle,'image':filename,'source':str(path),'diagnostic_checker':checker,'reference_camera_fitted':False})
        (OUT/'external_renders.json').write_text(json.dumps(renders,ensure_ascii=False,indent=2),encoding='utf-8');print('REFINEMENT_RENDER_DONE '+filename,flush=True)
