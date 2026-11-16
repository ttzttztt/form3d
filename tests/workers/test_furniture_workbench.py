import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
import trimesh
from services.api.models import AssetEditRequest, JobRequest
from services.api.geometry import build_template, validate_glb
from services.api.glb_document import read_glb, write_glb, set_part_ids, parts_catalog, compact_static
from asset_operations import apply_operation
from furniture_parts import table_cut
from mesh_quality import inspect_document, geometry_stats
from verify_asset_upgrade import signature


class FurnitureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.path = self.folder / "source.glb"
        build_template(JobRequest(image_id="a" * 32, template="table"), self.path)
        self.doc, self.binary, self.extra = read_glb(self.path)
        set_part_ids(self.doc)

    def request(self, **values):
        return AssetEditRequest(**values).model_dump()

    def output(self):
        self.binary = compact_static(self.doc, self.binary)
        path = self.folder / "output.glb"
        write_glb(path, self.doc, self.binary, self.extra)
        self.assertEqual(validate_glb(path)["errors"], 0)
        return path

    def test_auto_existing_parts_keeps_transforms_and_all_surfaces(self):
        before = signature(self.path)
        e = apply_operation(self.doc, self.binary, self.request(operation="auto_parts", category="table"))
        out = self.output()
        self.assertEqual(e["method"], "existing_primitives_preserved")
        self.assertEqual(signature(out), before)
        self.assertTrue(all(p["logical_group_id"] for p in parts_catalog(self.doc)))

    def test_merge_keeps_different_materials_and_node_instances(self):
        before = signature(self.path)
        parts = parts_catalog(self.doc)
        old_materials = [p["base_color_factor"] for p in parts]
        r = self.request(operation="merge_parts", part_ids=[parts[0]["id"], parts[1]["id"]], name="Joined")
        apply_operation(self.doc, self.binary, r)
        out = self.output()
        after = parts_catalog(self.doc)
        self.assertEqual(after[0]["logical_group_id"], after[1]["logical_group_id"])
        self.assertEqual([p["base_color_factor"] for p in after], old_materials)
        self.assertEqual(signature(out), before)

    def test_partial_face_assignment_preserves_remainder_identity_and_scope(self):
        parts = parts_catalog(self.doc)
        source = parts[0]["id"]
        target = parts[1]["id"]
        before = signature(self.path)
        apply_operation(
            self.doc,
            self.binary,
            self.request(
                operation="assign_faces", target_part_id=target, face_selection=[{"part_id": source, "faces": [0, 1]}]
            ),
        )
        out = self.output()
        after = parts_catalog(self.doc)
        self.assertEqual(signature(out), before)
        remainder = next(p for p in after if p["id"] == source)
        self.assertIsNone(remainder["selection_role"])
        receiver = next(p for p in after if p["id"] == target)
        moved = next(p for p in after if p["selection_role"] == "selected")
        self.assertEqual(moved["logical_group_id"], receiver["logical_group_id"])
        self.assertEqual(moved["triangles"], 2)

    def test_whole_assignment_does_not_drop_or_reindex_faces(self):
        parts = parts_catalog(self.doc)
        source, target = parts[:2]
        before = signature(self.path)
        apply_operation(
            self.doc,
            self.binary,
            self.request(
                operation="assign_faces",
                target_part_id=target["id"],
                face_selection=[{"part_id": source["id"], "faces": list(range(source["triangles"]))}],
            ),
        )
        self.assertEqual(signature(self.output()), before)
        self.assertEqual(len(parts_catalog(self.doc)), len(parts))

    def test_extract_across_nodes_has_one_logical_group(self):
        parts = parts_catalog(self.doc)
        before = signature(self.path)
        apply_operation(
            self.doc,
            self.binary,
            self.request(
                operation="assign_faces",
                name="Both patches",
                face_selection=[{"part_id": p["id"], "faces": [0, 1]} for p in parts[:2]],
            ),
        )
        after = parts_catalog(self.doc)
        chosen = [p for p in after if p["selection_role"] == "selected"]
        self.assertEqual(len(chosen), 2)
        self.assertEqual(len({p["logical_group_id"] for p in chosen}), 1)
        self.assertEqual(signature(self.output()), before)

    def test_invalid_assignment_and_missing_target_are_rejected(self):
        source = parts_catalog(self.doc)[0]["id"]
        with self.assertRaises(ValueError):
            AssetEditRequest(operation="merge_parts", part_ids=[source])
        with self.assertRaises(ValueError):
            AssetEditRequest(operation="assign_faces", face_selection=[{"part_id": source, "faces": [0]}])
        with self.assertRaisesRegex(ValueError, "接收部件"):
            apply_operation(
                self.doc,
                self.binary,
                self.request(
                    operation="assign_faces",
                    target_part_id="missing",
                    face_selection=[{"part_id": source, "faces": [0]}],
                ),
            )

    def test_whole_quality_does_not_call_group_boundaries_new_holes(self):
        before = inspect_document(self.doc, self.binary)["whole_model"]
        source = parts_catalog(self.doc)[0]["id"]
        apply_operation(
            self.doc,
            self.binary,
            self.request(operation="assign_faces", name="Patch", face_selection=[{"part_id": source, "faces": [0, 1]}]),
        )
        after = inspect_document(self.doc, self.binary)["whole_model"]
        self.assertEqual(before, after)

    def test_cleanup_removes_same_winding_duplicate_and_preserves_reverse(self):
        v = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0]])
        f = np.array([[0, 1, 2], [1, 2, 0], [2, 1, 0]])
        stats, bad = geometry_stats(v, f)
        self.assertEqual(stats["duplicate_faces"], 1)
        self.assertEqual(int(bad.sum()), 1)
        self.assertFalse(bad[2])

    def test_gentle_repair_has_bounded_movement_and_valid_normals(self):
        mesh = trimesh.creation.icosphere(subdivisions=3)
        rng = np.random.default_rng(17)
        mesh.vertices += rng.normal(0, 0.006, mesh.vertices.shape)
        mesh.export(self.path)
        self.doc, self.binary, self.extra = read_glb(self.path)
        set_part_ids(self.doc)
        e = apply_operation(self.doc, self.binary, self.request(operation="repair_geometry", repair_strength="gentle"))
        p = e["parts"][0]
        self.assertLessEqual(p["max_displacement_ratio"], 0.00200001)
        self.assertLessEqual(p["laplacian_mean_after"], p["laplacian_mean_before"] * 1.02)
        self.output()

    def test_noop_cleanup_is_not_published_as_an_improvement(self):
        with self.assertRaisesRegex(ValueError, "无需创建"):
            apply_operation(self.doc, self.binary, self.request(operation="repair_geometry", repair_strength="cleanup"))

    def test_degenerate_face_cleanup_cannot_open_closed_surface(self):
        mesh = trimesh.creation.icosphere(subdivisions=2)
        mesh.vertices = np.round(mesh.vertices * 1024) / 1024
        face = mesh.faces[0]
        mesh.vertices[face[0]] = (mesh.vertices[face[1]] + mesh.vertices[face[2]]) / 2
        mesh.export(self.path)
        self.doc, self.binary, self.extra = read_glb(self.path)
        set_part_ids(self.doc)
        before = inspect_document(self.doc, self.binary)["whole_model"]
        self.assertTrue(before["watertight"])
        self.assertGreater(before["degenerate_faces"], 0)
        with self.assertRaisesRegex(ValueError, "无需创建"):
            apply_operation(self.doc, self.binary, self.request(operation="repair_geometry", repair_strength="cleanup"))
        self.doc, self.binary, self.extra = read_glb(self.path)
        set_part_ids(self.doc)
        evidence = apply_operation(
            self.doc, self.binary, self.request(operation="repair_geometry", repair_strength="gentle")
        )
        after = inspect_document(self.doc, self.binary)["whole_model"]
        self.assertTrue(after["watertight"])
        self.assertEqual(after["boundary_edges"], 0)
        self.assertGreater(evidence["parts"][0]["retained_bad_faces_to_preserve_topology"], 0)

    def test_table_proposals_follow_tilted_top_without_rotating_geometry(self):
        angles = np.linspace(0, np.pi * 2, 64, endpoint=False)
        ys = np.linspace(0.001, 0.999, 500)
        centers = []
        normals = []
        for y in ys:
            radius = 0.12 if y < 0.9 else 1.0
            centers.extend(np.c_[radius * np.cos(angles), np.full(64, y), radius * np.sin(angles)])
            normals.extend(np.c_[np.cos(angles), np.zeros(64), np.sin(angles)])
        for y, ny in [(1.0, 1.0), (0.9, -1.0)]:
            for radius in np.linspace(0.15, 0.99, 50):
                centers.extend(np.c_[radius * np.cos(angles), np.full(64, y), radius * np.sin(angles)])
                normals.extend(np.tile([0, ny, 0], (64, 1)))
        c = np.asarray(centers)
        n = np.asarray(normals)
        area = np.ones(len(c))
        angle = np.deg2rad(17)
        rotation = np.array([[1, 0, 0], [0, np.cos(angle), -np.sin(angle)], [0, np.sin(angle), np.cos(angle)]])
        rotated = c @ rotation.T
        before = rotated.copy()
        labels, names, evidence = table_cut(rotated, n @ rotation.T, area)
        self.assertGreater(evidence["observed_tilt_degrees"], 15)
        self.assertTrue(np.all(labels[c[:, 1] >= 0.9] == 1))
        self.assertTrue(np.all(labels[c[:, 1] < 0.85] == 0))
        np.testing.assert_array_equal(rotated, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
