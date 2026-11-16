"""Fetch a pinned public model only; no user inputs or authentication are sent."""

import argparse, concurrent.futures, hashlib, json, time, urllib.request
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(args):
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    revision = metadata["sha"]
    base = Path(args.output)
    if metadata["id"] != "VAST-AI/HoloPart" or metadata.get("gated") or metadata.get("private"):
        raise ValueError("Only the reviewed public ungated model is authorized")
    base.mkdir(parents=True, exist_ok=True)
    report = Path(args.report)
    if report.exists():
        raise ValueError("Preserve download attempts")

    def verify(path, item):
        if path.stat().st_size != item["size"]:
            raise ValueError("Incorrect size: " + item["rfilename"])
        sha = digest(path)
        if item.get("lfs"):
            if sha != item["lfs"]["sha256"]:
                raise ValueError("LFS hash mismatch")
        else:
            blob = path.read_bytes()
            git_sha = hashlib.sha1(("blob " + str(len(blob)) + "\0").encode() + blob).hexdigest()
            if git_sha != item["blobId"]:
                raise ValueError("Git blob hash mismatch")
        return {"path": item["rfilename"], "bytes": item["size"], "sha256": sha, "status": "verified"}

    def fetch(item):
        file = base / item["rfilename"]
        file.parent.mkdir(parents=True, exist_ok=True)
        if file.exists():
            return verify(file, item)
        partial = file.with_suffix(file.suffix + ".retry.download")
        for attempt in range(3):
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                if offset != item["size"]:
                    url = f"https://hf-mirror.com/VAST-AI/HoloPart/resolve/{revision}/{item['rfilename']}?download=true&attempt={attempt}"
                    headers = {"User-Agent": "img-to3D-public-model-fetch/1"}
                    if offset:
                        headers["Range"] = f"bytes={offset}-"
                    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as response:
                        if offset and response.status != 206:
                            raise ValueError("Resume range refused")
                        with partial.open("ab" if offset else "wb") as stream:
                            last = time.monotonic()
                            while True:
                                data = response.read(4 * 1024 * 1024)
                                if not data:
                                    break
                                stream.write(data)
                                if time.monotonic() - last > 20:
                                    print(
                                        json.dumps({"file": item["rfilename"], "downloaded_bytes": stream.tell()}),
                                        flush=True,
                                    )
                                    last = time.monotonic()
                record = verify(partial, item)
                if file.exists():
                    verify(file, item)
                else:
                    partial.replace(file)
                print(json.dumps(record), flush=True)
                return record
            except Exception as e:
                print(json.dumps({"file": item["rfilename"], "attempt": attempt, "error": str(e)}), flush=True)
                if attempt == 2:
                    return {"path": item["rfilename"], "status": "failed", "error": str(e)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(fetch, [i for i in metadata["siblings"] if i["rfilename"] != ".gitattributes"]))
    facts = {
        "model_id": metadata["id"],
        "model_revision": revision,
        "license_from_model_card": "MIT",
        "gated": False,
        "source_revision": "48dd632c9a7412e6688573bb4f153e0ade7e7325",
        "user_images_submitted": False,
        "files": records,
        "ready": all(r["status"] == "verified" for r in records),
    }
    report.write_text(json.dumps(facts, indent=2), encoding="utf-8")
    print("MODEL_READY", facts["ready"], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--metadata", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--report", required=True)
    run(p.parse_args())
