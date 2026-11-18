"""The whole-furniture mask keeps thin pieces that a box-prompted SAM mask leaves out."""

import unittest

import numpy as np
from PIL import Image

from plan_assembly_from_photo import complete_with_studio_foreground, studio_foreground


def studio_photo():
    """A dark cabinet on thin red legs, plus a separate vase, on a white background."""
    rgb = np.full((120, 160, 3), 255, np.uint8)
    rgb[20:70, 40:120] = (40, 60, 160)  # cabinet
    rgb[70:110, 50:53] = (200, 20, 20)  # legs
    rgb[70:110, 107:110] = (200, 20, 20)
    rgb[90:110, 140:150] = (30, 120, 30)  # vase beside it, not touching
    return Image.fromarray(rgb)


class WholeMaskCompletionTests(unittest.TestCase):
    def test_studio_foreground_needs_a_plain_background(self):
        self.assertIsNotNone(studio_foreground(studio_photo()))
        noisy = np.random.default_rng(0).integers(0, 255, (120, 160, 3), dtype=np.uint8)
        self.assertIsNone(studio_foreground(Image.fromarray(noisy)))

    def test_legs_touching_the_sam_mask_are_added_and_separate_objects_are_not(self):
        studio = studio_foreground(studio_photo())
        sam = np.zeros(studio.shape, bool)
        sam[20:70, 40:120] = True  # SAM stopped at the cabinet body
        whole = complete_with_studio_foreground(sam, studio, (35, 15, 125, 112))
        self.assertTrue(whole[100, 51] and whole[100, 108])
        self.assertFalse(whole[100, 145])

    def test_without_a_sam_mask_components_inside_the_box_are_used(self):
        studio = studio_foreground(studio_photo())
        whole = complete_with_studio_foreground(None, studio, (35, 15, 125, 112))
        self.assertTrue(whole[40, 80] and whole[100, 51])
        self.assertFalse(whole[100, 145])


if __name__ == "__main__":
    unittest.main()
