"""Synthetic topology regressions, not additional furniture designs."""
import unittest
import numpy as np
import trimesh
from mesh_integrity import exact_storage_mesh


class StorageTopologyTests(unittest.TestCase):
    def test_uv_seams_are_welded_without_collapsing_a_real_thin_feature(self):
        source=trimesh.creation.box(extents=[1,1,1e-8]);vertices=source.vertices[source.faces].reshape(-1,3)
        seams=trimesh.Trimesh(vertices,np.arange(len(vertices)).reshape(-1,3),process=False)
        mesh,facts=exact_storage_mesh(seams)
        self.assertTrue(mesh.is_watertight);self.assertTrue(mesh.volume>0)
        self.assertAlmostEqual(mesh.extents[2],1e-8,places=14);self.assertFalse(facts['positions_moved'])

    def test_exact_zero_area_artifact_does_not_become_a_physical_part(self):
        source=trimesh.creation.box();source.faces=np.vstack([source.faces,[0,0,1]])
        mesh,facts=exact_storage_mesh(source)
        self.assertTrue(mesh.is_watertight);self.assertEqual(facts['removed_exact_zero_area_faces'],1)
        self.assertEqual(facts['positive_area_faces_removed'],0)

    def test_a_real_missing_face_is_not_repaired_by_audit_cleanup(self):
        source=trimesh.creation.box();source.update_faces(np.arange(len(source.faces)-1))
        mesh,_=exact_storage_mesh(source);self.assertFalse(mesh.is_watertight)


if __name__=='__main__':unittest.main()
