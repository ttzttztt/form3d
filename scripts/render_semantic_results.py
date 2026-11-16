"""Render whole-instance colours and isolated observed surfaces for honest review."""
import argparse,json,sys
from pathlib import Path
import bpy,bmesh
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--folder',required=True);p.add_argument('--groups',type=int,nargs='*');p.add_argument('--views',nargs='+',default=['front','side','back','under']);a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);folder=Path(a.folder).resolve();manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));records=[]
for stage,name in [('all',None)]+[(f'group_{i}',g['name']) for i,g in enumerate(manifest['operation']['groups']) if a.groups is None or i in a.groups]:
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(folder/'style.glb'));scene=bpy.context.scene
    if name:
        for o in list(scene.objects):
            if o.type!='MESH':continue
            slots={i for i,m in enumerate(o.data.materials) if m and m.name==name};bm=bmesh.new();bm.from_mesh(o.data);bmesh.ops.delete(bm,geom=[f for f in bm.faces if f.material_index not in slots],context='FACES');bm.to_mesh(o.data);bm.free()
            if not len(o.data.polygons):bpy.data.objects.remove(o,do_unlink=True)
    objects=list(scene.objects);meshes=[o for o in objects if o.type=='MESH'];points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices];low=Vector(tuple(min(v[k] for v in points) for k in range(3)));high=Vector(tuple(max(v[k] for v in points) for k in range(3)));scale=1/max(high-low);parent=bpy.data.objects.new('Display normalization',None);scene.collection.objects.link(parent)
    for o in objects:
        if o.parent is None:o.parent=parent
    parent.scale=(scale,)*3;parent.location=-(low+high)*.5*scale
    scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.use_denoising=True;scene.render.threads_mode='FIXED';scene.render.threads=6;scene.render.resolution_x=520;scene.render.resolution_y=440;scene.render.resolution_percentage=100
    world=bpy.data.worlds.new('Neutral');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Color'].default_value=(.8,.85,.9,1);world.node_tree.nodes['Background'].inputs['Strength'].default_value=.7;scene.world=world
    for label,pos,power in [('key',(-3,-4,5),450),('fill',(3,2,2),200)]:
        data=bpy.data.lights.new(label,'AREA');data.energy=power;data.size=4;o=bpy.data.objects.new(label,data);scene.collection.objects.link(o);o.location=pos
    data=bpy.data.cameras.new('Diagnostic');camera=bpy.data.objects.new('Diagnostic',data);scene.collection.objects.link(camera);data.type='ORTHO';data.ortho_scale=1.4;scene.camera=camera
    for angle,pos in [('front',(2.5,-3,1.8)),('side',(0,-3,.15)),('back',(-2.5,3,1.8)),('under',(-1,2,-2.5))]:
        if angle not in a.views:continue
        camera.location=pos;camera.rotation_euler=(-camera.location).to_track_quat('-Z','Y').to_euler();file=f'{stage}_{angle}.png';scene.render.filepath=str(folder/file);bpy.ops.render.render(write_still=True);records.append({'stage':stage,'name':name,'view':angle,'file':file,'reference_camera_fitted':False});(folder/'renders.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');print('INSTANCE_RENDER',file,flush=True)
