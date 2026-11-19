"""Parts split along smooth surface (colour or print) merge; parts split at a crease stay apart."""

import unittest

import numpy as np

try:
    import trimesh
    from segment_shape_by_photo import merge_smooth_seams
except ImportError:  # pragma: no cover - CI installs the worker dependencies
    trimesh = None


def cube():
    mesh = trimesh.creation.box((1.0, 1.0, 1.0))
    for _ in range(4):
        mesh = mesh.subdivide()
    return mesh


@unittest.skipIf(trimesh is None, "trimesh and opencv are required")
class SmoothSeamMergeTests(unittest.TestCase):
    def test_border_across_flat_faces_merges(self):
        mesh = cube()
        labels = (mesh.triangles_center[:, 0] > 0.1).astype(int)  # a print boundary across four faces
        merged, record = merge_smooth_seams(mesh, labels, 2)
        self.assertEqual(len(np.unique(merged)), 1)
        self.assertEqual(sum(len(v) for v in record.values()), 1)

    def test_border_along_box_edges_is_kept(self):
        mesh = cube()
        labels = (mesh.face_normals[:, 2] > 0.9).astype(int)  # the top panel, bounded by 90-degree edges
        merged, record = merge_smooth_seams(mesh, labels, 2)
        self.assertEqual(len(np.unique(merged)), 2)
        self.assertEqual(record, {})


if __name__ == "__main__":
    unittest.main()
