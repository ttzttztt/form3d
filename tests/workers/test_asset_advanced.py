"""Meaningful static edit invariants and failure controls (fixtures, not product fidelity)."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "services/workers")]
import numpy as np
from services.api.models import AssetEditRequest, JobRequest
from services.api.geometry import build_template, validate_glb
from services.api.glb_document import read_glb, write_glb, parts_catalog, set_part_ids, compact_static
from edit_asset import group_geometry, accessor_array
from asset_operations import apply_operation
from _env import pymeshlab_ready, PYMESHLAB_REASON


class AdvancedAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "source.glb"
        build_template(JobRequest(image_id="a" * 32, template="cabinet"), self.path)
        self.doc, self.binary, self.extra = read_glb(self.path)
        set_part_ids(self.doc)

    def request(self, **values):
        return AssetEditRequest(**values).model_dump()

    def valid(self):
        self.binary = compact_static(self.doc, self.binary)
        write_glb(self.root / "output.glb", self.doc, self.binary, self.extra)
        self.assertEqual(validate_glb(self.root / "output.glb")["errors"], 0)

    def test_split_ids_survive_rename_and_material_and_unchanged_siblings(self):
        before = parts_catalog(self.doc)
        first = before[0]
        r = self.request(operation="face_group", face_selection=[{"part_id": first["id"], "faces": [0, 1]}])
        apply_operation(self.doc, self.binary, r)
        split = parts_catalog(self.doc)
        self.assertEqual(sum(p["triangles"] for p in split), sum(p["triangles"] for p in before))
        self.assertEqual({p["id"] for p in before[1:]}, {p["id"] for p in split[2:]})
        self.assertEqual(len({p["id"] for p in split}), len(split))
        ids = [p["id"] for p in split]
        self.assertEqual(split[0]["selection_role"], "remainder")
        self.assertEqual(split[1]["selection_role"], "selected")
        self.assertEqual(split[1]["source_part_id"], first["id"])
        apply_operation(self.doc, self.binary, self.request(operation="rename", part_ids=[ids[0]], name="Door"))
        apply_operation(self.doc, self.binary, self.request(part_ids=[ids[0]], color="#ff0000"))
        self.valid()
        self.assertEqual(ids, [p["id"] for p in parts_catalog(self.doc)])
        self.assertEqual(parts_catalog(self.doc)[0]["name"], "Door")

    def test_subset_bounds_use_indexed_vertices(self):
        first = parts_catalog(self.doc)[0]
        apply_operation(
            self.doc,
            self.binary,
            self.request(operation="face_group", face_selection=[{"part_id": first["id"], "faces": [0, 1]}]),
        )
        # A flat selected face must not split using invisible vertices from its old shared POSITION.
        part = parts_catalog(self.doc)[1]
        # Verify all selected index vertices actually determine the cut, independent of unused entries.
        primitive = self.doc["meshes"][self.doc["nodes"][part["node"]]["mesh"]]["primitives"][part["primitive"]]
        positions = accessor_array(self.doc, self.binary, primitive["attributes"]["POSITION"])
        indices = accessor_array(self.doc, self.binary, primitive["indices"]).ravel()
        axis = int(np.argmin(np.ptp(positions[indices], axis=0)))
        with self.assertRaisesRegex(ValueError, "没有分出多个区域"):
            group_geometry(
                self.doc, self.binary, self.request(operation="plane_group", part_ids=[part["id"]], axis="xyz"[axis])
            )

    def test_invalid_face_and_duplicate_contract_fail(self):
        with self.assertRaises(ValueError):
            AssetEditRequest(operation="face_group")
        with self.assertRaises(ValueError):
            AssetEditRequest(operation="face_group", face_selection=[{"part_id": "p", "faces": [-1]}])
        with self.assertRaises(ValueError):
            AssetEditRequest(
                operation="face_group", face_selection=[{"part_id": "p", "faces": [0]}, {"part_id": "p", "faces": [1]}]
            )
        first = parts_catalog(self.doc)[0]
        with self.assertRaisesRegex(ValueError, "选面编号"):
            apply_operation(
                self.doc,
                self.binary,
                self.request(operation="face_group", face_selection=[{"part_id": first["id"], "faces": [1000000]}]),
            )

    def test_instanced_nodes_have_independent_stable_ids(self):
        self.doc["nodes"][1]["mesh"] = self.doc["nodes"][0]["mesh"]
        ids = [p["id"] for p in parts_catalog(self.doc)]
        apply_operation(self.doc, self.binary, self.request(operation="rename", part_ids=[ids[0]], name="Only first"))
        self.assertNotEqual(parts_catalog(self.doc)[1]["name"], "Only first")
        self.valid()
        self.assertEqual(ids, [p["id"] for p in parts_catalog(self.doc)])

    def test_real_maps_embedded_packed_roughness_and_transform(self):
        from PIL import Image

        path = self.root / "map.png"
        Image.new("RGB", (32, 32), (64, 128, 192)).save(path)
        request = self.request(
            base_color_image="b" * 32, normal_image="c" * 32, roughness_image="d" * 32, uv_scale=2, uv_rotation=90
        )
        request["_texture_paths"] = {s: str(path) for s in ("base_color_image", "normal_image", "roughness_image")}
        positions = {
            a: accessor_array(self.doc, self.binary, a).tobytes()
            for a in {p["attributes"]["POSITION"] for m in self.doc["meshes"] for p in m["primitives"]}
        }
        result = apply_operation(self.doc, self.binary, request)
        self.assertTrue(result["planar_uv_parts"])
        for a, data in positions.items():
            self.assertEqual(accessor_array(self.doc, self.binary, a).tobytes(), data)
        self.valid()
        material = self.doc["materials"][0]
        info = material["pbrMetallicRoughness"]["baseColorTexture"]
        self.assertEqual(info["extensions"]["KHR_texture_transform"]["scale"], [2, 2])
        image = self.doc["images"][
            self.doc["textures"][material["pbrMetallicRoughness"]["metallicRoughnessTexture"]["index"]]["source"]
        ]
        view = self.doc["bufferViews"][image["bufferView"]]
        import io

        pixel = Image.open(
            io.BytesIO(self.binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]])
        ).getpixel((0, 0))
        self.assertEqual(pixel[2], 255)
        self.assertEqual(pixel[0], 255)
        self.assertTrue(0 < pixel[1] < 255)

    def test_compaction_prevents_revision_buffer_growth(self):
        sizes = []
        for i in range(12):
            apply_operation(self.doc, self.binary, self.request(color="#%02x1122" % i))
            self.binary = compact_static(self.doc, self.binary)
            sizes.append(len(self.binary))
            self.assertEqual(len(self.doc["meshes"]), len({n["mesh"] for n in self.doc["nodes"] if "mesh" in n}))
        self.assertEqual(len(set(sizes)), 1)
        self.valid()

    def test_texture_on_extended_document_keeps_unused_meshes_valid(self):
        from PIL import Image

        self.doc["extensionsUsed"] = ["KHR_materials_ior"]
        self.doc["materials"][0].setdefault("extensions", {})["KHR_materials_ior"] = {"ior": 1.5}
        path = self.root / "map.png"
        Image.new("RGB", (32, 32), (128, 128, 255)).save(path)
        r = self.request(normal_image="b" * 32, part_ids=[parts_catalog(self.doc)[0]["id"]])
        r["_texture_paths"] = {"normal_image": str(path)}
        apply_operation(self.doc, self.binary, r)
        self.valid()

    def test_compaction_retains_textures_reachable_only_from_material_extensions(self):
        from PIL import Image

        path = self.root / "extension.png"
        target = [parts_catalog(self.doc)[0]["id"]]
        for color in [(20, 30, 40), (128, 128, 255)]:
            Image.new("RGB", (32, 32), color).save(path)
            r = self.request(base_color_image="b" * 32, normal_image="c" * 32, part_ids=target)
            r["_texture_paths"] = {s: str(path) for s in ("base_color_image", "normal_image")}
            apply_operation(self.doc, self.binary, r)
        part = parts_catalog(self.doc)[0]
        primitive = self.doc["meshes"][self.doc["nodes"][part["node"]]["mesh"]]["primitives"][part["primitive"]]
        material = self.doc["materials"][primitive["material"]]
        sheen = material["pbrMetallicRoughness"].pop("baseColorTexture")
        normal = material.pop("normalTexture")
        material.setdefault("extensions", {}).update(
            KHR_materials_sheen={"sheenColorTexture": sheen}, KHR_materials_clearcoat={"clearcoatNormalTexture": normal}
        )
        self.doc["extensionsUsed"] = list(
            set(self.doc.get("extensionsUsed", [])) | {"KHR_materials_sheen", "KHR_materials_clearcoat"}
        )
        positions = accessor_array(self.doc, self.binary, primitive["attributes"]["POSITION"]).copy()
        signatures = {p["id"]: p["material_signature"] for p in parts_catalog(self.doc, self.binary)}
        old_size = len(self.binary)
        self.binary = compact_static(self.doc, self.binary)
        self.assertLess(len(self.binary), old_size)
        self.assertEqual({p["id"]: p["material_signature"] for p in parts_catalog(self.doc, self.binary)}, signatures)
        part = parts_catalog(self.doc)[0]
        primitive = self.doc["meshes"][self.doc["nodes"][part["node"]]["mesh"]]["primitives"][part["primitive"]]
        np.testing.assert_array_equal(
            accessor_array(self.doc, self.binary, primitive["attributes"]["POSITION"]), positions
        )
        material = self.doc["materials"][primitive["material"]]
        import io

        for ext, key in [
            ("KHR_materials_sheen", "sheenColorTexture"),
            ("KHR_materials_clearcoat", "clearcoatNormalTexture"),
        ]:
            info = material["extensions"][ext][key]
            image = self.doc["images"][self.doc["textures"][info["index"]]["source"]]
            view = self.doc["bufferViews"][image["bufferView"]]
            start = view["byteOffset"]
            self.assertEqual(
                Image.open(io.BytesIO(self.binary[start : start + view["byteLength"]])).getpixel((0, 0)),
                (128, 128, 255),
            )
        self.valid()

    @unittest.skipUnless(pymeshlab_ready(), PYMESHLAB_REASON)
    def test_lod_changes_geometry_and_preserves_parts(self):
        import trimesh

        mesh = trimesh.creation.icosphere(subdivisions=3)
        mesh.export(self.path)
        self.doc, self.binary, self.extra = read_glb(self.path)
        set_part_ids(self.doc)
        parts = parts_catalog(self.doc)
        result = apply_operation(self.doc, self.binary, self.request(operation="decimate", lod_ratio=0.7))
        self.assertLess(result["parts"][0]["after"], result["parts"][0]["before"])
        self.assertEqual([p["id"] for p in parts_catalog(self.doc)], [p["id"] for p in parts])
        self.valid()

    def test_lod_textured_and_low_face_controls(self):
        first = parts_catalog(self.doc)[0]
        with self.assertRaisesRegex(ValueError, "面数过少"):
            apply_operation(self.doc, self.binary, self.request(operation="decimate", part_ids=[first["id"]]))
        p = self.doc["meshes"][self.doc["nodes"][0]["mesh"]]["primitives"][0]
        p["attributes"]["TEXCOORD_0"] = p["attributes"]["POSITION"]
        with self.assertRaisesRegex(ValueError, "UV"):
            apply_operation(self.doc, self.binary, self.request(operation="decimate", part_ids=[first["id"]]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
