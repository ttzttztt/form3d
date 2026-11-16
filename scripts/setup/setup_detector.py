"""Download a public Grounding DINO checkpoint; never uploads product images."""

import concurrent.futures
import json
import os
from pathlib import Path
import urllib.request
import time

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / ".models" / "grounding-dino-tiny"
FILES = [
    "config.json",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "special_tokens_map.json",
    "vocab.txt",
    "model.safetensors",
]


def download_checkpoint(target):
    base = "https://hf-mirror.com/IDEA-Research/grounding-dino-tiny/resolve/main/model.safetensors?download=true"
    request = urllib.request.Request(base + "&size=1", headers={"Range": "bytes=0-0", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        total = int(response.headers["Content-Range"].split("/")[-1])
        response.read()
    chunk_size = 4 * 1024 * 1024
    parts = (total + chunk_size - 1) // chunk_size

    def chunk(index):
        start, end = index * chunk_size, min((index + 1) * chunk_size, total) - 1
        destination = target.with_suffix(".part%04d" % index)
        if destination.is_file() and destination.stat().st_size == end - start + 1:
            return destination
        for attempt in range(3):
            try:
                request = urllib.request.Request(
                    base + "&part=%s" % index,
                    headers={"Range": "bytes=%s-%s" % (start, end), "User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(request, timeout=35) as response:
                    if response.headers.get("Content-Range") != "bytes %s-%s/%s" % (start, end, total):
                        raise ValueError("Unexpected download range")
                    data = response.read(end - start + 2)
                if len(data) != end - start + 1:
                    raise ValueError("Incomplete checkpoint range")
                destination.write_bytes(data)
                return destination
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(chunk, index) for index in range(parts)]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            future.result()
            if index % 8 == 0 or index == parts:
                print(
                    "Checkpoint: %s/%s parts (%.0f MB)" % (index, parts, min(index * chunk_size, total) / 1024**2),
                    flush=True,
                )
    temporary = target.with_suffix(".download")
    with temporary.open("wb") as output:
        for index in range(parts):
            output.write(target.with_suffix(".part%04d" % index).read_bytes())
    if temporary.stat().st_size != total:
        raise ValueError("Checkpoint assembly size mismatch")
    temporary.replace(target)
    for index in range(parts):
        target.with_suffix(".part%04d" % index).unlink()
    print("Downloaded model.safetensors: %.0f MB" % (total / 1024**2), flush=True)


def download(name):
    DESTINATION.mkdir(parents=True, exist_ok=True)
    target = DESTINATION / name
    if target.is_file() and target.stat().st_size > 100:
        print("Cached: " + name, flush=True)
        return
    if name.endswith(".safetensors"):
        return download_checkpoint(target)
    errors = []
    for host in ["https://hf-mirror.com", "https://huggingface.co"]:
        route = "resolve" if name.endswith(".safetensors") else "raw"
        url = host + "/IDEA-Research/grounding-dino-tiny/" + route + "/main/" + name
        url += "?local_setup=1"
        if route == "resolve":
            url += "?download=true"
        temporary = target.with_suffix(target.suffix + ".download")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=45) as response, temporary.open("wb") as output:
                total, last = 0, 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    total += len(chunk)
                    if total - last >= 32 * 1024 * 1024:
                        print("%s: %.0f MB" % (name, total / 1024**2), flush=True)
                        last = total
            if name.endswith(".json"):
                json.loads(temporary.read_text(encoding="utf-8"))
            if name.endswith(".safetensors") and total < 100_000_000:
                raise ValueError("Checkpoint response is incomplete")
            temporary.replace(target)
            print("Downloaded: " + name, flush=True)
            return
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc).split("?")[0][:150])
            temporary.unlink(missing_ok=True)
    if name == "tokenizer.json":
        print("Optional fast tokenizer unavailable; vocab.txt is sufficient", flush=True)
        return
    raise RuntimeError(name + ": " + " / ".join(errors))


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, FILES))
    print("Detector files ready: " + str(DESTINATION), flush=True)
