import json, sys, tempfile, unittest
from unittest.mock import Mock, patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services/workers")]
import numpy as np, trimesh, cv2
from PIL import Image
from shapely.geometry import Polygon, box
from photo_part_evidence import (
    camera_matrix,
    project,
    unproject_to_plane,
    constrain_to_photo_rays,
    rasterize,
    associate,
    paint,
    alpha_polygon,
    product_mask,
)
from soft_part_repair import grid_in_hull, sheets
from solid_partition import prepare_mesh
from reconstruct_parts import intersections


class PhotoOptimizationTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.folder = Path(t.name)

    def test_projection_plane_inverse_matches_known_coordinates(self):
        matrix = camera_matrix(np.zeros(3), 1, 0.4, 0.3, 0.6)
        center = np.array([0.1, 0.2, 0])
        axes = np.eye(3)
        local = np.array([[-0.3, 0.2], [0.1, 0.4], [0.2, -0.1]])
        world = center + local @ axes[:, :2].T
        pixels, _ = project(world, matrix)
        np.testing.assert_allclose(unproject_to_plane(pixels, matrix, center, axes), local, atol=1e-8)

    def test_photo_ray_constraint_preserves_outline_with_two_depth_layers(self):
        matrix = np.array([[80.0, 0, 64, 0], [0, 80, 64, 0], [0, 0, 1, 0]])
        center = np.array([0.0, 0.0, 3.0])
        mesh = trimesh.creation.box(extents=[1, 0.7, 0.2])
        mesh.apply_translation(center)
        before, _ = project(np.c_[mesh.vertices[:, :2], np.full(len(mesh.vertices), 3)], matrix)
        result, evidence = constrain_to_photo_rays(mesh, matrix, center, np.eye(3), 0.1)
        pixels, _ = project(result.vertices, matrix)
        np.testing.assert_allclose(pixels, before, atol=1e-8)
        self.assertTrue(result.is_watertight)
        self.assertTrue(evidence["same_reference_used_for_constraint_and_comparison"])

    def test_depth_is_per_pixel_and_independent_of_triangle_order(self):
        matrix = np.array([[10.0, 0, 32, 0], [0, 10, 32, 0], [0, 0, 1, 0]])
        pixels = np.array([[10.0, 10], [54, 10], [32, 54]])

        def mesh(depth):
            z = np.array(depth)
            v = np.c_[(pixels[:, 0] - 32) * z / 10, (pixels[:, 1] - 32) * z / 10, z]
            return trimesh.Trimesh(v, [[0, 1, 2]], process=False)

        sloped, flat = mesh([1, 4, 4]), mesh([2, 2, 2])
        first, _ = rasterize({"sloped": sloped, "flat": flat}, matrix, (64, 64))
        second, _ = rasterize({"flat": flat, "sloped": sloped}, matrix, (64, 64))
        self.assertEqual(first[14, 15], 1)
        self.assertEqual(first[14, 49], 2)
        self.assertEqual(second[14, 15], 2)
        self.assertEqual(second[14, 49], 1)

    def test_closed_silhouette_is_union_of_front_and_back_triangles(self):
        meshes = {"box": trimesh.creation.box()}
        matrix = camera_matrix(np.zeros(3), 1, 0.4, 0.4, 0.6)
        union = paint(meshes, matrix) > 0
        visible = rasterize(meshes, matrix, (256, 256))[0] > 0
        self.assertGreater(np.logical_and(union, visible).sum() / np.logical_or(union, visible).sum(), 0.95)

    def scene(self):
        a = trimesh.creation.box(extents=[0.5, 0.6, 0.2])
        a.apply_translation([-0.6, 0, 0])
        b = a.copy()
        b.apply_translation([1.2, 0, 0])
        meshes = {"left": a, "right": b}
        matrix = camera_matrix(np.zeros(3), 1.5, 0, 0.05, 0.6)
        camera = {"projection_from_world": matrix.tolist(), "image_size": [256, 256], "silhouette_iou": 0.9}
        labels = paint(meshes, matrix, (256, 256), True)
        return meshes, camera, labels

    def candidates(self, masks):
        refs = []
        for i, mask in enumerate(masks):
            name = f"{i + 1:032x}"
            Image.fromarray(np.uint8(mask) * 255).save(self.folder / (name + "_mask.png"))
            refs.append(
                {
                    "id": name,
                    "detection": i,
                    "source_crop_in_product_pixels": [0, 0, 256, 256],
                    "mask_file": name + "_mask.png",
                }
            )
        return {"candidates": refs}

    def test_spatial_correspondence_ignores_duplicate_same_object_variants(self):
        meshes, camera, labels = self.scene()
        left = labels == 1
        right = labels == 2
        refs = self.candidates([right, left, left.copy()])
        result, _ = associate(meshes, camera, refs, self.folder, "left", labels)
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["candidate_id"], refs["candidates"][1]["id"])
        self.assertGreater(result["instance_margin"], 0.5)

    def test_ambiguous_disjoint_half_references_do_not_force_match(self):
        meshes, camera, labels = self.scene()
        mask = labels == 1
        yy, xx = np.nonzero(mask)
        mid = (yy.min() + yy.max()) / 2
        halves = [mask & (np.indices(mask.shape)[0] <= mid), mask & (np.indices(mask.shape)[0] > mid)]
        result, _ = associate(meshes, camera, self.candidates(halves), self.folder, "left", labels)
        self.assertEqual(result["status"], "needs_confirmation")

    def test_nonconvex_outline_is_not_filled_by_a_convex_hull(self):
        polygon = Polygon([[-1, -1], [1, -1], [0.65, -0.2], [0.65, 0.2], [1, 1], [-1, 1], [-0.65, 0.2], [-0.65, -0.2]])
        xy, faces, _, used = grid_in_hull(np.array(polygon.exterior.coords), 48, polygon)
        self.assertLess(used.area, used.convex_hull.area * 0.9)
        mesh = sheets(xy, faces, np.full(len(xy), 0.12), np.full(len(xy), -0.12), np.eye(3), np.zeros(3))
        mesh, _ = prepare_mesh(mesh)
        self.assertTrue(mesh.is_watertight and mesh.is_winding_consistent)
        self.assertEqual(intersections(mesh), 0)
        self.assertAlmostEqual(abs(mesh.volume), polygon.area * 0.24, delta=0.01)

    def test_reference_with_large_hole_is_rejected(self):
        image = Image.new("RGBA", (200, 200), (20, 30, 40, 0))
        image.paste((50, 60, 70, 255), (10, 10, 190, 190))
        image.paste((0, 0, 0, 0), (50, 50, 150, 150))
        path = self.folder / "bad.png"
        image.save(path)
        with self.assertRaisesRegex(ValueError, "较大缺口"):
            alpha_polygon(path)

    def test_flat_roof_does_not_invent_buttons_from_photo_pattern(self):
        from soft_surface_details import refine_seat_details

        source = trimesh.creation.box(extents=[2, 0.2, 1.5])
        source.apply_translation([0, 0.1, 0])
        known = source.face_normals[:, 1] > 0.9
        axis = np.linspace(-0.8, 0.8, 12)
        xy = np.array([(x, z) for x in axis for z in np.linspace(-0.6, 0.6, 10)])
        image = np.full((256, 256, 3), 180, np.uint8)
        image[100:110, 100:110] = 0
        matrix = camera_matrix(np.array([0, 0.1, 0]), 2, 0.3, 0.8, 0.6)
        top, evidence = refine_seat_details(
            xy,
            np.full(len(xy), 0.2),
            0,
            box(-1, -0.75, 1, 0.75),
            source,
            known,
            Polygon(),
            {"rgb": image, "projection_from_world": matrix},
        )
        self.assertEqual(evidence["dimple_candidates"], [])
        self.assertEqual(evidence["unobserved_buttons_added"], 0)

    def test_invisible_source_does_not_guess_a_reference(self):
        meshes, camera, labels = self.scene()
        refs = self.candidates([labels == 1])
        result, _ = associate(meshes, camera, refs, self.folder, "left", np.zeros_like(labels))
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertNotIn("candidate_id", result)

    def test_clutter_without_whole_product_mask_refuses_without_rembg(self):
        raw = np.random.default_rng(20261113).integers(0, 200, (128, 128, 3), dtype=np.uint8)
        photo = self.folder / "photo.png"
        Image.fromarray(raw).save(photo)
        rembg = Mock()
        with patch.dict(sys.modules, {"rembg": rembg}), self.assertRaisesRegex(ValueError, "清理背景"):
            product_mask(
                photo,
                {"product_crop_pixels": [0, 0, 128, 128]},
                self.folder,
                {"target": {"x": 0, "y": 0, "width": 1, "height": 1}},
            )
        rembg.new_session.assert_not_called()

    def test_closed_disconnected_source_is_not_healthy(self):
        from auto_part_optimization import source_health

        left = trimesh.creation.box()
        right = left.copy()
        right.apply_translation([2, 0, 0])
        stats = source_health(trimesh.util.concatenate([left, right]))
        self.assertTrue(stats["closed"])
        self.assertEqual(stats["components"], 2)
        self.assertFalse(stats["valid_solid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
