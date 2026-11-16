"""Calibrated RGB and 16-bit ray-distance images, in source GLTF coordinates."""

import argparse, json, math, sys
from pathlib import Path
import bpy
from mathutils import Matrix, Vector

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--views", type=int, default=6)
a = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
out = Path(a.output).resolve()
out.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(a.input).resolve()))
scene = bpy.context.scene
original = list(scene.objects)
meshes = [o for o in original if o.type == "MESH"]
points = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
if not points:
    raise ValueError("No source mesh")
low = Vector(tuple(min(v[k] for v in points) for k in range(3)))
high = Vector(tuple(max(v[k] for v in points) for k in range(3)))
scale = 1 / max(high - low)
parent = bpy.data.objects.new("Display only", None)
scene.collection.objects.link(parent)
for o in original:
    if o.parent is None:
        o.parent = parent
parent.scale = (scale,) * 3
parent.location = -(low + high) * 0.5 * scale
bpy.context.view_layer.update()
rotation = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
source_to_display = parent.matrix_world @ rotation
scene.render.engine = "CYCLES"
scene.cycles.samples = 8
scene.cycles.use_denoising = True
scene.render.threads_mode = "FIXED"
scene.render.threads = 6
scene.render.resolution_x = 640
scene.render.resolution_y = 640
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
world = bpy.data.worlds.new("Neutral")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.82, 0.85, 0.9, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.65
scene.world = world
for name, position, power in [("key", (-3, -4, 5), 450), ("fill", (3, 2, 3), 300)]:
    data = bpy.data.lights.new(name, "AREA")
    data.energy = power
    data.size = 4
    o = bpy.data.objects.new(name, data)
    scene.collection.objects.link(o)
    o.location = position
camera_data = bpy.data.cameras.new("Calibrated")
camera_data.lens = 48
camera = bpy.data.objects.new("Calibrated", camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
depth = bpy.data.materials.new("Diagnostic distance")
depth.use_nodes = True
nodes = depth.node_tree.nodes
nodes.clear()
camera_node = nodes.new("ShaderNodeCameraData")
divide = nodes.new("ShaderNodeMath")
divide.operation = "DIVIDE"
divide.inputs[1].default_value = 8
emission = nodes.new("ShaderNodeEmission")
output = nodes.new("ShaderNodeOutputMaterial")
links = depth.node_tree.links
links.new(camera_node.outputs["View Distance"], divide.inputs[0])
links.new(divide.outputs[0], emission.inputs["Color"])
links.new(emission.outputs[0], output.inputs[0])
slots = {o.name: list(o.data.materials) for o in meshes}
records = []
for i in range(a.views):
    angle = math.radians(45 + i * 360 / a.views)
    camera.location = (2.4 * math.cos(angle), -2.4 * math.sin(angle), 1.15)
    camera.rotation_euler = (-camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()
    for o in meshes:
        o.data.materials.clear()
        for mat in slots[o.name]:
            o.data.materials.append(mat)
    scene.view_settings.view_transform = "AgX"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.cycles.samples = 8
    scene.cycles.use_denoising = True
    scene.render.filepath = str(out / f"view_{i}.png")
    bpy.ops.render.render(write_still=True)
    projection = camera.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(), x=640, y=640, scale_x=1, scale_y=1)
    view = camera.matrix_world.inverted() @ source_to_display
    for o in meshes:
        for j in range(len(o.data.materials)):
            o.data.materials[j] = depth
        if not len(o.data.materials):
            o.data.materials.append(depth)
    scene.view_settings.view_transform = "Raw"
    scene.render.image_settings.color_mode = "BW"
    scene.render.image_settings.color_depth = "16"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.render.filepath = str(out / f"depth_{i}.png")
    bpy.ops.render.render(write_still=True)
    records.append(
        {
            "index": i,
            "image": f"view_{i}.png",
            "depth": f"depth_{i}.png",
            "depth_scale": 8,
            "clip_from_source": [list(row) for row in projection @ view],
            "view_from_source": [list(row) for row in view],
            "source_display_scale": scale,
            "image_size": [640, 640],
        }
    )
    (out / "views.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print("SEMANTIC_VIEW " + str(i), flush=True)
