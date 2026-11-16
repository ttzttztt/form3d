import unittest
from services.api.assembly_proposals import normalize_proposal


class ProposalNormalizationTests(unittest.TestCase):
    def value(self, kind="top"):
        return {
            "furniture": [
                {"category": "table", "bbox": [0, 0, 1000, 1000], "parts": [{"kind": kind, "bbox": [10, 10, 900, 200]}]}
            ]
        }

    def test_known_alias_preserves_original_without_modifying_input(self):
        value = self.value()
        result, warnings = normalize_proposal(value)
        self.assertEqual(result["furniture"][0]["parts"][0]["kind"], "tabletop")
        self.assertEqual(result["furniture"][0]["parts"][0]["raw_kind"], "top")
        self.assertEqual(value["furniture"][0]["parts"][0]["kind"], "top")
        self.assertEqual(warnings, [])

    def test_ambiguous_label_is_not_guessed_to_be_a_cabinet_body(self):
        result, warnings = normalize_proposal(self.value("topbox"))
        self.assertEqual(result["furniture"][0]["parts"][0]["kind"], "unknown")
        self.assertTrue(warnings)

    def test_boolean_and_duplicate_box_are_refused(self):
        value = self.value()
        value["furniture"][0]["parts"][0]["bbox"][0] = True
        with self.assertRaises(ValueError):
            normalize_proposal(value)
        value = self.value()
        value["furniture"][0]["parts"] *= 2
        with self.assertRaises(ValueError):
            normalize_proposal(value)
