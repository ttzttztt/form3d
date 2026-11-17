import unittest

import numpy as np

from part_kind_rules import resolve_kind

SHAPE = (200, 200)
WHOLE = np.zeros(SHAPE, bool)
WHOLE[20:180, 20:180] = True


def box(y0, y1, x0, x1):
    mask = np.zeros(SHAPE, bool)
    mask[y0:y1, x0:x1] = True
    return mask


def ev(*pairs):
    return [{"kind": k, "score": s} for k, s in pairs]


class ResolveKindTests(unittest.TestCase):
    def test_wide_short_region_is_a_drawer_not_a_door(self):
        kind, record = resolve_kind(ev(("door", 0.39), ("drawer", 0.35)), box(30, 60, 30, 170), WHOLE)
        self.assertEqual((kind, record["method"]), ("drawer", "shape"))

    def test_tall_region_is_a_door_even_with_lower_score(self):
        kind, _ = resolve_kind(ev(("door", 0.33), ("drawer", 0.49)), box(30, 170, 30, 90), WHOLE)
        self.assertEqual(kind, "door")

    def test_top_slab_is_a_tabletop_and_thin_upright_is_a_leg(self):
        top, _ = resolve_kind(ev(("tabletop", 0.73), ("leg", 0.70)), box(20, 40, 20, 180), WHOLE)
        leg, _ = resolve_kind(ev(("tabletop", 0.73), ("leg", 0.70)), box(40, 180, 30, 45), WHOLE)
        self.assertEqual((top, leg), ("tabletop", "leg"))

    def test_clear_score_margin_decides_when_shape_is_silent(self):
        kind, record = resolve_kind(ev(("seat_cushion", 0.82), ("backrest", 0.70)), box(60, 140, 40, 160), WHOLE)
        self.assertEqual(kind, "seat_cushion")

    def test_ambiguous_region_stays_unknown(self):
        kind, record = resolve_kind(ev(("frame", 0.40), ("body", 0.38)), box(40, 160, 40, 160), WHOLE)
        self.assertEqual((kind, record["method"]), ("unknown", "unresolved"))


if __name__ == "__main__":
    unittest.main()
