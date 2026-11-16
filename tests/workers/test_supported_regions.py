import copy, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services/workers")]
import numpy as np, trimesh
from supported_regions import refine_supported_regions, merge_observation_evidence, enforce_observation_veto


class SupportedRegionTests(unittest.TestCase):
    def fixture(self):
        mesh = trimesh.creation.icosphere(subdivisions=2)
        n = len(mesh.faces)
        labels = np.where(mesh.triangles_center[:, 0] > 0, 1, 2)
        support = np.stack([np.where(labels == i, 2, 0) for i in (1, 2)]).astype(np.uint8)
        evidence = {
            "visible_views": np.full(n, 3, np.uint8),
            "support_views": support,
            "scores": support.astype(float) / 4,
        }
        groups = [{"label": i, "source_kind": "pillow"} for i in (1, 2)]
        return mesh, labels, groups, evidence

    def test_visible_negative_evidence_blocks_growth_into_neighbour(self):
        mesh, labels, groups, evidence = self.fixture()
        bad = np.flatnonzero(labels == 1)[20:35]
        labels[bad] = 0
        evidence["support_views"][0, bad] = 1
        evidence["support_views"][1, bad] = 0
        result, _, meta = refine_supported_regions(
            mesh.vertices, mesh.faces, mesh.triangles_center, mesh.area_faces, labels, groups, evidence
        )
        self.assertTrue((result[bad] == 0).all())
        self.assertTrue(meta["visible_exclusion_veto"])
        self.assertTrue(np.all(labels[bad] == 0))

    def test_already_assigned_contradicted_face_is_not_a_seed(self):
        mesh, labels, groups, evidence = self.fixture()
        bad = np.flatnonzero(labels == 1)[20:35]
        evidence["support_views"][0, bad] = 1
        result, _, meta = refine_supported_regions(
            mesh.vertices, mesh.faces, mesh.triangles_center, mesh.area_faces, labels, groups, evidence
        )
        self.assertTrue((result[bad] == 0).all())
        self.assertEqual(meta["contradicted_assignments_removed"], len(bad))

    def test_one_view_only_fragment_without_multiview_anchor_stays_unknown(self):
        mesh, labels, groups, evidence = self.fixture()
        evidence["support_views"][1, labels == 2] = 1
        evidence["visible_views"][labels == 2] = 1
        result, retained, _ = refine_supported_regions(
            mesh.vertices, mesh.faces, mesh.triangles_center, mesh.area_faces, labels, groups, evidence
        )
        self.assertNotIn(2, [g["label"] for g in retained])
        self.assertTrue((result[labels == 2] == 0).all())

    def test_opposite_side_evidence_is_unioned_before_final_veto(self):
        mesh, labels, groups, evidence = self.fixture()
        merge_observation_evidence(evidence, [{"from_label": 2, "to_label": 1}])
        labels[:] = 1
        result, count = enforce_observation_veto(labels, [groups[0]], evidence)
        self.assertTrue((result == 1).all())
        self.assertEqual(count, 0)
        self.assertTrue((evidence["support_views"][0] <= evidence["visible_views"]).all())

    def test_postprocessing_cannot_reintroduce_a_contradicted_assignment(self):
        mesh, labels, groups, evidence = self.fixture()
        bad = np.flatnonzero(labels == 1)[:4]
        labels[bad] = 2
        result, count = enforce_observation_veto(labels, groups, evidence)
        self.assertEqual(count, 4)
        self.assertTrue((result[bad] == 0).all())

    def test_source_arrays_untouched_and_bad_evidence_refused(self):
        mesh, labels, groups, evidence = self.fixture()
        before = mesh.vertices.copy()
        faces = mesh.faces.copy()
        refine_supported_regions(
            mesh.vertices, mesh.faces, mesh.triangles_center, mesh.area_faces, labels, groups, evidence
        )
        np.testing.assert_array_equal(mesh.vertices, before)
        np.testing.assert_array_equal(mesh.faces, faces)
        evidence["scores"] = evidence["scores"][:, :-1]
        with self.assertRaises(ValueError):
            refine_supported_regions(
                mesh.vertices, mesh.faces, mesh.triangles_center, mesh.area_faces, labels, groups, evidence
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
