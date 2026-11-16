# -*- coding: utf-8 -*-
"""Static geometry grouping tests with triangle/attribute preservation."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.api.geometry import build_template, validate_glb
from services.api.models import JobRequest
from services.api.glb_document import read_glb, write_glb, parts_catalog, material_edit
from edit_asset import group_geometry, accessor_array


class GroupingTests(unittest.TestCase):
    def test_plane_group_keeps_triangles_and_original_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "original.glb"
            build_template(JobRequest(image_id="a" * 32, template="cabinet"), source)
            doc, binary, extra = read_glb(source)
            before = source.read_bytes()
            positions = {
                p["attributes"]["POSITION"]: accessor_array(doc, binary, p["attributes"]["POSITION"]).tobytes()
                for m in doc["meshes"]
                for p in m["primitives"]
            }
            count = sum(p["triangles"] for p in parts_catalog(doc))
            group_geometry(doc, binary, {"operation": "plane_group", "axis": "y", "position": 0.5, "part_ids": []})
            self.assertEqual(sum(p["triangles"] for p in parts_catalog(doc)), count)
            for idx, data in positions.items():
                self.assertEqual(accessor_array(doc, binary, idx).tobytes(), data)
            output = Path(directory) / "grouped.glb"
            write_glb(output, doc, binary, extra)
            self.assertEqual(validate_glb(output)["errors"], 0)
            self.assertEqual(source.read_bytes(), before)

    def test_connected_cube_does_not_become_six_fake_semantic_parts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.glb"
            build_template(JobRequest(image_id="a" * 32, template="table"), path)
            doc, binary, _ = read_glb(path)
            with self.assertRaisesRegex(ValueError, "没有分出多个区域"):
                group_geometry(
                    doc,
                    binary,
                    {
                        "operation": "connected_components",
                        "part_ids": [],
                        "axis": "y",
                        "position": 0.5,
                        "min_faces": 1,
                        "max_groups": 32,
                    },
                )

    def test_single_part_material_change_does_not_leak_to_other_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.glb"
            build_template(JobRequest(image_id="a" * 32, template="table"), path)
            doc, binary, _ = read_glb(path)
            doc["nodes"][1]["mesh"] = doc["nodes"][0]["mesh"]
            second = doc["nodes"][1]["mesh"]
            material_edit(
                doc,
                {
                    "color": "#ff0000",
                    "opacity": 1,
                    "metalness": 0,
                    "roughness": 0.8,
                    "mode": "replace",
                    "part_ids": ["node_0_primitive_0"],
                },
            )
            self.assertEqual(doc["nodes"][1]["mesh"], second)
            self.assertNotEqual(doc["nodes"][0]["mesh"], second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
