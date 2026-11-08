"""Small PNG pictures of meshes, drawn without a GPU (for lists of stored models).

The triangles are seen obliquely from the front (-y) and above, shaded flat by one light and
drawn back to front (painter's algorithm). Good enough for a thumbnail; a triangle that cuts
through another can be drawn slightly wrong.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

from cad_common.mesh_export import Mesh


def render_png(meshes: list[Mesh], width: int = 320, height: int = 240, tilt_deg: float = 50.0,
               background: tuple[int, int, int] = (42, 46, 51)) -> bytes:
    tilt = np.radians(tilt_deg)
    view = np.array([0.0, -np.sin(tilt), np.cos(tilt)])  # towards the viewer
    up = np.array([0.0, np.cos(tilt), np.sin(tilt)])  # screen up
    light = np.array([-0.4, -0.5, 0.75])
    light /= np.linalg.norm(light)
    polys, colours, depths = [], [], []
    for m in meshes:
        tri = np.asarray(m.vertices, dtype=np.float64)[np.asarray(m.triangles, dtype=np.int64)]  # n x 3 x 3
        if not len(tri):
            continue
        normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        length = np.linalg.norm(normal, axis=1)
        keep = length > 0
        tri, normal = tri[keep], normal[keep] / length[keep, None]
        facing = normal @ view > 0.0
        tri, normal = tri[facing], normal[facing]
        shade = 0.45 + 0.55 * np.clip(normal @ light, 0, 1)
        rgb = np.asarray(m.color or (0.8, 0.8, 0.8))
        colours.append(np.clip(shade[:, None] * rgb[None, :] * 255, 0, 255).astype(np.uint8))
        polys.append(np.stack([tri[..., 0], tri @ up], axis=-1))  # screen x, y
        depths.append(tri.mean(axis=1) @ view)
    img = Image.new("RGB", (width, height), background)
    if polys:
        polys, colours, depths = np.concatenate(polys), np.concatenate(colours), np.concatenate(depths)
        lo, hi = polys.reshape(-1, 2).min(axis=0), polys.reshape(-1, 2).max(axis=0)
        scale = 0.9 * min(width / max(hi[0] - lo[0], 1e-6), height / max(hi[1] - lo[1], 1e-6))
        centre = (lo + hi) / 2
        px = (polys[..., 0] - centre[0]) * scale + width / 2
        py = height / 2 - (polys[..., 1] - centre[1]) * scale
        draw = ImageDraw.Draw(img)
        for i in np.argsort(depths):  # far first
            draw.polygon([(px[i, 0], py[i, 0]), (px[i, 1], py[i, 1]), (px[i, 2], py[i, 2])], fill=tuple(int(x) for x in colours[i]))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
