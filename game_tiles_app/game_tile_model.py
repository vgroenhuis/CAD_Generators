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
    tile goes in CONNECTOR_SOCKET deep from either side. The stop is a flat triangle across
    every inside corner, whose open edge the printer bridges. Bulges on the inside of the
    walls clamp the tiles. Thickness and colour depth don't apply to it.

    Can also be run standalone:  python game_tile_model.py --type bricks --shape hexagon --out tile.step
"""

from __future__ import annotations

import argparse
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Callable

from cad_common.text import printable_text

import numpy as np
from build123d import (
    Align, Axis, Box, Color, Compound, Cylinder, Kind, Location, Part, Plane, Polygon, Pos, Rectangle, Rot, Sketch, export_step, extrude, mirror,
    loft, offset, revolve,
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
    base_colour: str = "white"  # the bottom of the tile, below everything visible on top; "" = the tile's own base colour
    # The rough, hilly top in the printed mesh (3MF, preview; not the STEP file). Negative: the
    # type's own value (ROUGHNESS, HILLS); a depth or hill height of 0 leaves it smooth or flat.
    rough_depth: float = -1.0  # mm, how far the surface goes up and down
    rough_size: float = -1.0  # mm, the size of the bumps (wavelength)
    hill_height: float = -1.0  # mm, how far the gentle hills go up and down


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
    height = 1.4 * a  # tall and sharp: the tip is 0.2 mm wide
    taper = math.degrees(math.atan((a / 2 - 0.1) / height))
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
    straps = _fuse(straps) - knob - leaf - frame  # on the faces, not in the wood
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


LAVA_CRACK = 0.5  # mm; width of the glowing cracks in lava rock


def _lava(c: Ctx) -> Design:
    """Dark rock plates floating on glowing lava; the plates have glowing cracks, the lava bubbles."""
    cells, full = _stones(c, 9 * c.k, c.line(1.8))
    corners = {(round(x, 1), round(y, 1)) for cell in full for x, y in cell}
    bubbles = [_circle(x, y, max(0.9, 1.1 * c.k)) for x, y in sorted(corners)
               if c.inside(x, y, 1.5) and c.rng.random() < 0.35]
    rock_h = c.hgt(1.5)
    rocks, glows, cut_rocks = [], [], []
    for cell in cells:
        region = _sk(c.outline & _poly(cell))
        if not region.faces():
            continue
        # Each rock as a solid with sloping sides; glowing cracks are cut into it afterwards
        # (cutting them into the outline first would give awkward sloped faces).
        rock = _fuse(_raised(region, rock_h, 20))
        size = float(np.ptp(cell[:, 0]) + np.ptp(cell[:, 1])) / 2
        crack = _lava_cracks(c, cell, size) if size > 4 * c.k and c.rng.random() < 0.2 else None  # about 1 in 5
        crack = _sk(crack & region) if crack is not None else None  # inside the rock and the tile
        if crack is None or not crack.faces():
            rocks.append(region)
        else:
            rocks.append(_sk(region - crack))  # the lava colour runs on under the crack
            # Cut through the whole rock, so a crack that reaches the edge opens onto the lava;
            # the glow fills it to just under the rock's top (and follows its sloping sides).
            whole = rock
            rock = Part((rock - Pos(0, 0, -1) * extrude(crack, amount=rock_h + 2)).wrapped)
            glow = Part((extrude(crack, amount=rock_h - 0.2) & whole).wrapped)
            if glow.solids():
                glows.append(glow)
        cut_rocks.append(rock)
    return Design("orange", [Layer("dark_rock", _union(rocks), solids=cut_rocks),
                             Layer("orange", None, solids=glows),
                             Layer("yellow", _union(bubbles), c.hgt(0.6), taper=30)])


def _tapered(points, w0: float, w1: float) -> Sketch | None:
    """Band along a polyline whose width goes from w0 at the first point to w1 at the last."""
    pts = np.asarray(points, dtype=float)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    widths = w0 + (w1 - w0) * np.concatenate([[0], np.cumsum(seg)]) / max(seg.sum(), 1e-9)
    parts = []
    for (p0, p1), wa, wb in zip(zip(pts[:-1], pts[1:]), widths[:-1], widths[1:]):
        d = (p1 - p0) / max(np.linalg.norm(p1 - p0), 1e-9)
        n = np.array([-d[1], d[0]])
        parts.append(_poly([p0 - n * wa / 2, p1 - n * wb / 2, p1 + n * wb / 2, p0 + n * wa / 2]))
    parts += [_circle(x, y, w / 2, 12) for (x, y), w in zip(pts[1:-1], widths[1:-1])]
    return _union(parts)


def _lava_cracks(c: Ctx, cell: np.ndarray, size: float) -> Sketch | None:
    """Glowing cracks in a lava rock: mostly from a point on its edge (open to the lava there)
    jagged towards the middle, with short side branches; sometimes
    a crack only inside the rock, and sometimes a short second one from the edge."""
    centre = cell.mean(axis=0)
    mouth = tip = LAVA_CRACK  # one width all along

    def from_edge(reach: float):
        for _ in range(8):
            i = c.rng.randrange(len(cell))
            p = cell[i] + c.rng.uniform(0.25, 0.75) * (cell[(i + 1) % len(cell)] - cell[i])
            if c.inside(*p, 1.5):  # not on the tile's own edge
                heading = math.degrees(math.atan2(*(centre - p)[::-1])) + c.rng.uniform(-25, 25)
                return p, heading, reach * float(np.linalg.norm(centre - p))
        return None

    def jagged(p, heading, length, steps, spread=28):
        pts = [np.asarray(p, dtype=float)]
        for _ in range(steps):
            heading += c.rng.uniform(-spread, spread)
            s = length / steps * c.rng.uniform(0.7, 1.3)
            pts.append(pts[-1] + s * np.array([math.cos(math.radians(heading)), math.sin(math.radians(heading))]))
        return pts, heading

    parts = []
    starts = []
    if c.rng.random() < 0.75:
        start = from_edge(c.rng.uniform(1.3, 1.7))
        if start:
            p, heading, length = start
            p = p - 1.0 * np.array([math.cos(math.radians(heading)), math.sin(math.radians(heading))])  # begin in the lava
            starts.append((p, heading, length + 1.0, mouth))
            if c.rng.random() < 0.4:
                second = from_edge(c.rng.uniform(0.5, 0.8))
                if second:
                    q, h2, l2 = second
                    q = q - 1.0 * np.array([math.cos(math.radians(h2)), math.sin(math.radians(h2))])
                    starts.append((q, h2, l2 + 1.0, 0.85 * mouth + 0.15 * tip))
    if not starts:  # a crack inside the rock, widest in the middle
        a = c.rng.uniform(0, 360)
        for h in (a, a + 180 + c.rng.uniform(-30, 30)):
            starts.append((centre, h, 0.3 * size, 0.9 * mouth))
    for p, heading, length, width in starts:
        steps = max(3, round(length / (1.6 * c.k)))
        pts, _ = jagged(p, heading, length, steps)
        parts.append(_tapered(pts, width, tip))
        # Side branches from the wider part, thinner and short.
        for j in range(1, len(pts) - 1):
            if c.rng.random() < 0.35:
                w = width + (tip - width) * j / (len(pts) - 1)
                side = math.degrees(math.atan2(*(pts[j + 1] - pts[j])[::-1])) + c.rng.choice((-1, 1)) * c.rng.uniform(35, 65)
                bpts, _ = jagged(pts[j], side, length * c.rng.uniform(0.2, 0.35), 2, 20)
                parts.append(_tapered(bpts, max(tip, 0.8 * w), tip))
    return _union([s for s in parts if s is not None])


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


TREE_UNDERSIDE = 70.0  # degrees from upright: how flat the underside of a tier of foliage may be (75 prints fine)


def _tree(c: Ctx) -> Design:
    """A fir tree standing on the grass: three tiers of foliage on a brown trunk, with roots,
    a patch of bare earth, pine cones and moss round it. The undersides of the tiers are
    flat overhangs (TREE_UNDERSIDE), which print without supports. The trunk stops where the
    foliage starts: above that every layer is all foliage, printed in one colour."""
    y0, rt = c.cy, max(2.4, 0.18 * c.inr)  # centre and trunk radius (thick, so it is strong)
    shift = Pos(0, y0, 0)
    rise = 1 / math.tan(math.radians(TREE_UNDERSIDE))  # the underside rises this much per mm outwards
    z_bottom = max(4.0, 0.3 * c.inr)  # where the lowest tier starts, on the trunk
    tiers, rim, prev_cone = [], None, 0.0
    for frac in (0.74, 0.55, 0.37):
        r = frac * c.inr
        cone = 1.2 * r  # height of the cone above the tier's rim
        rim = z_bottom + rise * (r - rt) if rim is None else rim + 0.55 * prev_cone
        zb = rim - rise * (r - rt)
        profile = Plane.XZ * Polygon((0, zb), (rt, zb), (r, rim), (r - 0.4, rim + 0.4), (0, rim + cone), align=None)
        tiers.append(revolve(profile, Axis.Z))
        prev_cone = cone
    trunk = Cylinder(rt, z_bottom, align=(Align.CENTER, Align.CENTER, Align.MIN))
    foliage = _fuse(tiers)
    # Roots: raised, and fused with the trunk (they start inside it), so they are joined to it.
    roots = []
    a0 = c.rng.uniform(0, 360)
    for j in range(5):
        a = math.radians(a0 + j * 72 + c.rng.uniform(-15, 15))
        length = c.rng.uniform(3.5, 5.5) * c.k
        bend = math.radians(c.rng.uniform(-20, 20))
        pts = [((rt - 1.0) * math.cos(a), y0 + (rt - 1.0) * math.sin(a)),
               ((rt + 0.5 * length) * math.cos(a), y0 + (rt + 0.5 * length) * math.sin(a)),
               ((rt + length) * math.cos(a + bend / 2), y0 + (rt + length) * math.sin(a + bend / 2))]
        roots.append(_polyline(pts, c.line(1.4)))
    roots_region = _union(roots)
    wood = _fuse([shift * trunk] + _raised(roots_region, c.hgt(0.7), 25))
    footprint = _union([_circle(0, y0, rt + 0.1), roots_region])  # (a little wider: the circle is a polygon)
    # Bare earth round the trunk, pine cones and moss further out.
    patch = _blob(0, y0, rt + 3.0 * c.k, c.rng, n=11, jitter=0.2)
    keep_out = [(0, y0, rt + 6.5 * c.k)]
    cones = []
    for x, y, r in c.scatter(max(2, int(c.area / 450)), 1.2 * c.k, 1.5 * c.k, 1.5, margin=0.8, avoid=keep_out):
        cones.append(_poly(_teardrop(x, y, r, 2.4 * r, c.rng.uniform(0, 360))))
    moss = [_blob(x, y, r, c.rng) for x, y, r in
            c.scatter(max(2, int(c.area / 350)), 1.5 * c.k, 3.0 * c.k, 1.0, avoid=keep_out)]
    return Design("green", [
        Layer("dark_green", _union(moss), c.hgt(0.4), taper=20),
        Layer("brown", _union(cones), c.hgt(1.0), taper=25),
        Layer("brown", patch),
        Layer("dark_brown", footprint, solids=[wood]),
        Layer("dark_green", None, solids=[shift * foliage]),
    ])


def _hull_outline(length: float, beam: float, y0: float, n: int = 16) -> np.ndarray:
    """Outline of a hull seen from above, pointing to +y: a flat stern at y0 - length/2, straight
    sides and a pointed bow over the front 40 %. Always 2n + 1 points (for lofting)."""
    bow = 0.4 * length
    t = np.linspace(-length / 2, length / 2, n + 1)
    u = np.clip((t - (length / 2 - bow)) / bow, 0, 1)
    half = beam / 2 * (1 - u ** 2)
    right = np.column_stack([half[:-1], y0 + t[:-1]])
    left = np.column_stack([-half[:-1], y0 + t[:-1]])[::-1]
    return np.vstack([right, [[0, y0 + length / 2]], left])


def _ship(c: Ctx) -> Design:
    """A sailing ship on the water: a wooden hull whose sides flare out at 27 degrees (so it
    prints without supports) with a cabin and a mast carrying a mainsail and a jib, upright
    white plates standing on the deck. It sails to +X (to +Y on a tile longer in y), so the
    preview shows it side-on. Waves round it and a white wake behind."""
    along_y = c.h > c.w
    turn = 0.0 if along_y else -90.0  # the ship is drawn sailing to +y, then turned

    def place(pts):  # ship coordinates (sailing to +y, centred on 0) to tile coordinates
        return _rotate(np.asarray(pts, dtype=float), turn) + (0, c.cy)

    move = Pos(0, c.cy, 0) * Rot(0, 0, turn)
    length, beam = 1.7 * c.inr, 0.6 * c.inr
    while length > 10 and not all(c.inside(x, y, 1.0) for x, y in place(_hull_outline(length, beam, 0))):
        length, beam = 0.95 * length, 0.95 * beam  # e.g. on a triangle, which narrows at the top
    k = length / 34  # the ship's own scale (34 mm long on a 40 mm tile)
    depth = max(3.0, 5 * k)  # hull height above the water
    flare = 0.5 * depth
    deck_pts = _hull_outline(length, beam, 0)
    bottom_pts = _hull_outline(length - 2 * flare, beam - 2 * flare, 0)
    hull = loft([Polygon(*map(tuple, bottom_pts), align=None).face(),
                 Pos(0, 0, depth) * Polygon(*map(tuple, deck_pts), align=None).face()])
    rail = max(1.2, 1.4 * k)
    sink = min(0.8, 0.3 * depth)
    well = _sk(offset(_poly(deck_pts), -rail))  # the deck lies `sink` below the rail
    hull = Part((hull - Pos(0, 0, depth - sink) * extrude(well, amount=sink + 1)).wrapped)
    deck = depth - sink
    # Cabin at the stern, mast a little ahead of the middle.
    cab_l, cab_w, cab_h = 0.2 * length, 0.45 * beam, max(2.0, 3 * k)
    cab_y = -length / 2 + rail + 0.5 + cab_l / 2
    cabin = Pos(0, cab_y, deck) * Box(cab_w, cab_l, cab_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    roof = Pos(0, cab_y, deck + cab_h) * extrude(_rect(-cab_w / 2 - 0.4, -cab_l / 2 - 0.4, cab_w / 2 + 0.4, cab_l / 2 + 0.4),
                                                    amount=0.6, taper=40)
    mast_y, mast_r = 0.08 * length, max(1.0, 1.1 * k)
    top = deck + 1.05 * length
    mast = Pos(0, mast_y, deck) * Cylinder(mast_r, top - deck, align=(Align.CENTER, Align.CENTER, Align.MIN))
    sail_t = max(1.2, 1.2 * k)

    def plate(points):  # an upright plate along the ship (in the YZ plane), sail_t thick
        return extrude(Plane.YZ * Polygon(*points, align=None), amount=sail_t / 2, both=True)

    head = top - max(2.0, 2.5 * k)
    clew = cab_y + cab_l / 2 + 1.0  # the mainsail stands on the deck, ahead of the cabin
    main = plate([(mast_y, deck), (mast_y, head), (clew, deck)])
    bow_y = length / 2 - 0.18 * length  # where the deck is still wide enough for the jib
    jib = plate([(mast_y, deck), (mast_y, 0.78 * head + 0.22 * deck), (bow_y, deck)])
    sails = Part((main + jib - mast).wrapped)
    # The water: waves away from the ship, a wake behind it and bow waves along its sides.
    keep = _sk(offset(_poly(place(deck_pts)), 1.5 * c.k))
    length_w, pitch_y = 11 * c.k, 6.5 * c.k
    waves = []
    for x, y in c.grid(length_w * 1.3, pitch_y, stagger=True, jitter=0.8 * c.k):
        if c.inside(x, y, 1.5 * c.k):
            waves.append(_wave(x, y, length_w, 1.1 * c.k, c.line(1.5)))
    stern = -length / 2
    wake = []
    for side in (-1, 1):
        wake.append(_polyline(place([(side * (beam / 2 + 0.5), stern - 1.5 * c.k), (side * (beam / 2 + 6 * c.k), stern - 9 * c.k),
                                     (side * (beam / 2 + 9 * c.k), stern - 16 * c.k)]), c.line(1.4)))
        bx = side * (0.5 * beam + 2.6 * c.k)
        wake.append(_polyline(place([(side * 1.8 * c.k, length / 2 + 1.0 * c.k), (bx, length / 2 - 0.3 * length),
                                     (bx + side * 2 * c.k, length / 2 - 0.45 * length)]), c.line(1.2)))
    foam = [_circle(x, y, r) for x, y, r in c.scatter(max(2, int(c.area / 300)), 0.6 * c.k, 0.9 * c.k, 1.0,
                                                      avoid=[(x, y, beam) for x, y in place([(0, t) for t in np.linspace(-length / 2, length / 2, 7)])])]

    def away(regions):
        u = _union([r for r in regions if r is not None])
        return _sk(u - keep) if u is not None else None

    return Design("blue", [
        Layer("light_blue", away(waves), c.hgt(0.8), taper=15),
        Layer("white", away(wake), c.hgt(0.7), taper=20),
        Layer("white", away(foam), c.hgt(0.9), taper=25),
        Layer("wood", _poly(place(bottom_pts)), solids=[move * hull]),
        Layer("dark_brown", None, solids=[move * cabin, move * Part(roof.wrapped), move * mast]),
        Layer("white", None, solids=[move * sails]),
    ])


def _bulb(c: Ctx) -> Design:
    """A light bulb standing on its screw socket (black insulator, steel thread), shining:
    yellow rays on a dark floor. The glass is round on top; below its widest point it
    narrows to the socket, no flatter than 50 degrees from upright, so it prints without
    supports."""
    y0 = c.cy
    shift = Pos(0, y0, 0)
    big = 0.45 * c.inr  # radius of the glass
    rs = 0.5 * big  # radius of the socket
    band = max(1.0, 0.15 * big)  # black insulator at the bottom
    sock_h = 0.8 * big
    n = max(2, round((sock_h - band) / max(1.2, 0.25 * big)))
    pitch = (sock_h - band) / n
    groove = min(0.5, 0.4 * pitch)
    prof = [(0, band), (rs, band)]
    for i in range(n):  # the thread: the outward slopes are 40 degrees from upright at most
        z = band + i * pitch
        prof += [(rs - groove, z + pitch / 2), (rs, z + pitch)]
    prof.append((0, sock_h))
    socket = revolve(Plane.XZ * Polygon(*prof, align=None), Axis.Z)
    insulator = Cylinder(rs, band, align=(Align.CENTER, Align.CENTER, Align.MIN))
    neck = 0.85 * rs
    low = math.radians(50)  # where the neck meets the round glass, below its middle
    zc = sock_h + (big * math.cos(low) - neck) + big * math.sin(low)  # the neck widens at 45 degrees
    glass = [(0, sock_h), (neck, sock_h)] + [(big * math.cos(t), zc + big * math.sin(t))
                                             for t in np.linspace(-low, math.pi / 2, 28)]
    bulb = revolve(Plane.XZ * Polygon(*glass, align=None), Axis.Z)
    rays = []
    r0 = rs + max(1.5, 2.0 * c.k)
    for i in range(16):  # long and short rays in turn
        a = math.radians(i * 22.5 + 11.25)
        r1 = (0.95 if i % 2 == 0 else 0.72) * c.inr
        half = (0.07 if i % 2 == 0 else 0.06) * r1
        tip = (r0 * math.cos(a), y0 + r0 * math.sin(a))
        side = np.array([-math.sin(a), math.cos(a)]) * half
        end = np.array([r1 * math.cos(a), y0 + r1 * math.sin(a)])
        rays.append(_poly([tip, tuple(end + side), tuple(end - side)]))
    return Design("dark_grey", [
        Layer("yellow", _union(rays), c.hgt(0.6), taper=20),
        Layer("black", _circle(0, y0, rs + 0.1), solids=[shift * insulator]),
        Layer("steel", None, solids=[shift * Pos(0, 0, 0) * socket]),
        Layer("yellow", None, solids=[shift * bulb]),
    ])


def _key(c: Ctx) -> Design:
    """An old gold key lying flat, raised, on a dark red cushion with a few sparkles: a ring
    bow with a hole, a collar, the shaft and a bit with notches."""
    y0 = c.cy
    length = 1.7 * c.inr

    def corners(n):
        bow_r, bit_h, sw = 0.2 * n, 0.2 * n, max(2.0, 0.075 * n)
        return [(-n / 2, y0 - bow_r), (-n / 2, y0 + bow_r), (n / 2, y0 + sw / 2), (n / 2, y0 - sw / 2 - bit_h)]

    while length > 12 and not all(c.inside(x, y, 1.0) for x, y in corners(length)):
        length *= 0.95  # e.g. on a triangle
    bow_r, sw = 0.2 * length, max(2.0, 0.075 * length)
    bx = -length / 2 + bow_r
    bow = _sk(_circle(bx, y0, bow_r) - _circle(bx, y0, 0.55 * bow_r))
    shaft = _rect(bx + 0.8 * bow_r, y0 - sw / 2, length / 2, y0 + sw / 2)
    bit_l, bit_h = 0.25 * length, 0.2 * length
    x1 = length / 2
    bit = _rect(x1 - bit_l, y0 - sw / 2 - bit_h, x1, y0)
    notch = max(1.2, bit_l / 5)
    bit = _sk(bit - _rect(x1 - 0.66 * bit_l - notch / 2, y0 - sw / 2 - bit_h - 1, x1 - 0.66 * bit_l + notch / 2, y0 - sw / 2 - 0.45 * bit_h)
              - _rect(x1 - 0.3 * bit_l - notch / 2, y0 - sw / 2 - bit_h - 1, x1 - 0.3 * bit_l + notch / 2, y0 - sw / 2 - 0.7 * bit_h))
    cx = bx + bow_r + 0.05 * length
    collar = _union([_rect(cx + d, y0 - 0.085 * length, cx + d + max(1.2, 0.035 * length), y0 + 0.085 * length)
                     for d in (0.0, 0.07 * length)])
    gold = _union([bow, shaft, bit])
    avoid = [(x, y0 - 0.05 * length, 0.25 * length) for x in np.linspace(-length / 2 + bow_r, length / 2 - 0.1 * length, 5)]
    sparkles = [_star(x, y, rr, 0.32 * rr, 4, 0) for x, y, rr in
                c.scatter(int(c.area / 450), 2.0 * max(1, c.k), 2.6 * max(1, c.k), 0.5, avoid=avoid)]
    return Design("dark_red", [Layer("white", _union(sparkles), c.hgt(0.6)),
                               Layer("gold", gold, c.hgt(1.6), taper=15),
                               Layer("gold", collar, c.hgt(2.2), taper=20)])


def _weight(c: Ctx) -> Design:
    """A cartoon "100t" weight that has just landed: a dark iron block narrowing upwards with
    a handle on top and "100t" set into its front face (white), on cracked earth with chips."""
    y0 = c.cy
    shift = Pos(0, y0, 0)
    b = 1.25 * c.inr  # bottom side (fits in the largest circle inside the tile)
    t, h = 0.62 * b, 0.62 * b
    block = loft([Rectangle(b, b).face(), Pos(0, 0, h) * Rectangle(t, t).face()])
    hw, hh = 0.55 * t, 0.34 * t  # the handle: an arch across the top
    bar = max(2.0, 0.13 * t)
    arch = _sk(_rect(-hw / 2, 0, hw / 2, hh) - _rect(-hw / 2 + bar, -1, hw / 2 - bar, hh - bar))
    handle = Pos(0, 0, h) * extrude(Plane.XZ * arch, amount=max(2.0, 0.12 * t), both=True)
    iron = _fuse([block, handle])
    # "100t" set into the sloping front face (towards -y), flush.
    up = np.array([0.0, (b - t) / 2, h])
    normal = np.array([0.0, -h, (b - t) / 2])
    face = Plane(origin=(0, -(b + t) / 4, h / 2), x_dir=(1, 0, 0), z_dir=tuple(normal / np.linalg.norm(normal)))
    size = 0.25 * b
    letters = extrude(face * printable_text("100t", size), amount=-0.8) & block
    iron = Part((iron - letters).wrapped)
    cracks = []
    for i in range(8):
        side = i % 4
        u = c.rng.uniform(-0.4, 0.4) * b
        x, y, ang = [(u, -b / 2, -90), (b / 2, u, 0), (u, b / 2, 90), (-b / 2, u, 180)][side]
        cracks += _crack(c, x, y0 + y, ang + c.rng.uniform(-30, 30), 4, 3.0 * c.k)
    chips = [_blob(x, y, r, c.rng, n=6) for x, y, r in c.scatter(max(3, int(c.area / 200)), 0.7 * c.k, 1.3 * c.k, 1.0,
                                                                avoid=[(0, y0, 0.75 * b)])]
    return Design("brown", [
        Layer("black", _union(cracks), height=-0.6),
        Layer("dark_grey", _union(chips), c.hgt(0.8), taper=25),
        Layer("dark_grey", _rect(-b / 2, y0 - b / 2, b / 2, y0 + b / 2), solids=[shift * iron]),
        Layer("white", None, solids=[shift * Part(letters.wrapped)]),
    ])


# --- Large 3D shapes: sea waves, a dune, a mountain, a lightning bolt ---

def _lofted_ridge(xs, profile) -> Part:
    """A ridge running along x: the (y, z) polygon profile(x) (always the same number of
    points) at every x in xs, joined by flat faces."""
    sections = [Plane.YZ.offset(float(x)) * Polygon(*[(float(y), float(z)) for y, z in profile(x)], align=None) for x in xs]
    return Part(loft(sections, ruled=True).wrapped)


def _clip_to_tile(c: Ctx, part, top: float) -> Part:
    """`part` cut off at the tile's outline (up to `top`, from 2 mm below the top face)."""
    return Part((part & Pos(0, 0, -2) * extrude(c.outline, amount=top + 3)).wrapped)


def _sea(c: Ctx) -> Design:
    """Rolling sea: big waves across the tile, a gentle back and a steep front, with white
    foam on the highest crests and small ripples in the troughs. The waves repeat from tile
    to tile in both directions."""
    n = max(2, round(c.h / (13 * c.k)))
    pitch = c.h / n
    height = c.hgt(3.5)
    back, front = 0.5 * pitch, 0.35 * pitch
    xs = np.linspace(-c.w / 2 - 1, c.w / 2 + 1, 25)
    ridges, feet = [], []
    for j in range(n):
        yc = -c.h / 2 + front + j * pitch  # the crest; the steep front faces -y (the viewer)
        m, phase, shift = c.rng.choice((1, 2)), c.rng.uniform(0, 2 * math.pi), c.rng.uniform(0, 2 * math.pi)

        def profile(x, yc=yc, m=m, phase=phase, shift=shift):
            h = height * (1 + 0.28 * math.cos(2 * math.pi * m * x / c.w + phase))
            y0 = yc + 0.03 * pitch * math.sin(2 * math.pi * x / c.w + shift)
            s = np.linspace(0, 1, 9)
            rise = [(y0 + back * (1 - t), h * (0.5 - 0.5 * math.cos(math.pi * t))) for t in s]  # gentle back
            fall = [(y0 - front * t, h * (1 - t) ** 1.6) for t in s[1:]]  # steep front
            return [(y0 + back, -0.4)] + rise + fall + [(y0 - front, -0.4)]
        ridges.append(_clip_to_tile(c, _lofted_ridge(xs, profile), 2 * height))
        ends = np.array([(profile(x)[0][0], profile(x)[-1][0]) for x in xs])
        feet.append(_poly(np.vstack([np.column_stack([xs, ends[:, 1] - 0.2]), np.column_stack([xs, ends[:, 0] + 0.2])[::-1]])))

    def crest(r):  # the foam: the part above 1.08 * height, if any (none where the tile cuts a wave low)
        top = r & Pos(-c.w, -c.h, 1.08 * height) * Box(2 * c.w, 2 * c.h, 2 * height, align=Align.MIN)
        try:
            return Part(top.wrapped)
        except AssertionError:  # an empty result
            return Part()
    caps = [crest(r) for r in ridges]
    waves = [Part((r - cap).wrapped) if cap.solids() else r for r, cap in zip(ridges, caps)]
    caps = [cap for cap in caps if cap.solids()]
    # Ripples and a few foam flecks in the flat troughs between the waves.
    ripples, flecks = [], []
    for j in range(n):
        y = -c.h / 2 + j * pitch + back + front + 0.075 * pitch  # middle of the trough after wave j
        if not -c.h / 2 < y < c.h / 2:
            continue
        x = np.linspace(-c.w / 2 - 2, c.w / 2 + 2, 60)
        ripples.append(_stroke(np.column_stack([x, y + 0.25 * c.k * np.sin(2 * math.pi * 3 * x / c.w + j)]), 0.8))
    ripples = _union(ripples)
    ripples = _sk(ripples - _union(feet)) if ripples is not None else None  # in the troughs only
    return Design("blue", [Layer("light_blue", ripples, c.hgt(0.4)),
                           Layer("blue", None, solids=waves),
                           Layer("white", None, solids=caps)])


def _dune(c: Ctx) -> Design:
    """A sand dune across the tile: a long, gentle windward slope with wind ripples and a sharp
    crest above a steep slip face; pebbles and a shell on the flat sand. The dune continues on
    the tiles to the left and right."""
    height = max(1.5, 6 * c.k)
    windward, slip = 3.4 * height, height / math.tan(math.radians(32))
    amp = 0.06 * c.h
    yc0 = (windward - slip) / 2 * 0.9 + c.cy
    ph1, ph2 = c.rng.uniform(0, 2 * math.pi), c.rng.uniform(0, 2 * math.pi)
    xs = np.linspace(-c.w / 2 - 1, c.w / 2 + 1, 25)

    def crest(x):
        return (yc0 + amp * math.sin(2 * math.pi * x / c.w + ph1),
                height * (1 + 0.12 * math.cos(4 * math.pi * x / c.w + ph2)))

    def profile(x):
        yc, h = crest(x)
        s = np.linspace(0, 1, 12)
        rise = [(yc - windward * (1 - t), h * (3 * t * t - 2 * t ** 3) ** 0.85) for t in s]
        fall = [(yc + slip * h / height * t, h * (1 - t) ** 1.15) for t in s[1:5:1]] + [(yc + slip * h / height, 0.0)]
        return [(yc - windward, -0.4)] + rise + fall + [(yc + slip * h / height, -0.4)]
    dune = _clip_to_tile(c, _lofted_ridge(xs, profile), 2 * height)
    # Wind ripples across the windward slope, following the surface; none on the slip face,
    # nor on the flat sand (its pebbles and shell stand there).
    crest_pts = np.array([crest(x) for x in xs])
    foot = _sk(_poly(np.vstack([np.column_stack([xs, crest_pts[:, 0] - windward - 1]),
                                np.column_stack([xs, crest_pts[:, 0] + slip * crest_pts[:, 1] / height + 1])[::-1]])))
    slip_face = _poly(np.vstack([np.column_stack([xs, crest_pts[:, 0] - 0.3]),
                                 np.column_stack([xs, crest_pts[:, 0] + slip * crest_pts[:, 1] / height + 0.6])[::-1]]))
    pitch = 3.6 * c.k
    xr = np.linspace(-c.w / 2 - 2, c.w / 2 + 2, 70)
    ripples = [_stroke(np.column_stack([xr, y0 + 0.6 * c.k * np.sin(2 * math.pi * 2 * xr / c.w + 0.9 * j)]), c.line(1.0))
               for j, y0 in enumerate(np.arange(-c.h / 2, c.h / 2 + pitch, pitch))]
    ripples = _sk(_sk(_sk(_union(ripples) - slip_face) & foot) & c.outline)
    lift = c.hgt(0.5)
    ground = dune + Pos(0, 0, -1) * extrude(_rect(-c.w, -c.h, c.w, c.h), amount=1)
    skin = Part((((Pos(0, 0, lift) * ground) & (Pos(0, 0, -1) * extrude(ripples, amount=3 * height))) - ground).wrapped)
    ys = crest_pts[:, 0]
    keep_out = [(x, y, 0.6 * windward) for x, y in zip(xs[::3], ys[::3] - 0.3 * windward)]
    keep_out += [(x, y, 0.5 * slip + 1) for x, y in zip(xs[::3], ys[::3] + 0.5 * slip)]
    dots = [_circle(x, y, r) for x, y, r in c.scatter(int(c.area / 200), 0.6, 0.9 * max(1, c.k), 1.0, avoid=keep_out)]
    shells, ribs = [], []
    for x, y, r in c.scatter(1, 2.4 * c.k, 3.0 * c.k, 2.0, avoid=keep_out):
        s, rb = _shell(x, y, r, c.rng.uniform(0, 360))
        shells.append(s)
        ribs += rb
    off = lambda sk: _sk(sk - foot) if sk is not None else None  # flat sand only
    return Design("sand", [Layer("sand", None, solids=[dune]),
                           Layer("tan", None, solids=[skin] if skin.solids() else []),
                           Layer("tan", off(_union(dots)), c.hgt(0.5), taper=30),
                           Layer("white", off(_union(shells)), c.hgt(0.9), taper=15),
                           Layer("white", off(_union(ribs)), c.hgt(0.5))])


def _peak(c: Ctx, x0: float, y0: float, radius: float, height: float, below: float) -> Part:
    """A rocky peak: irregular polygons, each inside the one below, joined by flat faces;
    standing on the top face and reaching `below` into the tile."""
    n, levels = 13, 7
    angles = np.linspace(0, 2 * math.pi, n, endpoint=False) + c.rng.uniform(0, 1)
    prev = None
    sections = []
    for i in range(levels + 1):
        t = i / levels
        base = radius * max(0.04, (1 - t) ** 1.25)
        r = np.array([base * c.rng.uniform(0.72, 1.08) for _ in range(n)])
        if prev is not None:
            r = np.minimum(r, 0.94 * prev)  # every level inside the one below: no overhangs
        prev = r
        z = height * t
        pts = [(x0 + rr * math.cos(a), y0 + rr * math.sin(a)) for rr, a in zip(r, angles)]
        if i == 0:
            sections.append(Plane.XY.offset(-below) * Polygon(*pts, align=None))
        sections.append(Plane.XY.offset(z) * Polygon(*pts, align=None))
    return Part(loft(sections, ruled=True).wrapped)


def _mountain(c: Ctx) -> Design:
    """A rocky mountain with a snowy top and a lower second peak, on grassland with tufts and
    boulders."""
    depth = c.p.inlay_depth
    big_r, big_h = 0.6 * c.inr, 0.95 * c.inr
    x1, y1 = -0.12 * c.inr, c.cy + 0.06 * c.inr
    x2, y2 = x1 + 0.62 * c.inr, y1 - 0.3 * c.inr
    rock = _peak(c, x1, y1, big_r, big_h, depth) + _peak(c, x2, y2, 0.42 * c.inr, 0.55 * big_h, depth)
    rock = _clip_to_tile(c, rock, big_h + 1)
    snow = Part((rock & Pos(-c.w, -c.h, 0.66 * big_h) * Box(2 * c.w, 2 * c.h, big_h, align=Align.MIN)).wrapped)
    rock = Part((rock - snow).wrapped)
    keep_out = [(x1, y1, big_r + 0.8), (x2, y2, 0.42 * c.inr + 0.8)]
    tufts = [_blob(x, y, r, c.rng, 8, 0.3) for x, y, r in c.scatter(int(c.area / 110), 0.9 * c.k, 1.6 * c.k, 1.2, avoid=keep_out)]
    boulders = [_blob(x, y, r, c.rng, 7, 0.25) for x, y, r in c.scatter(max(2, int(c.area / 500)), 1.2 * c.k, 2.0 * c.k, 1.5,
                                                                           avoid=keep_out)]
    return Design("green", [Layer("dark_green", _union(tufts), c.hgt(0.6), taper=25),
                            Layer("grey", _union(boulders), c.hgt(1.2), taper=30),
                            Layer("grey", None, solids=[rock]),
                            Layer("white", None, solids=[snow] if snow.solids() else [])])


def _thunderstorm(c: Ctx) -> Design:
    """A lightning bolt standing on the wet ground where it strikes, with a scorch mark round
    it; slanting rain and puddles with splash rings."""
    h = 0.95 * c.inr
    sink = min(0.6, c.p.thickness - 1.0)
    # The bolt in its own plane (u across, z up), as fractions of its height. Every underside
    # slopes at least 34 degrees from horizontal, so it prints standing.
    shape = [(-0.02, 0.0), (0.05, 0.0), (0.30, 0.45), (0.12, 0.47), (0.36, 1.0), (0.10, 1.0), (-0.08, 0.62), (0.0, 0.50)]
    du = -0.14  # centre the bolt over its foot
    profile = [((u + du) * h, z * h) for u, z in shape]
    # Sunk straight down from its foot, so at the top face it is exactly the foot.
    profile = [(profile[0][0], -sink), (profile[1][0], -sink)] + profile[1:] + [profile[0]]
    thick = max(2.4, 2.4 * c.k)
    bx, by = 0.0, c.cy
    bolt = _fin(profile, thick, 0, bx, by)
    # Where the bolt strikes: its foot, a small rectangle in the middle of the scorch mark. The
    # foot is an inlay of its own in yellow, so the black meets the bolt with no ground between.
    foot = _rect(bx + (-0.02 + du) * h, by - thick / 2, bx + (0.05 + du) * h, by + thick / 2)
    sx, sy = bx + (0.015 + du) * h, by
    foot_r = 4.5 * c.k
    a = np.radians(np.linspace(0, 360, 16, endpoint=False) + c.rng.uniform(0, 20))
    rr = foot_r * np.array([c.rng.uniform(1.0, 1.6) if i % 2 == 0 else c.rng.uniform(0.45, 0.6) for i in range(16)])
    scorch = _poly(np.column_stack([sx + rr * np.cos(a), sy + rr * np.sin(a)]))
    avoid = [(sx, sy, 1.6 * foot_r)]
    puddle_xy = c.scatter(max(1, int(c.area / 700)), 3.5 * c.k, 5.0 * c.k, 3.0, avoid=avoid)
    puddles = [_blob(x, y, r, c.rng, 12, 0.15) for x, y, r in puddle_xy]
    rings = []
    for x, y, r in puddle_xy:
        for q in (0.35, 0.7):
            a0 = c.rng.uniform(0, 360)
            rings += [_arc(x, y, q * r, MIN_LINE, a0, a0 + 150), _arc(x, y, q * r, MIN_LINE, a0 + 190, a0 + 330)]
    streaks = []
    pitch = 4.2 * c.k
    for x, y in c.grid(pitch, pitch * 1.4, stagger=True, jitter=1.0 * c.k):
        if (c.inside(x, y, 2.5 * c.k) and math.hypot(x - sx, y - sy) > 1.7 * foot_r
                and all(math.hypot(x - px, y - py) > pr + 2.5 * c.k for px, py, pr in puddle_xy)):
            d = _rotate(np.array([[0.0, -2.0 * c.k], [0.0, 2.0 * c.k]]), 25) + (x, y)
            streaks.append(_polyline(d, MIN_LINE))
    sunk = c.hgt(0.6)
    return Design("dark_grey", [Layer("dark_grey", _union(puddles), height=-sunk),
                                Layer("light_blue", _union(rings), height=-sunk + 0.3),
                                Layer("light_blue", _union(streaks), c.hgt(0.6)),
                                Layer("black", scorch),
                                Layer("yellow", foot, solids=[bolt])])


def _laser(c: Ctx) -> Design:
    """A horizontal laser: a steel emitter with a black lens on its right face and a red beam
    running from the lens across the tile."""
    y0 = c.cy
    x0 = -c.w / 2 + 2.5 * c.k
    x1 = x0 + 6 * c.k
    body = _rect(x0, y0 - 4.5 * c.k, x1, y0 + 4.5 * c.k)
    lens = _rect(x1 - 1.4 * c.k, y0 - 1.8 * c.k, x1, y0 + 1.8 * c.k)
    beam = _rect(x1, y0 - c.line(1.6) / 2, c.w / 2 + 1, y0 + c.line(1.6) / 2)  # to the edge (clipped to the tile)
    return Design("dark_grey", [Layer("steel", body, c.hgt(4.0)),
                                Layer("black", lens, c.hgt(4.0)),
                                Layer("red", beam, c.hgt(0.8))])


def _mirror(c: Ctx) -> Design:
    """An upright steel mirror standing along the diagonal."""
    sink = min(0.6, c.p.thickness - 1.0)
    thick = max(1.2, 1.2 * c.k)
    height = c.hgt(7.0)
    d = np.array([1.0, 1.0]) / math.sqrt(2)  # along the diagonal
    length = 1.4 * c.inr
    # Shorter when the tile is narrow, so that both ends of the mirror stay on the tile.
    while length > 2 and not all(c.inside(*(sg * length / 2 * d), 1.0) for sg in (-1, 1)):
        length -= 1
    profile = [(-length / 2, -sink), (length / 2, -sink), (length / 2, height), (-length / 2, height)]
    plate = _fin(profile, thick, 45, 0.0, c.cy)
    return Design("dark_grey", [Layer("steel", None, solids=[plate])])


# --- Connector: a sleeve that joins two tiles of the same shape ---

# Wall thickness and clearance are parameters (TileParams.wall, .clearance): 1.2 and 0.1 mm by
# default; 0.8 mm walls printed poorly and no clearance was too tight.
CONNECTOR_SOCKET = 2.4  # mm, how deep a tile goes in from either side (all heights multiples of 0.2 mm layers)
CONNECTOR_STOP_HEIGHT = 0.6  # mm, height of the stops halfway up: three layers of 0.2 mm
CONNECTOR_HEIGHT = 2 * CONNECTOR_SOCKET + CONNECTOR_STOP_HEIGHT  # mm, total height
CONNECTOR_CORNER = 5.0  # mm, how far a corner stop reaches along each wall from the corner
CONNECTOR_CIRCLE_STOPS = 4  # a round connector gets this many flat stops, cut off by a straight bridge
CONNECTOR_CIRCLE_DEPTH = 1.0  # mm, how far such a stop reaches in, at its middle
CONNECTOR_BULGE = 0.5  # mm, how far a clamping bulge sticks out of the wall
CONNECTOR_BULGE_LENGTH = 10.0  # mm, its length along the wall at most (a third of a shorter edge)
CONNECTOR_TYPES = ("connector_corners",)
CONNECTOR_COLOUR = "grey"


def _connector(c: Ctx) -> Design:
    return Design(CONNECTOR_COLOUR, [])  # the sleeve itself is made by _connector_body


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


def _bulge(length: float, z0: float, z1: float) -> Part:
    """A clamping bulge on the inside of a wall, in its own frame: x along the wall (centred),
    y inwards from the wall's inner face, z up from z0 to z1. CONNECTOR_BULGE high, with 45
    degree slopes all round, so a tile slides over it and it prints without support; it
    reaches 0.4 mm into the wall to join it."""
    d, sink = CONNECTOR_BULGE, 0.4
    side = Plane.YZ * Polygon(*[(-sink, z0), (0, z0), (d, z0 + d), (d, z1 - d), (0, z1), (-sink, z1)],
                               align=None)  # across the wall: (y, z)
    plan = _poly([(-length / 2, -sink), (-length / 2, 0), (-length / 2 + d, d), (length / 2 - d, d),
                  (length / 2, 0), (length / 2, -sink)])  # seen from above: (x, y), counterclockwise
    across = extrude(side, amount=length / 2 + 1, both=True)
    along = Pos(0, 0, z0 - 1) * extrude(plan, amount=z1 - z0 + 2)
    return Part((across & along).wrapped)


def _connector_bulges(p: TileParams) -> list[Part]:
    """Clamping bulges on the inside of the walls, at the middle of the edges: two opposite
    edges get one in the lower socket, two others one in the upper socket, so each tile is
    clamped from two directions and the sleeve flexes. A hexagon has three pairs of opposite
    edges: the third pair gets none. A triangle has no opposite edges: every edge gets one in
    both sockets. A circle gets four, a quarter turn apart."""
    lower = (0.2, CONNECTOR_SOCKET)
    upper = (CONNECTOR_SOCKET + CONNECTOR_STOP_HEIGHT, CONNECTOR_HEIGHT - 0.2)
    if p.shape == "circle":
        r = p.size / 2 + p.clearance
        length = min(CONNECTOR_BULGE_LENGTH, 0.3 * r)  # short, as the wall curves away from it
        places = [((r * math.cos(t), r * math.sin(t)), math.degrees(t) + 90, [lower if k % 2 == 0 else upper], length)
                  for k, t in enumerate(np.radians(np.arange(4) * 90.0))]
    else:
        pts = _grow_polygon(outline_points(p), p.clearance)
        n = len(pts)
        places = []
        for i in range(n):
            p0, p1 = pts[i], pts[(i + 1) % n]
            edge = float(np.hypot(*(p1 - p0)))
            if n == 3:
                halves = [lower, upper]
            elif n == 6:
                halves = [[lower], [upper], []][i % 3]
            else:
                halves = [lower if i % 2 == 0 else upper]
            places.append(((p0 + p1) / 2, math.degrees(math.atan2(*(p1 - p0)[::-1])),
                           halves, min(CONNECTOR_BULGE_LENGTH, edge / 3)))
    out = []
    for (x, y), angle, halves, length in places:
        for z0, z1 in halves:  # the edge runs along x, counterclockwise: inwards is +y
            out.append(Location((float(x), float(y), 0), (0, 0, angle)) * _bulge(length, z0, z1))
    return out


def _connector_body(c: Ctx) -> Part:
    """The sleeve, bottom at z = 0: the tile outline grown by the clearance inside, a wall
    around it, halfway up the corner stops (_corner_stops), and the clamping bulges
    (_connector_bulges). Corners stay sharp, like the tile's."""
    p = c.p
    inner = _sk(offset(c.outline, p.clearance, kind=Kind.INTERSECTION)) if p.clearance else c.outline
    outer = _sk(offset(inner, p.wall, kind=Kind.INTERSECTION))
    wall = extrude(_sk(outer - inner), amount=CONNECTOR_HEIGHT)
    stop = _sk(inner & _union(_corner_stops(c.p)))
    stops = Pos(0, 0, CONNECTOR_SOCKET) * extrude(stop, amount=CONNECTOR_STOP_HEIGHT)
    return _fuse([Part(wall.wrapped), Part(stops.wrapped)] + _connector_bulges(p))


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
    "dune": TileType("Dune", "Terrain", _dune, "a sand dune across the tile: rippled windward slope, sharp crest, steep slip face"),
    "mountain": TileType("Mountain", "Terrain", _mountain, "rocky mountain with a snowy top and a second peak, on grassland"),
    "bricks": TileType("Bricks", "Terrain", _bricks, "brick wall in running bond with deep mortar joints"),
    "water": TileType("Water", "Elements", _water, "raised waves with white foam"),
    "sea": TileType("Sea", "Elements", _sea, "rolling sea: big waves across the tile with foam on the crests"),
    "thunderstorm": TileType("Thunderstorm", "Elements", _thunderstorm,
                             "a lightning bolt striking the wet ground, with a scorch mark, slanting rain and puddles"),
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
    "ship": TileType("Ship", "Objects", _ship,
                     "sailing ship on the waves with a mainsail and a jib, sailing along the tile (+X), with its wake behind"),
    "bulb": TileType("Light bulb", "Objects", _bulb, "light bulb standing on its screw socket, shining yellow rays on the floor"),
    "key": TileType("Key", "Objects", _key, "old gold key lying on a dark red cushion"),
    "weight": TileType("100t weight", "Objects", _weight, "cartoon iron weight marked 100t, landed on cracked earth"),
    "laser": TileType("Laser", "Objects", _laser, "a horizontal red laser beam from a steel emitter with a black lens, across the tile"),
    "mirror": TileType("Mirror (diagonal)", "Objects", _mirror,
                       "upright steel mirror standing along the diagonal"),
    "tree": TileType("Tree", "Objects", _tree,
                     "fir tree standing on grass, three tiers of foliage on a trunk, with roots and pine cones"),
    "connector_corners": TileType("Connector", "Special", _connector,
                                  f"sleeve to join a tile rigidly on top of a part of the same shape: "
                                  f"{CONNECTOR_HEIGHT:g} mm high, each tile goes in {CONNECTOR_SOCKET:g} mm from either side "
                                  f"and stops on a flat triangle in every inside corner ({CONNECTOR_CORNER:g} mm along each wall, "
                                  f"{CONNECTOR_STOP_HEIGHT:g} mm high), whose open edge is printed as a bridge "
                                  f"(a round one has {CONNECTOR_CIRCLE_STOPS} flat stops); "
                                  f"{CONNECTOR_BULGE:g} mm bulges inside the walls clamp the tiles, "
                                  "in the lower half on two opposite edges and in the upper half on two others. "
                                  "Wall thickness and clearance can be set"),
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
    "rain": (0.15, 3.0, "surface"),
    "fire": (0.2, 2.5, "surface"),
    "weight": (0.3, 2.5, "surface"),
    "tree": (0.45, 2.0, "both"),  # bark and foliage rough in all directions, the grass in height
    "key": (0.2, 2.5, "surface"),
    "sea": (0.15, 4.0, "surface"),
    "dune": (0.12, 3.0, "surface"),
    "mountain": (0.4, 2.5, "both"),  # rock and snow rough in all directions, the grass in height
    "thunderstorm": (0.15, 3.0, "surface"),
    "bulb": (0.15, 2.5, "surface"),
    "ship": (0.15, 4.0, "surface"),  # like the water tile
    "laser": (0.1, 2.5, "surface"),
    "mirror": (0.1, 2.5, "surface"),
}

# Bodies that stay smooth above the tile's top face on a rough tile (only "surface" mode): a
# made object lying on rough ground. Below the top they get the same roughness as the ground
# they are set into, so the two still meet.
SMOOTH_ABOVE_TOP = {
    "key": ("gold", "white"),  # the key and the sparkles
    "bulb": ("yellow", "black", "steel"),  # the bulb and its socket (the yellow rays on the floor too)
    "ship": ("wood", "dark_brown", "white"),
    "laser": ("steel", "black"),
    "mirror": ("steel",),
    "thunderstorm": ("yellow",),  # the lightning bolt  # the ship and its sails (the white foam too); the waves are rough
}


# Gentle hills in the printed mesh (3MF, preview), per type: (amplitude mm, wavelength mm), see
# cad_common/mesh_fuzz.hills. They fade out towards the tile's edges, so tiles still meet level.
HILLS = {
    "earth": (0.6, 22.0),
    "sand": (0.6, 22.0),
    "grass": (0.6, 22.0),
    "cobblestone": (0.5, 22.0),
    "tree": (0.6, 22.0),
    "mountain": (0.6, 22.0),
}


DEFAULT_ROUGH_SIZE = 2.5  # mm, bump size for a type that is smooth unless asked
DEFAULT_HILL_SIZE = 22.0  # mm, hill size for a type that is flat unless asked


def roughness(p: TileParams) -> tuple[float, float, str] | None:
    """(amplitude mm, wavelength mm, mode) of the rough top, or None: the type's own
    (ROUGHNESS) unless the parameters say otherwise."""
    own = ROUGHNESS.get(p.tile_type)
    amp = p.rough_depth if p.rough_depth >= 0 else (own[0] if own else 0.0)
    size = p.rough_size if p.rough_size > 0 else (own[1] if own else DEFAULT_ROUGH_SIZE)
    return (amp, size, own[2] if own else "surface") if amp > 0 else None


def hilliness(p: TileParams) -> tuple[float, float] | None:
    """(amplitude mm, wavelength mm) of the gentle hills, or None (see roughness)."""
    own = HILLS.get(p.tile_type)
    amp = p.hill_height if p.hill_height >= 0 else (own[0] if own else 0.0)
    return (amp, own[1] if own else DEFAULT_HILL_SIZE) if amp > 0 else None


# --- Building ---

def validate(p: TileParams) -> None:
    if p.tile_type not in TILE_TYPES:
        raise ValueError(f"Unknown tile type '{p.tile_type}'; choose one of: {', '.join(TILE_TYPES)}.")
    if p.shape not in SHAPES:
        raise ValueError(f"Unknown shape '{p.shape}'; choose one of: {', '.join(SHAPES)}.")
    if p.rough_depth > 2:
        raise ValueError("Roughness depth can be at most 2 mm.")
    if p.rough_size > 0 and not 0.5 <= p.rough_size <= 50:
        raise ValueError("Roughness size must be between 0.5 and 50 mm.")
    if p.hill_height > 5:
        raise ValueError("Hill height can be at most 5 mm.")
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
    if p.base_colour and p.base_colour not in PALETTE:
        raise ValueError(f"Unknown base colour '{p.base_colour}'; choose one of: {', '.join(PALETTE)}.")
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
    # The bottom of the tile as a body of its own (base_colour), up to just below the lowest
    # visible point of the top (inlays, grooves, sunk parts), on a 0.2 mm layer.
    split = _base_split(p, design, min((s.bounding_box().min.Z for s in cuts), default=top))
    if split:
        slab = Part(extrude(c.outline, amount=split).wrapped)
        bodies[design.base][0] = Part((bodies[design.base][0] - slab).wrapped)
        # The bottom body first; joined to other parts in that colour (e.g. white foam), if any.
        bodies = {p.base_colour: [slab] + bodies.get(p.base_colour, []),
                  **{name: parts for name, parts in bodies.items() if name != p.base_colour}}
    return {name: parts for name, parts in bodies.items() if parts}


BASE_LAYER = 0.2  # mm; the bottom body ends on a multiple of this


def _base_split(p: TileParams, design: Design, lowest: float) -> float:
    """Height of the bottom body in base_colour (0: none): below `lowest` (the lowest point of
    the top) by at least one layer, on a layer boundary, and at least two layers thick."""
    if not p.base_colour or p.base_colour == design.base:
        return 0.0
    split = math.floor((lowest - BASE_LAYER) / BASE_LAYER + 1e-6) * BASE_LAYER
    return round(split, 3) if split >= 2 * BASE_LAYER - 1e-9 else 0.0


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
    if p.tile_type not in CONNECTOR_TYPES and p.base_colour and p.base_colour != design.base:
        names = [p.base_colour] + [n for n in names if n != p.base_colour]
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


def describe(p: TileParams, colors: list[str] | None = None) -> str:
    """A sentence about the tile; `colors` (colors_used) when already known, as working them
    out makes the whole design."""
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
    colors = colors if colors is not None else colors_used(p)
    bottom = (f" The bottom (below everything you see on top) is a body of its own in {p.base_colour.replace('_', ' ')}, "
              f"to save the scarcer colours." if colors[0] == p.base_colour and p.base_colour else "")
    return (f"{n}: {t.title.lower()}, {t.description}; {p.shape}, {dims}, {p.thickness:g} mm thick. "
            f"{len(colors)} colours: {', '.join(c.replace('_', ' ') for c in colors)} (bottom first).{bottom}")


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
    ap.add_argument("--base-colour", default="white", help="colour of the tile's bottom body ('' = the tile's own)")
    ap.add_argument("--out", default="game_tile.step")
    a = ap.parse_args()
    p = TileParams(a.type, a.shape, a.size, a.length, a.thickness, a.inlay_depth, a.count, a.seed, a.wall, a.clearance, a.base_colour)
    export_step(build_tiles(p), a.out)
    print(describe(p))
    print(f"Wrote {a.out}")


if __name__ == "__main__":
    main()
