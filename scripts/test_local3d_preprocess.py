"""Regression checks for pale product details and user-supplied alpha."""
import unittest
import json
import struct
from pathlib import Path
import tempfile
from unittest.mock import patch
import numpy as np
from PIL import Image, ImageDraw

from local3d_preprocess import remove_product_background
from local3d_export import prepare_vertex_appearance
from generate_local3d import write_json


class PreparationTests(unittest.TestCase):
    def test_ivory_tabletop_is_preserved_on_white(self):
        image = Image.new("RGBA", (200, 200), "white")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((35, 25, 165, 45), fill=(232, 230, 220))
        drawing.ellipse((65, 44, 135, 175), fill=(130, 185, 30))
        result, method = remove_product_background(image, None)
        self.assertEqual(method, "white_background_connected_components")
        self.assertEqual(result.getpixel((50, 35))[3], 255)
        self.assertEqual(result.getpixel((10, 10))[3], 0)
        self.assertEqual(result.getpixel((100, 100))[3], 255)

    def test_supplied_alpha_is_preserved(self):
        image = Image.new("RGBA", (100, 100), (255, 255, 255, 0))
        ImageDraw.Draw(image).rectangle((30, 30, 70, 70), fill=(255, 255, 255, 255))
        result, method = remove_product_background(image, None)
        self.assertEqual(method, "provided_alpha")
        self.assertEqual(result.tobytes(), image.tobytes())

    def test_vertex_color_is_linearized_without_changing_geometry(self):
        import trimesh
        mesh = trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[0,1,0]], faces=[[0,1,2]],
                               vertex_colors=[[128,128,128,255]]*3, process=False)
        vertices = mesh.vertices.copy()
        prepare_vertex_appearance(mesh)
        self.assertEqual(mesh.visual.vertex_colors[0].tolist(), [55,55,55,255])
        self.assertTrue(np.array_equal(mesh.vertices, vertices))
        self.assertEqual(mesh.visual.material.metallicFactor, 0)
        content = mesh.export(file_type='glb')
        length = struct.unpack_from('<I', content, 12)[0]
        document = json.loads(content[20:20+length])
        primitive = document['meshes'][0]['primitives'][0]
        self.assertIn('COLOR_0', primitive['attributes'])
        material = document['materials'][primitive['material']]['pbrMetallicRoughness']
        self.assertEqual(material['metallicFactor'], 0)
        self.assertEqual(material['roughnessFactor'], .8)

    def test_progress_write_retries_windows_sharing_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'progress.json'
            target.write_text('{}', encoding='utf-8')
            replace = Path.replace
            attempts = []
            def initially_locked(source, destination):
                attempts.append(1)
                if len(attempts) < 3:
                    raise PermissionError('simulated Windows sharing violation')
                return replace(source, destination)
            with patch.object(Path, 'replace', initially_locked):
                write_json(target, {'stage':'generated'})
            self.assertEqual(len(attempts), 3)
            self.assertEqual(json.loads(target.read_text())['stage'], 'generated')


if __name__ == "__main__":
    unittest.main(verbosity=2)
