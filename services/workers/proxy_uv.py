"""Bounded UV transfer from an xatlas proxy; original triangles never change."""

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree


def nearest_surface(points, triangles, k=24):
    import trimesh

    tree = cKDTree(triangles.mean(1))
    k = min(k, len(triangles))
    all_ids = []
    all_points = []
    all_distances = []
    for start in range(0, len(points), 2048):
        p = points[start : start + 2048]
        _, ids = tree.query(p, k=k)
        ids = np.asarray(ids).reshape(len(p), k)
        candidate = triangles[ids].reshape(-1, 3, 3)
        query = np.repeat(p, k, axis=0)
        closest = trimesh.triangles.closest_point(candidate, query).reshape(len(p), k, 3)
        distance = np.linalg.norm(closest - p[:, None, :], axis=2)
        best = np.argmin(distance, axis=1)
        rows = np.arange(len(p))
        all_ids.append(ids[rows, best])
        all_points.append(closest[rows, best])
        all_distances.append(distance[rows, best])
    return np.concatenate(all_points), np.concatenate(all_distances), np.concatenate(all_ids)


def proxy_unwrap(vertices, faces):
    import pymeshlab, xatlas, trimesh

    proxy_vertices, _, weld = np.unique(vertices, axis=0, return_index=True, return_inverse=True)
    proxy_faces = weld[faces]
    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(proxy_vertices.astype(float), proxy_faces.astype(np.int32)))
    if len(faces) > 12000:
        ms.meshing_decimation_quadric_edge_collapse(
            targetfacenum=12000,
            preserveboundary=True,
            preservenormal=True,
            preservetopology=True,
            optimalplacement=True,
        )
    proxy = ms.current_mesh()
    v = proxy.vertex_matrix().astype(np.float32)
    f = proxy.face_matrix().astype(np.uint32)
    t = v[f]
    area = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
    f = f[area > max(float(np.ptp(v, axis=0).max()), 1e-9) ** 2 * 1e-14]
    if not len(f) or len(f) > 25000:
        raise ValueError("代理网格无法在安全面数内保留边界，请使用快速分区或选择更小部件")
    atlas = xatlas.Atlas()
    atlas.add_mesh(v, f)
    pack = xatlas.PackOptions()
    pack.padding = 4
    pack.resolution = 2048
    atlas.generate(pack_options=pack)
    mapping, af, uv = atlas[0]
    if not np.array_equal(np.asarray(mapping)[af], f):
        raise ValueError("代理展开改变了面顺序，未发布 UV 回传")
    edges = np.concatenate((af[:, [0, 1]], af[:, [1, 2]], af[:, [2, 0]]))
    edges.sort(1)
    owners = np.tile(np.arange(len(af)), 3)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    e = edges[order]
    o = owners[order]
    same = np.all(e[1:] == e[:-1], axis=1)
    a = o[:-1][same]
    b = o[1:][same]
    graph = sparse.csr_matrix((np.ones(len(a) * 2), (np.r_[a, b], np.r_[b, a])), shape=(len(f), len(f)))
    count, chart = connected_components(graph, directed=False)
    if count > 256:
        raise ValueError("代理 UV 图块过多，建议选择更小部件或快速分区")
    original = vertices[faces]
    proxy_tri = v[f]
    _, center_distance, which = nearest_surface(original.mean(1), proxy_tri, 32)
    face_chart = chart[which]
    pairs = np.c_[faces.ravel(), np.repeat(face_chart, 3)]
    unique, inverse = np.unique(pairs, axis=0, return_inverse=True)
    new_uv = np.zeros((len(unique), 2))
    distances = np.zeros(len(unique))
    atlas_tri = uv[af]
    for label in range(count):
        selected = np.flatnonzero(unique[:, 1] == label)
        if not len(selected):
            continue
        proxy_ids = np.flatnonzero(chart == label)
        tri = proxy_tri[proxy_ids]
        closest, d, local = nearest_surface(vertices[unique[selected, 0]], tri, 24)
        bary = trimesh.triangles.points_to_barycentric(tri[local], closest)
        new_uv[selected] = np.einsum("ni,nij->nj", bary, atlas_tri[proxy_ids[local]])
        distances[selected] = d
    diagonal = max(float(np.linalg.norm(np.ptp(vertices, axis=0))), 1e-9)
    maximum = float(max(distances.max(), center_distance.max()) / diagonal)
    if not np.isfinite(new_uv).all() or maximum > 0.03:
        raise ValueError("代理 UV 回传距离超过保护阈值，请使用更小部件或快速分区")
    new_faces = inverse.reshape(-1, 3)
    t = new_uv[new_faces]
    edge = t[:, 1] - t[:, 0]
    other = t[:, 2] - t[:, 0]
    uv_area = abs(edge[:, 0] * other[:, 1] - edge[:, 1] * other[:, 0])
    geom_area = np.linalg.norm(np.cross(original[:, 1] - original[:, 0], original[:, 2] - original[:, 0]), axis=1)
    collapsed = float(geom_area[uv_area < 1e-12].sum() / max(geom_area.sum(), 1e-15))
    if collapsed > 0.01:
        raise ValueError("代理回传导致较多 UV 塌缩，未发布；请使用快速分区")
    return (
        unique[:, 0],
        new_faces,
        new_uv,
        {
            "algorithm": "proxy_xatlas_transfer",
            "proxy_faces": len(f),
            "charts": int(count),
            "max_transfer_distance_ratio": maximum,
            "collapsed_geometry_area_fraction": collapsed,
            "transfer_method": "nearby proxy triangle candidates + closest-point projection; approximate",
            "positions_preserved": True,
        },
    )
