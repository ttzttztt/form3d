"""Orchestration contracts for the one-click parts_first route.

Workers are replaced by fakes that write the files each real worker writes, so these tests
cover sequencing, gates, cancellation and publication, not model quality.
"""

import io
import json
import os
import sys
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
from services.api.assembly_planning import plan_from_image_observations
from services.api.geometry import GLBBuilder, validate_glb

READY = {"available": True, "checks": {}, "missing": []}


def picture():
    output = io.BytesIO()
    image = Image.new("RGBA", (160, 120), "white")
    ImageDraw.Draw(image).rectangle((35, 20, 125, 40), fill="#ad947a")
    image.save(output, "PNG")
    return output.getvalue()


ORIGINAL_RUN = parts_first._Runner.run


class FakeWorkers:
    """Writes the artifacts of each stage; behaviour is switched per test.

    The plan stage builds a real AssemblyPlan with the planner's own builder and real masks;
    the export stage assembles one box per planned part, so plan edits flow through to the GLB.
    The CPU-only parametric worker is run for real (with this interpreter).
    """

    def __init__(
        self,
        store,
        kinds=("tabletop", "leg"),
        category="table",
        geometry_gate="passed",
        linked=True,
        block=None,
        oom_profiles=(),
        decode_failures=0,
    ):
        self.store, self.kinds, self.category = store, kinds, category
        self.geometry_gate, self.linked, self.block = geometry_gate, linked, block
        self.oom_profiles = list(oom_profiles)  # profiles that run out of memory, in call order
        self.decode_failures = decode_failures
        self.calls, self.commands = [], []
        self.stopped = threading.Event()

    def __call__(self, runner, name, command, progress_path=None, stage_messages=None):
        blocking = self.block == name  # decided before the call is visible to the test
        if blocking:
            self.stopped.clear()
        self.calls.append(name)
        root = runner.folder
        command = [str(part) for part in command]
        self.commands.append(command)
        if name == "parametric":
            return ORIGINAL_RUN(runner, name, [sys.executable] + command[1:], progress_path, stage_messages)
        if name == "generate":
            (root / "raw").mkdir()  # like PartCrafter, the output folder exists from the start
        if blocking:
            try:
                while True:  # a long-running worker; only cancellation ends it
                    runner.check_cancelled()
                    time.sleep(0.01)
            finally:
                self.stopped.set()
        if name == "plan":
            self.write_plan(root / "plan", command)
        elif name == "generate" and self.decode_failures:
            self.decode_failures -= 1
            facts = {"status": "failed", "error": "Some native part slots failed to decode", "vram_profile": {"name": "low"}}
            (root / "raw" / "generation.json").write_text(json.dumps(facts), encoding="utf-8")
            raise ValueError("部件优先流程「generate」阶段失败：Some native part slots failed to decode")
        elif name == "generate" and self.oom_profiles:
            requested = command[command.index("--vram-profile") + 1]
            used = self.oom_profiles.pop(0) if requested == "auto" else requested
            facts = {"status": "failed", "out_of_memory": True, "vram_profile": {"name": used}}
            (root / "raw" / "generation.json").write_text(json.dumps(facts), encoding="utf-8")
            raise ValueError("部件优先流程「generate」阶段失败：CUDA out of memory")
        elif name == "generate":
            facts = {"status": "raw_candidates_ready", "vram_profile": {"name": "low"}, "tokens_per_part": 512}
            facts["gpu_peak_reserved_bytes"] = 5 * 1024**3
            (root / "raw" / "generation.json").write_text(json.dumps(facts), encoding="utf-8")
        elif name == "audit":
            (root / "raw" / "audit").mkdir()
            slots = len(self.physical(root / "plan"))
            status = "photo_linked_hypothesis" if self.linked else "ambiguous"
            audit = {
                "geometry_gate": self.geometry_gate,
                "slots": [{"slot": i, "geometry_gate": self.geometry_gate} for i in range(slots)],
                "photo_evidence": {"matches": [{"raw_slot": i, "link_status": status} for i in range(slots)]},
            }
            (root / "raw" / "audit" / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
        elif name == "export":
            self.write_assembly(root / "plan", root / "assembly")

    @staticmethod
    def physical(plan_folder):
        plan = json.loads((plan_folder / "plan.json").read_text(encoding="utf-8"))
        return [p for p in plan["parts"] if p.get("geometry_role", "physical_part") == "physical_part"]

    def write_plan(self, folder, command):
        import numpy as np

        folder.mkdir()
        self.image_id = command[command.index("--image-id") + 1]
        self.source = Path(command[command.index("--input") + 1])
        size, rows, whole = (120, 160), [], np.zeros((120, 160), bool)
        for number, kind in enumerate(self.kinds):
            mask = np.zeros(size, bool)
            if kind == "tabletop":
                mask[20:32, 20:140] = True
            else:  # legs and other parts: distinct narrow columns
                left = 24 + 18 * number
                mask[32 : 110 - 4 * (number % 2), left : left + 6] = True
            whole |= mask
            path = folder / f"mask_{number}.png"
            Image.fromarray(mask.astype("uint8") * 255).save(path)
            rows.append(
                {
                    "kind": kind,
                    "mask_file": path.name,
                    "mask_sha256": file_hash(path),
                    "target": {"x": 0.1 + 0.05 * number, "y": 0.1, "width": 0.05, "height": 0.2},
                    "visibility": "partial",
                    "evidence_kind": "original_photo",
                }
            )
        Image.fromarray(whole.astype("uint8") * 255).save(folder / "whole_mask.png")
        plan = plan_from_image_observations(
            self.image_id, file_hash(self.source), self.category, {"x": 0, "y": 0, "width": 1, "height": 1}, rows
        )
        (folder / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
        (folder / "observations.json").write_text(json.dumps({"parts": rows}), encoding="utf-8")
        Image.new("RGB", (8, 8), "white").save(folder / "observations.png")

    def write_assembly(self, plan_folder, folder):
        folder.mkdir()
        plan = json.loads((plan_folder / "plan.json").read_text(encoding="utf-8"))
        builder = GLBBuilder("#aaaaaa")
        index = 0
        for part in plan["parts"]:
            if part.get("geometry_role") == "structural_group":
                part["status"] = "ready"
                continue
            builder.box(part["name"], (index * 2.0, 0, 0), (0.08, 0.7, 0.08) if part["kind"] == "leg" else (1, 0.1, 1))
            primitive = part["id"] + "__geometry"
            builder.document["nodes"][index]["extras"] = {"form_part_ids": {"0": primitive}}
            builder.document["meshes"][index]["primitives"][0]["extras"] = {
                "form_logical_group_id": part["id"],
                "form_semantic_kind": part["kind"],
            }
            part.update(status="ready", primitive_ids=[primitive])
            index += 1
        builder.save(folder / "model.glb")
        model_sha = file_hash(folder / "model.glb")
        for part in plan["parts"]:
            if part.get("geometry_role") != "structural_group":
                part["model_sha256"] = model_sha
        plan["status"] = "ready_for_review"
        AssemblyPlan.model_validate(plan)
        (folder / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        evidence = {
            "status": "candidate_ready_for_review",
            "model_sha256": model_sha,
            "part_ids": [p["id"] for p in plan["parts"] if p.get("geometry_role") != "structural_group"],
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
        job = self.wait(self.start(workers, parts_plan_review=False, parts_parametric=False))
        self.assertEqual(job["status"], "awaiting_review", job.get("error"))
        self.assertEqual(workers.calls, ["plan", "generate", "audit", "export"])
        self.assertEqual(job["report"]["route"], "parts_first")
        self.assertFalse(job["report"]["modeling_notes"]["complete_assembly_accepted"])
        stages = [event["stage"] for event in job["events"]]
        self.assertIn("parts_planned", stages)
        self.assertEqual(self.client.get(job["model_url"]).status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/files/parts_overlay.png").status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/files/assembly_plan.json").status_code, 200)
        asset = self.client.get(f"/api/jobs/{job['id']}/asset").json()
        planned = {p["id"] for p in job["parts_plan"]["parts"]}
        self.assertEqual({p.get("logical_group_id") for p in asset["parts"]}, planned)

    def test_plan_review_pauses_then_edits_flow_into_the_assembly(self):
        workers = FakeWorkers(self.store, kinds=("tabletop", "leg", "leg"))
        job = self.wait(self.start(workers, parts_parametric=False))
        self.assertEqual(job["status"], "awaiting_plan_review", job.get("error"))
        self.assertEqual(workers.calls, ["plan"])
        plan = job["parts_plan"]
        self.assertEqual(plan["count"], 3)
        self.assertEqual([p["index"] for p in plan["parts"]], [1, 2, 3])
        self.assertIn("panel", plan["kind_options"])
        by_index = {p["index"]: p["id"] for p in plan["parts"]}
        response = self.client.post(
            f"/api/jobs/{job['id']}/parts-plan/confirm",
            json={"remove": [by_index[3]], "kinds": {by_index[2]: "frame"}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        job = self.wait(job, until=("queued", "running"))
        self.assertEqual(job["status"], "awaiting_review", job.get("error"))
        self.assertEqual(workers.calls, ["plan", "generate", "audit", "export"])
        kinds = sorted(p["semantic_kind"] for p in self.client.get(f"/api/jobs/{job['id']}/asset").json()["parts"])
        self.assertEqual(kinds, ["frame", "tabletop"])
        folder = self.store.root / "jobs" / job["id"] / "parts_first" / "plan"
        self.assertTrue((folder / "plan.original.json").is_file())  # the automatic plan is kept
        confirmed = json.loads((folder / "confirmed.json").read_text(encoding="utf-8"))
        self.assertEqual(confirmed["removed"], [by_index[3]])

    def test_invalid_plan_edits_are_refused_and_job_keeps_waiting(self):
        job = self.wait(self.start(FakeWorkers(self.store)))
        ids = [p["id"] for p in job["parts_plan"]["parts"]]
        cases = {
            "unknown part": {"remove": ["part_" + "f" * 32]},
            "kind for another category": {"kinds": {ids[0]: "seat_cushion"}},
            "nothing left": {"remove": ids},
        }
        for name, body in cases.items():
            with self.subTest(name):
                response = self.client.post(f"/api/jobs/{job['id']}/parts-plan/confirm", json=body)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self.client.get("/api/jobs/" + job["id"]).json()["status"], "awaiting_plan_review")

    def test_conflicting_kinds_must_be_resolved_before_generation(self):
        workers = FakeWorkers(self.store, kinds=("tabletop", "unknown"))
        job = self.wait(self.start(workers))
        self.assertEqual(job["status"], "awaiting_plan_review")
        self.assertIn("冲突", job["parts_plan"]["problem"])
        unknown = next(p["id"] for p in job["parts_plan"]["parts"] if p["kind"] == "unknown")
        refused = self.client.post(f"/api/jobs/{job['id']}/parts-plan/confirm", json={})
        self.assertEqual(refused.status_code, 409)
        fixed = self.client.post(f"/api/jobs/{job['id']}/parts-plan/confirm", json={"kinds": {unknown: "leg"}})
        self.assertEqual(fixed.status_code, 200, fixed.text)
        self.assertEqual(self.wait(job)["status"], "awaiting_review")

    def test_plan_missing_the_defining_part_is_not_built(self):
        workers = FakeWorkers(self.store, kinds=("leg", "leg"))
        job = self.wait(self.start(workers))
        self.assertEqual(job["status"], "awaiting_plan_review")
        self.assertIn("桌面", job["parts_plan"]["problem"])
        refused = self.client.post(f"/api/jobs/{job['id']}/parts-plan/confirm", json={})
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(workers.calls, ["plan"])

    def test_unresolved_plan_without_review_stops_before_generation(self):
        workers = FakeWorkers(self.store, kinds=("tabletop", "unknown"))
        job = self.wait(self.start(workers, parts_plan_review=False))
        self.assertEqual(job["status"], "awaiting_input")
        self.assertIn("部件规划未通过", job["error"])
        self.assertEqual(workers.calls, ["plan"])
        self.assertFalse((self.store.root / "jobs" / job["id"] / "model.glb").exists())

    def test_failed_audit_is_not_published(self):
        for kwargs in ({"geometry_gate": "failed"}, {"linked": False}):
            with self.subTest(**kwargs):
                workers = FakeWorkers(self.store, **kwargs)
                job = self.wait(self.start(workers, parts_plan_review=False, parts_parametric=False))
                self.assertEqual(job["status"], "awaiting_input")
                self.assertIn("未通过审计", job["error"])
                self.assertEqual(workers.calls, ["plan", "generate", "audit"])
                self.assertFalse((self.store.root / "jobs" / job["id"] / "model.glb").exists())

    def test_cancel_during_generation_stops_without_publishing(self):
        workers = FakeWorkers(self.store, block="generate")
        job = self.start(workers, parts_plan_review=False, parts_parametric=False)
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

    def test_waiting_plan_can_be_cancelled(self):
        job = self.wait(self.start(FakeWorkers(self.store)))
        self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/cancel").status_code, 200)
        response = self.client.post(f"/api/jobs/{job['id']}/parts-plan/confirm", json={})
        self.assertEqual(response.status_code, 409)

    def test_restart_after_confirmation_resumes_without_planning_again(self):
        workers = FakeWorkers(self.store, block="generate")
        job = self.wait(self.start(workers, parts_parametric=False))
        self.client.post(f"/api/jobs/{job['id']}/parts-plan/confirm", json={})
        for _ in range(500):
            if workers.calls[-1:] == ["generate"]:
                break
            time.sleep(0.01)
        # Simulate a crash mid-generation: a fresh worker run of the same queued job.
        workers.block = None
        self.client.post(f"/api/jobs/{job['id']}/cancel")
        self.assertTrue(workers.stopped.wait(5))  # the interrupted worker has really exited
        self.store.update(job["id"], lambda item: item.update(status="queued"), allow_cancelled=True)
        from services.api.pipeline import run_job

        run_job(self.store, job["id"])
        job = self.client.get("/api/jobs/" + job["id"]).json()
        self.assertEqual(job["status"], "awaiting_review", job.get("error"))
        self.assertEqual(workers.calls, ["plan", "generate", "generate", "audit", "export"])
        superseded = list((self.store.root / "jobs" / job["id"] / "parts_first").glob("raw_superseded_*"))
        self.assertEqual(len(superseded), 1)

    def test_all_hard_parts_are_built_parametrically_without_generation(self):
        workers = FakeWorkers(self.store, kinds=("tabletop", "leg", "leg"))
        job = self.wait(self.start(workers, parts_plan_review=False))
        self.assertEqual(job["status"], "awaiting_review", job.get("error"))
        self.assertEqual(workers.calls, ["plan", "parametric"])  # no GPU stage at all
        self.assertEqual(job["report"]["evidence"]["source_engine"], "parametric_from_masks")
        self.assertTrue(any("深度" in w for w in job["report"]["warnings"]))
        parts = self.client.get(f"/api/jobs/{job['id']}/asset").json()["parts"]
        self.assertEqual(sorted(p["semantic_kind"] for p in parts), ["leg", "leg", "tabletop"])

    def test_hard_parts_without_generator_environment_still_work(self):
        ready = {**READY, "generator_available": False, "missing": ["generator_weights"]}
        with patch("services.api.parts_first.parts_first_status", return_value=ready):
            hard = self.wait(self.start(FakeWorkers(self.store), parts_plan_review=False))
            self.assertEqual(hard["status"], "awaiting_review", hard.get("error"))
            soft = FakeWorkers(self.store, kinds=("seat_cushion", "leg"), category="sofa")
            job = self.wait(self.start(soft, parts_plan_review=False, object_category="sofa"))
        self.assertEqual(job["status"], "failed")
        self.assertIn("seat_cushion", job["error"])
        self.assertEqual(soft.calls, ["plan"])

    def test_mixed_furniture_replaces_only_hard_parts_after_generation(self):
        workers = FakeWorkers(self.store, kinds=("seat_cushion", "leg"), category="sofa")
        job = self.wait(self.start(workers, parts_plan_review=False, object_category="sofa"))
        self.assertEqual(job["status"], "awaiting_review", job.get("error"))
        self.assertEqual(workers.calls, ["plan", "generate", "audit", "export", "parametric"])
        fit = job["report"]["evidence"]["parametric_fit"]
        self.assertEqual([(r["kind"], r["replaced"]) for r in fit["parts"]], [("leg", True)])
        stages = [e["stage"] for e in job["events"]]
        self.assertIn("parts_generated", stages)  # VRAM peak and profile reported

    def test_out_of_memory_retries_with_smaller_profiles(self):
        workers = FakeWorkers(self.store, oom_profiles=["low"])
        job = self.wait(self.start(workers, parts_plan_review=False, parts_parametric=False))
        self.assertEqual(job["status"], "awaiting_review", job.get("error"))
        profiles = [
            c[c.index("--vram-profile") + 1] for c, n in zip(workers.commands, workers.calls) if n == "generate"
        ]
        self.assertEqual(profiles, ["auto", "minimal"])
        self.assertIn("parts_vram_retry", [e["stage"] for e in job["events"]])
        folder = self.store.root / "jobs" / job["id"] / "parts_first"
        self.assertEqual(len(list(folder.glob("raw_oom_low_*"))), 1)  # the failed attempt is kept

    def test_decode_failure_retries_once_with_another_seed(self):
        workers = FakeWorkers(self.store, decode_failures=1)
        job = self.wait(self.start(workers, parts_plan_review=False, parts_parametric=False))
        self.assertEqual(job["status"], "awaiting_review", job.get("error"))
        generate = [c for c, n in zip(workers.commands, workers.calls) if n == "generate"]
        self.assertEqual(len(generate), 2)
        self.assertNotIn("--seed", generate[0])
        self.assertEqual(generate[1][generate[1].index("--seed") + 1], "43")
        self.assertEqual(generate[1][generate[1].index("--vram-profile") + 1], "low")  # same profile
        workers = FakeWorkers(self.store, decode_failures=2)
        job = self.wait(self.start(workers, parts_plan_review=False, parts_parametric=False))
        self.assertEqual(job["status"], "failed")  # only one retry

    def test_out_of_memory_at_smallest_profile_explains_what_to_do(self):
        workers = FakeWorkers(self.store, oom_profiles=["minimal"])
        job = self.wait(self.start(workers, parts_plan_review=False, parts_parametric=False))
        self.assertEqual(job["status"], "failed")
        self.assertIn("显存不足", job["error"])

    def test_detection_queue_is_not_blocked_by_long_jobs(self):
        started = threading.Event()
        release = threading.Event()

        def long_job():
            started.set()
            release.wait(5)

        for _ in range(2):
            self.application.state.executor.submit(long_job)
        started.wait(2)
        done = self.application.state.quick_executor.submit(lambda: "detected")
        try:
            self.assertEqual(done.result(timeout=2), "detected")
        finally:
            release.set()


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
