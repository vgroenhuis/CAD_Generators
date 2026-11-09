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

    The connector is no tile but a sleeve of the tile's shape, to join two tiles rigidly (one
    on top of a part of the same shape): a thin wall with a stop inside halfway up, so each
    tile goes in CONNECTOR_SOCKET deep from either side. The stop is a ledge along the walls
    (with gaps) or, the other type, a flat triangle across every inside corner, whose open
    edge the printer bridges. Thickness and colour depth don't
    apply to it.

    Can also be run standalone:  python game_tile_model.py --type bricks --shape hexagon --out tile.step
"""

from __future__ import annotations

import argparse
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from build123d import (
    Axis, Box, Color, Compound, Cylinder, Kind, Part, Plane, Polygon, Pos, Rectangle, Rot, Sketch, export_step, extrude, mirror,
    offset, revolve,
)

log = logging.getLogger("cad_generators.game_tiles")

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
    wall: float = 1.2  # connectors only: wall thickness
    clearance: float = 0.1  # connectors only: gap between tile and wall on every side


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


def _crack(c: Ctx, x: float, y: float, angle: float, steps: int, step: float, width: float = MIN_LINE,
           branch: float = 0.25, spread: float = 40) -> list[Sketch]:
    """A random crack: a wandering polyline from (x, y), with short side branches."""
    pts, out = [(x, y)], []
    for _ in range(steps):
        angle += c.rng.uniform(-spread, spread)
        s = c.rng.uniform(0.7, 1.3) * step
        x, y = x + s * math.cos(math.radians(angle)), y + s * math.sin(math.radians(angle))
        pts.append((x, y))
        if c.rng.random() < branch:
            b = math.radians(angle + c.rng.choice((-1, 1)) * c.rng.uniform(40, 70))
            length = c.rng.uniform(0.5, 1.0) * step
            out.append(_polyline([(x, y), (x + length * math.cos(b), y + length * math.sin(b))], width))
    out.append(_polyline(pts, width))
    return [s for s in out if s is not None]


def _arc(x: float, y: float, r: float, width: float, a0: float, a1: float) -> Sketch:
    """Band of `width` along a circular arc from a0 to a1 degrees (less than a full turn)."""
    a = np.radians(np.linspace(a0, a1, max(8, int(abs(a1 - a0) / 8))))
    return _stroke(np.column_stack([x + r * np.cos(a), y + r * np.sin(a)]), width)


def _shell(x: float, y: float, r: float, heading: float) -> tuple[Sketch, list[Sketch]]:
    """A scallop shell: fan with a wavy edge and two small ears at the hinge, plus its ribs."""
    t = np.radians(np.linspace(-70, 70, 40))
    rr = r * (1 + 0.06 * np.cos(9 * t))
    edge = np.column_stack([rr * np.cos(t), rr * np.sin(t)])
    ears = np.array([[0.05 * r, -0.35 * r], [-0.15 * r, -0.3 * r], [-0.15 * r, 0.3 * r], [0.05 * r, 0.35 * r]])
    outline = np.vstack([edge, ears[3:], ears[2:3], ears[1:2], ears[0:1]])
    shell = _poly(_rotate(outline, heading) + (x, y))
    ribs = [_polyline(_rotate(np.array([[0.25 * r, 0.0], [0.85 * r * math.cos(a), 0.85 * r * math.sin(a)]]), heading) + (x, y), 0.7)
            for a in np.radians([-40, 0, 40])]
    return shell, ribs


def _bird_tracks(c: Ctx, count: int) -> list[Sketch]:
    """A short trail of three-toed footprints."""
    x, y = c.rng.uniform(-0.3, 0.3) * c.w, c.rng.uniform(-0.3, 0.3) * c.h
    heading = c.rng.uniform(0, 360)
    toe = 1.5 * max(1, c.k)
    prints = []
    for i in range(count):
        heading += c.rng.uniform(-15, 15)
        hr = math.radians(heading)
        side = 1.2 * max(1, c.k) * (1 if i % 2 else -1)
        px, py = x + side * -math.sin(hr), y + side * math.cos(hr)
        if c.inside(px, py, 2.5 * toe):
            for d in (-35, 0, 35):
                a = math.radians(heading + d)
                prints.append(_polyline([(px, py), (px + toe * math.cos(a), py + toe * math.sin(a))], MIN_LINE))
        x, y = x + 3.2 * max(1, c.k) * math.cos(hr), y + 3.2 * max(1, c.k) * math.sin(hr)
    return prints


# --- Patterns: one function per tile type ---

def _earth(c: Ctx) -> Design:
    """Soil with dark clods, stones, small pebbles and dry cracks."""
    clod_xy = c.scatter(int(c.area / 80), 1.3 * c.k, 3.2 * c.k, 0.8)
    stone_xy = c.scatter(int(c.area / 220), 0.8 * c.k, 1.6 * c.k, 0.8, avoid=clod_xy)
    pebble_xy = c.scatter(int(c.area / 45), 0.45, 0.75 * max(1, c.k), 0.5, avoid=clod_xy + stone_xy)
    clods = [_blob(x, y, r, c.rng) for x, y, r in clod_xy]
    stones = [_blob(x, y, r, c.rng, 7, 0.2) for x, y, r in stone_xy]
    pebbles = [_blob(x, y, r, c.rng, 6, 0.15) for x, y, r in pebble_xy]
    cracks = []
    for x, y, _ in c.scatter(max(1, int(c.area / 700)), 1.0, 1.0, 8 * c.k):
        cracks += _crack(c, x, y, c.rng.uniform(0, 360), c.rng.randint(3, 5), 2.5 * c.k)
    return Design("brown", [Layer("dark_brown", _union(cracks), height=-c.hgt(0.4)),
                            Layer("dark_brown", _union(clods), c.hgt(1.0), taper=25),
                            Layer("grey", _union(stones), c.hgt(1.5), taper=20),
                            Layer("grey", _union(pebbles), c.hgt(0.6), taper=30)])


def _sand(c: Ctx) -> Design:
    """Wind ripples with pebbles, a few shells, crab holes with little mounds and bird tracks."""
    pitch = c.h / max(1, round(c.h / (6.5 * c.k)))  # whole number of ripples, so tiles join up
    wavelength = c.w / max(1, round(c.w / (16 * c.k)))
    x = np.linspace(-c.w / 2 - 2, c.w / 2 + 2, 80)
    ripples = []
    for j, y0 in enumerate(np.arange(-c.h / 2, c.h / 2 + pitch, pitch)):
        y = y0 + 1.4 * c.k * np.sin(2 * math.pi * x / wavelength + j * 1.3)
        ripples.append(_stroke(np.column_stack([x, y]), c.line(1.2)))
    shell_xy = c.scatter(max(1, int(c.area / 700)), 2.6 * c.k, 3.2 * c.k, 2.0)
    hole_xy = c.scatter(max(2, int(c.area / 450)), 1.5 * c.k, 1.5 * c.k, 2.0, avoid=shell_xy)
    dots = [_circle(x, y, r) for x, y, r in c.scatter(int(c.area / 140), 0.6, 0.9 * max(1, c.k), 1.0, avoid=shell_xy + hole_xy)]
    shells, ribs = [], []
    for x, y, r in shell_xy:
        s, rb = _shell(x, y, r, c.rng.uniform(0, 360))
        shells.append(s)
        ribs += rb
    hole_r = max(0.6, 0.6 * c.k)
    mounds = [_sk(_circle(x, y, 1.5 * c.k) - _circle(x, y, hole_r)) for x, y, _ in hole_xy]
    holes = [_circle(x, y, hole_r) for x, y, _ in hole_xy]
    return Design("sand", [Layer("tan", _union(ripples), c.hgt(0.6)),
                           Layer("tan", _union(_bird_tracks(c, 6)), height=-c.hgt(0.3)),
                           Layer("tan", _union(dots), c.hgt(0.5), taper=30),
                           Layer("tan", _union(mounds), c.hgt(0.5), taper=30),
                           Layer("sand", _union(holes), height=-c.hgt(0.8)),
                           Layer("white", _union(shells), c.hgt(0.9), taper=15),
                           Layer("white", _union(ribs), c.hgt(0.5))])


def _asphalt(c: Ctx) -> Design:
    """A flat road: a dashed centre line and solid edge lines."""
    width = max(1.2, 0.05 * c.s)
    dash = c.h / 4  # dashes of a quarter tile with equal gaps, centred on y = 0: they continue on the next tile
    line = [_rect(-width / 2, y - dash / 2, width / 2, y + dash / 2) for y in (-c.h / 2, 0, c.h / 2)]
    edge_x = c.w / 2 - 3 * c.k
    edges = [_rect(sx * edge_x - width / 2, -c.h, sx * edge_x + width / 2, c.h) for sx in (-1, 1)]
    return Design("asphalt", [Layer("white", _union(line + edges))])  # a flat road


def _wave(x, y, length, amplitude, width) -> Sketch:
    t = np.linspace(0, 1, 30)
    pts = np.column_stack([x + (t - 0.5) * length, y + amplitude * np.sin(2 * math.pi * t)])
    return _stroke(pts, np.maximum(0.6, width * np.sin(math.pi * t) ** 0.5))


def _water(c: Ctx) -> Design:
    """Waves with foam, ripple rings and a few lily pads (one with a flower)."""
    length, pitch_y = 11 * c.k, 6.5 * c.k
    pad_xy = c.scatter(max(1, int(c.area / 900)), 3.6 * c.k, 4.6 * c.k, 2.0)
    waves, foam = [], []
    for x, y in c.grid(length * 1.3, pitch_y, stagger=True, jitter=0.8 * c.k):
        if c.inside(x, y, 1.5 * c.k):  # waves may run off the edge (clipped)
            waves.append(_wave(x, y, length, 1.1 * c.k, c.line(1.5)))
            if c.rng.random() < 0.35 and c.inside(x + length * 0.28, y + 2.2 * c.k, 1.5):
                foam.append(_circle(x + length * 0.28, y + 2.2 * c.k, max(0.6, 0.7 * c.k)))
    rings = []
    for x, y, _ in c.scatter(max(1, int(c.area / 1000)), 5 * c.k, 5 * c.k, 1.0, avoid=pad_xy):
        for rr in (2.2 * c.k, 4.0 * c.k):
            a0 = c.rng.uniform(0, 360)
            rings += [_arc(x, y, rr, MIN_LINE, a0, a0 + 130), _arc(x, y, rr, MIN_LINE, a0 + 170, a0 + 320)]
    pads, veins, petals = [], [], []
    for i, (x, y, r) in enumerate(pad_xy):
        notch = c.rng.uniform(0, 360)
        pad = _sk(_circle(x, y, r) - _poly(_rotate(np.array([[0, 0], [1.3 * r, -0.35 * r], [1.3 * r, 0.35 * r]]), notch) + (x, y)))
        pads.append(pad)
        veins += [_polyline([(x, y), (x + 0.8 * r * math.cos(math.radians(a)), y + 0.8 * r * math.sin(math.radians(a)))], 0.8)
                  for a in notch + np.array([60, 120, 180, 240, 300])]
        if i == 0:
            pr = max(0.8, 0.9 * c.k)
            petals += [_circle(x - 0.3 * r + 1.1 * pr * math.cos(a), y + 1.1 * pr * math.sin(a), pr) for a in np.radians(np.arange(6) * 60)]
    return Design("blue", [Layer("light_blue", _union(waves), c.hgt(0.8), taper=15),
                           Layer("light_blue", _union(rings), c.hgt(0.5)),
                           Layer("white", _union(foam), c.hgt(1.0), taper=25),
                           Layer("green", _union(pads), c.hgt(1.0), taper=15),
                           Layer("green", _union(veins), c.hgt(0.6)),
                           Layer("white", _union(petals), c.hgt(1.8), taper=20)])


def _rain(c: Ctx) -> Design:
    """Drops and streaks, puddles with splash rings."""
    pitch = 8 * c.k
    puddle_xy = c.scatter(max(1, int(c.area / 900)), 4.0 * c.k, 5.5 * c.k, 3.0)
    drops, streaks = [], []
    for x, y in c.grid(pitch, pitch, stagger=True, jitter=1.2 * c.k):
        if c.inside(x, y, 3.2 * c.k) and all(math.hypot(x - a, y - b) > r + 3 * c.k for a, b, r in puddle_xy):
            drops.append(_poly(_teardrop(x, y, 1.3 * c.k, 3.4 * c.k, 110)))
        xs, ys = x + pitch / 2, y + pitch / 4
        if c.rng.random() < 0.6 and c.inside(xs, ys, 2.6 * c.k):
            d = _rotate(np.array([[0.0, -2.2 * c.k], [0.0, 2.2 * c.k]]), 20) + (xs, ys)
            streaks.append(_polyline(d, MIN_LINE))
    puddles = [_blob(x, y, r, c.rng, 12, 0.15) for x, y, r in puddle_xy]
    rings = []
    for x, y, r in puddle_xy:
        for rr in (0.35 * r, 0.7 * r):
            a0 = c.rng.uniform(0, 360)
            rings += [_arc(x, y, rr, MIN_LINE, a0, a0 + 150), _arc(x, y, rr, MIN_LINE, a0 + 190, a0 + 330)]
    sunk = c.hgt(0.6)
    return Design("slate", [Layer("slate", _union(puddles), height=-sunk),
                            Layer("light_blue", _union(rings), height=-sunk + 0.3),
                            Layer("white", _union(streaks), c.hgt(0.6)),
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
    """Flames as crossed upright plates (orange outside, a smaller yellow core crossing them),
    charcoal chunks around their feet and glowing embers."""
    pads, oranges, yellows = [], [], []
    thick = max(1.2, 1.6 * c.k)
    flame_xy = c.scatter(max(1, int(c.area / 260)), 3.0 * c.k, 4.4 * c.k, 1.5 * c.k)
    for x, y, r in flame_xy:
        a0 = c.rng.uniform(0, 90)
        outer = [_fin(_flame_profile(r, c.rng.uniform(-1, 1)), thick, a0 + 90 * i, x, y) for i in range(2)]
        inner = [_fin(_flame_profile(0.62 * r, c.rng.uniform(-0.6, 0.6)), thick * 2.2, a0 + 45 + 90 * i, x, y) for i in range(2)]
        core = _fuse(inner)
        oranges.append(Part((_fuse(outer) - core).wrapped))
        yellows.append(core)
        pads.append(_circle(x, y, r))
    coal = []
    for x, y, r in flame_xy:
        for _ in range(c.rng.randint(2, 3)):
            a = c.rng.uniform(0, 2 * math.pi)
            d = r + 1.6 * c.k
            cx, cy = x + d * math.cos(a), y + d * math.sin(a)
            if c.inside(cx, cy, 1.8 * c.k):
                coal.append(_blob(cx, cy, c.rng.uniform(1.0, 1.5) * c.k, c.rng, 6, 0.25))
    coal_xy = [(x, y, r + 2.5 * c.k) for x, y, r in flame_xy]
    embers = [_circle(x, y, r) for x, y, r in c.scatter(int(c.area / 160), 0.6, 0.9, 1.0, avoid=coal_xy)]
    return Design("dark_red", [Layer("dark_grey", _union(coal), c.hgt(1.0), taper=20),
                               Layer("orange", _union(pads), solids=oranges), Layer("yellow", None, solids=yellows),
                               Layer("orange", _union(embers), c.hgt(0.8), taper=30)])


def _bricks(c: Ctx) -> Design:
    """Running bond with deep mortar joints; some bricks darker, some sticking out a little,
    some with chipped corners, and small pits in the surface."""
    rows = max(2, round(c.h / (8 * c.k)))
    row_h = c.h / rows
    per_row = max(1, round(c.w / (2 * row_h)))
    brick_w = c.w / per_row
    mortar = c.line(1.2)
    bricks, dark, proud, proud_dark = [], [], [], []
    for j in range(rows):
        y = -c.h / 2 + (j + 0.5) * row_h
        shift = brick_w / 2 if j % 2 else 0.0
        for i in range(-1, per_row + 1):
            x = -c.w / 2 + (i + 0.5) * brick_w + shift
            x0, y0 = x - brick_w / 2 + mortar / 2, y - row_h / 2 + mortar / 2
            x1, y1 = x + brick_w / 2 - mortar / 2, y + row_h / 2 - mortar / 2
            b = _rect(x0, y0, x1, y1)
            if c.rng.random() < 0.3:  # a chipped corner
                cx, cy = c.rng.choice([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
                chip = c.rng.uniform(1.5, 2.5) * c.k
                sx, sy = (1 if cx == x0 else -1), (1 if cy == y0 else -1)
                b = _sk(b - _poly([(cx, cy), (cx + sx * chip, cy), (cx, cy + sy * chip)]))
            is_dark = c.rng.random() < 0.25
            (dark if is_dark else bricks).append(b)
            if c.rng.random() < 0.2:
                (proud_dark if is_dark else proud).append(b)
    joints = _sk(c.outline - _union(bricks + dark))
    plain = _union(bricks)
    pits = [_circle(x, y, 0.45) for x, y, _ in c.scatter(int(c.area / 60), 0.5, 0.5, 0.8)]
    pits = _sk(_union(pits) & plain) if pits and plain is not None else None
    lift = c.hgt(0.4)
    return Design("brick", [Layer("brick", _union(proud), lift), Layer("dark_brick", _union(dark)),
                            Layer("dark_brick", _union(proud_dark), lift),
                            Layer("brick", pits, height=-c.hgt(0.3)),
                            Layer("light_grey", joints, height=-c.hgt(1.2))])


def _spikes(c: Ctx) -> Design:
    """Steel spikes on plates, on a floor of diamond tread plate."""
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
    tread, step = [], 3.5 * c.k
    for j, y in enumerate(np.arange(-c.h / 2, c.h / 2 + step, step)):
        for i, x in enumerate(np.arange(-c.w / 2, c.w / 2 + step, step)):
            ang = 45 if (i + j) % 2 else -45
            seg = _rotate(np.array([[-1.1 * c.k, 0.0], [1.1 * c.k, 0.0]]), ang) + (x, y)
            tread.append(_polyline(seg, MIN_LINE))
    return Design("dark_grey", [Layer("dark_grey", _union(tread), c.hgt(0.4)),
                                Layer("steel", _union(plates), solids=spikes)])


def _door(c: Ctx) -> Design:
    """Door lying flat (a trapdoor): raised planks with grain and braces in a frame, black iron
    hinge straps with rivets, gold handle and keyhole."""
    frame = max(2.0, 3 * c.k)
    inner = _sk(offset(c.outline, -frame))
    planks, gap = 4, c.line(1.0)
    plank_w = (c.w - 2 * frame) / planks
    strips, grain = [], []
    for i in range(planks):
        x0 = -c.w / 2 + frame + i * plank_w
        strips.append(_rect(x0 + gap / 2, -c.h, x0 + plank_w - gap / 2, c.h))
        for _ in range(2):
            gx = x0 + c.rng.uniform(0.25, 0.75) * plank_w
            ys = np.linspace(-c.h / 2, c.h / 2, 40)
            xs = gx + 0.5 * c.k * np.sin(ys / (c.rng.uniform(5, 9) * c.k) + c.rng.uniform(0, 6))
            grain.append(_stroke(np.column_stack([xs, ys]), 0.8))
    brace_h = 0.1 * c.h
    brace_y = (-0.27 * c.h, 0.27 * c.h)
    braces = _union([_rect(-c.w, y - brace_h / 2, c.w, y + brace_h / 2) for y in brace_y])
    wood = _sk(_sk(inner & _union(strips)) - braces)
    seams = _sk(inner - _union(strips) - braces)
    plank_h, brace_top = c.hgt(0.6), c.hgt(1.4)
    r = 2.4 * c.k
    # The handle and keyhole halfway to the edge, where the tile is wide enough for them
    # (a triangle narrows towards the top).
    hx = min((c.w / 2 - frame) * 0.55, _half_width(c, -7.5 * c.k, r) - frame - r - 1.0)
    knob_h = max(1.5, 2.2 * c.k) + plank_h
    knob = Pos(hx, 0, 0) * revolve(Plane.XZ * Polygon((0, 0), (r, 0), (r, knob_h - 0.6), (r - 0.6, knob_h), (0, knob_h), align=None), Axis.Z)
    keyhole = _union([_circle(hx, -5 * c.k, max(0.8, 0.9 * c.k)),
                      _poly([(hx - 0.5 * max(1, c.k), -5 * c.k), (hx + 0.5 * max(1, c.k), -5 * c.k),
                             (hx + 0.8 * max(1, c.k), -7.5 * c.k), (hx - 0.8 * max(1, c.k), -7.5 * c.k)])])
    strap_x0, strap_x1 = -c.w / 2 + frame - 1.0, -c.w / 2 + frame + 0.45 * (c.w - 2 * frame)
    straps = _union([_rect(strap_x0, y - 0.3 * brace_h, strap_x1, y + 0.3 * brace_h) for y in brace_y])
    rivets = _union([_circle(x, y, max(0.6, 0.6 * c.k)) for y in brace_y
                     for x in np.linspace(strap_x0 + 2 * c.k, strap_x1 - 1.5 * c.k, 3)])
    return Design("dark_brown", [
        Layer("wood", wood, plank_h), Layer("dark_brown", _sk(wood & _union(grain)) if grain else None, plank_h - 0.3),
        Layer("dark_brown", seams, height=-0.6),
        Layer("dark_brown", _sk(inner & braces), brace_top, taper=20),
        Layer("black", straps, brace_top + 0.3), Layer("black", rivets, brace_top + 0.7, taper=30),
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
    # Black iron hinge straps on both faces, from the hinge side two thirds across the door.
    strap_len, strap_h, strap_t = 0.62 * leaf_w, max(1.6, 2.0 * c.k), 0.6
    straps = [Pos(-leaf_w / 2 + strap_len / 2, side * (t_leaf / 2 + strap_t / 2 - 0.1), z) * Box(strap_len, strap_t + 0.2, strap_h)
              for z in (0.22 * height, 0.62 * height) for side in (-1, 1)]
    straps = _fuse(straps) - knob
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
        Layer("black", None, solids=[shift * keyhole, shift * Part(straps.wrapped)]),
    ])


def _button(c: Ctx) -> Design:
    """Raised red push button in a yellow and black hazard ring, on a plate held by four screws."""
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
    screw_r = max(1.0, 1.3 * c.k)
    screws = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            # In the corners of a square tile; elsewhere on a circle around the button.
            x, y = sx * (c.w / 2 - 3.2 * c.k), y0 + sy * (c.h / 2 - 3.2 * c.k)
            if not c.inside(x, y, screw_r + 0.8) or math.hypot(x, y - y0) < r_ring + screw_r + 1:
                d = 0.86 * c.inr
                x, y = sx * d / math.sqrt(2), y0 + sy * d / math.sqrt(2)
            if c.inside(x, y, screw_r + 0.5):
                slot = _poly(_rotate(np.array([[-screw_r, -0.35], [screw_r, -0.35], [screw_r, 0.35], [-screw_r, 0.35]]),
                                     c.rng.uniform(0, 180)) + (x, y))
                screws.append(_sk(_circle(x, y, screw_r) - slot))
    return Design("grey", [Layer("black", _union(screws), c.hgt(0.5), taper=20),
                           Layer("yellow", ring, ring_h), Layer("black", hazard, ring_h),
                           Layer("red", _circle(0, y0, r_btn), solids=[Pos(0, y0, 0) * cap])])


def _grass(c: Ctx) -> Design:
    """Tufts of upright blades, some low patches of clover and a few flowers."""
    flowers = c.scatter(max(1, int(c.area / 550)), 3 * c.k, 3 * c.k, 2.0)
    clover_xy = c.scatter(max(1, int(c.area / 700)), 3.5 * c.k, 3.5 * c.k, 1.0, avoid=flowers)
    pads, tufts = [], []
    blade_w, blade_t = max(1.6, 1.8 * c.k), max(1.0, 1.0 * c.k)
    # The margin keeps the outer blades, which lean outwards, inside the tile.
    for x, y, _ in c.scatter(int(c.area / 60), 2.2 * c.k, 2.2 * c.k, -0.6 * c.k, margin=2.0 * c.k, avoid=flowers + clover_xy):
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
    clover = []
    for x, y, r in clover_xy:
        for _ in range(c.rng.randint(3, 5)):  # a little patch of three-leaf clovers
            cx, cy = x + c.rng.uniform(-0.6, 0.6) * r, y + c.rng.uniform(-0.6, 0.6) * r
            lr, a0 = max(0.75, 0.8 * c.k), c.rng.uniform(0, 120)
            clover += [_circle(cx + lr * math.cos(math.radians(a0 + 120 * k)), cy + lr * math.sin(math.radians(a0 + 120 * k)), lr)
                       for k in range(3)]
    petals, hearts = [], []
    for x, y, _ in flowers:
        pr = max(0.8, 1.0 * c.k)
        petals += [_circle(x + 1.3 * pr * math.cos(a), y + 1.3 * pr * math.sin(a), pr) for a in np.radians(np.arange(5) * 72 + 90)]
        hearts.append(_circle(x, y, max(0.7, 0.8 * c.k)))
    return Design("green", [Layer("dark_green", _union(clover), c.hgt(0.5), taper=20),
                            Layer("dark_green", _union(pads), solids=tufts),
                            Layer("white", _union(petals), c.hgt(1.6)), Layer("yellow", _union(hearts), c.hgt(2.2), taper=25)])


def _wood(c: Ctx) -> Design:
    """Planks (some a little higher than others) with sunk seams and grain, knots and raised nail heads."""
    rows = max(1, round(c.h / (10 * c.k)))
    pitch = c.h / rows
    seam_w = c.line(0.9)
    seams, grain, nails, knots, high = [], [], [], [], []
    for j in range(rows + 1):
        y = -c.h / 2 + j * pitch
        seams.append(_rect(-c.w, y - seam_w / 2, c.w, y + seam_w / 2))
    for j in range(rows):
        y0 = -c.h / 2 + j * pitch
        joint = c.rng.uniform(-0.3, 0.3) * c.w
        seams.append(_rect(joint - seam_w / 2, y0, joint + seam_w / 2, y0 + pitch))
        for xa, xb in ((-c.w, joint), (joint, c.w)):
            if c.rng.random() < 0.4:
                high.append(_rect(xa, y0, xb, y0 + pitch))
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
        if c.rng.random() < 0.6:  # a knot: an oval ring around a dark centre
            kx = c.rng.uniform(-0.4, 0.4) * c.w
            if abs(kx - joint) > 5 * c.k and c.inside(kx, y0 + pitch / 2, 3 * c.k):
                ky, rx, ry = y0 + pitch / 2, 2.4 * c.k, max(1.4, 1.5 * c.k)
                a = np.linspace(0, 2 * math.pi, 40, endpoint=False)
                outer = _poly(np.column_stack([kx + rx * np.cos(a), ky + ry * np.sin(a)]))
                inner = _poly(np.column_stack([kx + (rx - 0.8) * np.cos(a), ky + (ry - 0.8) * np.sin(a)]))
                knots += [_sk(outer - inner), _poly(np.column_stack([kx + 0.45 * rx * np.cos(a), ky + 0.4 * ry * np.sin(a)]))]
    return Design("wood", [Layer("wood", _union(high), c.hgt(0.25)),
                           Layer("dark_wood", _union(grain), height=-c.hgt(0.3)),
                           Layer("dark_wood", _union(knots), height=-c.hgt(0.3)),
                           Layer("dark_wood", _union(seams), height=-c.hgt(0.6)),
                           Layer("dark_wood", _union(nails), c.hgt(0.5), taper=35)])


def _stones(c: Ctx, spacing: float, gap: float) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Random cobbles: shrunk Voronoi cells (gap apart) and the unshrunk ones."""
    seeds = np.array([(x, y) for x, y in c.grid(spacing, spacing * 0.9, stagger=True, jitter=spacing * 0.25)
                      if abs(x) < c.w / 2 + spacing and abs(y) < c.h / 2 + spacing])
    bound = max(c.w, c.h)
    return _voronoi_cells(seeds, gap, bound), _voronoi_cells(seeds, 0.0, bound)


def _cobblestone(c: Ctx) -> Design:
    """Cobbles in two shades with sunk joints and moss growing in some of the joints. Each
    stone has steeply sloping sides and a small top; the rough surface (see ROUGHNESS) makes
    every stone uneven."""
    cells, _ = _stones(c, 8 * c.k, c.line(1.2))
    grey, light = [], []
    for cell in cells:
        (light if c.rng.random() < 0.4 else grey).append(_poly(cell))
    joints = _sk(c.outline - _union(grey + light))
    moss = [_blob(x, y, r, c.rng, 10, 0.35) for x, y, r in c.scatter(max(1, int(c.area / 500)), 1.8 * c.k, 2.6 * c.k, 3.0)]
    moss = _sk(_union(moss) & joints) if moss else None
    bulge = c.hgt(1.1)
    return Design("grey", [Layer("grey", _union(grey), bulge, taper=40), Layer("light_grey", _union(light), bulge, taper=40),
                           Layer("dark_grey", joints, height=-c.hgt(0.4)),
                           Layer("green", moss, height=-c.hgt(0.2))])


def _ice(c: Ctx) -> Design:
    """Ice with sunk cracks, shine, trapped air bubbles, frost specks and snow drifts at the edges."""
    cracks = []
    for x, y, _ in c.scatter(max(3, int(c.area / 200)), 1.0, 1.0, 4 * c.k):
        cracks += _crack(c, x, y, c.rng.uniform(0, 360), c.rng.randint(4, 7), 3.5 * c.k)
    shine = [_poly(_rotate(np.array([[-0.5, -2.5], [0.5, -2.5], [0.5, 2.5], [-0.5, 2.5]]) * max(1, c.k), 40) + (x, y))
             for x, y, _ in c.scatter(int(c.area / 400), 2.5 * c.k, 2.5 * c.k, 1.0)]
    bubbles = []
    for x, y, _ in c.scatter(max(1, int(c.area / 600)), 2.5 * c.k, 2.5 * c.k, 2.0):
        bubbles += [_circle(x + c.rng.uniform(-2, 2) * c.k, y + c.rng.uniform(-2, 2) * c.k, c.rng.uniform(0.5, 0.9)) for _ in range(4)]
    frost = [_circle(x, y, r) for x, y, r in c.scatter(int(c.area / 50), 0.45, 0.6, 0.8)]
    drifts = []
    for _ in range(60):  # snow piled up against the edge in a couple of places
        if len(drifts) >= max(1, int(c.area / 800)):
            break
        x, y = c.rng.uniform(-c.w / 2, c.w / 2), c.rng.uniform(-c.h / 2, c.h / 2)
        if c.inside(x, y, 0.5) and not c.inside(x, y, 2.5 * c.k):
            drifts.append(_blob(x, y, c.rng.uniform(3.5, 5.0) * c.k, c.rng, 12, 0.2))
    return Design("ice", [Layer("white", _union(frost)), Layer("light_blue", _union(shine), c.hgt(0.4)),
                          Layer("light_blue", _union(bubbles), height=-c.hgt(0.3)),
                          Layer("white", _union(cracks), height=-c.hgt(0.6)),
                          Layer("white", _union(drifts), c.hgt(0.9), taper=25)])


def _lava(c: Ctx) -> Design:
    """Dark rock plates floating on glowing lava; the plates have glowing cracks, the lava bubbles."""
    cells, full = _stones(c, 9 * c.k, c.line(1.8))
    corners = {(round(x, 1), round(y, 1)) for cell in full for x, y in cell}
    bubbles = [_circle(x, y, max(0.9, 1.1 * c.k)) for x, y in sorted(corners)
               if c.inside(x, y, 1.5) and c.rng.random() < 0.35]
    rock_h, groove = c.hgt(1.5), c.hgt(0.5)
    rocks, glows, cut_rocks = [], [], []
    for cell in cells:
        region = _sk(c.outline & _poly(cell))
        if not region.faces():
            continue
        rocks.append(region)
        # Each rock as a solid with sloping sides; glowing cracks are cut into its top
        # afterwards (cutting them into the outline first would give awkward sloped faces).
        rock = _fuse(_raised(region, rock_h, 20))
        size = float(np.ptp(cell[:, 0]) + np.ptp(cell[:, 1])) / 2
        if size > 5 * c.k and c.rng.random() < 0.7:
            x, y = cell.mean(axis=0)
            crack = _union(_crack(c, x, y, c.rng.uniform(0, 360), 2, 0.3 * size, branch=0.3, spread=35))
            crack = _sk(crack & _poly(centre_shrink(cell, 0.8)) & region) if crack is not None else None  # inside the rock and the tile
            if crack is not None and crack.faces():
                slot = Pos(0, 0, rock_h - groove) * extrude(crack, amount=groove + 1)
                rock = Part((rock - slot).wrapped)
                glows.append(Pos(0, 0, rock_h - groove) * extrude(crack, amount=groove - 0.2))
        cut_rocks.append(rock)
    return Design("orange", [Layer("dark_rock", _union(rocks), solids=cut_rocks),
                             Layer("orange", None, solids=glows),
                             Layer("yellow", _union(bubbles), c.hgt(0.6), taper=30)])


def centre_shrink(cell: np.ndarray, factor: float) -> np.ndarray:
    """A convex polygon scaled about its centre."""
    centre = cell.mean(axis=0)
    return centre + factor * (cell - centre)


def _finish(c: Ctx) -> Design:
    nx, ny = max(2, round(c.w / (10 * c.k))), max(2, round(c.h / (10 * c.k)))
    cw, ch = c.w / nx, c.h / ny
    squares = [_rect(x, y, x + cw, y + ch)
               for j in range(ny) for i in range(nx) if (i + j) % 2 == 0
               for x, y in [(-c.w / 2 + i * cw, -c.h / 2 + j * ch)]]
    return Design("white", [Layer("black", _union(squares), c.hgt(0.5))])


def _arrow(c: Ctx) -> Design:
    """Raised arrow on a conveyor belt: grooves across the belt and a raised rail on each side."""
    s = 2 * c.inr
    pts = [(-0.11 * s, -0.4 * s), (0.11 * s, -0.4 * s), (0.11 * s, 0.02 * s), (0.3 * s, 0.02 * s), (0, 0.4 * s),
           (-0.3 * s, 0.02 * s), (-0.11 * s, 0.02 * s)]
    pts = [(x, y + c.cy) for x, y in pts]
    step = 3.5 * c.k
    grooves = [_rect(-c.w, y - 0.5, c.w, y + 0.5) for y in np.arange(-c.h / 2, c.h / 2 + step, step)]
    rail = max(1.5, 2 * c.k)
    rails = [_rect(sx * c.w / 2 - rail, -c.h, sx * c.w / 2 + rail, c.h) for sx in (-1, 1)] if c.p.shape in ("square", "rectangle") else []
    return Design("dark_grey", [Layer("dark_grey", _union(grooves), height=-c.hgt(0.4)),
                                Layer("dark_grey", _union(rails), c.hgt(1.0)),
                                Layer("yellow", _poly(pts), c.hgt(1.2), taper=10)])


def _portal(c: Ctx) -> Design:
    """Swirling teleporter: raised spiral arms and rim, white centre, white runes around it."""
    radius, y0 = 0.84 * c.inr, c.cy
    rim_w = max(1.5, 1.5 * c.k)
    rim = _sk(_circle(0, y0, radius + rim_w) - _circle(0, y0, radius))
    runes = []
    rr = radius + rim_w + 2.2 * c.k
    for k, a in enumerate(np.linspace(0, 360, 12, endpoint=False)):
        x, y = rr * math.cos(math.radians(a)), y0 + rr * math.sin(math.radians(a))
        if not c.inside(x, y, 1.6 * c.k):
            continue
        if k % 3 == 0:
            runes.append(_circle(x, y, max(0.7, 0.8 * c.k)))
        else:  # a short tick, alternately along and across the circle
            d = 1.2 * c.k
            ang = a + (90 if k % 3 == 1 else 0)
            runes.append(_polyline(_rotate(np.array([[-d, 0.0], [d, 0.0]]), ang) + (x, y), MIN_LINE))
    return Design("dark_purple", [Layer("violet", _union(_spiral_arms(radius, y0)), c.hgt(1.0)), Layer("violet", rim, c.hgt(1.8)),
                                  Layer("white", _union(runes), c.hgt(0.6)),
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
    """A standing arch of even width around an opening down to the floor that a game piece can
    walk through; a thin white glow lines the opening and white gems are set into the arch,
    showing on both faces. The round top of the opening needs supports when printed (or
    bridges with a little sag)."""
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

    # The outside follows the opening (round top, straight sides), so the band is equally wide all round.
    ring = slab(_sk(_poly(opening(radius)) - _poly(opening(r_in + lining))), t_ring)
    glow = slab(_sk(_poly(opening(r_in + lining)) - _poly(opening(r_in))), t_ring)
    mid = (radius + r_in + lining) / 2  # middle of the band
    gem_r = max(0.9, 0.22 * (radius - r_in - lining))
    spots = [(mid * math.cos(math.radians(a)), cz + mid * math.sin(math.radians(a))) for a in (30, 90, 150)]
    spots += [(sx * mid, 0.4 * cz) for sx in (-1, 1)]
    gems = _fuse([Pos(x, 0, z) * Rot(90, 0, 0) * Cylinder(gem_r, t_ring + 1.0) for x, z in spots])
    ring = ring - gems
    shift = Pos(0, c.cy, 0)
    footprint = _sk(_rect(-radius, c.cy - t_ring / 2, radius, c.cy + t_ring / 2)
                    - _rect(-r_in - lining, c.cy - t_ring, r_in + lining, c.cy + t_ring))
    swirl = _union(_spiral_arms(0.9 * r_in, 0.0))
    swirl = Pos(0, c.cy, 0) * swirl if swirl is not None else None
    # An old flagstone floor with sunk joints (made uneven by the rough surface, see ROUGHNESS).
    pitch, joint = 9 * c.k, c.line(1.0)
    flags = [_rect(-c.w, y - joint / 2, c.w, y + joint / 2) for y in np.arange(-c.h, c.h, pitch)]
    for j, y in enumerate(np.arange(-c.h, c.h, pitch)):
        flags += [_rect(x - joint / 2, y, x + joint / 2, y + pitch) for x in np.arange(-c.w, c.w, pitch) + (pitch / 2 if j % 2 else 0)]
    return Design("dark_purple", [
        Layer("dark_purple", _union(flags), height=-c.hgt(0.6)),
        Layer("violet", swirl, c.hgt(0.4)),  # a small swirl on the floor in the opening
        Layer("violet", footprint, solids=[shift * ring]),
        Layer("white", None, solids=[shift * glow, shift * gems]),
    ])


def _pit(c: Ctx) -> Design:
    """Sunk black hole with a raised, cracked rim, rubble around it and a pair of eyes in the dark."""
    y0, r = c.cy, 0.6 * c.inr
    rim_r = r + max(2.0, 2.5 * c.k)
    rim = _blob(0, y0, rim_r, c.rng, 14, 0.08)
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
    rubble = []
    for _ in range(40):
        if len(rubble) >= 8:
            break
        a, d = c.rng.uniform(0, 2 * math.pi), rim_r + c.rng.uniform(1.0, 5.0) * c.k
        x, y = d * math.cos(a), y0 + d * math.sin(a)
        rad = c.rng.uniform(0.6, 1.2) * c.k
        if c.inside(x, y, rad + 0.5):
            rubble.append(_blob(x, y, rad, c.rng, 6, 0.25))
    depth = min(c.hgt(1.5), c.p.thickness - c.p.inlay_depth - 1.0)
    eye = max(0.7, 0.9 * c.k)
    a = np.linspace(0, 2 * math.pi, 16, endpoint=False)
    eyes = _union([_poly(np.column_stack([sx * 1.8 * c.k + eye * 1.3 * np.cos(a), y0 + 0.5 * c.k + eye * 0.75 * np.sin(a)]))
                   for sx in (-1, 1)])
    return Design("grey", [Layer("dark_grey", rim, c.hgt(1.0), taper=30),
                           Layer("dark_grey", _union(cracks), height=-c.hgt(0.5)),
                           Layer("dark_grey", _union(rubble), c.hgt(0.8), taper=25),
                           Layer("black", _blob(0, y0, r, c.rng, 14, 0.06), height=-depth),
                           Layer("yellow", eyes, height=-depth)])


def _star_tile(c: Ctx) -> Design:
    """Raised gold star with a higher inner star (a cut gem), sparkles and tiny distant stars."""
    y0, r = c.cy, 0.8 * c.inr
    big = _star(0, y0, r, 0.42 * r)
    core = _star(0, y0, 0.55 * r, 0.55 * 0.42 * r)
    sparkle_xy = c.scatter(int(c.area / 400), 2.2 * max(1, c.k), 2.8 * max(1, c.k), 0.5, avoid=[(0, y0, r)])
    sparkles = [_star(x, y, rr, 0.32 * rr, 4, 0) for x, y, rr in sparkle_xy]
    dots = [_circle(x, y, rr) for x, y, rr in c.scatter(int(c.area / 120), 0.45, 0.6, 1.5, avoid=[(0, y0, r)] + sparkle_xy)]
    return Design("blue", [Layer("white", _union(dots)), Layer("white", _union(sparkles), c.hgt(0.6)),
                           Layer("gold", big, c.hgt(1.5), taper=15), Layer("gold", core, c.hgt(2.3), taper=20)])


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
    dots = [_circle(x, y, rr) for x, y, rr in c.scatter(int(c.area / 120), 0.45, 0.6, 1.5,
                                                        avoid=[(x, c.cy, thick) for x in np.linspace(-tip_x - pad, tip_x + pad, 9)])]
    return Design("blue", [
        Layer("white", _union(dots)),
        Layer("white", _union(sparkles), c.hgt(0.6)),
        Layer("blue", None, solids=[shift * plinth]),
        Layer("gold", None, solids=[shift * star]),
    ])


# --- Connector: a sleeve that joins two tiles of the same shape ---

# Wall thickness and clearance are parameters (TileParams.wall, .clearance): 1.2 and 0.1 mm by
# default; 0.8 mm walls printed poorly and no clearance was too tight.
CONNECTOR_SOCKET = 2.4  # mm, how deep a tile goes in from either side (all heights multiples of 0.2 mm layers)
CONNECTOR_LEDGE = 0.3  # mm, how far the ledge inside sticks out (short, so it prints over the wall below)
CONNECTOR_LEDGE_HEIGHT = 0.6  # mm, its height: three layers of 0.2 mm
CONNECTOR_HEIGHT = 2 * CONNECTOR_SOCKET + CONNECTOR_LEDGE_HEIGHT  # mm, total height
CONNECTOR_GAP = 1 / 3  # gap in the ledge at the middle of every edge, as a fraction of the edge length
CONNECTOR_CIRCLE_GAPS = 8  # a round connector's ledge has this many gaps, evenly spread
CONNECTOR_CORNER = 5.0  # mm, how far a corner stop reaches along each wall from the corner
CONNECTOR_CIRCLE_STOPS = 4  # a round connector gets this many flat stops, cut off by a straight bridge
CONNECTOR_CIRCLE_DEPTH = 1.0  # mm, how far such a stop reaches in, at its middle
CONNECTOR_TYPES = ("connector", "connector_corners")
CONNECTOR_COLOUR = "grey"


def _connector(c: Ctx) -> Design:
    return Design(CONNECTOR_COLOUR, [])  # the sleeve itself is made by _connector_body


def _ledge_gaps(p: TileParams) -> list[Sketch]:
    """Where the ledge is left out: a stretch of CONNECTOR_GAP of every edge, at its middle
    (evenly spread round a circle). A short ledge in a corner prints more reliably than one
    overhanging all the way round."""
    pts = outline_points(p)
    if p.shape == "circle":
        n = CONNECTOR_CIRCLE_GAPS
        a = np.radians(np.arange(n) * 360 / n + 180 / n)
        r = p.size / 2
        pts_mid = np.column_stack([r * np.cos(a), r * np.sin(a)])
        spans = [(m, np.array([-math.sin(t), math.cos(t)]), CONNECTOR_GAP * 2 * math.pi * r / n) for m, t in zip(pts_mid, a)]
    else:
        spans = []
        for p0, p1 in zip(pts, np.roll(pts, -1, axis=0)):
            d = p1 - p0
            length = float(np.hypot(*d))
            spans.append(((p0 + p1) / 2, d / length, CONNECTOR_GAP * length))
    reach = CONNECTOR_LEDGE + p.clearance + p.wall + 1.0  # across the ledge, both ways
    gaps = []
    for m, d, width in spans:
        nrm = np.array([-d[1], d[0]])
        corners = [m + s * width / 2 * d + t * reach * nrm for s, t in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        gaps.append(_poly(corners))
    return gaps


def _grow_polygon(pts: np.ndarray, d: float) -> np.ndarray:
    """A convex counterclockwise polygon with every edge moved outwards by d (sharp corners)."""
    if not d:
        return pts
    out = []
    n = len(pts)
    for i in range(n):
        a, v, b = pts[i - 1], pts[i], pts[(i + 1) % n]
        n1 = np.array([(v - a)[1], -(v - a)[0]]) / np.hypot(*(v - a))  # outward normals of the two edges
        n2 = np.array([(b - v)[1], -(b - v)[0]]) / np.hypot(*(b - v))
        out.append(v + d * (n1 + n2) / (1 + float(n1 @ n2)))  # where the two moved edges meet
    return np.array(out)


def _corner_stops(p: TileParams) -> list[Sketch]:
    """Flat stops across the inside corners: a triangle reaching CONNECTOR_CORNER along both
    walls from every corner; its third edge is a bridge from wall to wall. A circle has no
    corners: it gets CONNECTOR_CIRCLE_STOPS segments, each cut off by a straight bridge
    CONNECTOR_CIRCLE_DEPTH from the wall at its middle. All measured from the inside of the
    wall, i.e. the tile outline grown by the clearance."""
    pts = _grow_polygon(outline_points(p), p.clearance)
    if p.shape == "circle":
        r = p.size / 2 + p.clearance
        half = math.acos((r - CONNECTOR_CIRCLE_DEPTH) / r)  # half the angle the bridge spans
        stops = []
        for k in range(CONNECTOR_CIRCLE_STOPS):
            mid = math.radians(45 + k * 360 / CONNECTOR_CIRCLE_STOPS)
            a = np.linspace(mid - half, mid + half, 12)
            stops.append(_poly(np.column_stack([r * np.cos(a), r * np.sin(a)])))  # the arc, closed by the chord
        return stops
    stops = []
    n = len(pts)
    for i in range(n):
        v, before, after = pts[i], pts[i - 1], pts[(i + 1) % n]
        reach = min(CONNECTOR_CORNER, 0.4 * float(np.hypot(*(after - v))), 0.4 * float(np.hypot(*(before - v))))
        a = v + reach * (before - v) / np.hypot(*(before - v))
        b = v + reach * (after - v) / np.hypot(*(after - v))
        stops.append(_poly([a, v, b]))
    return stops


def _connector_body(c: Ctx) -> Part:
    """The sleeve, bottom at z = 0: the tile outline grown by the clearance inside, a wall
    around it, and halfway up the stop: the ledge, with gaps at the middle of the edges
    (_ledge_gaps), or for "connector_corners" the corner stops (_corner_stops). Corners stay
    sharp, like the tile's."""
    p = c.p
    inner = _sk(offset(c.outline, p.clearance, kind=Kind.INTERSECTION)) if p.clearance else c.outline
    outer = _sk(offset(inner, p.wall, kind=Kind.INTERSECTION))
    wall = extrude(_sk(outer - inner), amount=CONNECTOR_HEIGHT)
    if c.p.tile_type == "connector_corners":
        stop = _sk(inner & _union(_corner_stops(c.p)))
    else:
        ledge_inner = _sk(offset(inner, -CONNECTOR_LEDGE, kind=Kind.INTERSECTION))
        stop = _sk(_sk(inner - ledge_inner) - _union(_ledge_gaps(c.p)))
    ledge = Pos(0, 0, CONNECTOR_SOCKET) * extrude(stop, amount=CONNECTOR_LEDGE_HEIGHT)
    return _fuse([Part(wall.wrapped), Part(ledge.wrapped)])


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
    "asphalt": TileType("Asphalt", "Terrain", _asphalt, "flat road with a dashed centre line and edge lines"),
    "cobblestone": TileType("Cobblestone", "Terrain", _cobblestone, "uneven cobbles with sunken, mossy joints"),
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
                               "standing arch that a game piece can walk through, with a glowing lining and a swirl on the floor"),
    "star": TileType("Star (flat)", "Objects", _star_tile, "raised gold star, for a bonus or goal"),
    "star_upright": TileType("Star (upright)", "Objects", _star_upright, "gem-bevelled gold star standing on its two lower points"),
    "finish": TileType("Finish", "Objects", _finish, "chequered start or finish"),
    "connector": TileType("Connector (ledge)", "Special", _connector,
                          f"sleeve to join a tile rigidly on top of a part of the same shape: "
                          f"{CONNECTOR_HEIGHT:g} mm high, a ledge inside halfway up ({CONNECTOR_LEDGE:g} mm deep, "
                          f"{CONNECTOR_LEDGE_HEIGHT:g} mm high), so each tile "
                          f"goes in {CONNECTOR_SOCKET:g} mm from either side; the ledge has gaps at the middle of the edges. "
                          "Wall thickness and clearance can be set"),
    "connector_corners": TileType("Connector (corner bridges)", "Special", _connector,
                                  f"sleeve like the connector with a ledge, but the tiles stop on a flat triangle in "
                                  f"every inside corner ({CONNECTOR_CORNER:g} mm along each wall, "
                                  f"{CONNECTOR_LEDGE_HEIGHT:g} mm high), whose open edge is printed as a bridge; "
                                  f"a round one has {CONNECTOR_CIRCLE_STOPS} flat stops instead"),
}


# Rough surfaces in the printed mesh (3MF, preview), per type: (amplitude mm, wavelength mm,
# mode), see cad_common/mesh_fuzz.py. "surface" roughens heights only (the tile stays flat
# underneath and straight at the sides); "object" roughens in all directions above the tile
# (the worn upright portal). Types not listed keep smooth, made-looking surfaces.
ROUGHNESS = {
    "earth": (0.35, 2.5, "surface"),
    "sand": (0.12, 3.0, "surface"),
    "grass": (0.2, 2.5, "surface"),
    "cobblestone": (0.45, 3.0, "surface"),
    "bricks": (0.12, 2.0, "surface"),
    "water": (0.15, 4.0, "surface"),
    "ice": (0.08, 3.0, "surface"),
    "lava": (0.25, 2.5, "surface"),
    "pit": (0.15, 2.5, "surface"),
    "portal": (0.15, 2.0, "surface"),
    "portal_upright": (0.35, 2.0, "both"),
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
    if p.tile_type in CONNECTOR_TYPES:  # thickness and colour depth don't apply
        if not 0.4 <= p.wall <= 10:
            raise ValueError("Wall thickness must be between 0.4 and 10 mm.")
        if not 0 <= p.clearance <= 2:
            raise ValueError("Clearance must be between 0 and 2 mm.")
    elif p.thickness < 1.5:
        raise ValueError("Thickness must be at least 1.5 mm.")
    elif not 0.2 <= p.inlay_depth <= p.thickness - 1.0:
        raise ValueError("Colour depth must be at least 0.2 mm and leave at least 1 mm of base below it.")
    if not 1 <= p.count <= MAX_COUNT:
        raise ValueError(f"Number of tiles must be between 1 and {MAX_COUNT}.")


def _meshable(shape) -> bool:
    """Whether every face can be meshed at the preview's and the 3MF file's tolerances (sloped
    sides of awkward shapes can give tiny faces that cannot)."""
    try:
        for tol, ang in ((0.01, 0.2), (0.02, 0.2)):  # the 3MF file's and the preview's
            shape.tessellate(tol, ang)  # the whole shape at once, as the exporters do
        return True
    except Exception:
        return False


def _raised(region: Sketch, height: float, taper: float, below: float = 0.0) -> list[Part]:
    """`region` as solids from `below` under the top face up to `height` above it, with the
    part above the top sloping inwards by `taper` degrees where the shape allows (a face that
    is too small for the slope, or whose slope cannot be meshed, keeps straight sides).
    Coordinates are relative to the top face."""
    if taper <= 0:
        return [Pos(0, 0, -below) * extrude(region, amount=below + height)]
    out = []
    for face in region.faces():
        straight = Pos(0, 0, -below) * extrude(face, amount=below + height)
        try:
            sloped = extrude(face, amount=height, taper=taper)
            if below > 0:
                sloped = _fuse([Pos(0, 0, -below) * extrude(face, amount=below), sloped])
            # Sloped sides of long curvy bands can give faces that cannot be meshed (no 3MF/preview).
            if sloped.is_valid and 0 < sloped.volume < straight.volume and _meshable(sloped):
                out.append(sloped)
                continue
        except Exception:
            pass
        out.append(straight)
    return out


def _bodies(p: TileParams, seed: int) -> dict[str, list[Part]]:
    """Solids of one tile centred on the origin (bottom at z = 0), by colour.

    Each coloured piece is one solid from the bottom of its inlay up to its top; pieces of one
    colour are not fused together (a slicer treats touching parts of one body as one). Only
    the base is fused with raised parts in its own colour (e.g. cobbles), when that can still
    be meshed."""
    c = Ctx(p, seed)
    if p.tile_type in CONNECTOR_TYPES:
        return {CONNECTOR_COLOUR: [_connector_body(c)]}
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
    base_raised = []
    cuts = []
    for layer, region in zip(design.layers, regions):
        parts = bodies.setdefault(layer.color, [])
        placed = [Pos(0, 0, top) * s for s in layer.solids]
        if layer.color == design.base:
            base_raised += placed
        else:
            parts += placed
            cuts += [s for s in placed if s.bounding_box().min.Z < top - 1e-6]  # e.g. sunk star points get room in the base
        if region is None or not region.faces():
            continue
        h = layer.height
        if layer.color == design.base:
            if h < 0:  # a groove in the base
                cuts.append(Pos(0, 0, top + h) * extrude(region, amount=-h))
            elif h > 0:  # raised in the base colour, standing on the top face
                base_raised += [Pos(0, 0, top) * s for s in _raised(region, h, layer.taper)]
            continue
        if h > 0:  # the inlay and the raised part above it as one solid
            parts += [Pos(0, 0, top) * s for s in _raised(region, h, layer.taper, below=depth)]
        else:  # flush, or sunk by -h: an inlay `depth` thick
            z0 = top - depth + h
            parts.append(Pos(0, 0, z0) * extrude(region, amount=depth))
        z0 = top - depth + min(h, 0.0)
        cuts.append(Pos(0, 0, z0) * extrude(region, amount=top - z0))
    base = extrude(c.outline, amount=top)
    if cuts:
        base = base - cuts  # (Solid.cut keeps only one solid when the result has several)
    base = Part(base.wrapped)
    if base_raised:
        fused = None
        try:
            fused = _fuse([base] + base_raised)
        except Exception:
            pass
        if fused is not None and _meshable(fused):
            bodies[design.base] = [fused]
        else:
            log.info("game tile %s: base kept apart from its raised parts", p.tile_type)
            bodies[design.base] = [base] + base_raised
    else:
        bodies[design.base] = [base]
    return {name: parts for name, parts in bodies.items() if parts}


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
    if p.tile_type in CONNECTOR_TYPES:
        n = f"{p.count} connectors" if p.count > 1 else "Connector"
        return (f"{n}: {t.description}; for {p.shape} tiles, {dims}: {p.wall:g} mm wall, {p.clearance:g} mm clearance, "
                f"so the outside is {p.clearance + p.wall:g} mm larger on every side. Print it standing as shown.")
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
    ap.add_argument("--wall", type=float, default=1.2, help="connector wall thickness (mm)")
    ap.add_argument("--clearance", type=float, default=0.1, help="connector clearance round the tile (mm)")
    ap.add_argument("--out", default="game_tile.step")
    a = ap.parse_args()
    p = TileParams(a.type, a.shape, a.size, a.length, a.thickness, a.inlay_depth, a.count, a.seed, a.wall, a.clearance)
    export_step(build_tiles(p), a.out)
    print(describe(p))
    print(f"Wrote {a.out}")


if __name__ == "__main__":
    main()
