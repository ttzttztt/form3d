"""Measure PartCrafter memory/time for each VRAM profile on this GPU, using one confirmed part plan.

    python scripts/tools/calibrate_vram.py --plan .data/jobs/<job_id>/parts_first/plan \
        --output experiments/local_verification/vram_<case>

Runs services/workers/generate_partcrafter.py once per profile (largest first), each in a fresh
process with its own output folder, and writes calibration.json plus a Markdown table. A profile
that runs out of memory is recorded and the next smaller one is tried. Use --dry-run to print the
commands only. Stop other GPU programs (and the workbench) first so the numbers are clean.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ["standard", "reduced", "low", "minimal"]


def default_python():
    path = ROOT / ".venv-parts" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return os.getenv("PARTS_PYTHON") or str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--plan", required=True, help="a parts_first/plan folder containing plan.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--profiles", nargs="+", default=PROFILES, choices=PROFILES)
    parser.add_argument("--python", default=default_python())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan = Path(args.plan)
    output = Path(args.output)
    rows = []
    parts = sum(
        p.get("geometry_role", "physical_part") == "physical_part"
        for p in json.loads((plan / "plan.json").read_text(encoding="utf-8"))["parts"]
    )
    for profile in args.profiles:
        folder = output / profile
        command = [
            args.python,
            "-X",
            "utf8",
            "-u",
            str(ROOT / "services/workers/generate_partcrafter.py"),
            "--input",
            str(plan / "generation_input.png"),
            "--plan",
            str(plan / "plan.json"),
            "--count-source",
            "image_plan",
            "--vram-profile",
            profile,
            "--output",
            str(folder),
        ]
        if args.dry_run:
            print(" ".join(command))
            continue
        if folder.exists():
            print(f"skip {profile}: {folder} exists (keep earlier measurements)")
            continue
        output.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with (output / f"{profile}.log").open("wb") as log:
            code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT)).returncode
        facts = {}
        try:
            facts = json.loads((folder / "generation.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        row = {
            "profile": profile,
            "parts": parts,
            "exit_code": code,
            "status": facts.get("status"),
            "out_of_memory": bool(facts.get("out_of_memory")),
            "tokens_per_part": facts.get("tokens_per_part"),
            "gpu_total_gib": round((facts.get("vram_profile") or {}).get("gpu_total_bytes", 0) / 1024**3, 2),
            "peak_reserved_gib": round(facts.get("gpu_peak_reserved_bytes", 0) / 1024**3, 2),
            "peak_allocated_gib": round(facts.get("gpu_peak_allocated_bytes", 0) / 1024**3, 2),
            "seconds": round(time.monotonic() - started, 1),
            "error": (facts.get("error") or "")[:200] or None,
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    if args.dry_run:
        return 0
    (output / "calibration.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    table = ["| 档位 | 部件数 | 结果 | 显存峰值 (GiB) | 用时 (s) |", "|---|---|---|---|---|"]
    for r in rows:
        result = "显存不足" if r["out_of_memory"] else ("成功" if r["exit_code"] == 0 else "失败")
        table.append(f"| {r['profile']} | {r['parts']} | {result} | {r['peak_reserved_gib']} | {r['seconds']} |")
    (output / "calibration.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    print("\n".join(table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
