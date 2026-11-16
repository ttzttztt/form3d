"""Automatic workflow contracts. Workers are mocked; real runs are separate."""

import json, shutil, tempfile, unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
from services.api.store import Store
from services.api.models import JobRequest, PartSurfaceRepairRequest, AssetEditRequest
from services.api.geometry import build_template
from services.api.glb_document import read_glb, write_glb
from services.api import part_optimization as service
from services.api import part_regeneration as tasks
from services.api.asset_editor import edit_asset


class PartOptimizationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name))
        self.job = {
            "id": "a" * 32,
            "status": "awaiting_review",
            "request": JobRequest(image_id="b" * 32).model_dump(),
            "events": [],
            "model_url": "/source.glb",
        }
        self.store.create_job(self.job, "", "")
        self.folder = self.store.root / "jobs" / self.job["id"]
        self.folder.mkdir(parents=True)
        self.source = self.folder / "model.glb"
        build_template(JobRequest(image_id="b" * 32, template="table"), self.source)
        doc, binary, extra = read_glb(self.source)
        doc["meshes"][0]["primitives"][0].setdefault("extras", {})["form_semantic_kind"] = "pillow"
        write_glb(self.source, doc, binary, extra)
        image = self.store.root / "images" / ("b" * 32) / "normalized.png"
        image.parent.mkdir(parents=True)
        Image.new("RGBA", (128, 128), "white").save(image)
        self.store.put_image({"id": "b" * 32, "normalized_path": str(image.relative_to(self.store.root))})
        self.ids = ["node_0_primitive_0"]
        self.executor = Mock()
        for module, name, value in [
            (service, "local_python", "mock-python"),
            (service, "segmentation_status", {"available": True}),
        ]:
            p = patch.object(module, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def start(self):
        result = service.start_optimization(
            self.store, self.job, PartSurfaceRepairRequest(part_ids=self.ids), self.executor
        )
        return result["id"], tasks.folder_for(self.store, self.job, result["id"])

    def worker(self, folder, command, *args, **kwargs):
        stage = command[command.index("--stage") + 1]
        if stage == "analyze":
            tasks.write_json(
                folder / "analysis.json",
                {
                    "route": self.route,
                    "reason": "fixture plan",
                    "kind": "pillow",
                    "needs_guided_reference": False,
                    "photo_association": {"status": "matched", "candidate_id": "c" * 32},
                },
            )
            tasks.write_json(folder / "camera.json", {"method": "mocked camera, not a measured fit"})
            shutil.copyfile(self.store.root / "images" / ("b" * 32) / "normalized.png", folder / "association.png")
        else:
            output = folder / "preview"
            output.mkdir()
            for name in ("model.glb", "part.glb", "diagnostic.glb"):
                shutil.copyfile(self.source, output / name)
            shutil.copyfile(folder / "association.png", folder / "comparison.png")
            checks = {
                "can_adopt": self.can_adopt,
                "part_silhouette_iou_before": 0.5,
                "part_silhouette_iou_after": 0.8,
                "reason": "mock contract fixture",
            }
            tasks.write_json(folder / "checks.json", checks)
            tasks.write_json(
                output / "manifest.json",
                {
                    "operation": {"operation": "replace_part", "method": "ai_regeneration", "photo_checks": checks},
                    "source_sha256": tasks.digest(self.source),
                    "model_sha256": tasks.digest(self.source),
                },
            )

    def run_ready(self, can_adopt=True):
        self.route = "photo_pillow"
        self.can_adopt = can_adopt
        identity, folder = self.start()
        with (
            patch.object(service, "copy_reference_cache", return_value={"reused_2d_proposals_only": True}),
            patch.object(service, "run_command", side_effect=self.worker),
            patch.object(service, "gpu_wait") as gpu,
        ):
            service.run_optimization(self.store, self.job["id"], identity)
        gpu.assert_not_called()
        self.assertEqual(tasks.state_result(self.store, self.job, identity)["status"], "ready")
        return identity, folder

    def test_start_is_read_only_and_context_bound_to_selected_scope(self):
        before = self.store.job(self.job["id"])
        identity, folder = self.start()
        self.assertEqual(self.store.job(self.job["id"]), before)
        self.executor.submit.assert_called_once()
        context = json.loads((folder / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(context["part_ids"], self.ids)
        result = tasks.state_result(self.store, self.job, identity)
        self.assertFalse(result["published"])
        self.assertNotIn(str(self.store.root), json.dumps(result))

    def test_unsupported_or_stale_scope_is_refused_before_queue(self):
        with self.assertRaises(ValueError):
            service.start_optimization(
                self.store, self.job, PartSurfaceRepairRequest(part_ids=["node_1_primitive_0"]), self.executor
            )
        with self.assertRaisesRegex(ValueError, "已变化"):
            service.start_optimization(
                self.store,
                {**self.job, "current_asset_version": "d" * 32},
                PartSurfaceRepairRequest(part_ids=self.ids),
                self.executor,
            )
        self.executor.submit.assert_not_called()

    def test_source_guided_auto_does_not_claim_hunyuan_inference(self):
        identity, folder = self.run_ready()
        manifest = json.loads((folder / "preview/manifest.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["generation_model"])
        self.assertEqual(manifest["generation_mode"], "photo_guided_optimization")
        result = tasks.state_result(self.store, self.job, identity)
        self.assertIn("association_url", result)
        self.assertIn("comparison_url", result)

    def test_uncertain_association_never_runs_reconstruction_or_publishes(self):
        self.route = "needs_input"
        identity, folder = self.start()
        calls = []

        def worker(*args, **kwargs):
            calls.append(args[1])
            return self.worker(*args, **kwargs)

        with (
            patch.object(service, "copy_reference_cache", return_value={"cached": True}),
            patch.object(service, "run_command", side_effect=worker),
        ):
            service.run_optimization(self.store, self.job["id"], identity)
        self.assertEqual(len(calls), 1)
        self.assertEqual(tasks.state_result(self.store, self.job, identity)["status"], "needs_input")
        self.assertFalse((folder / "preview").exists())
        self.assertNotIn("current_asset_version", self.store.job(self.job["id"]))

    def test_failed_photo_checks_cannot_be_overridden_by_direct_save(self):
        identity, folder = self.run_ready(False)
        request = AssetEditRequest(operation="replace_part", part_ids=self.ids, regeneration_preview_id=identity)
        with self.assertRaisesRegex(ValueError, "自动检查未允许"):
            tasks.verified_regeneration(self.store, self.job, request, self.source)
        self.assertNotIn("current_asset_version", self.store.job(self.job["id"]))

    def test_comparison_evidence_tampering_refuses_same_model_save(self):
        identity, folder = self.run_ready()
        request = AssetEditRequest(operation="replace_part", part_ids=self.ids, regeneration_preview_id=identity)
        (folder / "comparison.png").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "对照记录已变化"):
            tasks.verified_regeneration(self.store, self.job, request, self.source)

    def test_adoption_reuses_exact_preview_and_keeps_unreviewed_status(self):
        identity, folder = self.run_ready()
        request = AssetEditRequest(operation="replace_part", part_ids=self.ids, regeneration_preview_id=identity)
        with (
            patch("services.api.asset_editor.validate_glb", return_value={}),
            patch("services.api.asset_editor.subprocess.run") as worker,
        ):
            result = edit_asset(self.store, self.job["id"], request)
        worker.assert_not_called()
        self.assertEqual(result["editor_review_status"], "unreviewed")
        self.assertEqual(
            (self.folder / "assets" / result["version"] / "model.glb").read_bytes(),
            (folder / "preview/model.glb").read_bytes(),
        )

    def test_modified_context_and_cancel_before_launch_do_not_start_worker(self):
        identity, folder = self.start()
        (folder / "context.json").write_text("{}")
        with patch.object(service, "run_command") as worker:
            service.run_optimization(self.store, self.job["id"], identity)
        worker.assert_not_called()
        self.assertIn("请求已变化", tasks.state_result(self.store, self.job, identity)["error"])
        identity, folder = self.start()
        tasks.cancel_task(self.store, self.job, identity)
        with (
            patch.object(service, "copy_reference_cache", return_value={"cached": True}),
            patch("services.api.part_regeneration.subprocess.Popen") as process,
        ):
            service.run_optimization(self.store, self.job["id"], identity)
        process.assert_not_called()
        self.assertEqual(tasks.state_result(self.store, self.job, identity)["status"], "cancelled")

    def test_photo_or_segmentation_drift_rejects_already_ready_preview(self):
        for evidence in ("photo", "segmentation"):
            identity, folder = self.run_ready()
            request = AssetEditRequest(operation="replace_part", part_ids=self.ids, regeneration_preview_id=identity)
            path = (
                self.store.root / "images" / ("b" * 32) / "normalized.png"
                if evidence == "photo"
                else self.folder / "segmented.png"
            )
            previous = path.read_bytes() if path.exists() else None
            Image.new("RGBA", (128, 128), "red").save(path)
            with self.assertRaisesRegex(ValueError, "已变化"):
                tasks.verified_regeneration(self.store, self.job, request, self.source)
            if previous is None:
                path.unlink()
            else:
                path.write_bytes(previous)
        self.assertNotIn("current_asset_version", self.store.job(self.job["id"]))

    def test_cancel_during_gpu_wait_never_launches_image_worker(self):
        identity, folder = self.start()

        def cancel_wait(_):
            (folder / "cancel_requested").touch()

        with (
            patch.object(service, "copy_reference_cache", return_value=None),
            patch.object(service, "gpu_wait", side_effect=cancel_wait),
            patch.object(service, "GPU_LOCK") as lock,
            patch.object(service, "run_command") as worker,
        ):
            service.run_optimization(self.store, self.job["id"], identity)
        worker.assert_not_called()
        lock.release.assert_called_once()
        self.assertEqual(tasks.state_result(self.store, self.job, identity)["status"], "cancelled")

    def test_raw_generation_cache_requires_exact_input_worker_and_file_hashes(self):
        _, folder = self.start()
        generated = folder / "generated"
        generated.mkdir()
        shutil.copyfile(self.source, generated / "model.glb")
        image = self.store.root / "images" / ("b" * 32) / "normalized.png"
        shutil.copyfile(image, generated / "foreground.png")
        state = json.loads((folder / "status.json").read_text(encoding="utf-8"))
        state.update(generated_valid=True, reference_sha256="d" * 64)
        tasks.write_json(folder / "status.json", state)
        summary = {
            "model": "Hunyuan3D-2mini",
            "mode": "shape_only",
            "steps": 50,
            "resolution": 384,
            "seed": 42,
            "input_sha256": state["reference_sha256"],
            "worker_revision": tasks.digest(service.ROOT / "services/workers/generate_hunyuan3d.py"),
            "model_sha256": tasks.digest(generated / "model.glb"),
            "foreground_sha256": tasks.digest(generated / "foreground.png"),
        }
        tasks.write_json(generated / "local_summary.json", summary)
        target = self.folder / "cache_target"
        result = service.copy_generation_cache(self.store, self.job, state, target)
        self.assertTrue(result["raw_geometry_only"])
        self.assertEqual((target / "model.glb").read_bytes(), self.source.read_bytes())
        wrong = {**state, "reference_sha256": "e" * 64}
        self.assertIsNone(service.copy_generation_cache(self.store, self.job, wrong, self.folder / "wrong_input"))
        (generated / "model.glb").write_bytes(b"tampered")
        self.assertIsNone(service.copy_generation_cache(self.store, self.job, state, self.folder / "changed_geometry"))

    def test_unexpected_worker_exit_is_terminal_instead_of_waiting_forever(self):
        future = Future()
        self.executor.submit.return_value = future
        identity, folder = self.start()
        future.set_exception(SystemExit("controlled worker exit fixture"))
        result = tasks.state_result(self.store, self.job, identity)
        self.assertEqual(result["status"], "failed")
        self.assertTrue((folder / "unexpected_failure.log").is_file())
        self.assertNotIn("current_asset_version", self.store.job(self.job["id"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
