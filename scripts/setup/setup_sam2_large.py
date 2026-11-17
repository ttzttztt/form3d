"""Download the public SAM 2.1 Hiera Large checkpoint (Apache-2.0) for the parts planner.

The expected size and SHA-256 come from the model repository's file listing; the download
resumes after interruptions and is kept only when both match. Uses the SAM 2 source already
installed by setup_sam2.py (configs/sam2.1/sam2.1_hiera_l.yaml). Never uploads anything.

    python scripts/setup/setup_sam2_large.py   (HF_ENDPOINT overrides https://hf-mirror.com)
"""

import hashlib
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".models" / "sam2.1-hiera-large"
REPO = "facebook/sam2.1-hiera-large"
FILE = "sam2.1_hiera_large.pt"
HF = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
HEADERS = {"User-Agent": "img3d-sam2-setup"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def open_url(url, headers, hops=5):
    """urlopen that also follows 307/308 (not followed by urllib before Python 3.11)."""
    import urllib.error
    from urllib.parse import urljoin

    for _ in range(hops):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code not in (307, 308) or not exc.headers.get("Location"):
                raise
            url = urljoin(url, exc.headers["Location"])
    raise ValueError("Too many redirects: " + url)


def expected():
    with open_url(f"{HF}/api/models/{REPO}/tree/main", HEADERS) as response:
        listing = json.load(response)
    row = next(item for item in listing if item["path"] == FILE)
    return row["lfs"]["oid"], row["lfs"]["size"]


def main():
    MODEL.mkdir(parents=True, exist_ok=True)
    target = MODEL / FILE
    sha, size = expected()
    if target.is_file() and target.stat().st_size == size and sha256(target) == sha:
        print("SAM 2.1 Large already verified")
        return
    partial = target.with_suffix(".downloading")
    done = partial.stat().st_size if partial.exists() else 0
    # SAM2_LARGE_URL may point at Meta's original release
    # (https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt);
    # the size and SHA-256 are still checked against the model repository listing.
    url = os.getenv("SAM2_LARGE_URL") or f"{HF}/{REPO}/resolve/main/{FILE}?download=true"
    failures = 0
    while done < size:
        try:
            with open_url(url, {**HEADERS, "Range": f"bytes={done}-"}) as response, partial.open("ab") as out:
                for block in iter(lambda: response.read(4 * 1024 * 1024), b""):
                    out.write(block)
                    done += len(block)
                    print(f"\r{done / size:6.1%}", end="", flush=True)
        except (OSError, ValueError) as exc:  # timeouts and dropped connections: resume from `done`
            failures += 1
            if failures > 20:
                raise
            print(f"\nretry {failures} after {type(exc).__name__}", flush=True)
            done = partial.stat().st_size
    print()
    if partial.stat().st_size != size or sha256(partial) != sha:
        partial.unlink()
        raise ValueError("SAM 2.1 Large checkpoint failed verification; deleted, run again")
    partial.replace(target)
    (MODEL / "provenance.json").write_text(
        json.dumps({"repo": REPO, "file": FILE, "sha256": sha, "bytes": size, "license": "apache-2.0"}, indent=2),
        encoding="utf-8",
    )
    print("SAM 2.1 Large verified:", sha)


if __name__ == "__main__":
    main()
