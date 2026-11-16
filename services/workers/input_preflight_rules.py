# -*- coding: utf-8 -*-
"""Conservative, versioned input heuristics. These are not accuracy scores."""

import re
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

RULES = {
    "version": "1.1",
    "min_native_roi_pixels": 16384,
    "max_fragment_count": 200,
    "fragmented_largest_fraction": 0.75,
    "min_clutter_score": 0.35,
    "min_clutter_box_area_fraction": 0.01,
    "min_clutter_alpha_overlap": 0.08,
}
DIMENSION = re.compile(
    r"^\s*\d+(?:[.,]\d+)?\s*(?:mm|cm|m|in|inch(?:es)?|ft|feet|厘米|毫米|米|英寸|英尺|[\"″′\'])\s*$", re.I
)


def mask_metrics(image):
    mask = np.asarray(image.convert("RGBA"))[:, :, 3] > 127
    labels, count = ndimage.label(mask, np.ones((3, 3), int))
    sizes = np.bincount(labels.ravel())[1:]
    filled = ndimage.binary_fill_holes(mask)
    holes = filled & ~mask
    _, hole_count = ndimage.label(holes, np.ones((3, 3), int))
    total = int(mask.sum())
    return {
        "native_size": list(image.size),
        "foreground_pixels": total,
        "components": int(count),
        "largest_component_fraction": float(sizes.max() / total) if total else 0,
        "hole_count": int(hole_count),
        "hole_fraction": float(holes.sum() / max(1, filled.sum())),
        "score_note": "Heuristic geometry of alpha pixels only; not measured segmentation accuracy",
    }


def remove_dimension_components(image, ocr_results):
    """Erase only unit-bearing OCR regions with no main-product alpha overlap.

    No RGB inpainting, no largest-component-only filtering: separate leaves,
    thin parts, logos and unrecognized text remain unchanged.
    """
    image = image.convert("RGBA")
    data = np.array(image)
    labels, count = ndimage.label(data[:, :, 3] > 127, np.ones((3, 3), int))
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    main = int(sizes.argmax()) if count else 0
    removed = np.zeros(labels.shape, bool)
    records = []
    objects = ndimage.find_objects(labels)
    for polygon, text, score in ocr_results or []:
        record = {
            "polygon": [[float(x), float(y)] for x, y in polygon],
            "text": text,
            "confidence": float(score),
            "action": "preserved_non_dimension",
        }
        ambiguous_brand = bool(re.fullmatch(r"\s*\d+(?:[.,]\d+)?M\s*", text))
        if float(score) >= 0.65 and DIMENSION.fullmatch(text) and not ambiguous_brand:
            region = Image.new("L", image.size, 0)
            ImageDraw.Draw(region).polygon([tuple(point) for point in polygon], fill=255)
            region = ndimage.binary_dilation(np.asarray(region) > 0, iterations=3)
            ids = np.unique(labels[region])
            ids = ids[ids != 0]
            if main and main in ids:
                record["action"] = "preserved_product_overlap"
            else:
                safe = [int(identity) for identity in ids if sizes[identity] <= max(512, sizes[main] * 0.005)]
                selected = np.isin(labels, safe) & region
                # A dimension bracket may sit beside the recognized number.
                # Require two end ticks, elongated sparse ink, a matching
                # text location, and separation from the main product.
                xs = [point[0] for point in polygon]
                ys = [point[1] for point in polygon]
                tx0, tx1, ty0, ty1 = min(xs), max(xs), min(ys), max(ys)
                text_height = max(1, ty1 - ty0)
                text_width = max(1, tx1 - tx0)
                line_ids = []
                for identity, slices in enumerate(objects, 1):
                    if identity == main or slices is None or sizes[identity] > max(512, sizes[main] * 0.005):
                        continue
                    yy, xx = slices
                    w = xx.stop - xx.start
                    h = yy.stop - yy.start
                    ink = labels[slices] == identity
                    if sizes[identity] / (w * h) > 0.35:
                        continue
                    if h >= max(20, w * 5) and w >= 4:
                        gap = max(tx0 - xx.stop, xx.start - tx1, 0)
                        aligned = ty0 - text_height <= (yy.start + yy.stop) / 2 <= ty1 + text_height
                        ticks = np.count_nonzero(ink[:3].any(axis=0)) >= max(3, w * 0.4) and np.count_nonzero(
                            ink[-3:].any(axis=0)
                        ) >= max(3, w * 0.4)
                        match = gap <= text_height * 0.6 and aligned and text_height <= h <= text_height * 8 and ticks
                    elif w >= max(20, h * 5) and h >= 4:
                        gap = max(ty0 - yy.stop, yy.start - ty1, 0)
                        aligned = tx0 - text_width <= (xx.start + xx.stop) / 2 <= tx1 + text_width
                        ticks = np.count_nonzero(ink[:, :3].any(axis=1)) >= max(3, h * 0.4) and np.count_nonzero(
                            ink[:, -3:].any(axis=1)
                        ) >= max(3, h * 0.4)
                        match = gap <= text_height * 0.6 and aligned and text_width <= w <= text_width * 8 and ticks
                    else:
                        match = False
                    if match:
                        line_ids.append(identity)
                if line_ids:
                    selected |= np.isin(labels, line_ids)
                removed |= selected
                record.update(
                    action="removed_detached_dimension" if selected.any() else "no_visible_dimension_alpha",
                    removed_alpha_pixels=int(selected.sum()),
                    removed_dimension_brackets=len(line_ids),
                )
        records.append(record)
    data[removed, 3] = 0
    return Image.fromarray(data), Image.fromarray(removed.astype(np.uint8) * 255), records


def evaluate(metrics, native_size, clutter):
    reasons = []
    warnings = []
    if not metrics["foreground_pixels"]:
        reasons.append({"code": "empty_foreground", "message": "主体掩码为空，请重新选择目标"})
    if native_size[0] * native_size[1] < RULES["min_native_roi_pixels"]:
        reasons.append(
            {
                "code": "insufficient_native_pixels",
                "message": "目标在原图中的像素过少，请换近景或更清晰的原图；放大不能恢复缺失细节",
            }
        )
    if (
        metrics["components"] >= RULES["max_fragment_count"]
        or metrics["components"] >= 10
        and metrics["largest_component_fraction"] < RULES["fragmented_largest_fraction"]
    ):
        reasons.append(
            {
                "code": "fragmented_mask",
                "message": "主体掩码过于破碎，请检查透明/反射区域、遮挡和细小结构后重新提供图片",
            }
        )
    if metrics["hole_count"] >= 40 and metrics["hole_fraction"] > 0.02:
        warnings.append("掩码存在较多孔洞；可能是结构镂空，也可能是分割缺损，不能自动填补")
    risky = [item for item in clutter if item.get("requires_attention")]
    if risky:
        reasons.append(
            {
                "code": "foreground_clutter",
                "message": "发现可能遮挡或混入主体的物品："
                + "、".join(dict.fromkeys(item["label"] for item in risky))
                + "；需要清理图片或补充无遮挡视图",
            }
        )
    return {
        "status": "blocked" if reasons else "pass",
        "reasons": reasons,
        "warnings": warnings,
        "rule_version": RULES["version"],
        "rule_thresholds": RULES,
        "policy_note": "Heuristic input screening motivated by observed failures; not an appearance guarantee. No hidden-surface completion.",
    }
