"""Fetch pinned official SAM 2.1 Tiny image-prediction source and checkpoint."""

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".tools" / "SAM2"
MODEL = ROOT / ".models" / "sam2.1-hiera-tiny"
SOURCE_REVISION = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
MODEL_REVISION = "de431c4043854a71d8101e17995dfe596bf101a5"
WEIGHT_SIZE = 156008466
WEIGHT_SHA = "7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
HF = "https://hf-mirror.com"


def read(url):
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "img3d-sam2-setup"})
            with urllib.request.urlopen(request, timeout=35) as response:
                return response.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(attempt + 1)


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as file:
        for data in iter(lambda: file.read(4 * 1024 * 1024), b""):
            result.update(data)
    return result.hexdigest()


def source():
    base = "https://api.github.com/repos/facebookresearch/sam2/git/"
    tree = json.loads(read(base + "trees/" + SOURCE_REVISION + "?recursive=1"))
    names = {
        "sam2/__init__.py",
        "sam2/build_sam.py",
        "sam2/sam2_image_predictor.py",
        "sam2/configs/sam2.1/sam2.1_hiera_t.yaml",
        "LICENSE",
        "README.md",
    }
    entries = [
        item
        for item in tree["tree"]
        if item["type"] == "blob"
        and (
            item["path"] in names
            or item["path"].endswith(".py")
            and item["path"].startswith(("sam2/modeling/", "sam2/utils/"))
        )
    ]

    def one(item):
        target = SOURCE / item["path"]

        def git_hash(data):
            return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

        if target.is_file() and git_hash(target.read_bytes()) == item["sha"]:
            return
        blob = json.loads(read(base + "blobs/" + item["sha"]))
        data = base64.b64decode(blob["content"])
        if git_hash(data) != item["sha"]:
            raise ValueError("Source checksum mismatch: " + item["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, entries))
    (SOURCE / "source_revision.json").write_text(
        json.dumps(
            {
                "repository": "facebookresearch/sam2",
                "revision": SOURCE_REVISION,
                "files": len(entries),
                "license": "Apache-2.0",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("SAM 2 image source verified", flush=True)


def weights():
    MODEL.mkdir(parents=True, exist_ok=True)
    target = MODEL / "sam2.1_hiera_tiny.pt"
    if target.is_file() and target.stat().st_size == WEIGHT_SIZE and sha256(target) == WEIGHT_SHA:
        print("Cached SAM 2 weights verified", flush=True)
        return
    url = HF + "/facebook/sam2.1-hiera-tiny/resolve/" + MODEL_REVISION + "/sam2.1_hiera_tiny.pt?download=true"
    chunk_size = 4 * 1024 * 1024
    count = (WEIGHT_SIZE + chunk_size - 1) // chunk_size

    def chunk(index):
        start, end = index * chunk_size, min((index + 1) * chunk_size, WEIGHT_SIZE) - 1
        target_part = MODEL / ("checkpoint.part%03d" % index)
        if target_part.is_file() and target_part.stat().st_size == end - start + 1:
            return
        for attempt in range(5):
            try:
                request = urllib.request.Request(
                    url + "&part=" + str(index),
                    headers={"Range": "bytes=%d-%d" % (start, end), "User-Agent": "img3d-sam2-setup"},
                )
                with urllib.request.urlopen(request, timeout=40) as response:
                    if response.headers.get("Content-Range") != "bytes %d-%d/%d" % (start, end, WEIGHT_SIZE):
                        raise ValueError("Unexpected checkpoint range")
                    payload = response.read(end - start + 2)
                if len(payload) != end - start + 1:
                    raise ValueError("Incomplete range")
                target_part.write_bytes(payload)
                return
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(attempt + 1)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(chunk, index) for index in range(count)]
        for completed, future in enumerate(as_completed(futures), 1):
            future.result()
            if completed % 8 == 0 or completed == count:
                print("SAM 2 weights: %d/%d chunks" % (completed, count), flush=True)
    temporary = MODEL / "sam2.1_hiera_tiny.pt.download"
    with temporary.open("wb") as output:
        for index in range(count):
            output.write((MODEL / ("checkpoint.part%03d" % index)).read_bytes())
    if sha256(temporary) != WEIGHT_SHA:
        raise ValueError("SAM 2 checkpoint SHA-256 mismatch")
    temporary.replace(target)
    for index in range(count):
        (MODEL / ("checkpoint.part%03d" % index)).unlink()
    print("SAM 2 weights SHA-256 verified", flush=True)


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(source), pool.submit(weights)]
        for future in as_completed(futures):
            future.result()
    (MODEL / "provenance.json").write_text(
        json.dumps(
            {
                "model_id": "facebook/sam2.1-hiera-tiny",
                "model_revision": MODEL_REVISION,
                "source_revision": SOURCE_REVISION,
                "sha256": WEIGHT_SHA,
                "weight_bytes": WEIGHT_SIZE,
                "license": "Apache-2.0",
                "cuda_extension_used": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("SAM 2.1 Tiny assets ready", flush=True)
