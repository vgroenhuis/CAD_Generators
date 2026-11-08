"""Rough ("fuzzy") surfaces for printed meshes: subdivide the triangles finely, then move every
vertex by a smooth random displacement that depends only on its position.

Because the displacement is a function of position (a smooth warp of space), vertices shared by
two triangles, and surfaces of two bodies that touch, move together: meshes stay closed and the
coloured bodies of a model still fit each other. Only the mesh is changed (3MF, preview); a
STEP file keeps the exact smooth geometry.

Modes:
  "surface"  heights only (z), fading out towards the bed (z = 0) so the bottom stays flat;
             side walls stay where they are, so tiles still fit side by side
  "object"   all directions, only above `top` (fading in over 2 mm), e.g. a worn statue on a tile
"""

from __future__ import annotations

import numpy as np


def _hash(ix: np.ndarray, iy: np.ndarray, iz: np.ndarray, seed: int) -> np.ndarray:
    """Pseudo-random value in [-1, 1] for each integer lattice point."""
    with np.errstate(over="ignore"):
        h = (ix.astype(np.uint64) * np.uint64(73856093)) ^ (iy.astype(np.uint64) * np.uint64(19349663)) \
            ^ (iz.astype(np.uint64) * np.uint64(83492791)) ^ np.uint64((seed * 2654435761) & 0xFFFFFFFF)
        h ^= h >> np.uint64(13)
        h *= np.uint64(0x5BD1E995)
        h ^= h >> np.uint64(15)
    return (h & np.uint64(0xFFFFFF)).astype(np.float64) / float(0xFFFFFF) * 2.0 - 1.0


def value_noise(p: np.ndarray, seed: int) -> np.ndarray:
    """Smooth noise in [-1, 1] at points p (n x 3, in lattice units), trilinearly interpolated
    with smoothstep weights."""
    base = np.floor(p).astype(np.int64)
    f = p - base
    w = f * f * (3 - 2 * f)
    out = np.zeros(len(p))
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                corner = _hash(base[:, 0] + dx, base[:, 1] + dy, base[:, 2] + dz, seed)
                weight = (w[:, 0] if dx else 1 - w[:, 0]) * (w[:, 1] if dy else 1 - w[:, 1]) * (w[:, 2] if dz else 1 - w[:, 2])
                out += corner * weight
    return out


def fractal_noise(p: np.ndarray, seed: int) -> np.ndarray:
    """Two octaves of value noise, about [-1, 1]."""
    return (value_noise(p, seed) + 0.5 * value_noise(p * 2.3 + 17.1, seed + 1)) / 1.5


def subdivide(v: np.ndarray, t: np.ndarray, max_edge: float, active, max_iter: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """Split every edge longer than `max_edge` that has an `active` end (active(v) -> bool per
    vertex), keeping the mesh conforming: a triangle is split into 2, 3 or 4 according to how
    many of its edges are split, so no cracks appear."""
    for _ in range(max_iter):
        n = len(t)
        e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
        es = np.sort(e, axis=1)
        uniq, inv = np.unique(es, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        length = np.linalg.norm(v[uniq[:, 0]] - v[uniq[:, 1]], axis=1)
        act = active(v)
        split = (length > max_edge) & (act[uniq[:, 0]] | act[uniq[:, 1]])
        if not split.any():
            break
        mid = np.full(len(uniq), -1, dtype=np.int64)
        mid[split] = len(v) + np.arange(int(split.sum()))
        v = np.vstack([v, (v[uniq[split, 0]] + v[uniq[split, 1]]) / 2])
        m = mid[inv].reshape(3, n).T  # midpoints of edges ab, bc, ca (-1: not split)
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        ab, bc, ca = m[:, 0], m[:, 1], m[:, 2]
        s_ab, s_bc, s_ca = ab >= 0, bc >= 0, ca >= 0
        count = s_ab.astype(int) + s_bc + s_ca
        new = [t[count == 0]]
        k = count == 3
        new += [np.column_stack(x) for x in ((a[k], ab[k], ca[k]), (ab[k], b[k], bc[k]), (ca[k], bc[k], c[k]), (ab[k], bc[k], ca[k]))]
        k = (count == 1) & s_ab
        new += [np.column_stack(x) for x in ((a[k], ab[k], c[k]), (ab[k], b[k], c[k]))]
        k = (count == 1) & s_bc
        new += [np.column_stack(x) for x in ((a[k], b[k], bc[k]), (a[k], bc[k], c[k]))]
        k = (count == 1) & s_ca
        new += [np.column_stack(x) for x in ((a[k], b[k], ca[k]), (ca[k], b[k], c[k]))]
        k = (count == 2) & ~s_ca
        new += [np.column_stack(x) for x in ((ab[k], b[k], bc[k]), (a[k], ab[k], bc[k]), (a[k], bc[k], c[k]))]
        k = (count == 2) & ~s_ab
        new += [np.column_stack(x) for x in ((ca[k], bc[k], c[k]), (a[k], b[k], bc[k]), (a[k], bc[k], ca[k]))]
        k = (count == 2) & ~s_bc
        new += [np.column_stack(x) for x in ((a[k], ab[k], ca[k]), (ab[k], b[k], c[k]), (ab[k], c[k], ca[k]))]
        t = np.vstack([x for x in new if len(x)])
    return v, t


def fuzz(v: np.ndarray, t: np.ndarray, amplitude: float, wavelength: float, mode: str = "surface",
         top: float = 0.0, seed: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """The mesh (vertices in mm, triangles) with a rough surface; see the module docstring."""
    if mode == "surface":
        def weight(p):
            return np.clip(p[:, 2] / 1.0, 0, 1)  # nothing at the bed, full from 1 mm up
    else:
        def weight(p):
            return np.clip((p[:, 2] - top) / 2.0, 0, 1)  # nothing on the tile, full 2 mm above it
    v, t = subdivide(np.asarray(v, dtype=np.float64), np.asarray(t, dtype=np.int64), wavelength / 3,
                     lambda p: weight(p) > 0)
    w = weight(v) * amplitude
    q = v / wavelength
    if mode == "surface":
        v = v.copy()
        v[:, 2] += w * fractal_noise(np.column_stack([q[:, 0], q[:, 1], np.zeros(len(q))]), seed)
    else:
        d = np.column_stack([fractal_noise(q, seed + 10 * i) for i in range(3)])
        v = v + w[:, None] * d
    return v, t
