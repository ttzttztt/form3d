"""Parametric hard parts: closed meshes, honest fit gates, mask layout."""

import unittest

import numpy as np
import trimesh

from parametric_parts import box_mesh, cylinder_mesh, fit_primitive, layout_from_masks, translation


def as_trimesh(mesh):
    return trimesh.Trimesh(mesh["vertices"], mesh["faces"], process=False)


def merged(mesh):
    return trimesh.Trimesh(mesh["vertices"], mesh["faces"], process=True)  # weld seams to test closure


class BuilderTests(unittest.TestCase):
    def check_solid(self, mesh, volume):
        solid = merged(mesh)
        self.assertTrue(solid.is_watertight)
        self.assertTrue(solid.is_winding_consistent)
        self.assertAlmostEqual(solid.volume, volume, delta=volume * 0.02)
        centre = mesh["vertices"].mean(0)
        outward = np.einsum("ij,ij->i", mesh["normals"], mesh["vertices"] - centre)
        self.assertTrue((outward > -1e-6).all())
        self.assertEqual(mesh["uvs"].shape, (len(mesh["vertices"]), 2))

    def test_box_is_closed_outward_and_sized(self):
        self.check_solid(box_mesh([2, 0.1, 1], translation(1, 2, 3)), 0.2)

    def test_cylinder_is_closed_outward_and_sized(self):
        self.check_solid(cylinder_mesh(0.5, 0.3, 2.0, segments=96), np.pi * 0.5 * 0.3 * 2.0)

    def test_uv_density_is_in_model_units(self):
        box = box_mesh([2, 1, 1])
        span = box["uvs"].max(0) - box["uvs"].min(0)
        self.assertAlmostEqual(float(span.max()), 2.0, places=5)


class FitTests(unittest.TestCase):
    def test_slightly_noisy_box_becomes_a_box(self):
        source = trimesh.creation.box([1.2, 0.05, 0.7]).subdivide().subdivide()
        rotation = trimesh.transformations.rotation_matrix(0.3, [0, 1, 0])
        source.apply_transform(rotation)
        source.vertices += np.random.default_rng(0).normal(0, 0.002, source.vertices.shape)
        built, report = fit_primitive(source.vertices, source.faces, "tabletop")
        self.assertEqual(report["shape"], "box")
        self.assertTrue(report["accepted"], report)
        self.assertLess(report["mean_deviation"], 0.01)

    def test_round_leg_becomes_a_cylinder(self):
        source = trimesh.creation.cylinder(radius=0.03, height=0.7, sections=40)
        built, report = fit_primitive(source.vertices, source.faces, "leg")
        self.assertEqual(report["shape"], "cylinder")
        self.assertTrue(report["accepted"], report)

    def test_soft_or_irregular_shape_is_not_replaced(self):
        cushion = trimesh.creation.icosphere(subdivisions=3)
        cushion.apply_scale([0.6, 0.2, 0.5])
        _, report = fit_primitive(cushion.vertices, cushion.faces, "tabletop")
        self.assertFalse(report["accepted"], report)
        chair_leg = trimesh.util.concatenate(
            [
                trimesh.creation.box([0.05, 0.8, 0.05]),
                trimesh.creation.box([0.5, 0.05, 0.05], transform=translation(0.25, 0.4, 0)),
            ]
        )
        _, report = fit_primitive(chair_leg.vertices, chair_leg.faces, "leg")
        self.assertFalse(report["accepted"], report)


def rectangle(shape, u0, v0, u1, v1):
    mask = np.zeros(shape, bool)
    mask[v0:v1, u0:u1] = True
    return mask


def ellipse(shape, cu, cv, ru, rv):
    vv, uu = np.mgrid[: shape[0], : shape[1]]
    return ((uu - cu) / ru) ** 2 + ((vv - cv) / rv) ** 2 <= 1


class LayoutTests(unittest.TestCase):
    shape = (400, 500)

    def table(self, top):
        parts = [
            {"id": "top", "kind": "tabletop", "mask": top},
            {"id": "front_left", "kind": "leg", "mask": rectangle(self.shape, 60, 130, 80, 380)},
            {"id": "front_right", "kind": "leg", "mask": rectangle(self.shape, 420, 130, 440, 380)},
            {"id": "back_left", "kind": "leg", "mask": rectangle(self.shape, 110, 120, 125, 330)},
        ]
        whole = np.zeros(self.shape, bool)
        for part in parts:
            whole |= part["mask"]
        return layout_from_masks("table", parts, whole)

    def test_rectangular_table_layout(self):
        meshes, assumptions, params = self.table(rectangle(self.shape, 50, 80, 450, 130))
        bounds = {k: (m["vertices"].min(0), m["vertices"].max(0)) for k, m in meshes.items()}
        self.assertEqual(params["top"]["shape"], "box")
        self.assertAlmostEqual(bounds["front_left"][0][1], 0, places=5)  # legs stand on the ground
        self.assertAlmostEqual(bounds["front_left"][1][1], bounds["top"][0][1], places=5)  # and meet the top
        self.assertGreater(params["front_left"]["depth_position"], 0)  # lowest feet are at the front
        self.assertLess(params["back_left"]["depth_position"], 0)  # a higher foot stands further back
        self.assertTrue(any("深度" in item for item in assumptions))
        for mesh in meshes.values():
            self.assertTrue(merged(mesh).is_watertight)

    def test_round_top_becomes_a_disc(self):
        _, _, params = self.table(ellipse(self.shape, 250, 105, 200, 25))
        self.assertEqual(params["top"]["shape"], "cylinder")


if __name__ == "__main__":
    unittest.main()
