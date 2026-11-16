"""Pinned official Hunyuan3D-2mini shape-model download, with hash validation."""
import base64
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".tools" / "Hunyuan3D-2"
MODEL = ROOT / ".models" / "hunyuan3d-2mini"
SOURCE_REVISION = "f8db63096c8282cb27354314d896feba5ba6ff8a"
MODEL_REVISION = "f90a0f7df7d5e6f71109cf333f6a95a0ae3194a6"
WEIGHT_PATH = "hunyuan3d-dit-v2-mini/model.fp16.safetensors"
WEIGHT_SIZE = 3819958234
WEIGHT_SHA = "3cc66f3bea33e4062b7dbc875ffe1d70c4888914aec3e91b60f94e9bd01b522b"
HF = "https://hf-mirror.com"


def fetch(url):
    candidates = [url]
    if url.startswith(HF + "/tencent/") and "/raw/" in url:
        candidates = [url + '?quality_setup=20261111',
                      url.replace('/raw/', '/resolve/') + '?download=true&quality_setup=20261111',
                      url.replace('/' + MODEL_REVISION + '/', '/main/') + '?quality_setup=20261111',
                      url.replace(HF, 'https://huggingface.co') + '?quality_setup=20261111']
    for attempt in range(max(4, len(candidates) * 2)):
        try:
            candidate = candidates[attempt % len(candidates)]
            request = urllib.request.Request(candidate, headers={"User-Agent": "img3d-quality-evaluation"})
            with urllib.request.urlopen(request, timeout=40) as response:
                return response.read()
        except Exception:
            if attempt == max(4, len(candidates) * 2) - 1:
                raise
            time.sleep(attempt + 1)


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def download_source():
    base = "https://api.github.com/repos/Tencent-Hunyuan/Hunyuan3D-2/git/"
    tree = json.loads(fetch(base + "trees/" + SOURCE_REVISION + "?recursive=1"))
    entries = [entry for entry in tree["tree"] if entry["type"] == "blob" and
               (entry["path"].startswith("hy3dgen/shapegen/") and entry["path"].endswith(".py")
                or entry["path"].startswith("hy3dgen/") and entry["path"].count("/") == 1
                or entry["path"] in ("LICENSE", "NOTICE", "README.md", "examples/shape_gen_mini.py"))]
    def item(entry):
        target = SOURCE / entry["path"]
        def blob_hash(data):
            return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if target.is_file() and blob_hash(target.read_bytes()) == entry["sha"]:
            return
        blob = json.loads(fetch(base + "blobs/" + entry["sha"]))
        data = base64.b64decode(blob["content"])
        if blob_hash(data) != entry["sha"]:
            raise ValueError("Source checksum mismatch: " + entry["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(item, entries))
    (SOURCE / "source_revision.json").write_text(json.dumps({
        "repository": "https://github.com/Tencent-Hunyuan/Hunyuan3D-2", "revision": SOURCE_REVISION,
        "source_files": len(entries), "license": "Tencent Hunyuan Community License",
    }, indent=2), encoding="utf-8")
    print("Verified official shape-model source", flush=True)


def download_weights():
    target = MODEL / WEIGHT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == WEIGHT_SIZE and digest(target) == WEIGHT_SHA:
        print("Cached Hunyuan weights verified", flush=True)
        return
    url = HF + "/tencent/Hunyuan3D-2mini/resolve/" + MODEL_REVISION + "/" + WEIGHT_PATH + "?download=true"
    chunk_size = 4 * 1024 * 1024
    count = (WEIGHT_SIZE + chunk_size - 1) // chunk_size
    def chunk(index):
        start, end = index * chunk_size, min((index + 1) * chunk_size, WEIGHT_SIZE) - 1
        part = target.with_name(target.name + ".part%04d" % index)
        if part.is_file() and part.stat().st_size == end - start + 1:
            return
        for attempt in range(5):
            try:
                request = urllib.request.Request(url + "&part=" + str(index), headers={
                    "Range": "bytes=%d-%d" % (start, end), "User-Agent": "img3d-quality-evaluation"})
                with urllib.request.urlopen(request, timeout=45) as response:
                    if response.headers.get("Content-Range") != "bytes %d-%d/%d" % (start, end, WEIGHT_SIZE):
                        raise ValueError("Invalid checkpoint range")
                    payload = response.read(end - start + 2)
                if len(payload) != end - start + 1:
                    raise ValueError("Incomplete range")
                part.write_bytes(payload)
                return
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(attempt + 1)
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(chunk, index) for index in range(count)]
        for completed, future in enumerate(as_completed(futures), 1):
            future.result()
            if completed % 32 == 0 or completed == count:
                print("Hunyuan weights: %d/%d chunks (%.0f MiB)" %
                      (completed, count, min(completed * chunk_size, WEIGHT_SIZE) / 1024 ** 2), flush=True)
    temporary = target.with_name(target.name + ".download")
    with temporary.open("wb") as output:
        for index in range(count):
            with target.with_name(target.name + ".part%04d" % index).open("rb") as part:
                for data in iter(lambda: part.read(1024 * 1024), b""):
                    output.write(data)
    if digest(temporary) != WEIGHT_SHA:
        raise ValueError("Hunyuan weights SHA-256 failed")
    temporary.replace(target)
    # Discard only downloader-created chunks after the assembled file is verified.
    for index in range(count):
        target.with_name(target.name + ".part%04d" % index).unlink()
    print("Hunyuan weights SHA-256 verified", flush=True)


def download_configs():
    expected = {'LICENSE':'58e0779d576cb14caed1d443cf4d5785c2497fe1',
                'NOTICE':'0e623667e16ed2034540ca9ace4ebc8b33865baf',
                'README.md':'d7f5946d83c6752340e2c52a16b7fc40bcdca8d8',
                'hunyuan3d-dit-v2-mini/config.yaml':'9b5e721842d1bc751b3a54ee8adc8d59a2630367'}
    for filename in ("LICENSE", "NOTICE", "README.md", "hunyuan3d-dit-v2-mini/config.yaml"):
        destination = MODEL / filename
        if not destination.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = fetch(HF + "/tencent/Hunyuan3D-2mini/raw/" + MODEL_REVISION + "/" + filename)
            git_hash = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            if git_hash != expected[filename]:
                raise ValueError('Model support-file checksum mismatch: '+filename)
            destination.write_bytes(data)
    (MODEL / "provenance.json").write_text(json.dumps({
        "model_id": "tencent/Hunyuan3D-2mini", "variant": "hunyuan3d-dit-v2-mini",
        "model_revision": MODEL_REVISION, "source_revision": SOURCE_REVISION,
        "sha256": WEIGHT_SHA, "weight_bytes": WEIGHT_SIZE,
        "license": "Tencent Hunyuan Community License", "texture_model_downloaded": False,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--configs-only', action='store_true')
    args = parser.parse_args()
    if args.configs_only:
        download_configs()
        print('Hunyuan configs and license files ready', flush=True)
        raise SystemExit(0)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(download_source), pool.submit(download_weights), pool.submit(download_configs)]
        for future in as_completed(futures):
            future.result()
    print("Hunyuan3D-2mini shape assets ready", flush=True)
