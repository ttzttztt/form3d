"""Resolve a region claimed by two part prompts (e.g. "cabinet door" and "cabinet drawer").

Grounding DINO boxes for different prompts often land on the same region and SAM then cuts the
same mask. Detector scores of different prompts are not calibrated probabilities, so the score
alone only decides when the margin is clear. Shape is checked first: a drawer front is wider
than tall, a leg is tall and thin, a tabletop is a wide slab near the top of the furniture.
When neither shape nor a clear margin decides, the region stays "unknown" for the user.
"""

import numpy as np

SCORE_MARGIN = 0.10


def mask_features(mask, whole_mask):
    ys, xs = np.nonzero(mask)
    wy, wx = np.nonzero(whole_mask)
    width, height = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    whole_top, whole_height = wy.min(), max(wy.max() - wy.min() + 1, 1)
    whole_left, whole_width = wx.min(), max(wx.max() - wx.min() + 1, 1)
    return {
        "aspect": float(width / height),  # >1 wide, <1 tall
        "rel_y": float((ys.mean() - whole_top) / whole_height),  # 0 top of the furniture, 1 bottom
        "rel_x": float((xs.mean() - whole_left) / whole_width),
        "area_fraction": float(mask.sum() / max(whole_mask.sum(), 1)),
    }


def shape_fits(kind, f):
    """True: shape typical for this kind; False: shape contradicts it; None: shape says nothing."""
    aspect, rel_y, rel_x = f["aspect"], f["rel_y"], f["rel_x"]
    rules = {
        "tabletop": aspect >= 2.0 and rel_y <= 0.45,
        "shelf": aspect >= 3.0,
        "leg": aspect <= 0.6,
        "drawer": 1.3 <= aspect <= 8,
        "door": aspect <= 1.3,
        "seat_cushion": aspect >= 1.2 and rel_y >= 0.35,
        "backrest": rel_y <= 0.6,
        "back_cushion": rel_y <= 0.7,
        "armrest": rel_x <= 0.3 or rel_x >= 0.7,
    }
    return rules.get(kind)


def resolve_kind(evidence, mask, whole_mask):
    """evidence: [{"kind", "score", ...}] for one region. Returns (kind, resolution record)."""
    best = {}
    for row in evidence:
        if row["kind"] not in best or row["score"] > best[row["kind"]]:
            best[row["kind"]] = float(row["score"])
    features = mask_features(mask, whole_mask)
    fits = {kind: shape_fits(kind, features) for kind in best}
    record = {"candidates": best, "shape_fits": fits, "features": features}
    if len(best) == 1:
        return next(iter(best)), {**record, "method": "single_kind"}
    plausible = [k for k in best if fits[k] is not False] or list(best)
    if len(plausible) == 1:
        return plausible[0], {**record, "method": "shape"}
    preferred = [k for k in plausible if fits[k] is True]
    if len(preferred) == 1 and all(fits[k] is not True for k in plausible if k != preferred[0]):
        return preferred[0], {**record, "method": "shape"}
    ranked = sorted(plausible, key=lambda k: best[k], reverse=True)
    if best[ranked[0]] - best[ranked[1]] >= SCORE_MARGIN:
        return ranked[0], {**record, "method": "score_margin"}
    return "unknown", {**record, "method": "unresolved"}
