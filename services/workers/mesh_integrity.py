"""Check physical GLB topology without collapsing distinct representable positions."""


def exact_storage_mesh(mesh):
    import numpy as np, trimesh

    points = np.asarray(mesh.vertices, dtype=np.float32)
    if not np.isfinite(points).all():
        raise ValueError("Nonfinite stored positions")
    vertices, inverse = np.unique(points, axis=0, return_inverse=True)
    result = trimesh.Trimesh(vertices, inverse[mesh.faces], process=False)
    valid = result.area_faces > 0
    removed = int((~valid).sum())
    result.update_faces(valid)
    result.remove_unreferenced_vertices()
    return result, {
        "weld": "exact_float32_position_equality",
        "positions_moved": False,
        "removed_exact_zero_area_faces": removed,
        "positive_area_faces_removed": 0,
    }
