import hashlib, json, shutil, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
from services.api.models import AssetEditRequest, SemanticScanRequest, JobRequest
from services.api.geometry import build_template
from services.api.store import Store
from services.api.semantic_parts import start_scan, verified_scan, recover_interrupted_scans, scan_result
from services.api.semantic_validation import validate_semantic_proposal


class SemanticContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
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

    def test_whole_scan_only_and_strict_identifiers(self):
        for args in (
            {"operation": "semantic_parts"},
            {"operation": "semantic_parts", "semantic_scan_id": "../x"},
            {"operation": "semantic_parts", "semantic_scan_id": "c" * 32, "part_ids": ["part"]},
            {"operation": "material", "semantic_scan_id": "c" * 32},
        ):
            with self.assertRaises(ValueError):
                AssetEditRequest(**args)
        self.assertEqual(
            AssetEditRequest(operation="semantic_parts", semantic_scan_id="c" * 32).semantic_scan_id, "c" * 32
        )

    def test_start_is_read_only_and_deduplicates_same_input(self):
        executor = Mock()
        before = self.store.job(self.job["id"])
        with (
            patch("services.api.semantic_parts.semantic_status", return_value={"available": True}),
            patch("services.api.semantic_parts.revision", return_value="fixed"),
        ):
            a = start_scan(self.store, self.job, SemanticScanRequest(), executor)
            b = start_scan(self.store, self.job, SemanticScanRequest(), executor)
        self.assertEqual(a["scan_id"], b["scan_id"])
        self.assertFalse(a["published"])
        executor.submit.assert_called_once()
        self.assertEqual(self.store.job(self.job["id"]), before)

    def test_source_or_result_changes_refuse_save(self):
        identity = "c" * 32
        folder = self.folder / "semantic_scans" / identity
        folder.mkdir(parents=True)
        shutil.copyfile(self.source, folder / "model.glb")
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        (folder / "status.json").write_text(json.dumps({"status": "ready"}))
        (folder / "ready.json").write_text(
            json.dumps({"version": "original", "source_sha256": digest, "model_sha256": digest})
        )
        request = AssetEditRequest(operation="semantic_parts", semantic_scan_id=identity)
        (folder / "manifest.json").write_text(json.dumps({"operation": {"groups": [{"id": "1"}, {"id": "2"}]}}))
        self.assertEqual(verified_scan(self.store, self.job, request, self.source), folder)
        self.source.write_bytes(self.source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "已变化"):
            verified_scan(self.store, self.job, request, self.source)
        self.source.write_bytes((folder / "model.glb").read_bytes())
        (folder / "model.glb").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "校验失败"):
            verified_scan(self.store, self.job, request, self.source)

    def test_pending_scan_cannot_publish(self):
        folder = self.folder / "semantic_scans" / ("c" * 32)
        folder.mkdir(parents=True)
        (folder / "status.json").write_text(json.dumps({"status": "running"}))
        with self.assertRaisesRegex(ValueError, "尚未完成"):
            verified_scan(
                self.store,
                self.job,
                AssetEditRequest(operation="semantic_parts", semantic_scan_id="c" * 32),
                self.source,
            )

    def test_restart_marks_pending_failed_so_user_can_retry(self):
        for i, status in enumerate(("queued", "running", "ready")):
            folder = self.folder / "semantic_scans" / str(i)
            folder.mkdir(parents=True)
            (folder / "status.json").write_text(json.dumps({"status": status}))
        recover_interrupted_scans(self.store)
        states = [
            json.loads(p.read_text(encoding="utf-8"))["status"]
            for p in sorted((self.folder / "semantic_scans").glob("*/status.json"))
        ]
        self.assertEqual(states, ["failed", "failed", "ready"])

    def test_missing_environment_and_old_version_refused_before_queue(self):
        executor = Mock()
        with patch("services.api.semantic_parts.semantic_status", return_value={"available": False}):
            with self.assertRaises(ValueError):
                start_scan(self.store, self.job, SemanticScanRequest(), executor)
        with patch("services.api.semantic_parts.semantic_status", return_value={"available": True}):
            with self.assertRaisesRegex(ValueError, "已变化"):
                start_scan(self.store, {**self.job, "current_asset_version": "d" * 32}, SemanticScanRequest(), executor)
        executor.submit.assert_not_called()

    def test_unknown_input_category_is_not_forced_into_sofa(self):
        with (
            patch("services.api.semantic_parts.semantic_status", return_value={"available": True}),
            patch("services.api.semantic_parts.revision", return_value="fixed"),
        ):
            scan = start_scan(self.store, self.job, SemanticScanRequest(), Mock())
        state = json.loads(
            (self.folder / "semantic_scans" / scan["scan_id"] / "status.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["key"]["category"], "auto")

    def test_whole_chunky_object_cannot_hide_behind_an_unknown_remainder(self):
        invalid = {
            "operation": {
                "groups": [
                    {"kind": "unknown", "area_fraction_final": 0.24},
                    {"kind": "tabletop", "area_fraction_final": 0.76, "pca_eigenvalues": [0.27, 0.24, 0.196]},
                ]
            }
        }
        with self.assertRaisesRegex(ValueError, "未可靠区分"):
            validate_semantic_proposal(invalid)

    def test_thin_or_small_tabletop_candidate_is_not_rejected_by_whole_object_guard(self):
        for group in (
            {"kind": "tabletop", "area_fraction_final": 0.7, "pca_eigenvalues": [0.27, 0.24, 0.001]},
            {"kind": "tabletop", "area_fraction_final": 0.2, "pca_eigenvalues": [0.27, 0.24, 0.196]},
        ):
            validate_semantic_proposal({"operation": {"groups": [group]}})

    def test_old_ready_cache_is_invalidated_by_whole_object_semantic_guard(self):
        identity = "e" * 32
        folder = self.folder / "semantic_scans" / identity
        folder.mkdir(parents=True)
        (folder / "status.json").write_text(
            json.dumps({"scan_id": identity, "status": "ready", "stage": "ready", "key": {"version": "original"}})
        )
        (folder / "manifest.json").write_text(
            json.dumps(
                {
                    "operation": {
                        "groups": [
                            {"kind": "tabletop", "area_fraction_final": 0.76, "pca_eigenvalues": [0.27, 0.24, 0.196]},
                            {"kind": "unknown"},
                        ]
                    }
                }
            )
        )
        result = scan_result(self.store, self.job, identity)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["published"])
        self.assertIn("未可靠区分", result["error"])
        self.assertEqual(json.loads((folder / "status.json").read_text(encoding="utf-8"))["status"], "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
