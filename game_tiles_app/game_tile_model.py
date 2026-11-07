"""
    Multicolour game tiles: a tile whose top face shows a pattern in relief (earth, water,
    bricks, a door, a button, ...) in several colours, for multimaterial printing.

    Each colour is a separate body (named after the colour), so a slicer can assign one
    filament to each. The base body is the whole tile; the other colours are set `inlay_depth`
    into its top face and most stand out above it, some with sloping sides (stones, waves,
    rocks); grass blades, flames and the upright door are upright plates; mortar joints, seams,
    cracks and the pit are sunk. Asphalt (a road) stays flat. The tile is printed as shown:
    flat on its bottom face, pattern up, without supports. Its thickness has no upper limit,
    so it can also be a block or cube.

    Shapes: square (side = size), rectangle (size x length), hexagon (flat sides top and
    bottom, size across the flats), triangle (equilateral, side = size, pointing up) and
    circle (diameter = size). The pattern is drawn over the tile's bounding box and clipped to
    the outline; regular patterns (sand ripples, road markings, bricks, the checkerboard) repeat
    across square and rectangular tiles laid side by side. Random details (stones, drops,
    flames, ...) depend on `seed`; with several tiles each one gets its own variation.

    Can also be run standalone:  python game_tile_model.py --type bricks --shape hexagon --out tile.step
"""

from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from build123d import (
    Axis, Box, Color, Compound, Cylinder, Part, Plane, Polygon, Pos, Rectangle, Rot, Sketch, export_step, extrude, mirror, offset,
    revolve,
)

GRID_SPACING = 3.0  # mm between tiles in the print file
MAX_COUNT = 36
SHAPES = ("square", "rectangle", "hexagon", "triangle", "circle")
MIN_LINE = 1.0  # mm; narrowest stripe, crack or gap, so it prints with a 0.4 mm nozzle


@dataclass
class TileParams:
    tile_type: str = "earth"
    shape: str = "square"
    size: float = 40.0  # side (square, triangle), width (rectangle), across flats (hexagon), diameter (circle)
    length: float = 60.0  # rectangle only: its length along y
    thickness: float = 4.0
    inlay_depth: float = 0.6  # depth of the coloured inlays in the top face
    count: int = 1
    seed: int = 1


# Colour names (also the body names in the 3MF and STEP files) and their preview colours.
PALETTE = {
    "brown": (0.45, 0.29, 0.15), "dark_brown": (0.26, 0.16, 0.08), "grey": (0.55, 0.55, 0.55),
    "light_grey": (0.78, 0.78, 0.76), "dark_grey": (0.28, 0.28, 0.3), "black": (0.06, 0.06, 0.06),
    "white": (0.95, 0.95, 0.95), "sand": (0.93, 0.82, 0.55), "tan": (0.76, 0.6, 0.34),
    "asphalt": (0.2, 0.2, 0.22), "blue": (0.1, 0.35, 0.75), "light_blue": (0.45, 0.75, 0.98),
    "slate": (0.3, 0.35, 0.45), "dark_red": (0.55, 0.06, 0.03), "red": (0.85, 0.1, 0.08),
    "orange": (1.0, 0.5, 0.05), "yellow": (1.0, 0.85, 0.1), "brick": (0.7, 0.25, 0.15),
    "dark_brick": (0.5, 0.17, 0.1), "steel": (0.78, 0.8, 0.83), "wood": (0.78, 0.56, 0.32),
    "dark_wood": (0.42, 0.26, 0.12), "gold": (0.95, 0.72, 0.15), "green": (0.28, 0.62, 0.2),
    "dark_green": (0.12, 0.38, 0.1), "ice": (0.62, 0.84, 0.95), "dark_rock": (0.17, 0.12, 0.1),
    "violet": (0.62, 0.32, 0.92), "dark_purple": (0.2, 0.06, 0.3),
}


# --- 2D helpers (all in mm, tile centred on the origin) ---

def _sk(shape) -> Sketch:
    """A Sketch of the faces of `shape`, always wrapped in a compound: booleans on a Sketch
    holding a bare face silently return nothing."""
    return Sketch(Compound(shape.faces()).wrapped)


def _poly(points) -> Sketch:
    """Polygon face, made counterclockwise: a clockwise one would face down and extrude downwards."""
    pts = np.asarray(points, dtype=float)
    if np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1]) < 0:
        pts = pts[::-1]
    return _sk(Polygon(*[(float(x), float(y)) for x, y in pts], align=None))


def _circle(x: float, y: float, r: float, n: int = 0) -> Sketch:
    n = n or max(12, int(2 * math.pi * r / 0.5))
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return _poly(np.column_stack([x + r * np.cos(a), y + r * np.sin(a)]))


def _union(sketches: list) -> Sketch | None:
    sketches = [s for s in sketches if s is not None and s.faces()]
    if not sketches:
        return None
    if len(sketches) == 1:
        return sketches[0]
    return _sk(sketches[0].fuse(*sketches[1:]).clean())


def _rotate(points: np.ndarray, angle_deg: float) -> np.ndarray:
    a = math.radians(angle_deg)
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return points @ rot.T


def _blob(x, y, r, rng, n: int = 9, jitter: float = 0.3) -> Sketch:
    """Irregular rounded lump of about radius r."""
    a = np.linspace(0, 2 * math.pi, n, endpoint=False) + rng.uniform(0, 2 * math.pi)
    radii = r * (1 + jitter * (np.array([rng.random() for _ in range(n)]) * 2 - 1))
    return _poly(np.column_stack([x + radii * np.cos(a), y + radii * np.sin(a)]))


def _stroke(points: np.ndarray, width) -> Sketch:
    """Band of `width` (a number or one per point) along a smooth curve."""
    points = np.asarray(points, dtype=float)
    width = np.broadcast_to(np.asarray(width, dtype=float), (len(points),))
    tangent = np.gradient(points, axis=0)
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]]) * (width / 2)[:, None]
    return _poly(np.vstack([points + normal, (points - normal)[::-1]]))


def _polyline(points, width: float) -> Sketch | None:
    """Band of `width` along a polyline with corners (round joints)."""
    parts = []
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
        length, angle = math.hypot(x1 - x0, y1 - y0), math.degrees(math.atan2(y1 - y0, x1 - x0))
        rect = np.array([[0, -width / 2], [length, -width / 2], [length, width / 2], [0, width / 2]])
        parts.append(_poly(_rotate(rect, angle) + (x0, y0)))
    parts += [_circle(x, y, width / 2, 12) for x, y in points[1:-1]]
    return _union(parts)


def _teardrop(x, y, r, length, angle_deg) -> np.ndarray:
    """Outline of a drop: round end of radius r at (x, y), point `length` away at angle_deg."""
    beta = math.acos(min(r / length, 0.99))
    phi = np.linspace(math.pi / 2 + beta, 2.5 * math.pi - beta, 24)
    pts = np.vstack([[0, length], np.column_stack([r * np.cos(phi), r * np.sin(phi)])])
    return _rotate(pts, angle_deg - 90) + (x, y)


def _star(x, y, r_out, r_in, points: int = 5, angle_deg: float = 90) -> Sketch:
    a = np.radians(angle_deg) + np.arange(2 * points) * math.pi / points
    r = np.where(np.arange(2 * points) % 2 == 0, r_out, r_in)
    return _poly(np.column_stack([x + r * np.cos(a), y + r * np.sin(a)]))


def _clip_convex(poly: np.ndarray, normal: np.ndarray, limit: float) -> np.ndarray:
    """Part of a convex polygon where normal . p <= limit (Sutherland-Hodgman)."""
    out = []
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        dp, dq = normal @ p - limit, normal @ q - limit
        if dp <= 0:
            out.append(p)
        if dp * dq < 0:
            out.append(p + (q - p) * dp / (dp - dq))
    return np.array(out) if len(out) >= 3 else np.zeros((0, 2))


def _voronoi_cells(seeds: np.ndarray, gap: float, bound: float) -> list[np.ndarray]:
    """Voronoi cell of every seed, shrunk so neighbouring cells are `gap` apart."""
    cells = []
    square = np.array([[-bound, -bound], [bound, -bound], [bound, bound], [-bound, bound]], dtype=float)
    for i, s in enumerate(seeds):
        cell = square
        for j, t in enumerate(seeds):
            d = t - s
            dist = np.linalg.norm(d)
            if j == i or dist == 0:
                continue
            u = d / dist
            cell = _clip_convex(cell, u, u @ (s + t) / 2 - gap / 2)
            if len(cell) == 0:
                break
        if len(cell):
            cells.append(cell)
    return cells


# --- Tile outline ---

def outline_points(p: TileParams) -> np.ndarray:
    """Outline of the tile (counterclockwise), centred on its bounding box."""
    s = p.size
    if p.shape == "square":
        return np.array([[-s / 2, -s / 2], [s / 2, -s / 2], [s / 2, s / 2], [-s / 2, s / 2]])
    if p.shape == "rectangle":
        w, h = s, p.length
        return np.array([[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]])
    if p.shape == "hexagon":
        r = s / math.sqrt(3)  # corner radius for `size` across the flats
        a = np.radians(np.arange(6) * 60)
        return np.column_stack([r * np.cos(a), r * np.sin(a)])
    if p.shape == "triangle":
        h = s * math.sqrt(3) / 2
        return np.array([[-s / 2, -h / 2], [s / 2, -h / 2], [0, h / 2]])
    a = np.linspace(0, 2 * math.pi, 128, endpoint=False)
    return np.column_stack([s / 2 * np.cos(a), s / 2 * np.sin(a)])


class Ctx:
    """What a pattern needs to know about the tile: its size, outline and random generator."""

    def __init__(self, p: TileParams, seed: int):
        self.p = p
        pts = outline_points(p)
        self.outline = _poly(pts)
        self.w, self.h = float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1]))
        self.s = min(self.w, self.h)
        self.k = self.s / 40.0  # pattern scale: details are drawn for a 40 mm tile
        self.area = self.outline.area
        self.rng = random.Random(seed)
        # Centre and radius of the largest circle inside the tile, for centred emblems
        # (on a triangle that is lower than the middle of its bounding box).
        self.cy = -self.h / 6 if p.shape == "triangle" else 0.0
        self.inr = self.s / (2 * math.sqrt(3)) if p.shape == "triangle" else self.s / 2
        # Half-planes of the (convex) outline, for "is this circle inside" tests.
        nxt = np.roll(pts, -1, axis=0)
        edge = nxt - pts
        self._normals = np.column_stack([edge[:, 1], -edge[:, 0]]) / np.linalg.norm(edge, axis=1)[:, None]
        self._limits = np.einsum("ij,ij->i", self._normals, pts)

    def hgt(self, height: float) -> float:
        """A relief height for a 40 mm tile, scaled with the tile (at least 0.4 mm)."""
        return max(0.4, height * self.k)

    def line(self, width: float) -> float:
        """A line width scaled with the tile, but never narrower than MIN_LINE."""
        return max(MIN_LINE, width * self.k)

    def inside(self, x: float, y: float, r: float = 0.0) -> bool:
        return bool(np.all(self._normals @ np.array([x, y]) - self._limits <= -r))

    def scatter(self, count: int, rmin: float, rmax: float, gap: float = 0.5, margin: float = 0.3, avoid=()):
        """Up to `count` random circles (x, y, r) inside the tile that keep `gap` apart."""
        placed = list(avoid)
        out = []
        for _ in range(count * 30):
            if len(out) >= count:
                break
            r = self.rng.uniform(rmin, rmax)
            x, y = self.rng.uniform(-self.w / 2, self.w / 2), self.rng.uniform(-self.h / 2, self.h / 2)
            if not self.inside(x, y, r + margin):
                continue
            if any(math.hypot(x - a, y - b) < r + c + gap for a, b, c in placed):
                continue
            placed.append((x, y, r))
            out.append((x, y, r))
        return out

    def grid(self, pitch_x: float, pitch_y: float, stagger: bool = False, jitter: float = 0.0):
        """Points of a grid covering the tile (every other row shifted half a pitch if stagger)."""
        nx, ny = int(self.w / pitch_x) + 2, int(self.h / pitch_y) + 2
        for j in range(-ny, ny + 1):
            for i in range(-nx, nx + 1):
                x = (i + (0.5 if stagger and j % 2 else 0)) * pitch_x
                y = j * pitch_y
                if jitter:
                    x += self.rng.uniform(-jitter, jitter)
                    y += self.rng.uniform(-jitter, jitter)
                yield x, y


@dataclass
class Layer:
    """One coloured region of the top face.

    height: 0 = inlay flush with the top, > 0 raised that far above it (with sloping sides
    when `taper` > 0, in degrees), < 0 sunk that far below it. A layer with the base colour
    sinks or raises the base itself (a groove, raised cobbles). `solids` are extra 3D shapes in
    that colour standing on the top face (z = 0 there), e.g. spikes, grass blades, flames.
    """
    color: str
    region: Sketch | None
    height: float = 0.0
    solids: list = field(default_factory=list)
    taper: float = 0.0


@dataclass
class Design:
    base: str  # colour of the tile body
    layers: list[Layer]  # in drawing order: later layers cover earlier ones


def _fin(profile, thickness: float, angle_deg: float, x: float, y: float) -> Part:
    """Upright plate: `profile` (u, z) points in a vertical plane, `thickness` thick, turned
    angle_deg about the z axis and standing at (x, y)."""
    face = Plane.XZ * Polygon(*[(float(u), float(z)) for u, z in profile], align=None)
    plate = extrude(face, amount=thickness / 2, both=True)
    return Pos(x, y, 0) * Rot(0, 0, angle_deg) * plate


def _fuse(parts: list) -> Part:
    return Part(parts[0].fuse(*parts[1:]).clean().wrapped) if len(parts) > 1 else parts[0]


def _rect(x0, y0, x1, y1) -> Sketch:
    return _poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


# --- Patterns: one function per tile type ---

def _earth(c: Ctx) -> Design:
    clods = [_blob(x, y, r, c.rng) for x, y, r in c.scatter(int(c.area / 80), 1.3 * c.k, 3.2 * c.k, 0.8)]
    stones = [_blob(x, y, r, c.rng, 7, 0.2) for x, y, r in c.scatter(int(c.area / 220), 0.8 * c.k, 1.6 * c.k, 0.8)]
    return Design("brown", [Layer("dark_brown", _union(clods), c.hgt(1.0), taper=25),
                            Layer("grey", _union(stones), c.hgt(1.5), taper=20)])


def _sand(c: Ctx) -> Design:
    pitch = c.h / max(1, round(c.h / (6.5 * c.k)))  # whole number of ripples, so tiles join up
    wavelength = c.w / max(1, round(c.w / (16 * c.k)))
    x = np.linspace(-c.w / 2 - 2, c.w / 2 + 2, 80)
    ripples = []
    for j, y0 in enumerate(np.arange(-c.h / 2, c.h / 2 + pitch, pitch)):
        y = y0 + 1.4 * c.k * np.sin(2 * math.pi * x / wavelength + j * 1.3)
        ripples.append(_stroke(np.column_stack([x, y]), c.line(1.2)))
    dots = [_circle(x, y, r) for x, y, r in c.scatter(int(c.area / 140), 0.6, 0.9 * max(1, c.k), 1.0)]
    return Design("sand", [Layer("tan", _union(ripples), c.hgt(0.6)),
                           Layer("tan", _union(dots), c.hgt(0.5), taper=30)])


def _asphalt(c: Ctx) -> Design:
    width = max(1.2, 0.05 * c.s)
    dash = c.h / 4  # dashes of a quarter tile with equal gaps, centred on y = 0: they continue on the next tile
    line = [_rect(-width / 2, y - dash / 2, width / 2, y + dash / 2) for y in (-c.h / 2, 0, c.h / 2)]
    gravel = [_circle(x, y, r) for x, y, r in c.scatter(int(c.area / 30), 0.55, 0.8, 0.8,
                                                         avoid=[(0, y, width) for y in np.linspace(-c.h / 2, c.h / 2, 40)])]
    return Design("asphalt", [Layer("grey", _union(gravel)), Layer("white", _union(line))])  # a flat road


def _wave(x, y, length, amplitude, width) -> Sketch:
    t = np.linspace(0, 1, 30)
    pts = np.column_stack([x + (t - 0.5) * length, y + amplitude * np.sin(2 * math.pi * t)])
    return _stroke(pts, np.maximum(0.6, width * np.sin(math.pi * t) ** 0.5))


def _water(c: Ctx) -> Design:
    length, pitch_y = 11 * c.k, 6.5 * c.k
    waves, foam = [], []
    for x, y in c.grid(length * 1.3, pitch_y, stagger=True, jitter=0.8 * c.k):
        if c.inside(x, y, 1.5 * c.k):  # waves may run off the edge (clipped)
            waves.append(_wave(x, y, length, 1.1 * c.k, c.line(1.5)))
            if c.rng.random() < 0.35 and c.inside(x + length * 0.28, y + 2.2 * c.k, 1.5):
                foam.append(_circle(x + length * 0.28, y + 2.2 * c.k, max(0.6, 0.7 * c.k)))
    return Design("blue", [Layer("light_blue", _union(waves), c.hgt(0.8), taper=15),
                           Layer("white", _union(foam), c.hgt(1.0), taper=25)])


def _rain(c: Ctx) -> Design:
    pitch = 8 * c.k
    drops, streaks = [], []
    for x, y in c.grid(pitch, pitch, stagger=True, jitter=1.2 * c.k):
        if c.inside(x, y, 3.2 * c.k):
            drops.append(_poly(_teardrop(x, y, 1.3 * c.k, 3.4 * c.k, 110)))
        xs, ys = x + pitch / 2, y + pitch / 4
        if c.rng.random() < 0.6 and c.inside(xs, ys, 2.6 * c.k):
            d = _rotate(np.array([[0.0, -2.2 * c.k], [0.0, 2.2 * c.k]]), 20) + (xs, ys)
            streaks.append(_polyline(d, MIN_LINE))
    return Design("slate", [Layer("white", _union(streaks), c.hgt(0.6)),
                            Layer("light_blue", _union(drops), c.hgt(1.2), taper=15)])


def _flame_profile(r: float, bend: float) -> np.ndarray:
    """Side view of a flame standing on z = 0: the upper part of a drop, bent sideways towards
    the tip, flat at the bottom."""
    pts = _teardrop(0, 0, r, 2.8 * r, 90)  # tip first, then down the left side and up the right
    tip, rest = pts[:1], pts[1:]
    upper = rest[rest[:, 1] > 0.02 * r]
    left, right = upper[upper[:, 0] < 0], upper[upper[:, 0] >= 0]
    out = np.vstack([tip, left, [[-r, 0.0], [r, 0.0]], right])
    out[:, 0] += bend * r * 0.6 * np.clip(out[:, 1] / (2.8 * r), 0, 1) ** 2
    return out


def _fire(c: Ctx) -> Design:
    """Flames as crossed upright plates: orange outside, a smaller yellow core crossing them."""
    pads, oranges, yellows = [], [], []
    thick = max(1.2, 1.6 * c.k)
    for x, y, r in c.scatter(max(1, int(c.area / 260)), 3.0 * c.k, 4.4 * c.k, 1.5 * c.k):
        a0 = c.rng.uniform(0, 90)
        outer = [_fin(_flame_profile(r, c.rng.uniform(-1, 1)), thick, a0 + 90 * i, x, y) for i in range(2)]
        inner = [_fin(_flame_profile(0.62 * r, c.rng.uniform(-0.6, 0.6)), thick * 2.2, a0 + 45 + 90 * i, x, y) for i in range(2)]
        core = _fuse(inner)
        oranges.append(Part((_fuse(outer) - core).wrapped))
        yellows.append(core)
        pads.append(_circle(x, y, r))
    embers = [_circle(x, y, r) for x, y, r in c.scatter(int(c.area / 160), 0.6, 0.9, 1.0, avoid=[])]
    return Design("dark_red", [Layer("orange", _union(pads), solids=oranges), Layer("yellow", None, solids=yellows),
                               Layer("orange", _union(embers), c.hgt(0.8), taper=30)])


def _bricks(c: Ctx) -> Design:
    rows = max(2, round(c.h / (8 * c.k)))
    row_h = c.h / rows
    per_row = max(1, round(c.w / (2 * row_h)))
    brick_w = c.w / per_row
    mortar = c.line(1.2)
    bricks, dark = [], []
    for j in range(rows):
        y = -c.h / 2 + (j + 0.5) * row_h
        shift = brick_w / 2 if j % 2 else 0.0
        for i in range(-1, per_row + 1):
            x = -c.w / 2 + (i + 0.5) * brick_w + shift
            b = _rect(x - brick_w / 2 + mortar / 2, y - row_h / 2 + mortar / 2, x + brick_w / 2 - mortar / 2, y + row_h / 2 - mortar / 2)
            (dark if c.rng.random() < 0.25 else bricks).append(b)
    joints = _sk(c.outline - _union(bricks + dark))
    return Design("brick", [Layer("dark_brick", _union(dark)), Layer("light_grey", joints, height=-c.hgt(1.2))])


def _spikes(c: Ctx) -> Design:
    nx, ny = max(1, round(c.w / (10 * c.k))), max(1, round(c.h / (10 * c.k)))
    pitch = min(c.w / nx, c.h / ny)
    a = 0.68 * pitch  # base of each spike
    height = 0.9 * a
    taper = math.degrees(math.atan((a / 2 - 0.2) / height))
    plates, spikes = [], []
    for j in range(ny):
        for i in range(nx):
            x, y = -c.w / 2 + (i + 0.5) * c.w / nx, -c.h / 2 + (j + 0.5) * c.h / ny
            plate = a + 1.6
            if not all(c.inside(x + sx * plate / 2, y + sy * plate / 2, 0.5) for sx in (-1, 1) for sy in (-1, 1)):
                continue
            plates.append(_rect(x - plate / 2, y - plate / 2, x + plate / 2, y + plate / 2))
            spikes.append(Pos(x, y, 0) * extrude(Rectangle(a, a), amount=height, taper=taper))
    return Design("dark_grey", [Layer("steel", _union(plates), solids=spikes)])


def _door(c: Ctx) -> Design:
    """Door lying flat (a trapdoor): raised planks and braces in a frame."""
    frame = max(2.0, 3 * c.k)
    inner = _sk(offset(c.outline, -frame))
    planks, gap = 4, c.line(1.0)
    plank_w = (c.w - 2 * frame) / planks
    strips = []
    for i in range(planks):
        x0 = -c.w / 2 + frame + i * plank_w
        strips.append(_rect(x0 + gap / 2, -c.h, x0 + plank_w - gap / 2, c.h))
    brace_h = 0.1 * c.h
    braces = _union([_rect(-c.w, y - brace_h / 2, c.w, y + brace_h / 2) for y in (-0.27 * c.h, 0.27 * c.h)])
    wood = _sk(_sk(inner & _union(strips)) - braces)
    seams = _sk(inner - _union(strips) - braces)
    plank_h = c.hgt(0.6)
    hx = (c.w / 2 - frame) * 0.55
    r = 2.4 * c.k
    knob_h = max(1.5, 2.2 * c.k) + plank_h
    knob = Pos(hx, 0, 0) * revolve(Plane.XZ * Polygon((0, 0), (r, 0), (r, knob_h - 0.6), (r - 0.6, knob_h), (0, knob_h), align=None), Axis.Z)
    keyhole = _union([_circle(hx, -5 * c.k, max(0.8, 0.9 * c.k)),
                      _poly([(hx - 0.5 * max(1, c.k), -5 * c.k), (hx + 0.5 * max(1, c.k), -5 * c.k),
                             (hx + 0.8 * max(1, c.k), -7.5 * c.k), (hx - 0.8 * max(1, c.k), -7.5 * c.k)])])
    return Design("dark_brown", [
        Layer("wood", wood, plank_h), Layer("dark_brown", seams, height=-0.6),
        Layer("dark_brown", _sk(inner & braces), c.hgt(1.4), taper=20),
        Layer("black", keyhole, plank_h), Layer("gold", _circle(hx, 0, r), solids=[knob]),
    ])


def _arch(width: float, top: float, n: int = 24) -> list[tuple[float, float]]:
    """Outline (u, z) of a round-topped opening `width` wide, from z = 0 up to `top`."""
    r = width / 2
    a = np.linspace(0, math.pi, n)
    return [(r, 0.0)] + [(r * math.cos(t), top - r + r * math.sin(t)) for t in a] + [(-r, 0.0)]


def _half_width(c: Ctx, y0: float, y1: float) -> float:
    """Half the width of the tile over the whole band y0..y1 (the tile is symmetric in x)."""
    pts = outline_points(c.p)
    nxt = np.roll(pts, -1, axis=0)
    half = []
    for y in np.linspace(y0, y1, 5):
        xs = [x0 + (y - ya) * (x1 - x0) / (yb - ya) for (x0, ya), (x1, yb) in zip(pts, nxt) if (ya - y) * (yb - y) <= 0 and ya != yb]
        half.append(max(xs))
    return min(half)


def _door_upright(c: Ctx) -> Design:
    """A door standing upright in an arched frame as wide as the tile (so a game piece cannot
    walk around it), on a flagstone floor."""
    t_frame = max(4.0, 5 * c.k)
    t_leaf = 0.7 * t_frame
    w = 2 * _half_width(c, c.cy - t_frame / 2, c.cy + t_frame / 2)  # outer width of the frame
    fw = max(2.0, 2.6 * c.k)  # width of its posts and arch
    leaf_w = w - 2 * fw
    height = max(1.9 * c.inr, w / 2 + 0.6 * c.inr)  # top of the frame; the door has straight sides below the arch

    def slab(points, thickness):
        return extrude(Plane.XZ * Polygon(*points, align=None), amount=thickness / 2, both=True)

    leaf_outline = _arch(leaf_w, height - fw)
    frame = slab(_arch(w, height), t_frame) - slab(leaf_outline, t_frame + 1)
    leaf = slab(leaf_outline, t_leaf)
    groove = max(1.0, c.k)
    planks = max(3, round(leaf_w / (6 * max(1, c.k))))
    for i in range(1, planks):  # plank seams on both faces
        for side in (-1, 1):
            leaf = leaf - Pos(-leaf_w / 2 + i * leaf_w / planks, side * t_leaf / 2, height / 2) * Box(groove, 1.0, height)
    kx, kz = 0.3 * leaf_w, 0.42 * height
    kr = max(1.2, 1.5 * c.k)
    knob = Pos(kx, 0, kz) * Rot(90, 0, 0) * Cylinder(kr, t_leaf + 2 * kr)  # through the door: a knob on both sides
    hole_r = max(0.7, 0.7 * c.k)
    kz2 = kz - 3.5 * max(1, c.k)
    keyhole_outline = [(kx + hole_r * math.cos(a), kz2 + hole_r * math.sin(a)) for a in np.linspace(-0.3, math.pi + 0.3, 16)]
    keyhole_outline += [(kx - 0.9 * hole_r, kz2 - 2.6 * hole_r), (kx + 0.9 * hole_r, kz2 - 2.6 * hole_r)]
    keyhole = slab(keyhole_outline, t_leaf)  # flush with both faces
    leaf = leaf - knob - keyhole
    shift = Pos(0, c.cy, 0)
    footprint = _rect(-w / 2, c.cy - t_frame / 2, w / 2, c.cy + t_frame / 2)
    pitch, joint = 10 * c.k, c.line(1.0)
    flags = [_rect(-c.w, y - joint / 2, c.w, y + joint / 2) for y in np.arange(-c.h, c.h, pitch)]
    for j, y in enumerate(np.arange(-c.h, c.h, pitch)):
        flags += [_rect(x - joint / 2, y, x + joint / 2, y + pitch) for x in np.arange(-c.w, c.w, pitch) + (pitch / 2 if j % 2 else 0)]
    return Design("grey", [
        Layer("grey", _union(flags), height=-0.6),
        Layer("dark_brown", footprint, solids=[shift * frame]),
        Layer("wood", None, solids=[shift * leaf]),
        Layer("gold", None, solids=[shift * knob]),
        Layer("black", None, solids=[shift * keyhole]),
    ])


def _button(c: Ctx) -> Design:
    r_btn, r_ring, y0 = 0.48 * c.inr, 0.72 * c.inr, c.cy
    ring = _sk(_circle(0, y0, r_ring) - _circle(0, y0, r_btn + 0.08 * c.inr))
    stripes = []
    pitch = 4 * c.k
    for x in np.arange(-r_ring * 2, r_ring * 2, pitch):
        pts = _rotate(np.array([[x, -2 * r_ring], [x + pitch / 2, -2 * r_ring], [x + pitch / 2, 2 * r_ring], [x, 2 * r_ring]]), 45) + (0, y0)
        stripes.append(_poly(pts))
    hazard = _sk(ring & _union(stripes))
    height = max(2.0, 3 * c.k)
    cham = min(1.0, height / 3)
    cap = revolve(Plane.XZ * Polygon((0, 0), (r_btn, 0), (r_btn, height - cham), (r_btn - cham, height), (0, height), align=None), Axis.Z)
    ring_h = c.hgt(0.6)
    return Design("grey", [Layer("yellow", ring, ring_h), Layer("black", hazard, ring_h),
                           Layer("red", _circle(0, y0, r_btn), solids=[Pos(0, y0, 0) * cap])])


def _grass(c: Ctx) -> Design:
    """Tufts of upright blades (three thin plates each), with a few flowers."""
    flowers = c.scatter(max(1, int(c.area / 550)), 3 * c.k, 3 * c.k, 2.0)
    pads, tufts = [], []
    blade_w, blade_t = max(1.6, 1.8 * c.k), max(1.0, 1.0 * c.k)
    for x, y, _ in c.scatter(int(c.area / 60), 2.2 * c.k, 2.2 * c.k, -0.6 * c.k, avoid=flowers):
        # A fan of blades side by side along one direction, the outer ones leaning outwards.
        a0 = c.rng.uniform(0, 180)
        n = c.rng.randint(4, 5)
        blades = []
        for i in range(n):
            t = i / (n - 1) * 2 - 1  # -1 .. 1 across the fan
            hgt = c.rng.uniform(3.5, 6.0) * c.k * (1 - 0.25 * abs(t))
            lean = (1.6 * t + c.rng.uniform(-0.4, 0.4)) * c.k
            u = 0.9 * c.k * t
            bx, by = x + u * math.cos(math.radians(a0)), y + u * math.sin(math.radians(a0))
            twist = a0 + c.rng.uniform(-25, 25)
            blades.append(_fin([(-blade_w / 2, 0), (blade_w / 2, 0), (lean, hgt)], blade_t, twist, bx, by))
        tufts.append(_fuse(blades))
        pads.append(_circle(x, y, 0.9 * c.k + blade_w / 2 + 0.2))
    petals, hearts = [], []
    for x, y, _ in flowers:
        pr = max(0.8, 1.0 * c.k)
        petals += [_circle(x + 1.3 * pr * math.cos(a), y + 1.3 * pr * math.sin(a), pr) for a in np.radians(np.arange(5) * 72 + 90)]
        hearts.append(_circle(x, y, max(0.7, 0.8 * c.k)))
    return Design("green", [Layer("dark_green", _union(pads), solids=tufts),
                            Layer("white", _union(petals), c.hgt(1.6)), Layer("yellow", _union(hearts), c.hgt(2.2), taper=25)])


def _wood(c: Ctx) -> Design:
    rows = max(1, round(c.h / (10 * c.k)))
    pitch = c.h / rows
    seam_w = c.line(0.9)
    seams, grain, nails = [], [], []
    for j in range(rows + 1):
        y = -c.h / 2 + j * pitch
        seams.append(_rect(-c.w, y - seam_w / 2, c.w, y + seam_w / 2))
    for j in range(rows):
        y0 = -c.h / 2 + j * pitch
        joint = c.rng.uniform(-0.3, 0.3) * c.w
        seams.append(_rect(joint - seam_w / 2, y0, joint + seam_w / 2, y0 + pitch))
        for dx in (-2.2 * c.k, 2.2 * c.k):
            for dy in (0.27, 0.73):
                if c.inside(joint + dx, y0 + dy * pitch, 1.5):
                    nails.append(_circle(joint + dx, y0 + dy * pitch, max(0.7, 0.8 * c.k)))
        for _ in range(3):
            x0 = c.rng.uniform(-c.w / 2, c.w / 2 - 8 * c.k)
            length = c.rng.uniform(8, 18) * c.k
            yy = y0 + c.rng.uniform(0.3, 0.7) * pitch
            xs = np.linspace(x0, x0 + length, 30)
            ys = yy + 0.6 * c.k * np.sin((xs - x0) / length * 2 * math.pi * c.rng.uniform(0.5, 1.2))
            pts = np.column_stack([xs, ys])
            grain.append(_stroke(pts, np.maximum(0.5, 0.9 * np.sin(np.linspace(0, math.pi, 30)) ** 0.4)))
    return Design("wood", [Layer("dark_wood", _union(grain), height=-c.hgt(0.3)),
                           Layer("dark_wood", _union(seams), height=-c.hgt(0.6)),
                           Layer("dark_wood", _union(nails), c.hgt(0.5), taper=35)])


def _stones(c: Ctx, spacing: float, gap: float) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Random cobbles: shrunk Voronoi cells (gap apart) and the unshrunk ones."""
    seeds = np.array([(x, y) for x, y in c.grid(spacing, spacing * 0.9, stagger=True, jitter=spacing * 0.25)
                      if abs(x) < c.w / 2 + spacing and abs(y) < c.h / 2 + spacing])
    bound = max(c.w, c.h)
    return _voronoi_cells(seeds, gap, bound), _voronoi_cells(seeds, 0.0, bound)


def _cobblestone(c: Ctx) -> Design:
    cells, _ = _stones(c, 8 * c.k, c.line(1.2))
    grey, light = [], []
    for cell in cells:
        (light if c.rng.random() < 0.4 else grey).append(_poly(cell))
    joints = _sk(c.outline - _union(grey + light))
    bulge = c.hgt(0.8)
    return Design("grey", [Layer("grey", _union(grey), bulge, taper=30), Layer("light_grey", _union(light), bulge, taper=30),
                           Layer("dark_grey", joints, height=-c.hgt(0.4))])


def _ice(c: Ctx) -> Design:
    cracks = []
    for x, y, _ in c.scatter(max(3, int(c.area / 200)), 1.0, 1.0, 4 * c.k):
        angle = c.rng.uniform(0, 360)
        pts = [(x, y)]
        for _ in range(c.rng.randint(4, 7)):
            angle += c.rng.uniform(-40, 40)
            step = c.rng.uniform(2.5, 4.5) * c.k
            x, y = x + step * math.cos(math.radians(angle)), y + step * math.sin(math.radians(angle))
            pts.append((x, y))
            if c.rng.random() < 0.25:
                b = angle + c.rng.choice((-1, 1)) * c.rng.uniform(40, 70)
                length = c.rng.uniform(2, 4) * c.k
                cracks.append(_polyline([(x, y), (x + length * math.cos(math.radians(b)), y + length * math.sin(math.radians(b)))], MIN_LINE))
        cracks.append(_polyline(pts, MIN_LINE))
    shine = [_poly(_rotate(np.array([[-0.5, -2.5], [0.5, -2.5], [0.5, 2.5], [-0.5, 2.5]]) * max(1, c.k), 40) + (x, y))
             for x, y, _ in c.scatter(int(c.area / 400), 2.5 * c.k, 2.5 * c.k, 1.0)]
    return Design("ice", [Layer("light_blue", _union(shine), c.hgt(0.4)), Layer("white", _union(cracks), height=-c.hgt(0.6))])


def _lava(c: Ctx) -> Design:
    cells, full = _stones(c, 9 * c.k, c.line(1.8))
    rocks = _union([_poly(cell) for cell in cells])
    corners = {(round(x, 1), round(y, 1)) for cell in full for x, y in cell}
    bubbles = [_circle(x, y, max(0.9, 1.1 * c.k)) for x, y in sorted(corners)
               if c.inside(x, y, 1.5) and c.rng.random() < 0.35]
    return Design("orange", [Layer("dark_rock", rocks, c.hgt(1.5), taper=20),
                             Layer("yellow", _union(bubbles), c.hgt(0.6), taper=30)])


def _finish(c: Ctx) -> Design:
    nx, ny = max(2, round(c.w / (10 * c.k))), max(2, round(c.h / (10 * c.k)))
    cw, ch = c.w / nx, c.h / ny
    squares = [_rect(x, y, x + cw, y + ch)
               for j in range(ny) for i in range(nx) if (i + j) % 2 == 0
               for x, y in [(-c.w / 2 + i * cw, -c.h / 2 + j * ch)]]
    return Design("white", [Layer("black", _union(squares), c.hgt(0.5))])


def _arrow(c: Ctx) -> Design:
    s = 2 * c.inr
    pts = [(-0.11 * s, -0.4 * s), (0.11 * s, -0.4 * s), (0.11 * s, 0.02 * s), (0.3 * s, 0.02 * s), (0, 0.4 * s),
           (-0.3 * s, 0.02 * s), (-0.11 * s, 0.02 * s)]
    pts = [(x, y + c.cy) for x, y in pts]
    return Design("dark_grey", [Layer("yellow", _poly(pts), c.hgt(1.2), taper=10)])


def _portal(c: Ctx) -> Design:
    radius, y0 = 0.84 * c.inr, c.cy
    arms = []
    turns = 1.3 * math.pi
    t = np.linspace(0, 1, 60)
    for k in range(3):
        theta = 2 * math.pi * k / 3 + t * turns
        r = 0.12 * radius + t * 0.88 * radius
        pts = np.column_stack([r * np.cos(theta), y0 + r * np.sin(theta)])
        arms.append(_stroke(pts, np.maximum(MIN_LINE, (0.06 + 0.14 * t) * radius)))
    rim = _sk(_circle(0, y0, radius + max(1.5, 1.5 * c.k)) - _circle(0, y0, radius))
    return Design("dark_purple", [Layer("violet", _union(arms), c.hgt(1.0)), Layer("violet", rim, c.hgt(1.8)),
                                  Layer("white", _circle(0, y0, 0.14 * radius), c.hgt(2.2), taper=30)])


def _spiral_arms(radius: float, y0: float = 0.0) -> list[Sketch]:
    """Three spiral arms around (0, y0), widening outwards, reaching `radius`."""
    arms = []
    t = np.linspace(0, 1, 60)
    for k in range(3):
        theta = 2 * math.pi * k / 3 + t * 1.3 * math.pi
        r = 0.12 * radius + t * 0.88 * radius
        pts = np.column_stack([r * np.cos(theta), y0 + r * np.sin(theta)])
        arms.append(_stroke(pts, np.maximum(MIN_LINE, (0.06 + 0.14 * t) * radius)))
    return arms


def _portal_upright(c: Ctx) -> Design:
    """A standing ring, cut flat at the floor, with an opening down to the floor that a game
    piece can walk through; a thin white glow lines the opening. The round top of the opening
    needs supports when printed (or bridges with a little sag)."""
    radius = 0.85 * c.inr  # outside of the ring
    cz = 0.8 * radius  # centre of the ring above the floor
    r_in = 0.6 * radius  # the opening: round, with straight sides down to the floor
    lining = max(1.0, 0.08 * radius)
    t_ring = max(4.0, 5 * c.k)

    def opening(r):
        """Round-topped opening of radius r with straight sides down to the floor (its roof
        needs supports or bridges with a little sag)."""
        return [(r, 0.0)] + [(r * math.cos(t), cz + r * math.sin(t)) for t in np.linspace(0, math.pi, 48)] + [(-r, 0.0)]

    def slab(sketch, thickness):
        return extrude(Plane.XZ * sketch, amount=thickness / 2, both=True)

    outer = _sk(_circle(0, cz, radius, 96) & _rect(-radius, 0, radius, cz + radius))  # cut flat at the floor
    # Feet under the ring's outer bottom edges, where its underside gets steeper than 45 degrees.
    foot_x = radius * math.sin(math.radians(45))
    feet = _rect(-foot_x, 0, foot_x, cz - radius * math.cos(math.radians(45)))
    ring = slab(_sk(_union([outer, feet]) - _poly(opening(r_in + lining))), t_ring)
    glow = slab(_sk(_poly(opening(r_in + lining)) - _poly(opening(r_in))), t_ring)
    shift = Pos(0, c.cy, 0)
    half = radius * math.sqrt(1 - (cz / radius) ** 2)  # half the width of the ring at the floor
    footprint = _sk(_rect(-max(half, foot_x), c.cy - t_ring / 2, max(half, foot_x), c.cy + t_ring / 2)
                    - _rect(-r_in, c.cy - t_ring, r_in, c.cy + t_ring))
    swirl = _union(_spiral_arms(0.9 * r_in, 0.0))
    swirl = Pos(0, c.cy, 0) * swirl if swirl is not None else None
    return Design("dark_purple", [
        Layer("violet", swirl, c.hgt(0.4)),  # a small swirl on the floor in the opening
        Layer("violet", footprint, solids=[shift * ring]),
        Layer("white", None, solids=[shift * glow]),
    ])


def _pit(c: Ctx) -> Design:
    y0, r = c.cy, 0.6 * c.inr
    rim = _blob(0, y0, r + max(2.0, 2.5 * c.k), c.rng, 14, 0.08)
    cracks = []
    for a in np.linspace(0, 360, 7, endpoint=False) + c.rng.uniform(0, 50):
        a = math.radians(a + c.rng.uniform(-15, 15))
        rr = r + 1.5 * c.k
        pts = [(rr * math.cos(a), y0 + rr * math.sin(a))]
        heading = a
        for _ in range(c.rng.randint(3, 4)):
            heading += math.radians(c.rng.uniform(-35, 35))
            step = c.rng.uniform(1.6, 2.6) * c.k
            pts.append((pts[-1][0] + step * math.cos(heading), pts[-1][1] + step * math.sin(heading)))
        if c.inside(*pts[-1], 1.0):
            cracks.append(_polyline(pts, MIN_LINE))
    depth = min(c.hgt(1.5), c.p.thickness - c.p.inlay_depth - 1.0)
    return Design("grey", [Layer("dark_grey", rim, c.hgt(1.0), taper=30),
                           Layer("dark_grey", _union(cracks), height=-c.hgt(0.5)),
                           Layer("black", _blob(0, y0, r, c.rng, 14, 0.06), height=-depth)])


def _star_tile(c: Ctx) -> Design:
    y0, r = c.cy, 0.8 * c.inr
    big = _star(0, y0, r, 0.42 * r)
    sparkles = [_star(x, y, rr, 0.32 * rr, 4, 0) for x, y, rr in
                c.scatter(int(c.area / 400), 2.2 * max(1, c.k), 2.8 * max(1, c.k), 0.5, avoid=[(0, y0, r)])]
    return Design("blue", [Layer("white", _union(sparkles), c.hgt(0.6)), Layer("gold", big, c.hgt(1.5), taper=15)])


def _star_upright(c: Ctx) -> Design:
    """A star standing on its two lower points, bevelled on both faces like a gem, with a thin
    plinth in the notch between those points."""
    radius = 0.85 * c.inr
    # Inner corners at half the radius: then the undersides of the side points are no
    # steeper than 45 degrees, and the plinth fills the notch between the lower points.
    r_in = 0.5 * radius
    sink = min(0.5, c.p.thickness - 1.0)  # the lower points reach this far into the floor, to anchor the star
    tip_z = -radius * math.cos(math.radians(36))  # lower points, relative to the centre
    cz = -tip_z - sink
    thick = max(4.0, 5 * c.k)
    face = Plane.XZ * _star(0, cz, radius, r_in)
    half = extrude(face, amount=thick / 2)
    try:
        bevel = extrude(face, amount=thick / 2, taper=25)
        if bevel.is_valid and 0 < bevel.volume < half.volume and bevel.tessellate(0.05, 0.3)[1]:
            half = bevel
    except Exception:
        pass
    star = Part((half + mirror(half, Plane.XZ)).clean().wrapped)
    # A small, thin plinth low in the notch between the lower points (it braces them; the
    # points stand out in front of it on both faces).
    plinth_w = 0.5 * radius
    plinth_t = max(1.2, 0.3 * thick)
    plinth = extrude(Plane.XZ * _rect(-plinth_w, 0, plinth_w, 0.5 * (cz - r_in)), amount=plinth_t / 2, both=True) - star
    shift = Pos(0, c.cy, 0)
    tip_x = radius * math.sin(math.radians(36))
    pad = max(1.5, 0.12 * radius)
    sparkles = [_star(x, y, rr, 0.32 * rr, 4, 0) for x, y, rr in
                c.scatter(int(c.area / 400), 2.2 * max(1, c.k), 2.8 * max(1, c.k), 0.5,
                          avoid=[(x, c.cy, thick) for x in np.linspace(-tip_x - pad, tip_x + pad, 9)])]
    return Design("blue", [
        Layer("white", _union(sparkles), c.hgt(0.6)),
        Layer("blue", None, solids=[shift * plinth]),
        Layer("gold", None, solids=[shift * star]),
    ])


@dataclass
class TileType:
    title: str
    group: str
    build: Callable[[Ctx], Design]
    description: str


TILE_TYPES = {
    "earth": TileType("Earth", "Terrain", _earth, "brown soil with raised clods and stones"),
    "sand": TileType("Sand", "Terrain", _sand, "sand with raised wind ripples and pebbles"),
    "grass": TileType("Grass", "Terrain", _grass, "tufts of upright grass blades with a few flowers"),
    "asphalt": TileType("Asphalt", "Terrain", _asphalt, "flat road with gravel and a dashed centre line"),
    "cobblestone": TileType("Cobblestone", "Terrain", _cobblestone, "raised irregular cobbles with sunken joints"),
    "wood": TileType("Wooden floor", "Terrain", _wood, "planks with sunken seams and grain, raised nail heads"),
    "bricks": TileType("Bricks", "Terrain", _bricks, "brick wall in running bond with deep mortar joints"),
    "water": TileType("Water", "Elements", _water, "raised waves with white foam"),
    "rain": TileType("Rain", "Elements", _rain, "raised drops and streaks"),
    "ice": TileType("Ice", "Elements", _ice, "ice with sunken cracks and shine"),
    "fire": TileType("Fire", "Elements", _fire, "standing flames (crossed plates) and embers"),
    "lava": TileType("Lava", "Elements", _lava, "raised dark rock floating on glowing lava"),
    "spikes": TileType("Spikes", "Objects", _spikes, "a trap of raised steel spikes"),
    "door": TileType("Door (flat)", "Objects", _door, "trapdoor: raised planks and braces in a frame, gold handle and keyhole"),
    "door_upright": TileType("Door (upright)", "Objects", _door_upright,
                             "plank door in an arched frame as wide as the tile; gold knob on both sides"),
    "button": TileType("Button", "Objects", _button, "raised red push button in a hazard ring"),
    "pit": TileType("Pit", "Objects", _pit, "sunken black hole with a raised, cracked rim"),
    "arrow": TileType("Arrow", "Objects", _arrow, "raised direction or conveyor arrow, pointing to +Y"),
    "portal": TileType("Portal (flat)", "Objects", _portal, "raised swirling teleporter"),
    "portal_upright": TileType("Portal (upright)", "Objects", _portal_upright,
                               "standing ring that a game piece can walk through, with a glowing lining and a swirl on the floor"),
    "star": TileType("Star (flat)", "Objects", _star_tile, "raised gold star, for a bonus or goal"),
    "star_upright": TileType("Star (upright)", "Objects", _star_upright, "gem-bevelled gold star standing on its two lower points"),
    "finish": TileType("Finish", "Objects", _finish, "chequered start or finish"),
}


# --- Building ---

def validate(p: TileParams) -> None:
    if p.tile_type not in TILE_TYPES:
        raise ValueError(f"Unknown tile type '{p.tile_type}'; choose one of: {', '.join(TILE_TYPES)}.")
    if p.shape not in SHAPES:
        raise ValueError(f"Unknown shape '{p.shape}'; choose one of: {', '.join(SHAPES)}.")
    if not 15 <= p.size <= 200:
        raise ValueError("Tile size must be between 15 and 200 mm.")
    if p.shape == "rectangle" and not 15 <= p.length <= 200:
        raise ValueError("Tile length must be between 15 and 200 mm.")
    if p.thickness < 1.5:
        raise ValueError("Thickness must be at least 1.5 mm.")
    if not 0.2 <= p.inlay_depth <= p.thickness - 1.0:
        raise ValueError("Colour depth must be at least 0.2 mm and leave at least 1 mm of base below it.")
    if not 1 <= p.count <= MAX_COUNT:
        raise ValueError(f"Number of tiles must be between 1 and {MAX_COUNT}.")


def _raised(region: Sketch, height: float, taper: float) -> list[Part]:
    """`region` extruded up by `height`, with sides sloping inwards by `taper` degrees where the
    shape allows (a face too small for the slope keeps straight sides)."""
    if taper <= 0:
        return [extrude(region, amount=height)]
    out = []
    for face in region.faces():
        straight = extrude(face, amount=height)
        try:
            sloped = extrude(face, amount=height, taper=taper)
            # Sloped sides of long curvy bands can give faces that cannot be meshed (no 3MF/preview).
            if sloped.is_valid and 0 < sloped.volume < straight.volume and sloped.tessellate(0.05, 0.3)[1]:
                out.append(sloped)
                continue
        except Exception:
            pass
        out.append(straight)
    return out


def _bodies(p: TileParams, seed: int) -> dict[str, list[Part]]:
    """Solids of one tile centred on the origin (bottom at z = 0), by colour."""
    c = Ctx(p, seed)
    design = TILE_TYPES[p.tile_type].build(c)
    top, depth = p.thickness, p.inlay_depth
    # Clip every region to the tile, and let later layers cover earlier ones.
    regions = []
    for layer in design.layers:
        r = layer.region
        regions.append(_sk(c.outline & r) if r is not None and r.faces() else None)
    for i in range(len(regions)):
        later = _union(regions[i + 1:])
        if regions[i] is not None and later is not None:
            regions[i] = _sk(regions[i] - later)
    bodies: dict[str, list[Part]] = {design.base: []}
    cuts = []
    for layer, region in zip(design.layers, regions):
        parts = bodies.setdefault(layer.color, [])
        placed = [Pos(0, 0, top) * s for s in layer.solids]
        parts += placed
        if layer.color != design.base:  # solids reaching below the top (e.g. sunk star points) get room in the base
            cuts += [s for s in placed if s.bounding_box().min.Z < top - 1e-6]
        if region is None or not region.faces():
            continue
        h = layer.height
        if h > 0:
            parts += [Pos(0, 0, top) * s for s in _raised(region, h, layer.taper)]
        if layer.color == design.base:
            if h < 0:  # a groove in the base
                cuts.append(Pos(0, 0, top + h) * extrude(region, amount=-h))
            continue
        z0 = top - depth + min(h, 0.0)  # inlays are `depth` thick, also when sunk
        parts.append(Pos(0, 0, z0) * extrude(region, amount=depth))
        cuts.append(Pos(0, 0, z0) * extrude(region, amount=top - z0))
    base = extrude(c.outline, amount=top)
    if cuts:
        base = base - cuts  # (Solid.cut keeps only one solid when the result has several)
    bodies[design.base].insert(0, Part(base.wrapped))
    out = {}
    for name, parts in bodies.items():
        if not parts:
            continue
        try:  # one solid per colour where the pieces touch (inlay and the raised part on it)
            out[name] = [_fuse(parts)]
        except Exception:
            out[name] = parts
    return out


def _layout(p: TileParams) -> list[tuple[float, float]]:
    pts = outline_points(p)
    w, h = float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1]))
    n = 1
    while n * n < p.count:
        n += 1
    rows = math.ceil(p.count / n)
    out = []
    for i in range(p.count):
        row, col = divmod(i, n)
        out.append(((col - (n - 1) / 2) * (w + GRID_SPACING), ((rows - 1) / 2 - row) * (h + GRID_SPACING)))
    return out


def colors_used(p: TileParams) -> list[str]:
    """Colour names of the tile, base first (for the filament list)."""
    design = TILE_TYPES[p.tile_type].build(Ctx(p, p.seed))
    names = [design.base]
    for layer in design.layers:
        if layer.color not in names and (layer.region is not None or layer.solids):
            names.append(layer.color)
    return names


def build_tiles(p: TileParams) -> Compound:
    """All tiles in a grid, as one body per colour (labelled with the colour name)."""
    validate(p)
    by_color: dict[str, list[Part]] = {}
    for i, (x, y) in enumerate(_layout(p)):
        for name, solids in _bodies(p, p.seed * 1000 + i).items():
            by_color.setdefault(name, []).extend(Pos(x, y, 0) * s for s in solids)
    children = []
    for name, solids in by_color.items():
        body = Compound(children=[Part(s.wrapped) if not isinstance(s, Part) else s for s in solids])
        body.label, body.color = name, Color(*PALETTE[name])
        children.append(body)
    return Compound(children=children, label=f"game_tile_{p.tile_type}")


def describe(p: TileParams) -> str:
    t = TILE_TYPES[p.tile_type]
    if p.shape == "rectangle":
        dims = f"{p.size:g} x {p.length:g} mm"
    elif p.shape == "hexagon":
        dims = f"{p.size:g} mm across the flats"
    elif p.shape == "circle":
        dims = f"{p.size:g} mm diameter"
    else:
        dims = f"{p.size:g} mm sides"
    n = f"{p.count} tiles" if p.count > 1 else "Tile"
    colors = colors_used(p)
    return (f"{n}: {t.title.lower()}, {t.description}; {p.shape}, {dims}, {p.thickness:g} mm thick. "
            f"{len(colors)} colours: {', '.join(c.replace('_', ' ') for c in colors)} (base first).")


def main() -> None:
    ap = argparse.ArgumentParser(description="Multicolour game tile (STEP)")
    ap.add_argument("--type", default="earth", choices=list(TILE_TYPES))
    ap.add_argument("--shape", default="square", choices=SHAPES)
    ap.add_argument("--size", type=float, default=40.0)
    ap.add_argument("--length", type=float, default=60.0, help="rectangle length (mm)")
    ap.add_argument("--thickness", type=float, default=4.0)
    ap.add_argument("--inlay-depth", type=float, default=0.6)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="game_tile.step")
    a = ap.parse_args()
    p = TileParams(a.type, a.shape, a.size, a.length, a.thickness, a.inlay_depth, a.count, a.seed)
    export_step(build_tiles(p), a.out)
    print(describe(p))
    print(f"Wrote {a.out}")


if __name__ == "__main__":
    main()
