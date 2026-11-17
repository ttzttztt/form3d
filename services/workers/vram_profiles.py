"""PartCrafter settings that fit a given GPU, from the largest to the smallest footprint.

Memory grows with parts x tokens-per-part during sampling and with octree depth during mesh
decoding. The thresholds below are starting points: every run records its profile and peak
memory in generation.json, so they can be tuned on the actual card. When a run still runs out
of memory, the orchestrator retries once per lower profile in a fresh process.
"""

GIB = 1024**3

PROFILES = [
    {"name": "standard", "tokens": 1024, "dense_depth": 7, "mesh_depth": 8},
    {"name": "reduced", "tokens": 512, "dense_depth": 7, "mesh_depth": 8},
    {"name": "low", "tokens": 512, "dense_depth": 6, "mesh_depth": 7},
    {"name": "minimal", "tokens": 256, "dense_depth": 6, "mesh_depth": 7},
]
NAMES = [p["name"] for p in PROFILES]


def profile(name):
    return next(dict(p) for p in PROFILES if p["name"] == name)


def choose(total_bytes, num_parts):
    """Pick a starting profile from total VRAM and the planned part count."""
    gib = (total_bytes or 0) / GIB
    if gib >= 20:
        name = "standard"
    elif gib >= 10:
        name = "standard" if num_parts <= 6 else "reduced"
    elif gib >= 5.5:
        # Measured on an RTX 3060 Laptop 6 GB: 5 parts at "standard" peaked at 4.06 GiB (192 s).
        name = "standard" if num_parts <= 6 else "reduced" if num_parts <= 10 else "low"
    else:
        name = "low" if num_parts <= 4 else "minimal"
    return profile(name)


def lower(name):
    """The next smaller profile, or None when already at the smallest."""
    index = NAMES.index(name)
    return profile(NAMES[index + 1]) if index + 1 < len(NAMES) else None
