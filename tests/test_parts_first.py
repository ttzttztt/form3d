"""Orchestration contracts for the one-click parts_first route.

Workers are replaced by fakes that write the files each real worker writes, so these tests
cover sequencing, gates, cancellation and publication, not model quality.
"""

import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from services.api import parts_first
from services.api.app import create_app
from services.api.assembly_inputs import file_hash
from services.api.assembly_models import AssemblyPlan
from services.api.geometry import GLBBuilder, validate_glb

READY = {"available": True, "checks": {}, "missing": []}
PART = "part_" + "c" * 32


def picture():
    output = io.BytesIO()
    image = Image.new("RGBA", (160, 120), "white")
    ImageDraw.Draw(image).rectangle((35, 20, 125, 40), fill="#ad947a")
    image.save(output, "PNG")
    return output.getvalue()


class FakeWorkers:
    """Writes the artifacts of each stage; behaviour is switched per test."""

    def __init__(self, store, plan_status="planned", geometry_gate="passed", linked=True, block=None):
        self.store, self.plan_status, self.geometry_gate, self.linked, self.block = (
            store,
            plan_status,
            geometry_gate,
            linked,
            block,
        )
        self.calls = []

    def __call__(self, runner, name, command, progress_path=None, stage_messages=None):
        self.calls.append(name)
        root = runner.folder
        if self.block == name:
            while True:  # a long-running worker; only cancellation ends it
                runner.check_cancelled()
                time.sleep(0.01)
        if name == "plan":
            folder = root / "plan"
            folder.mkdir()
            kind = "tabletop" if self.plan_status == "planned" else "unknown"
            plan = {"status": self.plan_status, "parts": [{"id": PART, "name": "桌面 1", "kind": kind}]}
            (folder / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            Image.new("RGB", (8, 8), "white").save(folder / "observations.png")
            self.image_id = command[command.index("--image-id") + 1]
            self.source = Path(command[command.index("--input") + 1])
        elif name == "generate":
            (root / "raw").mkdir()
            (root / "raw" / "progress.json").write_text(
                json.dumps({"sequence": 1, "stage": "sampling", "step": 1, "total": 50}), encoding="utf-8"
            )
        elif name == "audit":
            (root / "raw" / "audit").mkdir()
            status = "photo_linked_hypothesis" if self.linked else "ambiguous"
            audit = {
                "geometry_gate": self.geometry_gate,
                "slots": [{"slot": 0, "geometry_gate": self.geometry_gate}],
                "photo_evidence": {"matches": [{"raw_slot": 0, "link_status": status}]},
            }
            (root / "raw" / "audit" / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
        elif name == "export":
            self.write_assembly(root / "assembly")

    def write_assembly(self, folder):
        folder.mkdir()
        builder = GLBBuilder("#aaaaaa")
        builder.box("synthetic top", (0, 0, 0), (1, 0.1, 1))
        primitive = PART + "__geometry"
        builder.document["nodes"][0]["extras"] = {"form_part_ids": {"0": primitive}}
        builder.document["meshes"][0]["primitives"][0]["extras"] = {
            "form_logical_group_id": PART,
            "form_semantic_kind": "tabletop",
        }
        builder.save(folder / "model.glb")
        model_sha = file_hash(folder / "model.glb")
        plan = {
            "id": "d" * 32,
            "primary_image_id": self.image_id,
            "primary_image_sha256": file_hash(self.source),
            "furniture_target": {"x": 0, "y": 0, "width": 1, "height": 1},
            "object_category": "table",
            "planning_basis": "image_first",
            "status": "ready_for_review",
            "parts": [
                {
                    "id": PART,
                    "name": "桌面 1",
                    "kind": "tabletop",
                    "identity_status": "geometry_hypothesis",
                    "geometry_method": "native_joint",
                    "status": "ready",
                    "primitive_ids": [primitive],
                    "model_sha256": model_sha,
                }
            ],
        }
        AssemblyPlan.model_validate(plan)
        (folder / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        evidence = {
            "status": "candidate_ready_for_review",
            "model_sha256": model_sha,
            "part_ids": [PART],
            "source_engine": "PartCrafter",
        }
        (folder / "assembly.json").write_text(json.dumps(evidence), encoding="utf-8")


class PartsFirstTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        for target in ("services.api.parts_first.parts_first_status", "services.api.app.parts_first_status"):
            patcher = patch(target, return_value=READY)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.application = create_app(self.temporary.name)
        self.client = TestClient(self.application)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store = self.application.state.store

    def start(self, workers, **overrides):
        patcher = patch.object(parts_first._Runner, "run", lambda runner, *a, **k: workers(runner, *a, **k))
        patcher.start()
        self.addCleanup(patcher.stop)
        image = self.client.post("/api/images", files={"file": ("table.png", picture(), "image/png")}).json()
        body = {"image_id": image["id"], "name": "桌", "route": "parts_first", "object_category": "table"}
        body.update(overrides)
        response = self.client.post("/api/jobs", json=body)
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def wait(self, job, until=("queued", "running")):
        for _ in range(500):
            value = self.client.get("/api/jobs/" + job["id"]).json()
            if value["status"] not in until:
                return value
            time.sleep(0.01)
        self.fail("parts_first job did not finish")

    def test_requires_furniture_category(self):
        image = self.client.post("/api/images", files={"file": ("t.png", picture(), "image/png")}).json()
        response = self.client.post("/api/jobs", json={"image_id": image["id"], "route": "parts_first"})
        self.assertEqual(response.status_code, 422)

    def test_unavailable_environment_is_refused_before_queueing(self):
        image = self.client.post("/api/images", files={"file": ("t.png", picture(), "image/png")}).json()
        missing = {"available": False, "checks": {}, "missing": ["generator_weights"]}
        with patch("services.api.app.parts_first_status", return_value=missing):
            response = self.client.post(
                "/api/jobs", json={"image_id": image["id"], "route": "parts_first", "object_category": "table"}
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("generator_weights", response.json()["detail"])

    def test_success_runs_all_stages_and_publishes_reviewable_assembly(self):
        workers = FakeWorkers(self.store)
        job = self.wait(self.start(workers))
        self.assertEqual(job["status"], "awaiting_review", job.get("error"))
        self.assertEqual(workers.calls, ["plan", "generate", "audit", "export"])
        self.assertEqual(job["report"]["route"], "parts_first")
        self.assertFalse(job["report"]["modeling_notes"]["complete_assembly_accepted"])
        stages = [event["stage"] for event in job["events"]]
        self.assertIn("parts_planned", stages)
        model = self.client.get(job["model_url"])
        self.assertEqual(model.status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/files/parts_overlay.png").status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/files/assembly_plan.json").status_code, 200)
        asset = self.client.get(f"/api/jobs/{job['id']}/asset").json()
        self.assertTrue(any(part.get("logical_group_id") == PART for part in asset["parts"]), asset)

    def test_unresolved_plan_stops_before_generation(self):
        workers = FakeWorkers(self.store, plan_status="needs_evidence")
        job = self.wait(self.start(workers))
        self.assertEqual(job["status"], "awaiting_input")
        self.assertIn("部件规划未通过", job["error"])
        self.assertEqual(workers.calls, ["plan"])
        self.assertFalse((self.store.root / "jobs" / job["id"] / "model.glb").exists())

    def test_failed_audit_is_not_published(self):
        for kwargs in ({"geometry_gate": "failed"}, {"linked": False}):
            with self.subTest(**kwargs):
                workers = FakeWorkers(self.store, **kwargs)
                job = self.wait(self.start(workers))
                self.assertEqual(job["status"], "awaiting_input")
                self.assertIn("未通过审计", job["error"])
                self.assertEqual(workers.calls, ["plan", "generate", "audit"])
                self.assertFalse((self.store.root / "jobs" / job["id"] / "model.glb").exists())

    def test_cancel_during_generation_stops_without_publishing(self):
        workers = FakeWorkers(self.store, block="generate")
        job = self.start(workers)
        for _ in range(500):
            if workers.calls[-1:] == ["generate"]:
                break
            time.sleep(0.01)
        self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/cancel").status_code, 200)
        job = self.wait(job, until=("queued", "running", "cancelling"))
        self.assertEqual(job["status"], "cancelled")
        time.sleep(0.1)
        self.assertEqual(workers.calls, ["plan", "generate"])
        self.assertFalse((self.store.root / "jobs" / job["id"] / "model.glb").exists())


class RunnerTests(unittest.TestCase):
    """The runner with real child processes: progress mirroring, failure text and cancellation."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.events = []
        store = type("Store", (), {"event": lambda _, job, stage, message, **k: self.events.append((stage, message))})()
        self.cancelled = threading.Event()

        def check():
            if self.cancelled.is_set():
                raise parts_first.Cancelled()

        self.runner = parts_first._Runner(store, "j", self.folder, check)

    def python(self, code):
        import sys

        return [sys.executable, "-c", code]

    def test_progress_is_mirrored_and_failure_reason_surfaces(self):
        progress = self.folder / "progress.json"
        code = (
            "import json,time,pathlib;p=pathlib.Path(%r)\n"
            "p.write_text(json.dumps({'sequence':1,'stage':'sampling','step':3,'total':50}));time.sleep(0.6)\n"
            "raise ValueError('decoder returned nothing')" % str(progress)
        )
        with self.assertRaisesRegex(ValueError, "decoder returned nothing"):
            self.runner.run("generate", self.python(code), progress, parts_first.PARTCRAFTER_STAGES)
        self.assertIn(("parts_generate", "按部件联合采样 3/50"), self.events)

    def test_cancellation_kills_the_worker(self):
        marker = self.folder / "finished"
        code = "import time,pathlib;time.sleep(5);pathlib.Path(%r).write_text('x')" % str(marker)
        threading.Timer(0.3, self.cancelled.set).start()
        started = time.monotonic()
        with self.assertRaises(parts_first.Cancelled):
            self.runner.run("audit", self.python(code))
        self.assertLess(time.monotonic() - started, 3)
        time.sleep(0.2)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
