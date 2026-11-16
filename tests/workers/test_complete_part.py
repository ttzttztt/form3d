import copy, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services/workers")]
import numpy as np, trimesh
from services.api.models import AssetEditRequest
from services.api.glb_document import read_glb, parts_catalog, write_glb, material_edit
from complete_part import completion_plan, complete_part, mesh_stats
from solid_partition import partition_box
from edit_asset import node_world_matrices, accessor_array


class CompletePartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "source.glb"
        m = trimesh.creation.icosphere(subdivisions=3)
        m.export(self.path)
        self.doc, self.binary, self.extra = read_glb(self.path)
        self.part = parts_catalog(self.doc)[0]
        p = self.doc["meshes"][self.doc["nodes"][self.part["node"]]["mesh"]]["primitives"][0]
        v = accessor_array(self.doc, self.binary, p["attributes"]["POSITION"])
        f = accessor_array(self.doc, self.binary, p["indices"]).reshape(-1, 3)
        c = v[f].mean(1)
        selected = np.flatnonzero((c[:, 2] > 0.75) & (abs(c[:, 0]) < 0.4) & (abs(c[:, 1]) < 0.4)).tolist()
        self.request = {
            "face_selection": [{"part_id": self.part["id"], "faces": selected}],
            "part_ids": [],
            "name": "test cushion",
            "completion_bounds": [[0.25, 0.25, 0.5], [0.75, 0.75, 1]],
        }

    def test_closed_parts_and_volume_conservation(self):
        m = trimesh.creation.icosphere(subdivisions=2)
        source, seat, cap, body, bcap, e = partition_box(m, [[-0.5, -0.5, 0], [0.5, 0.5, 1.1]])
        self.assertTrue(seat.is_watertight and body.is_watertight)
        self.assertTrue(cap.any() and bcap.any())
        self.assertAlmostEqual(source.volume, seat.volume + body.volume, places=6)
        self.assertLess(e["source_surface_area_relative_error"], 1e-6)

    def test_disjoint_axis_cannot_be_dropped_while_other_axes_cut(self):
        with self.assertRaisesRegex(ValueError, "没有包含源模型"):
            partition_box(trimesh.creation.box(), [[2, -0.2, -0.2], [3, 0.2, 0.2]])

    def test_ring_opening_not_filled_by_planar_caps(self):
        m = trimesh.creation.annulus(r_min=0.4, r_max=1, height=1, sections=40)
        source, seat, cap, body, bcap, e = partition_box(m, [[-1.1, -1.1, 0], [1.1, 1.1, 0.6]])
        self.assertTrue(seat.is_watertight and body.is_watertight)
        centers = seat.triangles_center[cap]
        self.assertGreater(np.linalg.norm(centers[:, :2], axis=1).min(), 0.3)
        self.assertAlmostEqual(seat.volume, source.volume / 2, places=5)

    def test_plan_read_only_and_reports_existing_open_boundaries(self):
        before = copy.deepcopy(self.doc)
        data = bytes(self.binary)
        plan = completion_plan(self.doc, self.binary, self.request)
        self.assertGreater(plan["guide"]["boundary_edges"], 0)
        self.assertEqual(self.doc, before)
        self.assertEqual(bytes(self.binary), data)

    def test_reconstruction_marks_new_surfaces_and_groups(self):
        evidence = complete_part(self.doc, self.binary, self.request)
        parts = parts_catalog(self.doc)
        self.assertEqual(len(parts), 4)
        self.assertEqual({p["completion_role"] for p in parts}, {"observed_surface", "inferred_interface"})
        self.assertTrue(evidence["part"]["watertight"])
        self.assertTrue(evidence["remainder"]["watertight"])
        self.assertFalse(evidence["positions_unchanged"])

    def test_material_only_targets_completed_group(self):
        result = complete_part(self.doc, self.binary, self.request)
        parts = parts_catalog(self.doc)
        ids = [p["id"] for p in parts if p["logical_group_id"] == result["part_group_id"]]
        before = {p["id"]: p["material_signature"] for p in parts}
        material_edit(self.doc, AssetEditRequest(operation="material", part_ids=ids, color="#297cb5").model_dump())
        after = parts_catalog(self.doc)
        self.assertEqual({p["id"] for p in after if p["material_signature"] != before[p["id"]]}, set(ids))

    def test_existing_completed_part_refused(self):
        result = complete_part(self.doc, self.binary, self.request)
        identity = next(p["id"] for p in parts_catalog(self.doc) if p["logical_group_id"] == result["part_group_id"])
        with self.assertRaisesRegex(ValueError, "已有重建"):
            completion_plan(self.doc, self.binary, {"part_ids": [identity]})

    def test_ambiguous_or_too_small_guide_rejected(self):
        with self.assertRaises(ValueError):
            completion_plan(self.doc, self.binary, {"part_ids": []})
        with self.assertRaises(ValueError):
            completion_plan(
                self.doc, self.binary, {**self.request, "face_selection": [{"part_id": self.part["id"], "faces": [0]}]}
            )

    def test_invalid_bounds_and_missing_scope_rejected_by_protocol(self):
        for bounds in (
            [[0, 0, 0], [float("nan"), 1, 1]],
            [[0, 0, 0], [0, 1, 1]],
            [[0, 0], [1, 1, 1]],
            [[0, 0, 0], [1, 1, 2]],
        ):
            with self.assertRaises(ValueError):
                AssetEditRequest(operation="complete_part", part_ids=["a"], completion_bounds=bounds)
        with self.assertRaises(ValueError):
            AssetEditRequest(operation="complete_part")

    def test_large_guide_excluded_by_bounds_refused(self):
        with self.assertRaisesRegex(ValueError, "排除了"):
            complete_part(
                self.doc, self.binary, {**self.request, "completion_bounds": [[0.0, 0.0, 0.0], [0.1, 0.1, 0.1]]}
            )

    def test_explicit_box_keeps_requested_thickness_instead_of_seed_roof(self):
        request = {**self.request, "completion_shape": "box"}
        plan = completion_plan(self.doc, self.binary, request)
        self.assertEqual(plan["contour_planes"], 0)
        self.assertEqual(plan["method"], "explicit_box_volume")
        result = complete_part(self.doc, self.binary, request)
        self.assertTrue(result["part"]["watertight"])
        self.assertLess(result["volume_partition_relative_error"], 1e-6)
        # Explicit Y limits are honoured, although the sparse guide occupies only a narrow Y band.
        part = next(
            p
            for p in parts_catalog(self.doc)
            if p["logical_group_id"] == result["part_group_id"] and p["completion_role"] == "observed_surface"
        )
        from furniture_parts import primitive_data

        primitive = self.doc["meshes"][self.doc["nodes"][part["node"]]["mesh"]]["primitives"][part["primitive"]]
        _, f, v, _, _, _ = primitive_data(self.doc, self.binary, part, primitive)
        np.testing.assert_allclose(v[f.ravel(), 1].min(), -0.5, atol=1e-6)
        np.testing.assert_allclose(v[f.ravel(), 1].max(), 0.5, atol=1e-6)

    def test_box_cut_cannot_silently_use_automatic_thickness(self):
        request = {**self.request, "completion_shape": "box"}
        request.pop("completion_bounds")
        with self.assertRaisesRegex(ValueError, "明确的三维边界"):
            complete_part(self.doc, self.binary, request)

    def test_nonuniform_scale_refused_without_mutating_source(self):
        node = self.doc["nodes"][self.part["node"]]
        node["translation"] = [2, 3, -1]
        node["scale"] = [1.2, 0.8, 1.5]
        before = copy.deepcopy(self.doc)
        binary = bytes(self.binary)
        with self.assertRaisesRegex(ValueError, "非均匀缩放"):
            complete_part(self.doc, self.binary, self.request)
        self.assertEqual(self.doc, before)
        self.assertEqual(bytes(self.binary), binary)

    def test_missing_source_surface_is_not_silently_filled(self):
        primitive = self.doc["meshes"][self.doc["nodes"][self.part["node"]]["mesh"]]["primitives"][0]
        from asset_operations import append_array

        f = accessor_array(self.doc, self.binary, primitive["indices"]).reshape(-1, 3)
        v = accessor_array(self.doc, self.binary, primitive["attributes"]["POSITION"])
        centers = v[f].mean(1)
        drop = int(np.argmin(centers[:, 2]))
        primitive["indices"] = append_array(
            self.doc, self.binary, np.delete(f, drop, axis=0).ravel(), "SCALAR", 5125, 34963
        )
        # Request indices are rebuilt after deleting one face, preserving the front seed.
        self.request["face_selection"][0]["faces"] = [
            i - (i > drop) for i in self.request["face_selection"][0]["faces"] if i != drop
        ]
        with self.assertRaisesRegex(ValueError, "椅身切口"):
            complete_part(self.doc, self.binary, self.request)


if __name__ == "__main__":
    unittest.main(verbosity=2)
