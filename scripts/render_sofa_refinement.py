"""Fixed diagnostic views, normalized display, not reference-camera matching."""
import json,sys
from pathlib import Path
import bpy
import bmesh
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/sofa_refinement_20261113';only_trials='--trial2' in sys.argv;records=json.loads((OUT/'renders.json').read_text(encoding='utf-8')) if only_trials else []
for case in json.loads((OUT/'cases.json').read_text(encoding='utf-8')):
    name=case['case']
    tasks=[('source',ROOT/'.data/jobs'/case['job']/'model.glb',False),('assembled',OUT/(name+'_diagnostic.glb'),False),('part',OUT/(name+'_diagnostic.glb'),True)]
    if 'sofa' in name:tasks.append(('previous',ROOT/'experiments/multifurniture_20261113'/(name+'_verified_part_1.glb'),False))
    if only_trials:tasks=[('trial2_assembled',OUT/(name+'_trial2_diagnostic.glb'),False),('trial2_part',OUT/(name+'_trial2_diagnostic.glb'),True)] if 'sofa' in name else []
    for stage,path,solo in tasks:
        if not path.exists():continue
        bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(path));scene=bpy.context.scene;objects=list(scene.objects)
        if solo:
            for o in objects:
                if o.type!='MESH':continue
                hidden={i for i,m in enumerate(o.data.materials) if m and m.name.startswith('preview_body')}
                bm=bmesh.new();bm.from_mesh(o.data);bmesh.ops.delete(bm,geom=[f for f in bm.faces if f.material_index in hidden],context='FACES');bm.to_mesh(o.data);bm.free()
                if not len(o.data.polygons):bpy.data.objects.remove(o,do_unlink=True)
        objects=list(scene.objects);meshes=[o for o in objects if o.type=='MESH'];points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices];low=Vector(tuple(min(v[a] for v in points) for a in range(3)));high=Vector(tuple(max(v[a] for v in points) for a in range(3)));scale=1/max(high-low);parent=bpy.data.objects.new('Display normalization only',None);scene.collection.objects.link(parent)
        for o in objects:
            if o.parent is None:o.parent=parent
        parent.scale=(scale,)*3;parent.location=-(low+high)*.5*scale
        scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.use_denoising=True;scene.render.threads_mode='FIXED';scene.render.threads=6;scene.render.resolution_x=480;scene.render.resolution_y=400;scene.render.resolution_percentage=100
        world=bpy.data.worlds.new('Neutral');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Color'].default_value=(.8,.85,.9,1);world.node_tree.nodes['Background'].inputs['Strength'].default_value=.65;scene.world=world
        for label,pos,energy in [('key',(-3,-4,5),450),('fill',(3,2,-1),200)]:
            data=bpy.data.lights.new(label,'AREA');data.energy=energy;data.size=4;o=bpy.data.objects.new(label,data);scene.collection.objects.link(o);o.location=pos;o.rotation_euler=(-o.location).to_track_quat('-Z','Y').to_euler()
        data=bpy.data.cameras.new('Diagnostic');cam=bpy.data.objects.new('Diagnostic',data);scene.collection.objects.link(cam);data.type='ORTHO';data.ortho_scale=1.4;scene.camera=cam
        for angle,pos in [('front',(2.5,-3,1.8)),('side',(0,-3,.08)),('bottom',(-1,2,-2.5))]:
            cam.location=pos;cam.rotation_euler=(-cam.location).to_track_quat('-Z','Y').to_euler();file=f'{name}_{stage}_{angle}.png';scene.render.filepath=str(OUT/file);bpy.ops.render.render(write_still=True);records.append({'case':name,'stage':stage,'view':angle,'image':file,'source':str(path),'reference_camera_fitted':False,'display_normalized':True});(OUT/'renders.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print('SOFA_RENDER '+file,flush=True)
