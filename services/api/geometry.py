"""Small, deterministic furniture templates with self-contained glTF 2.0 output.

These models are built from user-confirmed parameters, not inferred from images.
Coordinates are meters, right-handed, Y up; every box is a named part.
"""
import json
import shutil
import struct
import subprocess
from pathlib import Path


class GLBBuilder:
    def __init__(self, color):
        rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        self.document = {
            "asset": {"version": "2.0", "generator": "FORM parametric templates 0.1"},
            "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
            "accessors": [], "bufferViews": [],
            "materials": [
                {"name": "用户指定的近似底色", "pbrMetallicRoughness": {"baseColorFactor": linear + [1], "metallicFactor": 0, "roughnessFactor": 0.65}},
                {"name": "深色五金", "pbrMetallicRoughness": {"baseColorFactor": [0.035, 0.04, 0.05, 1], "metallicFactor": 0.65, "roughnessFactor": 0.35}},
            ],
        }
        self.binary = bytearray()
        self.minimum = [float("inf")] * 3
        self.maximum = [float("-inf")] * 3

    def accessor(self, values, components, kind, component_type, target, bounds=False):
        while len(self.binary) % 4:
            self.binary.append(0)
        offset = len(self.binary)
        code = "f" if component_type == 5126 else "H"
        self.binary.extend(struct.pack("<" + code * len(values), *values))
        view = len(self.document["bufferViews"])
        self.document["bufferViews"].append({"buffer": 0, "byteOffset": offset, "byteLength": len(values) * (4 if code == "f" else 2), "target": target})
        item = {"bufferView": view, "componentType": component_type, "count": len(values) // components, "type": kind}
        if bounds:
            item["min"] = [min(values[i::components]) for i in range(components)]
            item["max"] = [max(values[i::components]) for i in range(components)]
        self.document["accessors"].append(item)
        return len(self.document["accessors"]) - 1

    def box(self, name, center, size, material=0):
        x, y, z = [v / 2 for v in size]
        faces = [
            ([1, 0, 0], [(x, -y, -z), (x, y, -z), (x, y, z), (x, -y, z)]),
            ([-1, 0, 0], [(-x, -y, z), (-x, y, z), (-x, y, -z), (-x, -y, -z)]),
            ([0, 1, 0], [(-x, y, -z), (-x, y, z), (x, y, z), (x, y, -z)]),
            ([0, -1, 0], [(-x, -y, z), (-x, -y, -z), (x, -y, -z), (x, -y, z)]),
            ([0, 0, 1], [(x, -y, z), (x, y, z), (-x, y, z), (-x, -y, z)]),
            ([0, 0, -1], [(-x, -y, -z), (-x, y, -z), (x, y, -z), (x, -y, -z)]),
        ]
        positions, normals, indices = [], [], []
        for normal, corners in faces:
            start = len(positions) // 3
            positions.extend(v for corner in corners for v in corner)
            normals.extend(normal * 4)
            indices.extend([start, start + 1, start + 2, start, start + 2, start + 3])
        position = self.accessor(positions, 3, "VEC3", 5126, 34962, True)
        normal = self.accessor(normals, 3, "VEC3", 5126, 34962)
        index = self.accessor(indices, 1, "SCALAR", 5123, 34963)
        mesh = len(self.document["meshes"])
        self.document["meshes"].append({"name": name, "primitives": [{"attributes": {"POSITION": position, "NORMAL": normal}, "indices": index, "material": material}]})
        node = len(self.document["nodes"])
        self.document["nodes"].append({"name": name, "mesh": mesh, "translation": list(center)})
        self.document["scenes"][0]["nodes"].append(node)
        for i in range(3):
            self.minimum[i] = min(self.minimum[i], center[i] - size[i] / 2)
            self.maximum[i] = max(self.maximum[i], center[i] + size[i] / 2)

    def save(self, path):
        while len(self.binary) % 4:
            self.binary.append(0)
        self.document["buffers"] = [{"byteLength": len(self.binary)}]
        encoded = json.dumps(self.document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        encoded += b" " * (-len(encoded) % 4)
        total = 12 + 8 + len(encoded) + 8 + len(self.binary)
        content = struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(encoded), b"JSON") + encoded + struct.pack("<I4s", len(self.binary), b"BIN\x00") + self.binary
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
        return {"parts": len(self.document["meshes"]), "triangles": len(self.document["meshes"]) * 12,
                "dimensions_m": [self.maximum[i] - self.minimum[i] for i in range(3)], "bytes": total}


def build_template(request, destination: Path):
    w, d, h = request.dimensions.width, request.dimensions.depth, request.dimensions.height
    builder = GLBBuilder(request.color)
    thickness = min(0.025, min(w, d, h) * 0.08)
    t = thickness
    if request.template == "shelf":
        for n, x in enumerate((-w / 2 + t / 2, w / 2 - t / 2), 1):
            builder.box("侧板_%d" % n, (x, h / 2, 0), (t, h, d))
        for n in range(request.levels):
            y = t / 2 + (h - t) * n / (request.levels - 1)
            builder.box("层板_%d" % (n + 1), (0, y, 0), (w - 2 * t, t, d))
    elif request.template == "table":
        builder.box("桌面", (0, h - t / 2, 0), (w, t, d))
        leg = min(0.045, w * 0.12, d * 0.12)
        for i, (x, z) in enumerate([(sx * (w / 2 - leg), sz * (d / 2 - leg)) for sx in (-1, 1) for sz in (-1, 1)], 1):
            builder.box("桌腿_%d" % i, (x, (h - t) / 2, z), (leg, h - t, leg), 1)
    else:
        for i, x in enumerate((-w / 2 + t / 2, w / 2 - t / 2), 1):
            builder.box("柜侧板_%d" % i, (x, h / 2, 0), (t, h, d))
        for name, y in [("柜底板", t / 2), ("柜顶板", h - t / 2), ("内部层板", h / 2)]:
            builder.box(name, (0, y, 0), (w - 2 * t, t, d - t))
        builder.box("背板", (0, h / 2, -d / 2 + t / 2), (w - 2 * t, h - 2 * t, t))
        gap = min(0.004, w * 0.01)
        door_width = (w - 2 * t - gap) / 2
        for i, side in enumerate((-1, 1), 1):
            builder.box("柜门_%d" % i, (side * (gap / 2 + door_width / 2), h / 2, d / 2 - t / 2), (door_width, h - 2 * t, t))
    return builder.save(destination)


def inspect_glb(path):
    data = path.read_bytes()
    if len(data) < 28 or struct.unpack_from("<4sII", data) != (b"glTF", 2, len(data)):
        raise ValueError("输出不是有效的 GLB 2.0 文件")
    length, kind = struct.unpack_from("<I4s", data, 12)
    if kind != b"JSON" or 20 + length > len(data):
        raise ValueError("GLB JSON 数据不完整")
    doc = json.loads(data[20:20 + length])
    if doc.get("asset", {}).get("version") != "2.0" or not doc.get("meshes"):
        raise ValueError("模型中没有有效网格")
    if any(x.get("uri") for x in doc.get("buffers", []) + doc.get("images", [])):
        raise ValueError("模型引用了外部文件，需要先打包为自包含 GLB")
    triangles = 0
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            if primitive.get("mode", 4) == 4:
                accessor = primitive.get("indices", primitive["attributes"]["POSITION"])
                triangles += doc["accessors"][accessor]["count"] // 3
    return {"parts": len(doc["meshes"]), "triangles": triangles, "bytes": len(data), "glb_structure": "pass"}


def validate_glb(path):
    node = shutil.which("node")
    if not node:
        return {"status": "not_run", "reason": "node_not_available"}
    script = Path(__file__).resolve().parents[2] / "scripts" / "check_asset.cjs"
    result = subprocess.run([node, str(script), str(path.resolve())], capture_output=True, timeout=60,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ValueError("完整 glTF 校验无法完成，请检查文件与 Node 环境")
    report = json.loads(result.stdout)
    if report["status"] == "fail":
        raise ValueError("模型未通过 glTF 规范校验，暂不提供交付")
    return report
