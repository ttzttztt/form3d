"""Routing/contracts only. Synthetic fixtures do not measure model quality."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from services.api.segmentation import choose_segmentation, image_background_kind


class SegmentationRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def image(self, background):
        image = Image.new("RGBA", (80, 100), background)
        ImageDraw.Draw(image).rectangle((20, 20, 60, 80), fill="#aaaaaa")
        path = self.root / "input.png"
        image.save(path)
        return path

    def test_clean_images_preserve_basic_alpha_and_white_processing(self):
        for color, kind in [("white", "white_background"), ((0, 0, 0, 0), "provided_alpha")]:
            with self.subTest(kind=kind):
                path = self.image(color)
                original = path.read_bytes()
                self.assertEqual(image_background_kind(path), kind)
                self.assertEqual(choose_segmentation(path, "auto", True), ("basic", kind))
                self.assertEqual(path.read_bytes(), original)

    def test_scene_auto_uses_sam_only_when_ready(self):
        path = self.image("#847b69")
        self.assertEqual(choose_segmentation(path, "auto", True), ("sam2", "scene"))
        self.assertEqual(choose_segmentation(path, "auto", False), ("basic", "scene"))
        self.assertEqual(choose_segmentation(path, "basic", True), ("basic", "scene"))

    def test_explicit_sam_never_falls_back(self):
        path = self.image("white")
        self.assertEqual(choose_segmentation(path, "sam2", True), ("sam2", "white_background"))
        with self.assertRaisesRegex(ValueError, "实际运行验证"):
            choose_segmentation(path, "sam2", False)

    def test_tight_crop_routes_using_unchanged_white_source(self):
        source = self.image("white")
        crop = self.root / "crop.png"
        Image.new("RGBA", (40, 40), "#aaaaaa").save(crop)
        self.assertEqual(image_background_kind(crop), "scene")
        self.assertEqual(choose_segmentation(crop, "auto", True, source_path=source), ("sam2", "white_background"))
        self.assertEqual(choose_segmentation(crop, "auto", False, source_path=source), ("basic", "white_background"))
