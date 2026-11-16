"""Lifecycle and immutable adoption tests; inference is mocked explicitly."""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from services.api import part_regeneration as service
from services.api.asset_editor import edit_asset
from services.api.geometry import build_template
from services.api.glb_document import read_glb, write_glb
from services.api.models import (
    AssetEditRequest,
    JobRequest,
    PartReferenceRequest,
    PartRegenerationRequest,
    PartSurfaceRepairRequest,
)
from services.api.store import Store


class PartRegenerationTests(unittest.TestCase):
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
        self.image = self.store.root / "images" / ("b" * 32) / "normalized.png"
        self.image.parent.mkdir(parents=True)
        Image.new("RGBA", (128, 128), (50, 90, 100, 255)).save(self.image)
        self.store.put_image({"id": "b" * 32, "normalized_path": str(self.image.relative_to(self.store.root))})
        self.ids = ["node_0_primitive_0"]
        self.executor = Mock()
        for name, value in [
            ("segmentation_status", {"available": True}),
            ("detector_status", {"weights_ready": True}),
            ("engine_status", {"available": True}),
        ]:
            patched = patch.object(service, name, return_value=value)
            patched.start()
            self.addCleanup(patched.stop)

    def reference(self):
        result = service.start_reference(self.store, self.job, PartReferenceRequest(part_ids=self.ids), self.executor)
        folder = service.folder_for(self.store, self.job, result["id"], True)

        def worker(*args, **kwargs):
            candidate = "c" * 32
            shutil.copyfile(self.image, folder / (candidate + ".png"))
            shutil.copyfile(self.image, folder / (candidate + "_preview.png"))
            service.write_json(
                folder / "references.json",
                {
                    "candidates": [
                        {
                            "id": candidate,
                            "file": candidate + ".png",
                            "preview": candidate + "_preview.png",
                            "label": "参考 1",
                        }
                    ]
                },
            )

        with (
            patch.object(service, "segmentation_python", return_value="mock-python"),
            patch.object(service, "run_command", side_effect=worker),
        ):
            service.run_reference(self.store, self.job["id"], result["id"])
        self.assertEqual(json.loads((folder / "status.json").read_text(encoding="utf-8"))["status"], "ready")
        return result["id"], folder

    def generation(self):
        identity, _ = self.reference()
        body = PartRegenerationRequest(part_ids=self.ids, reference_scan_id=identity, reference_candidate_id="c" * 32)
        result = service.start_regeneration(self.store, self.job, body, self.executor)
        return result["id"], service.folder_for(self.store, self.job, result["id"])

    def fake_worker(self, fail_alignment=False):
        def worker(folder, command, *args, **kwargs):
            if "generate_hunyuan3d.py" in " ".join(command):
                output = Path(command[command.index("--output") + 1])
                output.mkdir()
                shutil.copyfile(self.source, output / "model.glb")
            else:
                if fail_alignment:
                    raise ValueError("对齐试验失败")
                output = Path(command[command.index("--output") + 1])
                output.mkdir()
                for name in ("model.glb", "part.glb", "diagnostic.glb"):
                    shutil.copyfile(self.source, output / name)
                request = json.loads(Path(command[command.index("--request") + 1]).read_text(encoding="utf-8"))
                service.write_json(
                    output / "manifest.json",
                    {
                        "operation": {
                            "operation": "replace_part",
                            "kind": request["kind"],
                            "method": request.get("method", "ai_regeneration"),
                        },
                        "source_sha256": service.digest(self.source),
                        "model_sha256": service.digest(output / "model.glb"),
                    },
                )

        return worker

    def ready(self):
        identity, folder = self.generation()
        with (
            patch.object(service, "local_python", return_value="mock-python"),
            patch.object(service, "run_command", side_effect=self.fake_worker()),
        ):
            service.run_regeneration(self.store, self.job["id"], identity)
        self.assertEqual(json.loads((folder / "status.json").read_text(encoding="utf-8"))["status"], "ready")
        return identity, folder

    def test_strict_protocol_forbids_cross_operation_and_unsaved_selection(self):
        for change in (
            {},
            {"regeneration_preview_id": "../x"},
            {"regeneration_preview_id": "d" * 32, "face_selection": [{"part_id": "x", "faces": [1]}]},
            {"regeneration_preview_id": "d" * 32, "completion_preview_id": "e" * 32},
        ):
            with self.assertRaises(ValueError):
                AssetEditRequest(operation="replace_part", part_ids=self.ids, **change)
        with self.assertRaises(ValueError):
            AssetEditRequest(operation="material", regeneration_preview_id="d" * 32)
        with self.assertRaises(ValueError):
            PartRegenerationRequest(part_ids=self.ids, reference_scan_id="../x", reference_candidate_id="c" * 32)

    def test_read_only_scans_and_generation_never_publish(self):
        before = copy.deepcopy(self.store.job(self.job["id"]))
        identity, _ = self.ready()
        result = service.state_result(self.store, self.job, identity)
        self.assertFalse(result["published"])
        self.assertEqual(self.store.job(self.job["id"]), before)
        self.assertEqual(result["appearance_review"], "unreviewed")
        self.assertNotIn("scope", result)
        self.assertNotIn(str(self.store.root), json.dumps(result))

    def test_adoption_copies_exact_preview_without_regeneration(self):
        identity, folder = self.ready()
        request = AssetEditRequest(operation="replace_part", part_ids=self.ids, regeneration_preview_id=identity)
        expected = (folder / "preview/model.glb").read_bytes()
        with (
            patch("services.api.asset_editor.subprocess.run") as worker,
            patch("services.api.asset_editor.validate_glb", return_value={}),
        ):
            result = edit_asset(self.store, self.job["id"], request)
        worker.assert_not_called()
        self.assertEqual((self.folder / "assets" / result["version"] / "model.glb").read_bytes(), expected)
        self.assertEqual(result["editor_review_status"], "unreviewed")
        self.assertEqual(result["manifest"]["regeneration_preview_id"], identity)

    def test_source_scope_or_version_changes_refuse_adoption(self):
        identity, _ = self.ready()
        request = AssetEditRequest(operation="replace_part", part_ids=self.ids, regeneration_preview_id=identity)
        with self.assertRaisesRegex(ValueError, "已变化"):
            service.verified_regeneration(
                self.store, self.job, request.model_copy(update={"part_ids": ["node_1_primitive_0"]}), self.source
            )
        with self.assertRaisesRegex(ValueError, "已变化"):
            service.verified_regeneration(
                self.store, self.job, request.model_copy(update={"base_version": "e" * 32}), self.source
            )
        self.source.write_bytes(self.source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "已变化"):
            service.verified_regeneration(self.store, self.job, request, self.source)

    def test_reference_model_part_and_diagnostic_tampering_refused(self):
        identity, folder = self.ready()
        request = AssetEditRequest(operation="replace_part", part_ids=self.ids, regeneration_preview_id=identity)
        for relative in (
            "reference.png",
            "preview/model.glb",
            "preview/part.glb",
            "preview/diagnostic.glb",
            "preview/manifest.json",
        ):
            path = folder / relative
            original = path.read_bytes()
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "校验失败"):
                service.verified_regeneration(self.store, self.job, request, self.source)
            path.write_bytes(original)

    def test_reference_manifest_and_candidate_tampering_refused_before_gpu(self):
        identity, folder = self.reference()
        request = PartRegenerationRequest(
            part_ids=self.ids, reference_scan_id=identity, reference_candidate_id="c" * 32
        )
        manifest = (folder / "references.json").read_bytes()
        (folder / "references.json").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "清单已变化"):
            service.start_regeneration(self.store, self.job, request, self.executor)
        (folder / "references.json").write_bytes(manifest)
        (folder / ("c" * 32 + ".png")).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "图片校验失败"):
            service.start_regeneration(self.store, self.job, request, self.executor)

    def test_generated_mesh_download_survives_failed_alignment_and_gpu_released(self):
        identity, folder = self.generation()
        with (
            patch.object(service, "local_python", return_value="mock-python"),
            patch.object(service, "run_command", side_effect=self.fake_worker(fail_alignment=True)),
        ):
            service.run_regeneration(self.store, self.job["id"], identity)
        result = service.state_result(self.store, self.job, identity)
        self.assertEqual(result["status"], "failed")
        self.assertIn("generated.glb", result["generated_url"])
        self.assertNotIn("preview_url", result)
        self.assertTrue(service.GPU_LOCK.acquire(blocking=False))
        service.GPU_LOCK.release()
        self.assertNotIn("current_asset_version", self.store.job(self.job["id"]))

    def test_cancelled_before_launch_does_not_start_child(self):
        identity, folder = self.generation()
        service.cancel_task(self.store, self.job, identity)
        with (
            patch.object(service, "subprocess") as process,
            patch.object(service, "local_python", return_value="mock-python"),
        ):
            service.run_regeneration(self.store, self.job["id"], identity)
        process.Popen.assert_not_called()
        self.assertEqual(service.state_result(self.store, self.job, identity)["status"], "cancelled")
        self.assertTrue(service.GPU_LOCK.acquire(blocking=False))
        service.GPU_LOCK.release()

    def test_source_version_changed_during_generation_keeps_downloadable_result(self):
        identity, folder = self.generation()
        generate = self.fake_worker()

        def worker(*args, **kwargs):
            generate(*args, **kwargs)
            self.store.update(self.job["id"], lambda job: job.update(current_asset_version="f" * 32))

        with (
            patch.object(service, "local_python", return_value="mock-python"),
            patch.object(service, "run_command", side_effect=worker),
        ):
            service.run_regeneration(self.store, self.job["id"], identity)
        result = service.state_result(self.store, self.job, identity)
        self.assertEqual(result["status"], "failed")
        self.assertIn("已变化", result["error"])
        self.assertIn("generated_url", result)

    def test_reference_upload_scope_mismatch_and_old_version_refused(self):
        identity, _ = self.reference()
        for changes in ({"reference_image_id": "f" * 32}, {"kind": "bolster"}, {"part_ids": ["node_1_primitive_0"]}):
            payload = dict(part_ids=self.ids, reference_scan_id=identity, reference_candidate_id="c" * 32)
            payload.update(changes)
            with self.assertRaisesRegex(ValueError, "已变化"):
                service.start_regeneration(self.store, self.job, PartRegenerationRequest(**payload), self.executor)
        with self.assertRaisesRegex(ValueError, "已变化"):
            service.start_reference(
                self.store,
                {**self.job, "current_asset_version": "d" * 32},
                PartReferenceRequest(part_ids=self.ids),
                self.executor,
            )

    def test_unsupported_uv_and_type_refused_before_queue(self):
        doc, binary, extra = read_glb(self.source)
        primitive = doc["meshes"][0]["primitives"][0]
        primitive["attributes"]["TEXCOORD_0"] = primitive["attributes"]["POSITION"]
        write_glb(self.source, doc, binary, extra)
        with self.assertRaisesRegex(ValueError, "贴图"):
            service.start_reference(self.store, self.job, PartReferenceRequest(part_ids=self.ids), self.executor)
        del primitive["attributes"]["TEXCOORD_0"]
        primitive["extras"] = {"form_semantic_kind": "bolster"}
        write_glb(self.source, doc, binary, extra)
        with self.assertRaisesRegex(ValueError, "类型不符"):
            service.start_reference(self.store, self.job, PartReferenceRequest(part_ids=self.ids), self.executor)
        self.executor.submit.assert_not_called()

    def test_executor_failure_is_terminal_and_restart_recovers_pending_only(self):
        self.executor.submit.side_effect = RuntimeError("closed")
        with self.assertRaisesRegex(ValueError, "队列不可用"):
            service.start_reference(self.store, self.job, PartReferenceRequest(part_ids=self.ids), self.executor)
        states = list(self.folder.glob("part_reference_scans/*/status.json"))
        self.assertEqual(json.loads(states[0].read_text(encoding="utf-8"))["status"], "failed")
        self.executor.submit.side_effect = None
        _, ready_folder = self.reference()
        identity, pending = self.generation()
        service.recover_part_regenerations(self.store)
        self.assertEqual(json.loads((pending / "status.json").read_text(encoding="utf-8"))["status"], "failed")
        self.assertEqual(json.loads((ready_folder / "status.json").read_text(encoding="utf-8"))["status"], "ready")

    def test_transparent_reference_keeps_alpha_and_does_not_claim_segmentation(self):
        from services.workers.prepare_part_reference import run
        from types import SimpleNamespace

        path = self.store.root / "transparent.png"
        source = Image.new("RGBA", (64, 64), (30, 60, 90, 0))
        source.paste((20, 30, 40, 200), (10, 10, 40, 40))
        source.save(path)
        output = self.store.root / "reference"
        run(SimpleNamespace(input=path, output=output, kind="pillow", target=[0.0, 0.0, 1.0, 1.0]))
        manifest = json.loads((output / "references.json").read_text(encoding="utf-8"))
        candidate = manifest["candidates"][0]
        self.assertEqual(Image.open(output / candidate["file"]).tobytes(), source.tobytes())
        self.assertEqual(manifest["method"], "provided_alpha_preserved")
        self.assertIsNone(candidate["hidden_regions_completed"])
        self.assertFalse(candidate["input_semantics_verified"])

    def surface_repair(self):
        doc, binary, extra = read_glb(self.source)
        doc["meshes"][0]["primitives"][0].setdefault("extras", {})["form_semantic_kind"] = "seat"
        write_glb(self.source, doc, binary, extra)
        with patch.object(service, "local_python", return_value="mock-python"):
            result = service.start_surface_repair(
                self.store, self.job, PartSurfaceRepairRequest(part_ids=self.ids), self.executor
            )
        return result["id"], service.folder_for(self.store, self.job, result["id"])

    def test_surface_repair_needs_no_gpu_or_reference_image_and_exact_adoption(self):
        identity, folder = self.surface_repair()
        with (
            patch.object(service, "local_python", return_value="mock-python"),
            patch.object(service, "run_command", side_effect=self.fake_worker()),
            patch.object(service, "gpu_wait") as gpu,
        ):
            service.run_surface_repair(self.store, self.job["id"], identity)
        gpu.assert_not_called()
        result = service.state_result(self.store, self.job, identity)
        self.assertEqual(result["status"], "ready")
        self.assertFalse((folder / "reference.png").exists())
        manifest = json.loads((folder / "preview/manifest.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["generation_model"])
        self.assertEqual(manifest["generation_mode"], "source_surface_partition")
        request = AssetEditRequest(operation="replace_part", part_ids=self.ids, regeneration_preview_id=identity)
        self.assertEqual(service.verified_regeneration(self.store, self.job, request, self.source), folder / "preview")
        with patch("services.api.asset_editor.validate_glb", return_value={}):
            result = edit_asset(self.store, self.job["id"], request)
        self.assertEqual(
            (self.folder / "assets" / result["version"] / "model.glb").read_bytes(),
            (folder / "preview/model.glb").read_bytes(),
        )

    def test_surface_repair_request_tampering_refused_and_cancel_does_not_launch(self):
        identity, folder = self.surface_repair()
        payload = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        payload["part_ids"] = ["different"]
        service.write_json(folder / "request.json", payload)
        with patch.object(service, "run_command") as worker:
            service.run_surface_repair(self.store, self.job["id"], identity)
        worker.assert_not_called()
        self.assertIn("请求已变化", service.state_result(self.store, self.job, identity)["error"])
        identity, folder = self.surface_repair()
        service.cancel_task(self.store, self.job, identity)
        with (
            patch.object(service, "local_python", return_value="mock-python"),
            patch.object(service, "subprocess") as process,
        ):
            service.run_surface_repair(self.store, self.job["id"], identity)
        process.Popen.assert_not_called()
        self.assertEqual(service.state_result(self.store, self.job, identity)["status"], "cancelled")

    def test_surface_repair_failure_releases_cpu_lock_and_cannot_publish(self):
        from services.api.completion_preview import RECONSTRUCTION_LOCK

        identity, folder = self.surface_repair()
        with (
            patch.object(service, "local_python", return_value="mock-python"),
            patch.object(service, "run_command", side_effect=ValueError("闭合失败")),
        ):
            service.run_surface_repair(self.store, self.job["id"], identity)
        self.assertEqual(service.state_result(self.store, self.job, identity)["status"], "failed")
        self.assertTrue(RECONSTRUCTION_LOCK.acquire(blocking=False))
        RECONSTRUCTION_LOCK.release()
        self.assertNotIn("current_asset_version", self.store.job(self.job["id"]))

    def test_surface_repair_refuses_pillow_group_before_queue(self):
        doc, binary, extra = read_glb(self.source)
        doc["meshes"][0]["primitives"][0].setdefault("extras", {})["form_semantic_kind"] = "pillow"
        write_glb(self.source, doc, binary, extra)
        with patch.object(service, "local_python", return_value="mock-python"):
            with self.assertRaisesRegex(ValueError, "类型不符"):
                service.start_surface_repair(
                    self.store, self.job, PartSurfaceRepairRequest(part_ids=self.ids), self.executor
                )
        self.executor.submit.assert_not_called()

    def test_small_foreground_is_refused_even_in_large_reference_canvas(self):
        image = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
        image.paste((40, 60, 70, 255), (200, 200, 270, 280))
        path = self.store.root / "tiny.png"
        image.save(path)
        with self.assertRaisesRegex(ValueError, "有效区域不足 96"):
            service.check_reference_pixels(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
