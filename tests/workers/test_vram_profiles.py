import unittest

from vram_profiles import GIB, NAMES, choose, lower


class VramProfileTests(unittest.TestCase):
    def test_small_cards_start_low_and_scale_with_part_count(self):
        self.assertEqual(choose(6 * GIB, 5)["name"], "standard")  # measured: 4.06 GiB peak
        self.assertEqual(choose(6 * GIB, 8)["name"], "reduced")
        self.assertEqual(choose(6 * GIB, 14)["name"], "low")
        self.assertEqual(choose(4 * GIB, 8)["name"], "minimal")
        self.assertEqual(choose(12 * GIB, 4)["name"], "standard")
        self.assertEqual(choose(12 * GIB, 12)["name"], "reduced")
        self.assertEqual(choose(24 * GIB, 16)["name"], "standard")
        self.assertEqual(choose(0, 2)["name"], "low")  # unknown memory: be conservative

    def test_lower_walks_down_to_the_smallest(self):
        self.assertEqual([lower(name) and lower(name)["name"] for name in NAMES], NAMES[1:] + [None])
        self.assertLessEqual(lower("standard")["tokens"], 1024)


if __name__ == "__main__":
    unittest.main()
