"""Build an image-first assembly proposal; observations are never mesh fragments."""

import hashlib, json, uuid
from .assembly_models import AssemblyPlan

NAMES = {
    "seat_cushion": "坐垫",
    "back_cushion": "靠枕",
    "backrest": "靠背",
    "bolster": "圆柱抱枕",
    "armrest": "扶手",
    "frame": "座架/柜体",
    "body": "整体软包主体",
    "leg": "支撑",
    "tabletop": "桌面",
    "door": "柜门",
    "drawer": "抽屉",
    "shelf": "层板",
    "panel": "板件",
    "other": "其他部件",
    "unknown": "待确认区域",
}


def plan_from_image_observations(image_id, image_sha256, category, target, observations, plan_id=None):
    identity = plan_id or uuid.uuid4().hex
    parts = []
    counts = {}
    seen_masks = set()
    for item in sorted(observations, key=lambda r: (r["kind"], r["target"]["x"], r["target"]["y"], r["mask_sha256"])):
        if item["mask_sha256"] in seen_masks:
            raise ValueError("One image mask cannot become two independent parts")
        seen_masks.add(item["mask_sha256"])
        kind = item["kind"]
        counts[kind] = counts.get(kind, 0) + 1
        key = hashlib.sha256((identity + kind + item["mask_sha256"]).encode()).hexdigest()[:32]
        region = item["target"]
        if (
            region["x"] < target["x"] - 1e-6
            or region["y"] < target["y"] - 1e-6
            or region["x"] + region["width"] > target["x"] + target["width"] + 1e-6
            or region["y"] + region["height"] > target["y"] + target["height"] + 1e-6
        ):
            raise ValueError("A part observation lies outside the selected furniture instance")
        parts.append(
            {
                "id": "part_" + key,
                "name": NAMES.get(kind, "部件") + " " + str(counts[kind]),
                "kind": kind,
                "identity_status": "image_instance" if kind != "unknown" else "unassigned",
                "geometry_method": "native_joint",
                "status": "needs_evidence" if kind == "unknown" else "planned",
                "observations": [
                    {
                        "image_id": image_id,
                        "image_sha256": image_sha256,
                        "mask_sha256": item["mask_sha256"],
                        "target": region,
                        "evidence_kind": item.get("evidence_kind", "original_input"),
                        "visibility": item.get("visibility", "partial"),
                        "semantic_verified": False,
                    }
                ],
            }
        )
    limitations = ["图像部件清单是本地识别建议，尚未验证实物结构。", "背面与遮挡部分包含推测，缺少真实尺寸。"]
    relations = []
    # A support body is a declared structural hypothesis, not an observed mask
    # or a shape template. Tables/chairs do not receive an invented extra frame.
    frame = next((p for p in parts if p["kind"] == "body"), None) or next(
        (p for p in parts if p["kind"] == "frame"), None
    )
    if parts and category in ("sofa", "cabinet") and frame is None:
        frame = {
            "id": "part_" + hashlib.sha256((identity + "support_body_hypothesis").encode()).hexdigest()[:32],
            "name": "装配组（内部框架未验证）",
            "kind": "frame",
            "identity_status": "geometry_hypothesis",
            "geometry_method": "unresolved",
            "geometry_role": "structural_group",
            "hidden_surface_status": "inferred",
        }
        parts.append(frame)
        limitations.append("未观察到的内部框架仅作为无网格装配组，不自动生成重复座架/柜体。")
    if frame is not None:
        seats = [p for p in parts if p["kind"] == "seat_cushion"]

        def nearest_seat(part):
            # This is a 2D placement hypothesis, never a confirmed joint.
            region = part["observations"][0]["target"] if part["observations"] else None
            if region is None or not seats:
                return None
            center = region["x"] + region["width"] / 2
            return min(
                seats,
                key=lambda s: abs(
                    s["observations"][0]["target"]["x"] + s["observations"][0]["target"]["width"] / 2 - center
                ),
            )

        for part in parts:
            if part["id"] == frame["id"]:
                continue
            part["parent_id"] = frame["id"]
            seat = nearest_seat(part)
            target_part = seat if seat and part["kind"] in ("back_cushion", "bolster") else frame
            relation = (
                "inside"
                if part["kind"] in ("drawer", "shelf")
                else "supported_by"
                if part["kind"] in ("seat_cushion", "back_cushion", "bolster", "tabletop")
                else "attached_to"
            )
            if target_part.get("geometry_role") == "structural_group":
                relation = "aligned_with"
            relations.append(
                {"part_id": part["id"], "target_part_id": target_part["id"], "kind": relation, "evidence": "inferred"}
            )
    status = "planned"
    if not parts or any(p.get("status") == "needs_evidence" for p in parts):
        status = "needs_evidence"
    if sum(p.get("geometry_role", "physical_part") == "physical_part" for p in parts) > 16:
        status = "needs_evidence"
        limitations.append("规划超过原生联合生成器的 16 个实体部件上限，需分层生成，未截断清单。")
    return AssemblyPlan.model_validate(
        {
            "id": identity,
            "primary_image_id": image_id,
            "primary_image_sha256": image_sha256,
            "furniture_target": target,
            "object_category": category,
            "planning_basis": "image_first",
            "status": status,
            "parts": parts,
            "relations": relations,
            "limitations": limitations,
        }
    )
