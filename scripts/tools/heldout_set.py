"""Pick a fixed, random held-out set of product photos for generalisation checks.

The set is drawn by keyword from images/ with a fixed seed and written to a JSON file. Photos in it
must never be used to tune thresholds; tune on the fixed development cases instead and report the
held-out numbers as they come.

    python scripts/tools/heldout_set.py --per-category 15 --output experiments/heldout/cases.json
"""

import argparse
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = {
    "cabinet": r"cabinet|dresser|nightstand|bookcase|bookshelf|sideboard|buffet|credenza|chest of drawers|tv console",
    "table": r"coffee table|side table|end table|dining table|desk|console table|bedside table|tea table|vanity table",
}
# Same products as the development cases (bookcase, cherry sideboard, orange mesh cabinet); scoring them
# as held-out would leak the tuning set into the generalisation numbers.
DEVELOPMENT_DUPLICATES = {"0006", "0732", "0831"}
EXCLUDE = r"lamp|handle|hood|mat\b|box|basket|mirror|toy|lego|cardboard|miniature|tray|organizer|chair|set\b"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-category", type=int, default=15)
    parser.add_argument("--seed", type=int, default=20261118)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    names = sorted(
        p.name for p in (ROOT / "images").iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    )
    rng = random.Random(args.seed)
    cases, used = [], set()
    for category, pattern in PATTERNS.items():
        pool = [
            n
            for n in names
            if re.search(pattern, n, re.I)
            and not re.search(EXCLUDE, n, re.I)
            and n not in used
            and n.split("_")[0] not in DEVELOPMENT_DUPLICATES
        ]
        for name in rng.sample(pool, min(args.per_category, len(pool))):
            used.add(name)
            cases.append({"case": f"{category}__{name.split('_')[0]}", "category": category, "image": f"images/{name}"})
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(len(cases), "cases ->", output)


if __name__ == "__main__":
    main()
