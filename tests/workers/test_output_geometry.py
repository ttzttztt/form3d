"""Safety fixtures for category-aware geometry rules, not reconstruction scores."""

import tempfile
import unittest
from pathlib import Path
import numpy as np
import trimesh
from analyze_geometry import analyze


class GeometryRulesTests(unittest.TestCase):
    def check(self, mesh, category):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.glb"
            mesh.export(path)
            return analyze(path, category)

    def test_sofa_cube_is_blocked_but_cabinet_box_is_kept(self):
        box = trimesh.creation.box([1, 1, 1])
        self.assertEqual(self.check(box, "sofa")["reasons"][0]["code"], "box_degeneracy")
        self.assertEqual(self.check(box, "cabinet")["status"], "pass")

    def test_rotated_flat_vase_is_blocked(self):
        mesh = trimesh.creation.box([1, 2, 0.01])
        mesh.apply_transform(trimesh.transformations.rotation_matrix(0.7, [1, 1, 0]))
        self.assertEqual(self.check(mesh, "vase")["status"], "blocked")

    def test_thin_panel_other_category_is_retained_with_warning(self):
        result = self.check(trimesh.creation.box([1, 2, 0.005]), "other")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["warnings"])

    def test_normal_volume_vase_is_retained_without_claiming_opening(self):
        result = self.check(trimesh.creation.cylinder(radius=0.4, height=2), "vase")
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["appearance_accepted"])

    def test_table_with_thin_top_and_separate_legs_is_retained(self):
        parts = [trimesh.creation.box([1.4, 0.025, 0.8])]
        for x, z in [(-0.6, -0.3), (0.6, -0.3), (-0.6, 0.3), (0.6, 0.3)]:
            leg = trimesh.creation.box([0.04, 0.75, 0.04])
            leg.apply_translation([x, -0.38, z])
            parts.append(leg)
        result = self.check(trimesh.util.concatenate(parts), "table")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["metrics"]["components"], 5)

    def test_geometry_positions_are_not_modified_by_inspection(self):
        mesh = trimesh.creation.icosphere(subdivisions=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.glb"
            mesh.export(path)
            before = path.read_bytes()
            analyze(path, "plant")
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
