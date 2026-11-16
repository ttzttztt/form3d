"""Render actual exported GLBs in identical neutral-clay review conditions.

Run using Blender. This never creates replacement model geometry; it imports
the candidate/baseline GLB and only applies uniform display normalization.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
EXPERIMENT=ROOT/'experiments'/'quality_20261111'


def material(name,color):
    mat=bpy.data.materials.new(name)
    mat.use_nodes=True
    shader=mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value=(*color,1)
    shader.inputs['Metallic'].default_value=0
    shader.inputs['Roughness'].default_value=.8
    return mat


def render_model(path,directory,label,views_requested=None):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(path))
    mesh_objects=[obj for obj in bpy.context.scene.objects if obj.type=='MESH']
    vertices=[]
    faces=[]
    for obj in mesh_objects:
        offset=len(vertices)
        vertices.extend(obj.matrix_world @ vert.co for vert in obj.data.vertices)
        faces.extend(tuple(offset+index for index in face.vertices) for face in obj.data.polygons)
    if not vertices:
        raise ValueError('Imported GLB has no mesh: '+str(path))
    low=Vector(tuple(min(point[axis] for point in vertices) for axis in range(3)))
    high=Vector(tuple(max(point[axis] for point in vertices) for axis in range(3)))
    scale=1/max(high-low)
    shift=Vector(((low.x+high.x)/2,(low.y+high.y)/2,low.z))
    normalized=[(point-shift)*scale for point in vertices]
    height=(high.z-low.z)*scale
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    data=bpy.data.meshes.new('Imported delivery geometry, uniformly normalized for display')
    data.from_pydata(normalized,[],faces)
    data.update()
    obj=bpy.data.objects.new('Actual GLB geometry',data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material('Shared neutral clay; source colors intentionally hidden',(.38,.39,.41)))
    for polygon in data.polygons:
        polygon.use_smooth=True
    scene=bpy.context.scene
    scene.render.engine='CYCLES'
    scene.cycles.samples=16
    scene.cycles.use_denoising=True
    scene.cycles.device='CPU'
    scene.render.resolution_x=640
    scene.render.resolution_y=640
    scene.render.resolution_percentage=100
    scene.view_settings.view_transform='AgX'
    world=bpy.data.worlds.new('Identical review studio')
    world.use_nodes=True
    world.node_tree.nodes.get('Background').inputs['Color'].default_value=(.85,.85,.85,1)
    world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.35
    scene.world=world
    bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.008))
    floor=bpy.context.object
    floor.data.materials.append(material('Review floor',(.92,.92,.92)))
    target=Vector((0,0,height/2))
    for name,location,power,size in [('key',(-3,-4,5),400,4),('fill',(3,-1,3),180,3),('rim',(0,3,4),250,3)]:
        light_data=bpy.data.lights.new(name,'AREA')
        light_data.energy=power
        light_data.shape='DISK'
        light_data.size=size
        light=bpy.data.objects.new(name,light_data)
        scene.collection.objects.link(light)
        light.location=location
        light.rotation_euler=(target-light.location).to_track_quat('-Z','Y').to_euler()
    camera_data=bpy.data.cameras.new('Shared orthographic review camera')
    camera=bpy.data.objects.new('Shared orthographic review camera',camera_data)
    scene.collection.objects.link(camera)
    scene.camera=camera
    camera_data.type='ORTHO'
    camera_data.ortho_scale=1.38
    directory.mkdir(parents=True,exist_ok=True)
    evidence={'model_file':str(path.relative_to(ROOT)),
              'model_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'material_override':'identical neutral clay, source textures/colors hidden',
              'scale':'uniform longest-axis normalization; proportions retained',
              'uniform_scale':scale,'view_matching':'fixed model views; not a fitted photo camera',
              'views':{}}
    views={'front':(0,-3,height/2+.08),'oblique':(1.7,-3,height/2+1.2),
           'side':(3,0,height/2+.08),'rear':(0,3,height/2+.08)}
    if views_requested:
        views.update(left=(-3,0,height/2+.08),opposite_oblique=(-1.7,3,height/2+1.2))
        views={name:views[name] for name in views_requested}
    for view,location in views.items():
        camera.location=location
        camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath=str(directory/(label+'_'+view+'.png'))
        bpy.ops.render.render(write_still=True)
        evidence['views'][view]={'file':label+'_'+view+'.png','camera':location,'target':list(target)}
    (directory/(label+'_render_evidence.json')).write_text(json.dumps(evidence,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',choices=['all','alien','chair','armchair'],default='all')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    protocol=json.loads((EXPERIMENT/'protocol.json').read_text(encoding='utf-8'))
    for case in protocol['cases']:
        if args.case!='all' and case['id']!=args.case:
            continue
        folder=EXPERIMENT/case['id']
        render_model(folder/'triposr'/'model.glb',folder/'renders','triposr')
        completed=[]
        for record in sorted((folder/'hunyuan').glob('attempt_*/execution.json')):
            item=json.loads(record.read_text(encoding='utf-8'))
            if item.get('status')=='completed' and item.get('technical_acceptance'):
                completed.append(record.parent)
        if completed:
            render_model(completed[-1]/'model.glb',folder/'renders','hunyuan')
    print('ACTUAL GLB REVIEW RENDERS COMPLETE',flush=True)


if __name__=='__main__':
    main()
