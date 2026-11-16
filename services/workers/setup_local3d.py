"""Download pinned public TripoSR source/weights for completely local inference.

Downloads are resumable and SHA-256 checked. Images are never uploaded.
This setup script does not install packages or change existing ML environments.
"""

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".tools" / "TripoSR"
MODELS = ROOT / ".models" / "triposr"
SOURCE_REVISION = "107cefdc244c39106fa830359024f6a2f1c78871"
MODEL_REVISION = "5b521936b01fbe1890f6f9baed0254ab6351c04a"
MODEL_SHA256 = "429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee"
MODEL_SIZE = 1677246742
HF = "https://hf-mirror.com"


def read_url(url, headers=None, timeout=35):
    request = urllib.request.Request(url, headers={"User-Agent": "img3d-local-setup", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def retry_read(url, headers=None):
    for attempt in range(4):
        try:
            return read_url(url, headers)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1 + attempt)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def small_file(url, destination, expected_sha=None):
    if destination.is_file() and (not expected_sha or sha256(destination) == expected_sha):
        return
    payload = retry_read(url)
    if expected_sha and hashlib.sha256(payload).hexdigest() != expected_sha:
        raise ValueError("Checksum mismatch: " + destination.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    temporary.write_bytes(payload)
    temporary.replace(destination)
    print("Downloaded " + str(destination.relative_to(ROOT)), flush=True)


def source_files():
    base = "https://api.github.com/repos/VAST-AI-Research/TripoSR/git/"
    listing = json.loads(retry_read(base + "trees/" + SOURCE_REVISION + "?recursive=1"))
    entries = [
        item
        for item in listing["tree"]
        if item["type"] == "blob"
        and (
            item["path"].startswith("tsr/")
            and item["path"].endswith(".py")
            or item["path"] in ("LICENSE", "README.md", "run.py", "requirements.txt", "examples/chair.png")
        )
    ]

    def fetch(item):
        target = SOURCE / item["path"]

        def git_hash(content):
            return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()

        if target.is_file() and git_hash(target.read_bytes()) == item["sha"]:
            return
        blob = json.loads(retry_read(base + "blobs/" + item["sha"]))
        content = base64.b64decode(blob["content"])
        if git_hash(content) != item["sha"]:
            raise ValueError("Source checksum mismatch: " + item["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, entries))
    (SOURCE / "source_revision.json").write_text(
        json.dumps(
            {
                "repository": "https://github.com/VAST-AI-Research/TripoSR",
                "revision": SOURCE_REVISION,
                "license": "MIT",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Pinned TripoSR source ready", flush=True)


def checkpoint():
    target = MODELS / "model.ckpt"
    if target.is_file() and target.stat().st_size == MODEL_SIZE and sha256(target) == MODEL_SHA256:
        print("Cached TripoSR weights verified", flush=True)
        return
    MODELS.mkdir(parents=True, exist_ok=True)
    url = HF + "/stabilityai/TripoSR/resolve/" + MODEL_REVISION + "/model.ckpt?download=true"
    chunk_size = 4 * 1024 * 1024
    count = (MODEL_SIZE + chunk_size - 1) // chunk_size

    def chunk(index):
        start, end = index * chunk_size, min((index + 1) * chunk_size, MODEL_SIZE) - 1
        part = MODELS / ("model.ckpt.part%04d" % index)
        if part.is_file() and part.stat().st_size == end - start + 1:
            return
        for attempt in range(5):
            try:
                request = urllib.request.Request(
                    url + "&part=" + str(index),
                    headers={"Range": "bytes=%d-%d" % (start, end), "User-Agent": "img3d-local-setup"},
                )
                with urllib.request.urlopen(request, timeout=40) as response:
                    if response.headers.get("Content-Range") != "bytes %d-%d/%d" % (start, end, MODEL_SIZE):
                        raise ValueError("Unexpected checkpoint range")
                    payload = response.read(end - start + 2)
                if len(payload) != end - start + 1:
                    raise ValueError("Incomplete checkpoint range")
                part.write_bytes(payload)
                return
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(1 + attempt)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(chunk, index) for index in range(count)]
        for complete, future in enumerate(as_completed(futures), 1):
            future.result()
            if complete % 16 == 0 or complete == count:
                print(
                    "TripoSR weights: %d/%d chunks (%.0f MiB)"
                    % (complete, count, min(complete * chunk_size, MODEL_SIZE) / 1024**2),
                    flush=True,
                )
    temporary = MODELS / "model.ckpt.download"
    with temporary.open("wb") as output:
        for index in range(count):
            with (MODELS / ("model.ckpt.part%04d" % index)).open("rb") as part:
                for payload in iter(lambda: part.read(1024 * 1024), b""):
                    output.write(payload)
    if sha256(temporary) != MODEL_SHA256:
        raise ValueError("TripoSR checkpoint SHA-256 verification failed")
    temporary.replace(target)
    # Only remove this downloader's verified temporary chunks, not user assets.
    for index in range(count):
        (MODELS / ("model.ckpt.part%04d" % index)).unlink()
    print("TripoSR weights SHA-256 verified", flush=True)


def support_files():
    small_file(HF + "/stabilityai/TripoSR/raw/" + MODEL_REVISION + "/config.yaml", MODELS / "config.yaml")
    small_file(HF + "/stabilityai/TripoSR/raw/" + MODEL_REVISION + "/README.md", MODELS / "MODEL_CARD.md")
    # TripoSR contains DINO weights; only the tokenizer architecture config is needed.
    dino = json.loads(retry_read(HF + "/api/models/facebook/dino-vitb16"))
    small_file(HF + "/facebook/dino-vitb16/raw/" + dino["sha"] + "/config.json", MODELS / "dino_config.json")
    background = json.loads(retry_read(HF + "/api/models/BritishWerewolf/U-2-Netp"))
    small_file(
        HF + "/BritishWerewolf/U-2-Netp/resolve/" + background["sha"] + "/onnx/model.onnx?download=true",
        MODELS / "u2netp.onnx",
        "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8",
    )
    (MODELS / "provenance.json").write_text(
        json.dumps(
            {
                "model": "stabilityai/TripoSR",
                "model_revision": MODEL_REVISION,
                "model_sha256": MODEL_SHA256,
                "source_revision": SOURCE_REVISION,
                "dino_config_revision": dino["sha"],
                "background_model": "BritishWerewolf/U-2-Netp",
                "background_revision": background["sha"],
                "license": "MIT",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=3) as setup:
        futures = [setup.submit(source_files), setup.submit(checkpoint), setup.submit(support_files)]
        for future in as_completed(futures):
            future.result()
    print("Local 3D source and weights ready", flush=True)
