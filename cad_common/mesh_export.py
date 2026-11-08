"""Fast 3MF export of build123d shapes, for slicing.

A 3MF file holds triangle meshes, which is what a slicer needs, and it can keep the
bodies of a two-colour model as separate coloured parts of one object (ready to assign
a filament to each). Writing it is much faster than writing STEP: STEP stores the exact
geometry (every surface, edge and vertex as text), 3MF only triangles.

The meshes come from OpenCascade's tessellation (the same as STL export). Vertices are
merged across faces so every mesh is closed, as 3MF requires.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import quoteattr

import numpy as np

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>"
)
_DEFAULT_COLOR = (0.8, 0.8, 0.8)


@dataclass
class MeshPart:
    name: str
    shape: object  # any build123d Shape
    color: tuple[float, float, float] | None = None  # rgb, 0..1


@dataclass
class MeshObject:
    """One printable object; with several parts the slicer gets one object made of
    coloured parts (e.g. the white and black body of a two-colour model)."""
    name: str
    parts: list[MeshPart] = field(default_factory=list)


def parts_of(shape, default_name: str = "part") -> list[MeshPart]:
    """The labelled, coloured bodies of a build123d assembly (its children), or the
    shape itself when it has none."""
    children = list(getattr(shape, "children", ()) or ())
    items = children if children else [shape]
    parts = []
    for i, item in enumerate(items):
        color = getattr(item, "color", None)
        rgb = tuple(color)[:3] if color is not None else None  # build123d Color iterates as r, g, b, a
        name = getattr(item, "label", "") or (default_name if len(items) == 1 else f"{default_name} {i + 1}")
        parts.append(MeshPart(name, item, rgb))
    return parts


def _mesh(shape, tolerance: float, angular_tolerance: float) -> tuple[np.ndarray, np.ndarray]:
    verts, tris = shape.tessellate(tolerance, angular_tolerance)
    v = np.array([(p.X, p.Y, p.Z) for p in verts], dtype=np.float64).reshape(-1, 3)
    t = np.array(tris, dtype=np.int64).reshape(-1, 3)
    if not len(v):
        return v, t
    # tessellate() repeats the vertices of shared edges for every face: merge them.
    key = np.round(v / 1e-4).astype(np.int64)
    _, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    t = inverse.reshape(-1)[t]
    t = t[(t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])]
    return v[first], t


def _mesh_xml(v: np.ndarray, t: np.ndarray) -> str:
    vs = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in v.tolist())
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in t.tolist())
    return f"<mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh>"


def _hex(rgb) -> str:
    r, g, b = (max(0, min(255, round(c * 255))) for c in (rgb or _DEFAULT_COLOR))
    return f"#{r:02X}{g:02X}{b:02X}"


def to_3mf(objects: list[MeshObject], tolerance: float = 0.01, angular_tolerance: float = 0.2) -> bytes:
    """Write the objects (millimetres, positions as modelled) to 3MF and return the bytes.

    `tolerance` is the largest distance (mm) between the mesh and the exact surface; it
    only matters for curved surfaces.
    """
    bases, resources, items = [], [], []
    next_id = 2  # id 1 is the material list
    for obj in objects:
        part_ids = []
        for part in obj.parts:
            v, t = _mesh(part.shape, tolerance, angular_tolerance)
            if not len(t):
                continue
            pindex = len(bases)
            bases.append(f"<base name={quoteattr(part.name)} displaycolor=\"{_hex(part.color)}\"/>")
            resources.append(
                f'<object id="{next_id}" type="model" pid="1" pindex="{pindex}" name={quoteattr(part.name)}>'
                f"{_mesh_xml(v, t)}</object>"
            )
            part_ids.append(next_id)
            next_id += 1
        if not part_ids:
            continue
        if len(part_ids) == 1:
            items.append(part_ids[0])
            continue
        comps = "".join(f'<component objectid="{i}"/>' for i in part_ids)
        resources.append(f'<object id="{next_id}" type="model" name={quoteattr(obj.name)}><components>{comps}</components></object>')
        items.append(next_id)
        next_id += 1
    if not items:
        raise ValueError("Nothing to export.")
    build = "".join(f'<item objectid="{i}"/>' for i in items)
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<resources><basematerials id="1">{"".join(bases)}</basematerials>{"".join(resources)}</resources>'
        f"<build>{build}</build>"
        "</model>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("3D/3dmodel.model", model)
    return buf.getvalue()


def shape_to_3mf(shape, name: str, tolerance: float = 0.01) -> bytes:
    """One object made of the assembly's coloured bodies (see parts_of)."""
    return to_3mf([MeshObject(name, parts_of(shape, name))], tolerance)


# --- Ready-made meshes (e.g. made rough with cad_common.mesh_fuzz) ---

@dataclass
class Mesh:
    name: str
    color: tuple[float, float, float] | None
    vertices: np.ndarray  # n x 3, mm
    triangles: np.ndarray  # m x 3


def meshes_of(shape, tolerance: float = 0.01, angular_tolerance: float = 0.2) -> list[Mesh]:
    """The coloured bodies of an assembly (see parts_of) as closed triangle meshes."""
    out = []
    for part in parts_of(shape):
        v, t = _mesh(part.shape, tolerance, angular_tolerance)
        if len(t):
            out.append(Mesh(part.name, part.color, v, t))
    return out


def meshes_to_3mf(name: str, meshes: list[Mesh]) -> bytes:
    """One object made of the meshes as coloured parts (like shape_to_3mf)."""
    bases, resources, ids = [], [], []
    for i, m in enumerate(meshes):
        bases.append(f"<base name={quoteattr(m.name)} displaycolor=\"{_hex(m.color)}\"/>")
        resources.append(f'<object id="{i + 2}" type="model" pid="1" pindex="{i}" name={quoteattr(m.name)}>'
                         f"{_mesh_xml(m.vertices, m.triangles)}</object>")
        ids.append(i + 2)
    if not ids:
        raise ValueError("Nothing to export.")
    if len(ids) == 1:
        item = ids[0]
    else:
        item = len(meshes) + 2
        comps = "".join(f'<component objectid="{i}"/>' for i in ids)
        resources.append(f'<object id="{item}" type="model" name={quoteattr(name)}><components>{comps}</components></object>')
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<resources><basematerials id="1">{"".join(bases)}</basematerials>{"".join(resources)}</resources>'
        f'<build><item objectid="{item}"/></build>'
        "</model>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("3D/3dmodel.model", model)
    return buf.getvalue()


def meshes_to_glb(meshes: list[Mesh]) -> bytes:
    """A binary glTF of the meshes, one node per mesh named after it, with its colour; in metres
    and Y-up like build123d's glTF export. No normals are stored: a viewer shades the
    triangles flat, which suits rough surfaces."""
    import json
    import struct

    bin_parts, views, accessors, gl_meshes, materials, nodes = [], [], [], [], [], []
    offset = 0

    def add(data: bytes, target: int) -> int:
        nonlocal offset
        pad = (-len(data)) % 4
        bin_parts.append(data + b"\0" * pad)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
        offset += len(data) + pad
        return len(views) - 1

    for i, m in enumerate(meshes):
        v = np.asarray(m.vertices, dtype=np.float64)
        pos = np.column_stack([v[:, 0], v[:, 2], -v[:, 1]]).astype(np.float32) / 1000.0  # Z-up mm -> Y-up m
        idx = np.asarray(m.triangles, dtype=np.uint32).reshape(-1)
        pv = add(pos.tobytes(), 34962)
        iv = add(idx.tobytes(), 34963)
        accessors.append({"bufferView": pv, "componentType": 5126, "count": len(pos), "type": "VEC3",
                          "min": pos.min(axis=0).tolist(), "max": pos.max(axis=0).tolist()})
        accessors.append({"bufferView": iv, "componentType": 5125, "count": len(idx), "type": "SCALAR"})
        # glTF colours are linear: convert from sRGB (as build123d's glTF export does).
        r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (m.color or _DEFAULT_COLOR))
        materials.append({"pbrMetallicRoughness": {"baseColorFactor": [r, g, b, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.7},
                          "name": m.name})
        gl_meshes.append({"primitives": [{"attributes": {"POSITION": len(accessors) - 2}, "indices": len(accessors) - 1,
                                          "material": i}], "name": m.name})
        nodes.append({"mesh": i, "name": m.name})
    gltf = {"asset": {"version": "2.0", "generator": "cad_common.mesh_export"}, "scene": 0,
            "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": gl_meshes,
            "materials": materials, "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": offset}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    binary = b"".join(bin_parts)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
