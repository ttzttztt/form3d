"""Run one furniture photo through the parts_first route of a running workbench and collect the results.

Usage (the workbench must already be running, e.g. on port 8001):

    python scripts/tools/run_parts_first_case.py --image path/to/sofa.jpg --category sofa \
        --name "灰色布艺沙发" --output experiments/local_verification/case_01

Options:
    --target X Y W H      furniture box in normalised image coordinates (default: whole image)
    --no-parametric       let AI generate every part (default: hard parts are parametric)
    --plan-edits FILE     JSON {"remove": [3], "kinds": {"2": "leg"}} applied at plan review. Parts are given
                          by the numbers drawn on parts_overlay.png (part ids also work); without the
                          file the automatic plan is confirmed unchanged
    --stop-at-plan        stop after planning, to look at parts_overlay.png before generating
    --job ID              continue a job that stopped at plan review (with --stop-at-plan) instead of
                          uploading again; --image/--category are then not needed
    --server URL          default http://127.0.0.1:8001

Writes into --output: summary.json (status, stages, timings, VRAM profile/peak, parts, warnings and
the full event log), the part plan and overlay, and model.glb / quality_report.json when generated.
Exit code 0 when the job reached awaiting_review, 2 when it stopped for review/input, 1 otherwise.
Only talks to the local workbench; never uploads anywhere else.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

FINAL = {"awaiting_review", "completed", "rejected", "failed", "cancelled", "awaiting_input"}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--image")
    parser.add_argument("--category", choices=["sofa", "chair", "table", "cabinet"])
    parser.add_argument("--job")
    parser.add_argument("--name", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--target", nargs=4, type=float, metavar=("X", "Y", "W", "H"))
    parser.add_argument("--no-parametric", action="store_true")
    parser.add_argument("--plan-edits")
    parser.add_argument("--stop-at-plan", action="store_true")
    parser.add_argument("--server", default="http://127.0.0.1:8001")
    parser.add_argument("--timeout-minutes", type=float, default=90)
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(base_url=args.server, timeout=60)
    started = time.monotonic()
    timeline = []

    def mark(label):
        timeline.append({"step": label, "seconds": round(time.monotonic() - started, 1)})
        print(f"[{timeline[-1]['seconds']:>7.1f}s] {label}", flush=True)

    config = client.get("/api/config").json()["providers"].get("parts_first", {})
    if not config.get("available"):
        return finish(output, {"status": "environment_not_ready", "parts_first": config}, timeline, 1)
    if args.job:
        job = client.get(f"/api/jobs/{args.job}").json()
        mark("continue job " + args.job)
        return follow(client, job, args, output, timeline, started, mark)
    if not args.image or not args.category:
        parser.error("--image and --category are required unless --job is given")
    image_path = Path(args.image)
    with image_path.open("rb") as stream:
        response = client.post("/api/images", files={"file": (image_path.name, stream, "image/png")})
    response.raise_for_status()
    image = response.json()
    mark("uploaded")
    body = {
        "image_id": image["id"],
        "name": args.name or image_path.stem,
        "route": "parts_first",
        "object_category": args.category,
        "parts_parametric": not args.no_parametric,
        "parts_plan_review": True,
    }
    if args.target:
        body["target"] = dict(zip(("x", "y", "width", "height"), args.target))
    response = client.post("/api/jobs", json=body)
    if response.status_code != 202:
        return finish(output, {"status": "create_refused", "detail": response.text}, timeline, 1)
    job = response.json()
    mark("job " + job["id"])
    return follow(client, job, args, output, timeline, started, mark)


def resolve_edits(edits, plan):
    """Map overlay numbers (or ids) in an edits file to part ids of this job's plan."""
    by_index = {str(p["index"]): p["id"] for p in plan["parts"] if p.get("index") is not None}
    ids = {p["id"] for p in plan["parts"]}

    def part_id(key):
        key = str(key)
        if key in ids:
            return key
        if key in by_index:
            return by_index[key]
        raise ValueError(f"plan edit refers to unknown part {key!r}; numbers on the overlay are {sorted(by_index)}")

    return {
        "remove": [part_id(k) for k in edits.get("remove", [])],
        "kinds": {part_id(k): v for k, v in edits.get("kinds", {}).items()},
    }


def follow(client, job, args, output, timeline, started, mark):
    deadline = time.monotonic() + args.timeout_minutes * 60
    confirmed = False
    last_stage = None
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["stage"] != last_stage:
            last_stage = job["stage"]
            mark(f"{job['status']} · {job['stage']} · {job['events'][-1]['message'] if job['events'] else ''}")
        if job["status"] == "awaiting_plan_review" and not confirmed:
            save(client, job, "parts_overlay.png", output)
            save(client, job, "parts_plan.json", output)
            if args.stop_at_plan and not args.job:
                return finish(output, summarise(job), timeline, 2)
            edits = json.loads(Path(args.plan_edits).read_text(encoding="utf-8")) if args.plan_edits else {}
            try:
                edits = resolve_edits(edits, job["parts_plan"])
            except ValueError as exc:
                return finish(output, {**summarise(job), "plan_confirm_error": str(exc)}, timeline, 2)
            response = client.post(f"/api/jobs/{job['id']}/parts-plan/confirm", json=edits)
            if response.status_code != 200:
                summary = summarise(job)
                summary["plan_confirm_error"] = response.json().get("detail", response.text)
                return finish(output, summary, timeline, 2)
            confirmed = True
            mark("plan confirmed" + (" with edits" if edits["remove"] or edits["kinds"] else ""))
            continue
        if job["status"] in FINAL:
            break
        time.sleep(2)
    else:
        return finish(output, {**summarise(job), "status": "timeout_waiting"}, timeline, 1)

    for name in (
        "parts_overlay.png",
        "parts_plan.json",
        "parts_fit.png",
        "parts_audit.json",
        "assembly_plan.json",
        "assembly_evidence.json",
    ):
        save(client, job, name, output)
    if job.get("model_url"):
        save(client, job, "model.glb", output)
        save(client, job, "quality_report.json", output)
    code = 0 if job["status"] == "awaiting_review" else 2 if job["status"] == "awaiting_input" else 1
    return finish(output, summarise(job), timeline, code)


def save(client, job, name, output):
    response = client.get(f"/api/jobs/{job['id']}/files/{name}")
    if response.status_code == 200:
        (output / name).write_bytes(response.content)


def summarise(job):
    report = job.get("report") or {}
    evidence = report.get("evidence") or {}
    fit = evidence.get("parametric_fit") or {}
    stages = [event["stage"] for event in job.get("events", [])]
    return {
        "job_id": job["id"],
        "status": job["status"],
        "error": job.get("error"),
        "stages": stages,
        # Which route the job took: AI generation (PartCrafter) or parametric parts only; None before either.
        "path": (
            "ai_generation"
            if {"parts_audit", "parts_generated", "parts_vram_retry"} & set(stages)
            else "parametric_only"
            if "parts_parametric" in stages
            else None
        ),
        "parts_plan": job.get("parts_plan"),
        "parts_generation": job.get("parts_generation"),
        "vram_retries": [e["message"] for e in job.get("events", []) if e["stage"] == "parts_vram_retry"],
        "parametric_fit": {
            "mode": fit.get("mode"),
            "parts": [
                {
                    k: row.get(k)
                    for k in ("kind", "replaced", "shape", "mean_deviation", "p95_deviation", "volume_ratio", "reason")
                }
                for row in fit.get("parts", [])
            ],
        }
        if fit
        else None,
        "metrics": job.get("metrics"),
        "warnings": report.get("warnings"),
        "events": job.get("events", []),
    }


def finish(output, summary, timeline, code):
    summary["timeline"] = timeline
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary.get(k) for k in ("status", "error", "path")}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
