"""Lossless GLB container edits. Geometry attributes and original versions stay intact."""

import copy
import hashlib
import json
import struct
from pathlib import Path

MAX_GLB = 128 * 1024 * 1024

# These extensions own material/texture references only, never geometry indices.
# Keep unknown geometry/animation extensions on the conservative no-pack path.
MATERIAL_EXTENSION_TEXTURES = {
    "KHR_materials_unlit": (),
    "KHR_materials_ior": (),
    "KHR_materials_emissive_strength": (),
    "KHR_materials_dispersion": (),
    "KHR_materials_clearcoat": ("clearcoatTexture", "clearcoatRoughnessTexture", "clearcoatNormalTexture"),
    "KHR_materials_sheen": ("sheenColorTexture", "sheenRoughnessTexture"),
    "KHR_materials_specular": ("specularTexture", "specularColorTexture"),
    "KHR_materials_transmission": ("transmissionTexture",),
    "KHR_materials_volume": ("thicknessTexture",),
    "KHR_materials_iridescence": ("iridescenceTexture", "iridescenceThicknessTexture"),
    "KHR_materials_anisotropy": ("anisotropyTexture",),
    "KHR_materials_pbrSpecularGlossiness": ("diffuseTexture", "specularGlossinessTexture"),
}


def read_glb(path):
    data = Path(path).read_bytes()
    if len(data) > MAX_GLB:
        raise ValueError("编辑器当前支持不超过 128 MiB 的 GLB")
    if len(data) < 20 or struct.unpack_from("<4sII", data) != (b"glTF", 2, len(data)):
        raise ValueError("无效 GLB")
    chunks = []
    offset = 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("GLB chunk 不完整")
        size, kind = struct.unpack_from("<I4s", data, offset)
        offset += 8
        if offset + size > len(data):
            raise ValueError("GLB chunk 越界")
        chunks.append((kind, data[offset : offset + size]))
        offset += size
    if not chunks or chunks[0][0] != b"JSON":
        raise ValueError("缺少 GLB JSON")
    doc = json.loads(chunks[0][1])
    binary = bytearray(next((data for kind, data in chunks if kind == b"BIN\0"), b""))
    if any(item.get("uri") for item in doc.get("buffers", []) + doc.get("images", [])):
        raise ValueError("编辑仅支持自包含 GLB")
    return doc, binary, [(kind, data) for kind, data in chunks[1:] if kind != b"BIN\0"]


def write_glb(path, doc, binary, extra_chunks=()):
    binary = bytearray(binary)
    binary.extend(b"\0" * (-len(binary) % 4))
    if doc.get("buffers"):
        doc["buffers"][0]["byteLength"] = len(binary)
    encoded = json.dumps(doc, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    chunks = [(b"JSON", encoded)]
    if binary:
        chunks.append((b"BIN\0", bytes(binary)))
    chunks.extend(extra_chunks)
    data = b"".join(struct.pack("<I4s", len(chunk), kind) + chunk for kind, chunk in chunks)
    if len(data) + 12 > MAX_GLB:
        raise ValueError("编辑后 GLB 超过本地编辑器大小限制")
    temporary = Path(path).with_suffix(".writing")
    temporary.write_bytes(struct.pack("<4sII", b"glTF", 2, len(data) + 12) + data)
    temporary.replace(path)


def active_nodes(doc):
    scenes = doc.get("scenes", [])
    roots = scenes[doc.get("scene", 0)].get("nodes", []) if scenes else list(range(len(doc.get("nodes", []))))
    seen = set()
    ordered = []

    def visit(index, ancestors):
        if index in ancestors:
            raise ValueError("循环节点不支持编辑")
        if index in seen:
            return
        seen.add(index)
        ordered.append(index)
        for child in doc["nodes"][index].get("children", []):
            visit(child, ancestors | {index})

    for root in roots:
        visit(root, set())
    return ordered


def resolved_material_signatures(doc, binary):
    """Compare material content, independent of packed texture/image indices."""
    textures = {}
    images = {}

    def image_content(index):
        if index not in images:
            item = copy.deepcopy(doc["images"][index])
            view_index = item.pop("bufferView", None)
            if view_index is not None:
                view = doc["bufferViews"][view_index]
                start = view.get("byteOffset", 0)
                item["embedded_sha256"] = hashlib.sha256(binary[start : start + view["byteLength"]]).hexdigest()
            images[index] = item
        return images[index]

    def texture_content(index):
        if index not in textures:
            item = copy.deepcopy(doc["textures"][index])
            if "source" in item:
                item["source"] = image_content(item["source"])
            if "sampler" in item:
                item["sampler"] = doc["samplers"][item["sampler"]]
            for extension in ("KHR_texture_basisu", "EXT_texture_webp"):
                ext = item.get("extensions", {}).get(extension)
                if ext and "source" in ext:
                    ext["source"] = image_content(ext["source"])
            textures[index] = item
        return textures[index]

    signatures = []
    for original in doc.get("materials", []):
        material = copy.deepcopy(original)
        pbr = material.get("pbrMetallicRoughness", {})
        infos = [pbr[key] for key in ("baseColorTexture", "metallicRoughnessTexture") if key in pbr]
        infos.extend(
            material[key] for key in ("normalTexture", "occlusionTexture", "emissiveTexture") if key in material
        )
        for extension, keys in MATERIAL_EXTENSION_TEXTURES.items():
            values = material.get("extensions", {}).get(extension, {})
            infos.extend(values[key] for key in keys if key in values)
        for info in infos:
            info["index"] = texture_content(info["index"])
        signatures.append(
            hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        )
    return signatures


def parts_catalog(doc, binary=None):
    parts = []
    signatures = resolved_material_signatures(doc, binary) if binary is not None else None
    for index in active_nodes(doc):
        node = doc["nodes"][index]
        if "mesh" not in node:
            continue
        mesh = doc["meshes"][node["mesh"]]
        for number, primitive in enumerate(mesh["primitives"]):
            material = doc.get("materials", [])[primitive["material"]] if "material" in primitive else {}
            accessor = doc["accessors"][primitive.get("indices", primitive["attributes"]["POSITION"])]
            pbr = material.get("pbrMetallicRoughness", {})
            extras = primitive.get("extras", {})
            parts.append(
                {
                    "id": node.get("extras", {})
                    .get("form_part_ids", {})
                    .get(str(number), f"node_{index}_primitive_{number}"),
                    "node": index,
                    "primitive": number,
                    "name": extras.get("form_part_name") or node.get("name") or mesh.get("name") or f"网格 {index + 1}",
                    "group_kind": extras.get("form_group_kind", "source_primitive"),
                    "source_part_id": extras.get("form_source_part"),
                    "selection_role": extras.get("form_selection_role"),
                    "logical_group_id": extras.get("form_logical_group_id"),
                    "proposal_status": extras.get("form_proposal_status"),
                    "completion_role": extras.get("form_completion_role"),
                    "completion_note": extras.get("form_completion_note"),
                    "semantic_color": extras.get("form_semantic_color"),
                    "semantic_kind": extras.get("form_semantic_kind"),
                    "triangles": accessor["count"] // 3 if primitive.get("mode", 4) == 4 else 0,
                    "material_name": material.get("name", "默认材质"),
                    "base_color_factor": pbr.get("baseColorFactor", [1, 1, 1, 1]),
                    "material_signature": signatures[primitive["material"]]
                    if signatures is not None and "material" in primitive
                    else hashlib.sha256(
                        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest(),
                    "metalness": pbr.get("metallicFactor", 1),
                    "roughness": pbr.get("roughnessFactor", 1),
                    "has_texture": bool(pbr.get("baseColorTexture")),
                    "has_vertex_colors": "COLOR_0" in primitive["attributes"],
                }
            )
    return parts


def set_part_ids(doc):
    """Node-owned identities also distinguish instances sharing one mesh."""
    for part in parts_catalog(doc):
        doc["nodes"][part["node"]].setdefault("extras", {}).setdefault("form_part_ids", {})[str(part["primitive"])] = (
            part["id"]
        )


def compact_static(doc, binary):
    """Collect unreachable static resources, retaining all nodes and their metadata.

    Unknown extensions/animation may own indices; leave them untouched.
    """
    if (
        doc.get("animations")
        or doc.get("skins")
        or set(doc.get("extensionsUsed", [])) - ({"KHR_texture_transform"} | set(MATERIAL_EXTENSION_TEXTURES))
    ):
        return binary

    def collect(key, used):
        mapping = {old: new for new, old in enumerate(sorted(used))}
        if used:
            doc[key] = [doc[key][old] for old in sorted(used)]
        else:
            doc.pop(key, None)
        return mapping

    meshes = collect("meshes", {n["mesh"] for n in doc.get("nodes", []) if "mesh" in n})
    for n in doc.get("nodes", []):
        if "mesh" in n:
            n["mesh"] = meshes[n["mesh"]]
    primitives = [p for m in doc["meshes"] for p in m["primitives"]]
    materials = collect("materials", {p["material"] for p in primitives if "material" in p})
    for p in primitives:
        if "material" in p:
            p["material"] = materials[p["material"]]
    infos = []
    for material in doc.get("materials", []):
        pbr = material.get("pbrMetallicRoughness", {})
        infos.extend(pbr[key] for key in ("baseColorTexture", "metallicRoughnessTexture") if key in pbr)
        infos.extend(
            material[key] for key in ("normalTexture", "occlusionTexture", "emissiveTexture") if key in material
        )
        for extension, texture_keys in MATERIAL_EXTENSION_TEXTURES.items():
            values = material.get("extensions", {}).get(extension, {})
            infos.extend(values[key] for key in texture_keys if key in values)
    textures = collect("textures", {info["index"] for info in infos})
    for info in infos:
        info["index"] = textures[info["index"]]
    images = collect("images", {t["source"] for t in doc.get("textures", []) if "source" in t})
    samplers = collect("samplers", {t["sampler"] for t in doc.get("textures", []) if "sampler" in t})
    for texture in doc.get("textures", []):
        if "source" in texture:
            texture["source"] = images[texture["source"]]
        if "sampler" in texture:
            texture["sampler"] = samplers[texture["sampler"]]
    accessors = set()
    for p in primitives:
        accessors.update(p["attributes"].values())
        if "indices" in p:
            accessors.add(p["indices"])
        for target in p.get("targets", []):
            accessors.update(target.values())
    remap = collect("accessors", accessors)
    for p in primitives:
        p["attributes"] = {key: remap[value] for key, value in p["attributes"].items()}
        if "indices" in p:
            p["indices"] = remap[p["indices"]]
        for target in p.get("targets", []):
            for key, value in target.items():
                target[key] = remap[value]
    # Keep images/textures (including material extensions), but collect stale geometry views.
    views = {a["bufferView"] for a in doc["accessors"] if "bufferView" in a}
    for a in doc["accessors"]:
        if "sparse" in a:
            views.update(a["sparse"][k]["bufferView"] for k in ("indices", "values"))
    views.update(i["bufferView"] for i in doc.get("images", []) if "bufferView" in i)
    viewmap = collect("bufferViews", views)
    packed = bytearray()
    for v in doc["bufferViews"]:
        if v.get("buffer", 0) != 0:
            raise ValueError("只支持一个内嵌 buffer")
        packed.extend(b"\0" * (-len(packed) % 4))
        offset = len(packed)
        packed.extend(binary[v.get("byteOffset", 0) : v.get("byteOffset", 0) + v["byteLength"]])
        v["byteOffset"] = offset
    for a in doc["accessors"]:
        if "bufferView" in a:
            a["bufferView"] = viewmap[a["bufferView"]]
        if "sparse" in a:
            for k in ("indices", "values"):
                a["sparse"][k]["bufferView"] = viewmap[a["sparse"][k]["bufferView"]]
    for i in doc.get("images", []):
        if "bufferView" in i:
            i["bufferView"] = viewmap[i["bufferView"]]
    return packed


def selected_primitives(doc, part_ids):
    catalog = parts_catalog(doc)
    lookup = {part["id"]: part for part in catalog}
    selected = list(lookup) if not part_ids else list(dict.fromkeys(part_ids))
    if not selected or any(part not in lookup for part in selected):
        raise ValueError("所选部件已变化，请刷新版本后重试")
    # Isolate an instanced mesh before modifying one node; other nodes remain independent.
    cloned = {}
    for identity in selected:
        part = lookup[identity]
        node = doc["nodes"][part["node"]]
        if part["node"] not in cloned:
            if sum(n.get("mesh") == node["mesh"] for n in doc["nodes"]) > 1:
                source = copy.deepcopy(doc["meshes"][node["mesh"]])
                doc["meshes"].append(source)
                node["mesh"] = len(doc["meshes"]) - 1
            cloned[part["node"]] = doc["meshes"][node["mesh"]]
    return [
        (lookup[identity], cloned[lookup[identity]["node"]]["primitives"][lookup[identity]["primitive"]])
        for identity in selected
    ]


def material_edit(doc, request):
    color = request["color"]
    srgb = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in srgb]
    material = {
        "name": request.get("name") or "用户编辑材质",
        "pbrMetallicRoughness": {
            "baseColorFactor": linear + [request["opacity"]],
            "metallicFactor": request["metalness"],
            "roughnessFactor": request["roughness"],
        },
    }
    if request["opacity"] < 1:
        material.update(alphaMode="BLEND", doubleSided=True)
    targets = selected_primitives(doc, request.get("part_ids", []))
    changed = []
    for part, primitive in targets:
        final = copy.deepcopy(material)
        original = doc.get("materials", [])[primitive["material"]] if "material" in primitive else {}
        if request["mode"] == "tint":
            final = copy.deepcopy(original)
            final.setdefault("pbrMetallicRoughness", {}).update(material["pbrMetallicRoughness"])
            final["name"] = material["name"]
            if request["opacity"] < 1:
                final.update(alphaMode="BLEND", doubleSided=True)
            else:
                final.pop("alphaMode", None)
                final.pop("alphaCutoff", None)
        else:
            primitive["attributes"].pop("COLOR_0", None)
            if original.get("doubleSided"):
                final["doubleSided"] = True
        doc.setdefault("materials", []).append(final)
        primitive["material"] = len(doc["materials"]) - 1
        changed.append(part["id"])
    return {
        "operation": "material",
        "changed_parts": changed,
        "mode": request["mode"],
        "note": "Parameter material only. Positions and triangles unchanged; replacement may remove predicted COLOR_0.",
    }
