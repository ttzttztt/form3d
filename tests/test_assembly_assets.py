"""Synthetic import contracts; not generated-furniture or appearance acceptance."""

import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from services.api.assembly_assets import attach_assembly_candidate
from services.api.assembly_models import AssemblyPlan
from services.api.assembly_inputs import file_hash
from services.api.geometry import GLBBuilder
from services.api.store import Store


class AssemblyImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "candidate"
        self.source.mkdir()
        self.store = Store(self.root / "store")
        self.image_id = "b" * 32
        self.job_id = "a" * 32
        self.part_id = "part_" + "c" * 32
        image = self.store.root / "input.png"
        image.write_bytes(b"synthetic image binding")
        image_sha = file_hash(image)
        self.store.put_image({"id": self.image_id, "normalized_path": "input.png"})
        self.directory = self.store.root / "jobs" / self.job_id
        self.directory.mkdir(parents=True)
        self.store.create_job(
            {
                "id": self.job_id,
                "name": "synthetic candidate",
                "status": "awaiting_assistant",
                "events": [],
                "request": {"route": "assistant", "image_id": self.image_id},
            },
            "",
            "",
        )
        builder = GLBBuilder("#aaaaaa")
        builder.box("synthetic panel", (0, 0, 0), (1, 0.1, 1))
        primitive_id = self.part_id + "__geometry"
        builder.document["nodes"][0]["extras"] = {"form_part_ids": {"0": primitive_id}}
        builder.document["meshes"][0]["primitives"][0]["extras"] = {
            "form_logical_group_id": self.part_id,
            "form_semantic_kind": "tabletop",
        }
        builder.save(self.source / "model.glb")
        model_sha = file_hash(self.source / "model.glb")
        self.plan = {
            "id": "d" * 32,
            "primary_image_id": self.image_id,
            "primary_image_sha256": image_sha,
            "furniture_target": {"x": 0, "y": 0, "width": 1, "height": 1},
            "object_category": "table",
            "planning_basis": "image_first",
            "status": "ready_for_review",
            "parts": [
                {
                    "id": self.part_id,
                    "name": "合成桌面",
                    "kind": "tabletop",
                    "identity_status": "geometry_hypothesis",
                    "geometry_method": "native_joint",
                    "status": "ready",
                    "primitive_ids": [primitive_id],
                    "model_sha256": model_sha,
                }
            ],
        }
        self.evidence = {
            "status": "candidate_ready_for_review",
            "model_sha256": model_sha,
            "part_ids": [self.part_id],
            "source_engine": "synthetic_test_only",
        }
        self.save()

    def save(self):
        AssemblyPlan.model_validate(self.plan)
        (self.source / "plan.json").write_text(json.dumps(self.plan), encoding="utf-8")
        (self.source / "assembly.json").write_text(json.dumps(self.evidence), encoding="utf-8")

    def test_real_glb_import_is_normalized_traceable_and_unaccepted(self):
        result = attach_assembly_candidate(self.store, self.job_id, self.source)
        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(result["review_status"], "pending")
        report = result["report"]
        self.assertEqual(report["units"], "normalized")
        self.assertFalse(report["ar_true_scale_ready"])
        self.assertEqual(report["evidence"]["source_engine"], "synthetic_test_only")
        self.assertFalse(report["modeling_notes"]["complete_assembly_accepted"])
        self.assertEqual(report["checks"]["appearance"], "needs_review")
        self.assertEqual(file_hash(self.directory / "model.glb"), self.evidence["model_sha256"])
        self.assertIsNone(result["preview_url"])

    def test_changed_image_model_part_hash_or_identity_rejected_without_publication(self):
        mutations = {
            "image": lambda: self.plan.update(primary_image_sha256="e" * 64),
            "model": lambda: self.evidence.update(model_sha256="e" * 64),
            "part_hash": lambda: self.plan["parts"][0].update(model_sha256="e" * 64),
            "identity": lambda: self.plan["parts"][0].update(primitive_ids=["wrong_id"]),
            "owner": lambda: self.plan["parts"][0].update(id="part_" + "e" * 32),
            "kind": lambda: self.plan["parts"][0].update(kind="leg"),
            "manifest": lambda: self.evidence.update(part_ids=[]),
            "not_ready": lambda: self.evidence.update(status="needs_evidence"),
        }
        original_plan = json.dumps(self.plan)
        original_evidence = json.dumps(self.evidence)
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.plan = json.loads(original_plan)
                self.evidence = json.loads(original_evidence)
                mutate()
                self.save()
                with self.assertRaises(ValueError):
                    attach_assembly_candidate(self.store, self.job_id, self.source)
                self.assertEqual(self.store.job(self.job_id)["status"], "awaiting_assistant")
                self.assertFalse((self.directory / "model.glb").exists())

    def test_original_model_and_finished_job_cannot_be_replaced(self):
        original = self.directory / "model.glb"
        original.write_bytes(b"preserve original")
        with self.assertRaises(ValueError):
            attach_assembly_candidate(self.store, self.job_id, self.source)
        self.assertEqual(original.read_bytes(), b"preserve original")
        original.unlink()
        self.store.update(self.job_id, lambda j: j.update(status="awaiting_review"))
        with self.assertRaises(ValueError):
            attach_assembly_candidate(self.store, self.job_id, self.source)
        self.assertFalse(original.exists())

    def test_missing_full_validator_never_publishes(self):
        with patch("services.api.assembly_assets.validate_glb", return_value={"status": "not_run"}):
            with self.assertRaises(ValueError):
                attach_assembly_candidate(self.store, self.job_id, self.source)
        self.assertFalse((self.directory / "model.glb").exists())

    def test_original_created_during_validation_is_not_overwritten(self):
        def competing_import(_):
            (self.directory / "model.glb").write_bytes(b"concurrent original")
            return {"status": "pass"}

        with patch("services.api.assembly_assets.validate_glb", side_effect=competing_import):
            with self.assertRaises(ValueError):
                attach_assembly_candidate(self.store, self.job_id, self.source)
        self.assertEqual((self.directory / "model.glb").read_bytes(), b"concurrent original")
        self.assertEqual(self.store.job(self.job_id)["status"], "awaiting_assistant")
        self.assertEqual(list(self.directory.glob("*.importing")), [])

    def test_missing_explicit_preview_never_publishes_a_broken_url(self):
        with self.assertRaises(ValueError):
            attach_assembly_candidate(self.store, self.job_id, self.source, self.root / "missing.png")
        self.assertFalse((self.directory / "model.glb").exists())


if __name__ == "__main__":
    unittest.main()
