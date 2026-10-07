"""
    Geometry construction for a two-colour camera calibration plate.

    Top face:    a regular checkerboard.
    Bottom face: an AprilGrid (Kalibr-style grid of tag36h11 AprilTags with black
                 squares in the corners between the tags).

    The plate is split into two solids that together fill it exactly:
      * "white": the plate with the black pattern cut out as shallow pockets
      * "black": the pattern that fills those pockets
    Both are exported as separate bodies in one STEP file, so a multimaterial
    slicer can assign one filament to each body.

    Black shapes that would touch only at a corner (checkerboard squares, diagonal tag
    cells, AprilGrid corner squares) are joined by a tiny bridge square, because a
    zero-width contact is a non-manifold edge that slicers reject.

    The number of squares/tags is derived from the plate size, the square/tag size
    and the minimum white margin; the pattern is centred on its face. Both faces
    are drawn as seen from outside the plate (so the bottom one is not mirrored).

    Can also be run standalone:
        python calibration_plate_model.py --out plate.step
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

from build123d import Box, Color, Compound, Part, Pos, Rectangle, Rot, Sketch, export_step, extrude

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tag36h11_codes import BIT_XY, CODES  # noqa: E402

Rect = tuple[float, float, float, float]  # (x0, y0, x1, y1) in face coordinates, mm

_BRIDGE_SIZE = 0.1  # mm; width of the bridge joining corner-touching black shapes


@dataclass
class PlateParams:
    width: float = 300.0  # along x
    length: float = 320.0  # along y
    thickness: float = 10.0
    depth: float = 1.0  # depth of the black layer
    margin: float = 10.0  # minimum white margin around each pattern
    square_size: float = 20.0  # checkerboard square
    tag_size: float = 34.0  # AprilTag outer black edge to edge
    tag_spacing: float = 0.3  # gap between tags as a fraction of tag_size (Kalibr convention)
    border_bits: int = 2  # black border width in bits: 2 = Kalibr, 1 = standard AprilTag/OpenCV
    corner_squares: bool = True  # black squares between tag corners (Kalibr AprilGrid)
    first_tag_id: int = 0


@dataclass
class PlateLayout:
    checker_cols: int
    checker_rows: int
    tag_cols: int
    tag_rows: int
    top: list[Rect] = field(default_factory=list)  # checkerboard squares and bridges
    bottom: list[Rect] = field(default_factory=list)  # AprilGrid cells, corner squares and bridges

    def kalibr_yaml(self, p: PlateParams) -> str:
        return (
            "target_type: 'aprilgrid'\n"
            f"tagCols: {self.tag_cols}\n"
            f"tagRows: {self.tag_rows}\n"
            f"tagSize: {p.tag_size / 1000:.6f}  # m\n"
            f"tagSpacing: {p.tag_spacing:g}\n"
        )

    def checkerboard_yaml(self, p: PlateParams) -> str:
        return (
            "target_type: 'checkerboard'\n"
            f"targetCols: {self.checker_cols - 1}  # inner corners\n"
            f"targetRows: {self.checker_rows - 1}\n"
            f"rowSpacingMeters: {p.square_size / 1000:.6f}\n"
            f"colSpacingMeters: {p.square_size / 1000:.6f}\n"
        )


def tag36h11_cells(tag_id: int, border_bits: int) -> list[list[bool]]:
    """Return the tag as a square grid [row][col] (row 0 = top), True = black cell."""
    if not 0 <= tag_id < len(CODES):
        raise ValueError(f"tag36h11 id must be between 0 and {len(CODES) - 1}.")
    n = 6 + 2 * border_bits
    black = [[True] * n for _ in range(n)]
    code = CODES[tag_id]
    for i, (x, y) in enumerate(BIT_XY):
        # BIT_XY indexes an 8x8 square with a 1-bit border; shift for wider borders.
        if code & (1 << (35 - i)):
            black[y - 1 + border_bits][x - 1 + border_bits] = False
    return black


def _row_runs(cells: list[list[bool]], x0: float, y_top: float, cell: float) -> list[Rect]:
    """Merge horizontal runs of black cells into rectangles."""
    rects = []
    for r, row in enumerate(cells):
        c = 0
        while c < len(row):
            if row[c]:
                start = c
                while c < len(row) and row[c]:
                    c += 1
                rects.append((x0 + start * cell, y_top - (r + 1) * cell, x0 + c * cell, y_top - r * cell))
            else:
                c += 1
    return rects


def _bridge(x: float, y: float, size: float) -> Rect:
    return (x - size / 2, y - size / 2, x + size / 2, y + size / 2)


def _diagonal_corners(cells: list[list[bool]]) -> list[tuple[int, int]]:
    """Grid vertices (row, col) where two black cells touch only at that corner."""
    out = []
    for r in range(len(cells) - 1):
        for c in range(len(cells[r]) - 1):
            a, b, d, e = cells[r][c], cells[r][c + 1], cells[r + 1][c], cells[r + 1][c + 1]
            if (a and e and not b and not d) or (b and d and not a and not e):
                out.append((r + 1, c + 1))
    return out


def pattern_warning(p: PlateParams) -> str | None:
    """Warn about a tag border / corner square mix that matches neither AprilGrid convention.

    Kalibr's AprilGrid uses a 2-bit border together with corner squares; a standard
    AprilTag grid uses a 1-bit border without them. A mix still builds, so this is a
    warning rather than an error.
    """
    if p.border_bits == 1 and p.corner_squares:
        return (
            "Corner squares are a Kalibr AprilGrid feature, but Kalibr's detector expects a 2-bit tag "
            "border and will not find 1-bit tags. Use a 2-bit border for Kalibr, or turn the corner "
            "squares off for a standard AprilTag grid."
        )
    if p.border_bits == 2 and not p.corner_squares:
        return (
            "A 2-bit tag border is the Kalibr AprilGrid format, but Kalibr's AprilGrid also has corner "
            "squares (they make the tag corners symmetric for accurate sub-pixel refinement). Turn the "
            "corner squares on for Kalibr, or use a 1-bit border for a standard AprilTag grid."
        )
    return None


def compute_layout(p: PlateParams) -> PlateLayout:
    if min(p.width, p.length, p.thickness, p.square_size, p.tag_size) <= 0:
        raise ValueError("Plate dimensions, square size and tag size must be greater than 0.")
    if not 0 < p.depth < p.thickness / 2:
        raise ValueError("Black depth must be positive and less than half the plate thickness.")
    if p.margin < 0 or p.tag_spacing <= 0:
        raise ValueError("Margin must be >= 0 and tag spacing must be > 0.")
    if p.border_bits not in (1, 2):
        raise ValueError("Border bits must be 1 or 2.")

    usable_w, usable_l = p.width - 2 * p.margin, p.length - 2 * p.margin

    # --- Checkerboard (top). The top-left square is black.
    s = p.square_size
    cols, rows = math.floor(usable_w / s), math.floor(usable_l / s)
    if cols < 3 or rows < 3:
        raise ValueError("Checkerboard needs at least 3x3 squares; reduce square size or margin.")
    x0, y_top = -cols * s / 2, rows * s / 2
    top = [
        (x0 + c * s, y_top - (r + 1) * s, x0 + (c + 1) * s, y_top - r * s)
        for r in range(rows)
        for c in range(cols)
        if (r + c) % 2 == 0
    ]
    # Every interior grid vertex of a checkerboard is a corner-only contact.
    bridge = min(_BRIDGE_SIZE, s / 10)
    top += [_bridge(x0 + c * s, y_top - r * s, bridge) for r in range(1, rows) for c in range(1, cols)]

    # --- AprilGrid (bottom). n tags span n*t + (n+1)*gap, gap squares included.
    t = p.tag_size
    gap = p.tag_spacing * t
    tag_cols = math.floor((usable_w - gap) / (t + gap))
    tag_rows = math.floor((usable_l - gap) / (t + gap))
    if tag_cols < 1 or tag_rows < 1:
        raise ValueError("No AprilTags fit; reduce tag size, spacing or margin.")
    if p.first_tag_id < 0 or p.first_tag_id + tag_cols * tag_rows > len(CODES):
        raise ValueError(
            f"Tag ids {p.first_tag_id}..{p.first_tag_id + tag_cols * tag_rows - 1} exceed tag36h11 (0-{len(CODES) - 1})."
        )
    gx0 = -(tag_cols * t + (tag_cols + 1) * gap) / 2
    gy0 = -(tag_rows * t + (tag_rows + 1) * gap) / 2
    cell = t / (6 + 2 * p.border_bits)
    bridge = min(_BRIDGE_SIZE, cell / 10)
    bottom: list[Rect] = []
    # Kalibr numbering: id 0 at bottom-left, increasing to the right, then upwards.
    for r in range(tag_rows):
        for c in range(tag_cols):
            tx = gx0 + gap + c * (t + gap)
            ty = gy0 + gap + r * (t + gap)
            cells = tag36h11_cells(p.first_tag_id + r * tag_cols + c, p.border_bits)
            bottom += _row_runs(cells, tx, ty + t, cell)
            bottom += [_bridge(tx + cc * cell, ty + t - cr * cell, bridge) for cr, cc in _diagonal_corners(cells)]
            if p.corner_squares:  # each tag corner touches a corner square diagonally
                bottom += [_bridge(tx + dx, ty + dy, bridge) for dx in (0, t) for dy in (0, t)]
    if p.corner_squares:
        for r in range(tag_rows + 1):
            for c in range(tag_cols + 1):
                x = gx0 + c * (t + gap)
                y = gy0 + r * (t + gap)
                bottom.append((x, y, x + gap, y + gap))

    return PlateLayout(cols, rows, tag_cols, tag_rows, top, bottom)


def _rects_to_solid(rects: list[Rect], z_top: float, depth: float) -> Part:
    """Union the rectangles in 2D and extrude them down from z_top."""
    with_faces = [Pos((x0 + x1) / 2, (y0 + y1) / 2) * Rectangle(x1 - x0, y1 - y0) for x0, y0, x1, y1 in rects]
    sketch = with_faces[0] if len(with_faces) == 1 else Sketch() + with_faces
    return Pos(0, 0, z_top) * extrude(sketch, amount=-depth)


def build_calibration_plate(p: PlateParams) -> tuple[Compound, PlateLayout]:
    """Build a compound with two bodies (labels 'white' and 'black') plus its layout."""
    layout = compute_layout(p)
    z = p.thickness / 2
    # The bottom pattern is built on top and flipped about Y, which keeps it readable from below.
    black_solids = [_rects_to_solid(layout.top, z, p.depth), Rot(0, 180, 0) * _rects_to_solid(layout.bottom, z, p.depth)]

    black = Part(Compound(black_solids).wrapped)
    white = Part(Box(p.width, p.length, p.thickness).cut(*black_solids).wrapped)
    white.label, black.label = "white", "black"
    white.color, black.color = Color(0.93, 0.93, 0.93), Color(0.07, 0.07, 0.07)
    return Compound(children=[white, black], label="calibration_plate"), layout


def export_calibration_plate(plate: Compound, path: str) -> None:
    export_step(plate, path)


def main() -> None:
    d = PlateParams()
    ap = argparse.ArgumentParser(description="Two-colour camera calibration plate (STEP)")
    ap.add_argument("--width", type=float, default=d.width)
    ap.add_argument("--length", type=float, default=d.length)
    ap.add_argument("--thickness", type=float, default=d.thickness)
    ap.add_argument("--depth", type=float, default=d.depth, help="black layer depth (mm)")
    ap.add_argument("--margin", type=float, default=d.margin, help="minimum white margin (mm)")
    ap.add_argument("--square", type=float, default=d.square_size, help="checkerboard square (mm)")
    ap.add_argument("--tag-size", type=float, default=d.tag_size, help="AprilTag size (mm)")
    ap.add_argument("--tag-spacing", type=float, default=d.tag_spacing, help="gap / tag size")
    ap.add_argument("--border-bits", type=int, default=d.border_bits, choices=(1, 2))
    ap.add_argument("--no-corner-squares", action="store_true")
    ap.add_argument("--first-id", type=int, default=d.first_tag_id)
    ap.add_argument("--out", default="calibration_plate.step")
    a = ap.parse_args()
    p = PlateParams(
        a.width, a.length, a.thickness, a.depth, a.margin, a.square, a.tag_size,
        a.tag_spacing, a.border_bits, not a.no_corner_squares, a.first_id,
    )
    warning = pattern_warning(p)
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)
    plate, layout = build_calibration_plate(p)
    export_calibration_plate(plate, a.out)
    print(f"Wrote {a.out}")
    print(f"Checkerboard: {layout.checker_cols}x{layout.checker_rows} squares\n{layout.checkerboard_yaml(p)}")
    print(f"AprilGrid: {layout.tag_cols}x{layout.tag_rows} tags\n{layout.kalibr_yaml(p)}")


if __name__ == "__main__":
    main()
