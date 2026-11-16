"""Encode predicted sRGB appearance using glTF's linear vertex-color contract."""
import numpy as np


def prepare_vertex_appearance(mesh):
    import trimesh
    colors = mesh.visual.vertex_colors.copy()
    rgb = colors[:, :3].astype(np.float32) / 255.0
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    colors[:, :3] = np.round(np.clip(linear, 0, 1) * 255).astype(np.uint8)
    mesh.visual.vertex_colors = colors
    # TripoSR predicts color, not roughness/metalness. This neutral matte
    # approximation avoids treating every product as shiny metal by default.
    mesh.visual.material = trimesh.visual.material.PBRMaterial(
        name="Predicted vertex color with approximate matte surface",
        baseColorFactor=[1., 1., 1., 1.], metallicFactor=0., roughnessFactor=.8)
    return mesh
