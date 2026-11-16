"""Limited rigid pose hypotheses, without changing the source surface."""

import numpy as np


def shortest_up_rotation(normal):
    normal = np.asarray(normal, dtype=float)
    if normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) < 1e-12:
        raise ValueError("Invalid normal")
    normal = normal / np.linalg.norm(normal)
    if normal[1] <= 0:
        raise ValueError("Expected an upward-facing normal")
    target = np.array([0.0, 1.0, 0.0])
    axis = np.cross(normal, target)
    cosine = float(normal @ target)
    cross = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    # Rodrigues in cross-product form: the shortest rotation has no free twist.
    return np.eye(3) + cross + cross @ cross / (1 + cosine)
