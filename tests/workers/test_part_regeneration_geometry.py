"""Geometry invariants and failure guards; no image inference claims."""

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services/workers"), str(ROOT / ".tools/geometry_extra")]
import numpy as np
import trimesh
from services.api.glb_document import read_glb, write_glb, parts_catalog, selected_primitives, compact_static
from replace_generated_part import replace_generated, cushion_slot, selected_group
from part_registration import register_part, observed_pose_surface
from furniture_parts import primitive_data
from edit_asset import accessor_array, node_world_matrices


class RegenerationGeometryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "source.glb"

    def asset(self):
        scene = trimesh.Scene()
        target = trimesh.creation.icosphere(subdivisions=2)
        target.apply_scale([0.55, 0.4, 0.15])
        scene.add_geometry(target, node_name="pillow")
        scene.add_geometry(
            trimesh.creation.box(), node_name="frame", transform=trimesh.transformations.translation_matrix([3, 0, 0])
        )
        scene.export(self.path)
        doc, binary, extra = read_glb(self.path)
        for i, (part, p) in enumerate(selected_primitives(doc, [])):
            p.setdefault("extras", {}).update(
                form_logical_group_id=f"group_{i}", form_semantic_kind="pillow" if i == 0 else "support"
            )
        return doc, binary, extra, target

    def signature(self, doc, binary, identity):
        part = next(p for p in parts_catalog(doc) if p["id"] == identity)
        p = doc["meshes"][doc["nodes"][part["node"]]["mesh"]]["primitives"][part["primitive"]]
        return {
            **{k: accessor_array(doc, binary, i).tobytes() for k, i in p["attributes"].items()},
            "indices": accessor_array(doc, binary, p["indices"]).tobytes(),
            "material": part["material_signature"],
            "transform": node_world_matrices(doc)[part["node"]].tobytes(),
        }

    def test_registration_recovers_translated_rotated_scaled_shape(self):
        candidate = trimesh.creation.icosphere(subdivisions=2)
        candidate.apply_scale([1, 0.65, 0.27])
        matrix = trimesh.transformations.rotation_matrix(0.4, [0.2, 0.6, 0.7])
        matrix[:3, :3] *= 0.7
        matrix[:3, 3] = [2, -1, 0.3]
        target = candidate.copy().apply_transform(matrix)
        aligned, evidence = register_part(candidate, target, "bolster")
        self.assertLess(evidence["sampled_core_distance_p85_diagonal_ratio"], 0.03)
        self.assertTrue(aligned.is_watertight)
        self.assertFalse(evidence["real_scale_verified"])
        points = (
            np.c_[candidate.vertices, np.ones(len(candidate.vertices))]
            @ np.array(evidence["candidate_to_source_world"]).T
        )
        np.testing.assert_allclose(points[:, :3], aligned.vertices, atol=1e-7)

    def test_incomplete_pillow_does_not_derive_thickness_from_its_fringe(self):
        source = trimesh.creation.icosphere(subdivisions=3)
        source.apply_scale([1, 0.65, 0.15])
        source.update_faces(source.triangles_center[:, 2] > 0)
        source.remove_unreferenced_vertices()
        surface, evidence = observed_pose_surface(source, "pillow")
        self.assertGreaterEqual(evidence["source_area_fraction"], 0.30)
        self.assertTrue(evidence["thickness_not_observed"])
        candidate = trimesh.creation.icosphere(subdivisions=2)
        candidate.apply_scale([1, 0.65, 0.15])
        _, fit = register_part(candidate, source, "pillow")
        self.assertIsNone(fit["thickness_constraint"])
        self.assertTrue(fit["thickness_constraint_skipped_for_open_source"])

    def test_extreme_thickness_and_empty_geometry_refused(self):
        candidate = trimesh.creation.icosphere(subdivisions=2)
        candidate.apply_scale([1, 0.8, 0.001])
        target = trimesh.creation.icosphere(subdivisions=2)
        target.apply_scale([1, 0.8, 0.3])
        with self.assertRaisesRegex(ValueError, "厚度"):
            register_part(candidate, target, "pillow")
        with self.assertRaisesRegex(ValueError, "表面为空"):
            register_part(trimesh.Trimesh(), target)

    def test_whole_group_replacement_preserves_unrelated_bytes_and_roundtrip(self):
        doc, binary, extra, candidate = self.asset()
        parts = parts_catalog(doc)
        identity = parts[1]["id"]
        before = self.signature(doc, binary, identity)
        result = replace_generated(doc, binary, {"part_ids": [parts[0]["id"]], "kind": "pillow"}, candidate)
        self.assertEqual(self.signature(doc, binary, identity), before)
        self.assertTrue(result["unrelated_groups_unchanged"])
        self.assertEqual(result["appearance_review"], "unreviewed")
        self.assertFalse(result["real_hidden_geometry_recovered"])
        write_glb(self.path, doc, compact_static(doc, binary), extra)
        loaded, buffer, _ = read_glb(self.path)
        self.assertEqual(self.signature(loaded, buffer, identity), before)
        _, _, stored = selected_group(loaded, buffer, [parts[0]["id"]])
        self.assertTrue(stored.is_watertight and stored.is_winding_consistent)
        self.assertEqual(len(stored.split()), 1)

    def test_multi_solid_and_open_generated_shapes_refused(self):
        for candidate in [
            trimesh.util.concatenate(
                [
                    trimesh.creation.box(),
                    trimesh.creation.box(transform=trimesh.transformations.translation_matrix([3, 0, 0])),
                ]
            ),
            trimesh.creation.box().submesh([np.arange(10)], append=True),
        ]:
            doc, binary, _, _ = self.asset()
            with self.assertRaises(ValueError):
                replace_generated(doc, binary, {"part_ids": [parts_catalog(doc)[0]["id"]], "kind": "pillow"}, candidate)

    def test_technical_patches_expand_to_one_logical_group(self):
        doc, binary, _, _ = self.asset()
        part, p = selected_primitives(doc, [parts_catalog(doc)[0]["id"]])[0]
        mesh = doc["meshes"][doc["nodes"][part["node"]]["mesh"]]
        mesh["primitives"].append(copy.deepcopy(p))
        doc["nodes"][part["node"]].setdefault("extras", {}).setdefault("form_part_ids", {})["1"] = "cap"
        key, entries, _ = selected_group(doc, binary, ["cap"])
        self.assertEqual(key, "group_0")
        self.assertEqual(len(entries), 2)
        with self.assertRaisesRegex(ValueError, "一个完整部件组"):
            selected_group(doc, binary, [part["id"], parts_catalog(doc)[-1]["id"]])

    def seat(self):
        from shapely.geometry import Polygon

        outline = Polygon([[-0.75, 0], [0.75, 0], [0.75, 0.5], [1, 0.5], [1, 0.6], [-1, 0.6], [-1, 0.5], [-0.75, 0.5]])
        return trimesh.creation.extrude_polygon(outline, height=1.8, engine="earcut")

    def test_cushion_seam_proposal_keeps_closed_frame_and_marks_estimated(self):
        upper, frame, evidence = cushion_slot(self.seat())
        self.assertTrue(frame.is_watertight)
        self.assertEqual(len(frame.split()), 1)
        self.assertAlmostEqual(evidence["cut_bottom_y"], 0.5, delta=0.015)
        self.assertTrue(evidence["boundary_is_estimated"])
        self.assertTrue(evidence["frame_geometry_changed"])
        self.assertLess(upper.extents[1], 0.12)

    def test_open_source_body_and_attached_backrest_refused(self):
        seat = self.seat()
        seat.update_faces(np.arange(len(seat.faces)) != 0)
        with self.assertRaisesRegex(ValueError, "尚未闭合"):
            cushion_slot(seat)
        seat = self.seat()
        back = trimesh.creation.box(extents=[2, 0.7, 0.2])
        back.apply_translation([0, 0.9, -0.8])
        combined = trimesh.util.concatenate([seat, back])
        with self.assertRaisesRegex(ValueError, "扶手或靠背"):
            cushion_slot(combined)

    def test_flat_cushion_uses_outline_to_prevent_wrong_rotation_and_overhang(self):
        target = trimesh.creation.box(extents=[2, 0.2, 1.5])
        target.apply_translation([0, 0.5, 0])
        candidate = trimesh.creation.box(extents=[2, 0.2, 1.5])
        candidate.apply_transform(trimesh.transformations.rotation_matrix(0.73, [0, 1, 0]))
        aligned, evidence = register_part(candidate, target, "cushion", bottom=0.4)
        np.testing.assert_allclose(aligned.bounds, target.bounds, atol=0.015)
        self.assertLess(evidence["outside_observed_footprint_area_fraction"], 0.01)
        self.assertEqual(evidence["method"], "horizontal_convex_outline_bidirectional_similarity_ICP")

    def test_wrong_cushion_footprint_is_refused(self):
        target = trimesh.creation.box(extents=[2, 0.2, 1.5])
        candidate = trimesh.creation.box(extents=[3, 0.2, 0.5])
        with self.assertRaisesRegex(ValueError, "外轮廓"):
            register_part(candidate, target, "cushion")

    def test_open_opposing_surfaces_supply_thickness_but_one_side_does_not(self):
        from observed_thickness import paired_thickness

        source = trimesh.creation.icosphere(subdivisions=3)
        source.apply_scale([0.5, 0.4, 0.12])
        source.update_faces(abs(source.triangles_center[:, 0]) < 0.47)
        source.remove_unreferenced_vertices()
        surface_patch, _ = observed_pose_surface(source, "pillow")
        evidence = paired_thickness(source, surface_patch)
        self.assertIsNotNone(evidence)
        self.assertGreater(evidence["core_thickness_source_units"], 0.12)
        one = source.copy()
        one.update_faces(one.triangles_center[:, 2] > 0)
        one.remove_unreferenced_vertices()
        surface_patch, _ = observed_pose_surface(one, "pillow")
        self.assertIsNone(paired_thickness(one, surface_patch))

    def test_paper_shell_rebuild_has_volume_closed_rim_and_no_intersections(self):
        from soft_part_repair import fill_paper_pillow
        from observed_thickness import paired_thickness
        from reconstruct_parts import intersections
        from solid_partition import prepare_mesh

        source = trimesh.creation.icosphere(subdivisions=3)
        source.apply_scale([0.5, 0.4, 0.12])
        source.update_faces(abs(source.triangles_center[:, 0]) < 0.47)
        source.remove_unreferenced_vertices()
        surface_patch, _ = observed_pose_surface(source, "pillow")
        measurement = paired_thickness(source, surface_patch)
        paper = trimesh.creation.box(extents=[0.9, 0.7, 0.004])
        for _ in range(3):
            paper = paper.subdivide()
        paper.vertices[:, 2] += 0.1 * (1 - (paper.vertices[:, 0] / 0.45) ** 2)
        repaired, evidence = fill_paper_pillow(paper, source, {"thickness_constraint": measurement})
        checked, _ = prepare_mesh(repaired)
        self.assertTrue(checked.is_watertight and checked.is_winding_consistent)
        self.assertEqual(intersections(checked), 0)
        self.assertGreater(checked.volume, paper.volume * 8)
        self.assertTrue(evidence["all_output_surfaces_reconstructed"])
        self.assertTrue(evidence["not_new_ai_inference"])

    def test_no_opposing_evidence_never_silently_inflates_pillow(self):
        from soft_part_repair import fill_paper_pillow

        paper = trimesh.creation.box(extents=[1, 0.8, 0.004])
        original = paper.vertices.copy()
        result, evidence = fill_paper_pillow(paper, paper, {})
        self.assertIsNone(evidence)
        np.testing.assert_array_equal(result.vertices, original)

    def test_bent_paper_shell_is_detected_separately_from_full_soft_volume(self):
        from soft_part_repair import shell_volume_ratio

        paper = trimesh.creation.box(extents=[1, 0.8, 0.004])
        for _ in range(3):
            paper = paper.subdivide()
        paper.vertices[:, 2] += 0.12 * (1 - (paper.vertices[:, 0] / 0.5) ** 2)
        self.assertLess(shell_volume_ratio(paper), 0.18)
        pillow = trimesh.creation.icosphere(subdivisions=2)
        pillow.apply_scale([0.5, 0.4, 0.12])
        self.assertGreater(shell_volume_ratio(pillow), 0.4)

    def test_preserved_seam_splits_caps_without_changing_other_group(self):
        scene = trimesh.Scene()
        scene.add_geometry(self.seat(), node_name="seat")
        scene.add_geometry(
            trimesh.creation.box(), node_name="other", transform=trimesh.transformations.translation_matrix([5, 0, 0])
        )
        scene.export(self.path)
        doc, binary, _ = read_glb(self.path)
        entries = selected_primitives(doc, [])
        for i, (p, q) in enumerate(entries):
            q.setdefault("extras", {}).update(
                form_semantic_kind="seat" if i == 0 else "support", form_logical_group_id="g" + str(i)
            )
        ids = [entries[0][0]["id"]]
        other = entries[1][0]["id"]
        before = self.signature(doc, binary, other)
        operation = replace_generated(doc, binary, {"part_ids": ids, "kind": "cushion", "method": "source_seam"})
        self.assertEqual(before, self.signature(doc, binary, other))
        self.assertEqual(operation["method"], "source_seam")
        self.assertLess(operation["placement"]["volume_partition_relative_error"], 1e-5)
        group = operation["part_group_ids"][0]
        parts = [p for p in parts_catalog(doc) if p["logical_group_id"] == group]
        self.assertEqual({p["completion_role"] for p in parts}, {"observed_surface", "inferred_interface"})
        _, _, mesh = selected_group(doc, binary, [parts[0]["id"]])
        self.assertTrue(mesh.is_watertight)

    def test_cushion_repair_refuses_mostly_occluded_roof(self):
        from soft_part_repair import rebuild_occluded_seat
        from shapely.geometry import box

        with self.assertRaisesRegex(ValueError, "大部分坐垫"):
            rebuild_occluded_seat(self.seat(), 0.6, 0.5, [box(-2, -2, 2, 3)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
