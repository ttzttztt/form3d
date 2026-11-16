import unittest
import numpy as np
import trimesh
from relax_part_contacts import solve


class ContactTests(unittest.TestCase):
    def test_overlapping_boxes_separate_with_anchor_and_surfaces_preserved(self):
        body = trimesh.creation.box(extents=[2, 1, 2])
        pillow = trimesh.creation.box()
        pillow.apply_translation([0, 0.95, 0])
        before = body.vertices.copy(), pillow.vertices.copy()
        offsets, report = solve({"body": body, "pillow": pillow}, "body")
        self.assertTrue(report["contact_gate_passed"])
        self.assertGreater(offsets["pillow"][1], 0)
        np.testing.assert_array_equal(offsets["body"], [0, 0, 0])
        np.testing.assert_array_equal(body.vertices, before[0])
        np.testing.assert_array_equal(pillow.vertices, before[1])
        self.assertLessEqual(np.linalg.norm(offsets["pillow"]), 0.04 * report["scene_diagonal"] + 1e-12)

    def test_a_large_penetration_is_not_silently_solved_by_unbounded_movement(self):
        body = trimesh.creation.box(extents=[2, 2, 2])
        pillow = trimesh.creation.box()
        offsets, report = solve({"body": body, "pillow": pillow}, "body")
        self.assertFalse(report["contact_gate_passed"])
        self.assertLessEqual(np.linalg.norm(offsets["pillow"]), 0.04 * report["scene_diagonal"] + 1e-12)

    def test_pose_guard_cannot_be_bypassed_to_improve_collision_score(self):
        body = trimesh.creation.box(extents=[2, 1, 2])
        pillow = trimesh.creation.box()
        pillow.apply_translation([0, 0.95, 0])
        guard = lambda shifts: np.linalg.norm(shifts["pillow"]) < 1e-12
        offsets, report = solve({"body": body, "pillow": pillow}, "body", pose_guard=guard)
        self.assertFalse(report["contact_gate_passed"])
        np.testing.assert_array_equal(offsets["pillow"], [0, 0, 0])
        with self.assertRaises(ValueError):
            solve({"body": body, "pillow": pillow}, "body", pose_guard=lambda shifts: False)


if __name__ == "__main__":
    unittest.main()
