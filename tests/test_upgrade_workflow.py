# -*- coding: utf-8 -*-
"""Contracts only: local model execution is measured separately in experiments."""

import json, shutil, sys, unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import test_part_optimization as fixtures
from services.api import part_optimization as service, part_candidates, part_regeneration as tasks, material_presets
from services.api.models import PartOptimizationRequest, PartSurfaceRepairRequest
from services.api.glb_document import read_glb, write_glb
from services.api.store import Store


class UpgradeWorkflowTests(unittest.TestCase):
    setUp = fixtures.PartOptimizationTests.setUp
    start = fixtures.PartOptimizationTests.start
    worker = fixtures.PartOptimizationTests.worker

    def extra_image(self, color="red", mode="RGBA"):
        identity = "e" * 32
        path = self.store.root / "images" / identity / "normalized.png"
        path.parent.mkdir(exist_ok=True)
        Image.new(mode, (128, 128), color).save(path)
        self.store.put_image({"id": identity, "normalized_path": str(path.relative_to(self.store.root))})
        return identity, path

    def start_with_view(self):
        identity, path = self.extra_image()
        result = service.start_optimization(
            self.store,
            self.job,
            PartOptimizationRequest(part_ids=self.ids, reference_views=[{"image_id": identity}]),
            self.executor,
        )
        return result["id"], tasks.folder_for(self.store, self.job, result["id"]), path

    def test_candidate_and_view_schema_limits(self):
        for body in ({"candidate_count": 4}, {"target_faces": 999}, {"reference_views": [{"image_id": "e" * 32}] * 2}):
            with self.assertRaises(ValueError):
                PartOptimizationRequest(part_ids=self.ids, **body)

    def test_atomic_progress_write_retries_transient_windows_reader_lock(self):
        path = self.folder / "atomic.json"
        tasks.write_json(path, {"version": 1})
        replace = Path.replace
        attempts = []

        def transient(source, destination):
            attempts.append(json.loads(path.read_text(encoding="utf-8"))["version"])
            if len(attempts) < 4:
                raise PermissionError("controlled Windows sharing violation")
            return replace(source, destination)

        with patch.object(Path, "replace", transient), patch.object(tasks.time, "sleep"):
            tasks.write_json(path, {"version": 2})
        self.assertEqual(attempts, [1, 1, 1, 1])
        self.assertEqual(json.loads(path.read_text())["version"], 2)

    def test_duplicate_pixels_with_different_png_mode_are_not_independent_views(self):
        identity, _ = self.extra_image("white", "RGB")
        with self.assertRaisesRegex(ValueError, "内容重复"):
            service.start_optimization(
                self.store,
                self.job,
                PartOptimizationRequest(part_ids=self.ids, reference_views=[{"image_id": identity}]),
                self.executor,
            )
        self.executor.submit.assert_not_called()

    def test_extra_photo_drift_prevents_any_worker_launch(self):
        identity, folder, path = self.start_with_view()
        Image.new("RGBA", (128, 128), "blue").save(path)
        with patch.object(service, "run_command") as worker:
            service.run_optimization(self.store, self.job["id"], identity)
        worker.assert_not_called()
        self.assertEqual(tasks.state_result(self.store, self.job, identity)["status"], "failed")

    def test_requested_extra_view_cannot_be_silently_omitted_from_ready_checks(self):
        identity, folder, _ = self.start_with_view()
        self.route = "photo_pillow"
        self.can_adopt = True
        with (
            patch.object(service, "copy_reference_cache", return_value={"cached": True}),
            patch.object(service, "run_command", side_effect=self.worker),
        ):
            service.run_optimization(self.store, self.job["id"], identity)
        result = tasks.state_result(self.store, self.job, identity)
        self.assertEqual(result["status"], "failed")
        self.assertIn("未完整参与", result["error"])
        self.assertFalse((folder / "ready.json").exists())

    def test_local_example_materials_are_deterministic_and_do_not_modify_jobs(self):
        before = self.store.job(self.job["id"])
        root = self.store.root / "preset_fixture"
        assets = root / "assets/catalog23_20261110"
        assets.mkdir(parents=True)
        for stem in ("corduroy", "leather", "oak"):
            Image.new("RGB", (16, 16), (90, 60, 30)).save(assets / (stem + "_color.jpg"))
            Image.new("RGB", (16, 16), (128, 128, 255)).save(assets / (stem + "_normal.png"))
        with patch.object(material_presets, "ROOT", root):
            first = material_presets.prepare_preset(self.store, "fabric")
            second = material_presets.prepare_preset(self.store, "fabric")
        self.assertEqual(first, second)
        self.assertIn("不代表", first["provenance"])
        self.assertEqual(self.store.job(self.job["id"]), before)
        self.assertEqual(set(first["textures"]), {"base_color_image", "normal_image"})

    def test_first_use_material_preset_is_safe_under_parallel_requests(self):
        from concurrent.futures import ThreadPoolExecutor

        fresh = Store(self.store.root / "fresh_preset_store")
        root = self.store.root / "parallel_preset_fixture"
        assets = root / "assets/catalog23_20261110"
        assets.mkdir(parents=True)
        Image.new("RGB", (16, 16), (90, 60, 30)).save(assets / "corduroy_color.jpg")
        Image.new("RGB", (16, 16), (128, 128, 255)).save(assets / "corduroy_normal.png")
        self.assertFalse((fresh.root / "images").exists())
        with patch.object(material_presets, "ROOT", root), ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(lambda _: material_presets.prepare_preset(fresh, "fabric"), range(16)))
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(len(fresh.images()), 2)
        self.assertEqual(fresh.jobs(), [])

    def prepare_candidates_fixture(self):
        _, folder = self.start()
        state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
        context = json.loads((folder / "context.json").read_text(encoding="utf-8"))
        (folder / "references").mkdir()
        Image.new("RGB", (128, 128), "gray").save(folder / "references/product.png")
        Image.new("RGBA", (128, 128), "white").save(folder / "reference.png")
        state["reference_sha256"] = tasks.digest(folder / "reference.png")
        tasks.write_json(
            folder / "analysis.json", {"route": "ai_regeneration", "photo_association": {"status": "matched"}}
        )
        tasks.write_json(folder / "camera.json", {"fixture": True})
        return folder, state, context

    def fake_cache(self, store, job, state, destination, seed=42):
        destination.mkdir()
        doc, binary, extra = read_glb(self.source)
        doc.setdefault("asset", {}).setdefault("extras", {})["fixture_seed"] = seed
        write_glb(destination / "model.glb", doc, binary, extra)
        shutil.copyfile(self.store.root / "images" / ("b" * 32) / "normalized.png", destination / "foreground.png")
        tasks.write_json(
            destination / "local_summary.json",
            {
                "seed": seed,
                "input_sha256": state["reference_sha256"],
                "model_sha256": tasks.digest(destination / "model.glb"),
            },
        )
        return {"raw_geometry_only": True, "fixture_no_ml_inference": True}

    def fake_candidate_worker(self, folder, *args, **kwargs):
        seed = int(folder.name.split("_")[1])
        output = folder / "preview"
        output.mkdir()
        for name in ("model.glb", "part.glb", "diagnostic.glb"):
            shutil.copyfile(folder / "generated/model.glb", output / name)
        for name in ("comparison.png", "before.png", "after.png"):
            shutil.copyfile(folder / "reference.png", folder / name)
        score = {42: 0.8, 77: 0.99, 123: 0.85}[seed]
        eligible = seed != 77
        checks = {
            "can_adopt": eligible,
            "part_silhouette_iou_after": score,
            "ranking": {"score": score},
            "reason": "controlled contract fixture",
            "quality_dimensions": [{"key": "performance", "metrics": {"triangles": 100000}}],
        }
        tasks.write_json(folder / "checks.json", checks)
        tasks.write_json(output / "manifest.json", {"operation": {"photo_checks": checks}})

    def test_candidate_selection_prioritizes_eligible_then_score_and_exact_bytes(self):
        folder, state, context = self.prepare_candidates_fixture()
        with (
            patch.object(service, "copy_generation_cache", side_effect=self.fake_cache),
            patch.object(part_candidates, "run_command", side_effect=self.fake_candidate_worker),
            patch.object(part_candidates, "validate_glb", return_value={"status": "pass"}),
            patch.object(part_candidates, "RECONSTRUCTION_LOCK"),
            patch.object(part_candidates, "gpu_wait") as gpu,
        ):
            selected = part_candidates.run_candidates(
                self.store, self.job, folder, state, context, lambda stage: context
            )
        self.assertEqual(selected["seed"], 123)
        self.assertFalse(state["inference_this_task"])
        gpu.assert_not_called()
        self.assertEqual(
            (folder / "preview/model.glb").read_bytes(), (folder / "candidates/seed_123/preview/model.glb").read_bytes()
        )
        self.assertFalse(state["candidate_results"][1]["eligible"])
        self.assertNotIn("current_asset_version", self.store.job(self.job["id"]))

    def test_all_alignment_failures_keep_valid_raw_shapes_but_never_publish(self):
        folder, state, context = self.prepare_candidates_fixture()
        with (
            patch.object(service, "copy_generation_cache", side_effect=self.fake_cache),
            patch.object(part_candidates, "run_command", side_effect=ValueError("controlled alignment refusal")),
            patch.object(part_candidates, "validate_glb", return_value={"status": "pass"}),
            patch.object(part_candidates, "RECONSTRUCTION_LOCK"),
        ):
            with self.assertRaisesRegex(ValueError, "所有候选"):
                part_candidates.run_candidates(self.store, self.job, folder, state, context, lambda stage: context)
        self.assertTrue((folder / "generated/model.glb").exists())
        self.assertFalse((folder / "preview").exists())
        self.assertTrue(state["generated_valid"])
        self.assertNotIn("current_asset_version", self.store.job(self.job["id"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
