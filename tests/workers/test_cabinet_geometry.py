"""Cabinet geometry against synthetic photos with known proportions and layout.

Each scene is a box cabinet rendered with a pinhole camera in two-point perspective (verticals
parallel, as in product photos). The estimate must recover height/width and depth/width, and the
front layout must recover the drawers, doors and open compartments that were drawn.
"""

import math
import unittest

import numpy as np

try:
    import cv2

    import cabinet_geometry as cg
except ImportError:  # pragma: no cover - CI installs opencv for the worker tests
    cv2 = None


def render(width, height, depth, yaw_deg, focal, distance, eye_height, fronts, size=(1200, 1000)):
    """Draw a cabinet. fronts: [(kind, u0, v0, u1, v1)] in front fractions. Returns rgb, mask."""
    W, H = size
    yaw = math.radians(yaw_deg)
    right = np.array([math.cos(yaw), 0, math.sin(yaw)])  # front horizontal direction
    back = np.array([-math.sin(yaw), 0, math.cos(yaw)])  # into the scene
    down = np.array([0.0, 1.0, 0.0])
    # Front-bottom-left corner placed so the cabinet sits roughly centred in the frame.
    origin = np.array([-width / 2 * math.cos(yaw), eye_height, distance]) - back * depth / 2
    cx, cy = W / 2, H / 2 - focal * (eye_height - height / 2) / distance  # frame the cabinet

    def project(p):
        return (focal * p[0] / p[2] + cx, focal * p[1] / p[2] + cy)

    def point(u, v, d=0.0):  # u across, v down from the top edge, d into the scene
        return origin + right * (u * width) - down * ((1 - v) * height) + back * d

    image = np.full((H, W, 3), 245, np.uint8)
    mask = np.zeros((H, W), np.uint8)

    def poly(points, colour):
        pts = np.int32([project(p) for p in points])
        cv2.fillPoly(image, [pts], colour)
        cv2.fillPoly(mask, [pts], 1)

    side_u = 0.0 if yaw_deg > 0 else 1.0  # the side facing the camera
    poly([point(side_u, 0), point(side_u, 0, depth), point(side_u, 1, depth), point(side_u, 1)], (120, 80, 50))
    if eye_height > height:  # camera above the top: the top face shows
        poly([point(0, 0), point(1, 0), point(1, 0, depth), point(0, 0, depth)], (200, 160, 120))
    poly([point(0, 0), point(1, 0), point(1, 1), point(0, 1)], (170, 115, 70))
    rng = np.random.default_rng(1)
    for kind, u0, v0, u1, v1 in fronts:
        inset = 0.006
        corners = [
            point(u0 + inset, v0 + inset),
            point(u1 - inset, v0 + inset),
            point(u1 - inset, v1 - inset),
            point(u0 + inset, v1 - inset),
        ]
        pts = np.int32([project(p) for p in corners])
        if kind == "open":  # dark back with random clutter
            cv2.fillPoly(image, [pts], (40, 25, 20))
            x0, y0 = pts.min(0)
            x1, y1 = pts.max(0)
            for _ in range(25):
                bx = int(rng.integers(x0, max(x0 + 1, x1 - 20)))
                bw = int(rng.integers(6, 30))
                bh = int(rng.integers(int(0.4 * (y1 - y0)), int(0.9 * (y1 - y0))))
                shade = int(rng.integers(150, 250))
                cv2.rectangle(image, (bx, y1 - bh), (min(x1, bx + bw), y1 - 2), (shade, shade, shade - 20), -1)
        else:
            cv2.fillPoly(image, [pts], (185, 125, 78))
            cv2.polylines(image, [pts], True, (60, 35, 20), 3)
    return image, mask.astype(bool)


SIDEBOARD = [
    ("drawer", 0, 0, 0.5, 0.33),
    ("drawer", 0, 0.33, 0.5, 0.66),
    ("drawer", 0, 0.66, 0.5, 1.0),
    ("door", 0.5, 0, 1.0, 1.0),
]
BOOKCASE = [("open", 0, 0, 1, 0.25), ("open", 0, 0.25, 1, 0.5), ("open", 0, 0.5, 1, 0.75), ("open", 0, 0.75, 1, 1)]


@unittest.skipIf(cv2 is None, "opencv not installed")
class CabinetGeometryTest(unittest.TestCase):
    def check(self, width, height, depth, yaw, focal, eye, fronts):
        image, mask = render(width, height, depth, yaw, focal, 6.0, eye, fronts)
        geometry = cg.estimate(image, mask)
        self.assertEqual(geometry["side"], "left" if yaw > 0 else "right")
        self.assertTrue(geometry["depth_measured"])
        hw = geometry["height"] / geometry["width"]
        dw = geometry["depth"] / geometry["width"]
        self.assertAlmostEqual(hw, height / width, delta=0.08 * height / width, msg=f"H/W {hw:.3f}")
        self.assertAlmostEqual(dw, depth / width, delta=0.15 * depth / width, msg=f"D/W {dw:.3f}")
        rectified, _ = cg.rectify(image, geometry)
        return [c["kind"] for c in cg.layout(rectified)]

    def test_sideboard_seen_from_the_left_and_above(self):
        kinds = self.check(1.4, 0.8, 0.42, 25, 1600, 1.3, SIDEBOARD)
        self.assertEqual(kinds.count("drawer"), 3)
        self.assertEqual(kinds.count("door"), 1)

    def test_bookcase_seen_from_the_right(self):
        kinds = self.check(0.9, 1.8, 0.3, -20, 1500, 1.2, BOOKCASE)
        self.assertEqual(kinds.count("open"), 4)

    def test_wide_lens_strong_perspective(self):
        self.check(1.2, 1.0, 0.5, 35, 900, 1.4, SIDEBOARD)

    def test_built_parts_reproject_onto_the_photo(self):
        image, mask = render(1.4, 0.8, 0.42, 25, 1600, 6.0, 1.3, SIDEBOARD)
        geometry, cells, parts, assumptions, iou = cg.analyse(image, mask)
        self.assertGreater(iou, 0.95)
        kinds = [p["kind"] for p in parts]
        self.assertEqual((kinds.count("body"), kinds.count("drawer"), kinds.count("door")), (1, 3, 1))
        for part in parts:  # every part is a closed solid with volume inside the carcass bounds
            v = part["mesh"]["vertices"]
            self.assertTrue(np.all(v.max(0) - v.min(0) > 0.003), part["name"])
            self.assertLessEqual(v[:, 0].max(), 0.5 + 1e-6)
            self.assertGreaterEqual(v[:, 0].min(), -0.5 - 1e-6)
        masks = cg.part_masks(geometry, parts, mask.shape)
        drawer_masks = [m for p, (m, seen) in zip(parts, masks) if p["kind"] == "drawer"]
        self.assertTrue(all(seen == "partial" for _, seen in masks if _ is not None))
        self.assertTrue(all(m.sum() > 500 for m in drawer_masks))


if __name__ == "__main__":
    unittest.main()
