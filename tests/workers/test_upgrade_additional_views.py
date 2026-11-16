# -*- coding: utf-8 -*-
"""Real API extra-image controls; synthetic render inputs explicitly labeled."""


def main():
    import argparse, io, json, sys, time
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(ROOT), str(ROOT / "services/workers")]
    import httpx
    from PIL import Image
    from services.api.store import Store
    from upgrade_record import OUT, record

    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["wrong", "synthetic"], required=True)
    p.add_argument("--tag", default="")
    p.add_argument("--file", default="synthetic_leather_oblique.png")
    p.add_argument("--job")
    p.add_argument("--part", default="坐面与主体 1")
    a = p.parse_args()
    store = Store(ROOT / ".data")
    cases = json.loads((OUT / "cases.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["case"] == "leather_sofa")
    if a.job:
        case = {**case, "job": a.job}
    base = "http://127.0.0.1:8001"
    root = f"/api/jobs/{case['job']}/asset"
    result = {
        "input_kind": "wrong_product_photo" if a.mode == "wrong" else "synthetic_render_regression",
        "real_second_product_photo": False,
        "checks": [],
    }
    client = httpx.Client(base_url=base, timeout=120)

    def get(url):
        response = client.get(url)
        response.raise_for_status()
        return response.json()

    def upload(bytes_, name):
        response = client.post("/api/images", files={"file": (name, bytes_, "image/png")})
        response.raise_for_status()
        return response.json()["id"]

    try:
        catalog = get(root)
        group = next(g for g in catalog["groups"] if g["name"] == a.part)
        version = catalog["version"]
        payload = {"version": version, "part_ids": group["part_ids"], "candidate_count": 1, "target_faces": 100000}
        if a.mode == "wrong":
            image = store.image(case["image_id"])
            buffer = io.BytesIO()
            Image.open(store.root / image["normalized_path"]).convert("RGBA").save(buffer, "PNG", compress_level=1)
            duplicate = upload(buffer.getvalue(), "same-photo-different-encoding.png")
            count = len(list((store.root / "jobs" / case["job"] / "part_regenerations").glob("*/status.json")))
            response = client.post(
                root + "/part-optimizations",
                json={**payload, "reference_views": [{"image_id": duplicate, "role": "side"}]},
            )
            assert response.status_code == 409, response.text
            assert len(list((store.root / "jobs" / case["job"] / "part_regenerations").glob("*/status.json"))) == count
            result["duplicate_response"] = response.json()
            result["checks"].append("duplicate_pixel_content_refused_before_queueing")
            other = next(c for c in cases if c["case"] == "accent_chair")
            image_id = other["image_id"]
        else:
            path = OUT / a.file
            image_id = upload(path.read_bytes(), path.name)
            result["provenance"] = path.stem + "_provenance.json"
        response = client.post(
            root + "/part-optimizations", json={**payload, "reference_views": [{"image_id": image_id, "role": "front"}]}
        )
        response.raise_for_status()
        task = response.json()
        result["task"] = task["id"]
        result["job"] = case["job"]
        result["version_before"] = version
        record("extra_view_api_test_started", mode=a.mode, task=task["id"], synthetic=a.mode == "synthetic")
        started = time.monotonic()
        last = None
        while time.monotonic() - started < 1500:
            state = get(root + "/part-regenerations/" + task["id"])
            if state["stage"] != last:
                print(state["stage"], flush=True)
                last = state["stage"]
            if state["status"] not in ("running", "queued"):
                break
            time.sleep(2)
        else:
            client.post(root + "/part-regenerations/" + task["id"] + "/cancel")
            raise TimeoutError("Supplemental-view test exceeded 25 minutes")
        result["state"] = state
        assert get(root)["version"] == version
        result["checks"].append("original_version_unchanged")
        if a.mode == "wrong":
            assert state["status"] in ("needs_input", "failed") or (
                state["status"] == "ready" and not state.get("photo_checks", {}).get("can_adopt")
            ), state
            result["checks"].append("wrong_furniture_not_ignored_or_adopted")
        elif state["status"] == "ready":
            views = state["photo_checks"]["views"]
            assert len(views) == 2
            assert any(v.get("additional_reference") and v["image_id"] == image_id for v in views)
            assert all(not v.get("capture_independence_verified") for v in views)
            result["checks"].append("additional_view_included_in_actual_before_after_checks")
        else:
            result["limitation"] = (
                "Supplemental render not reliably associated; evidence retained, no successful end-to-end claim"
            )
        result["elapsed_seconds"] = time.monotonic() - started
        record(
            "extra_view_api_test_finished",
            mode=a.mode,
            task=task["id"],
            status=state["status"],
            checks=result["checks"],
        )
    except Exception as exc:
        result["failure"] = str(exc)
        raise
    finally:
        (OUT / ("additional_view_" + a.mode + ("_" + a.tag if a.tag else "") + ".json")).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        client.close()
    print(
        json.dumps(
            {"mode": a.mode, "status": result["state"]["status"], "checks": result["checks"]}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
