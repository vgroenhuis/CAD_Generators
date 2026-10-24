"""
    Geometry construction for a two-colour cube with an AprilTag (tag16h5) on five faces and a
    label on the bottom face, which the camera never sees.

    The cube is split into two solids that together fill the cube exactly:
      * "white": the cube with the black tag cells cut out as shallow pockets
      * "black": the tag cells that fill those pockets
    Both are exported as separate bodies in one STEP file, so a multimaterial
    slicer can assign one filament to each body.

    With five different tags, the first four go on the side faces in counterclockwise order as seen
    from above (+X, +Y, -X, -Y) and the fifth on the top face (+Z). Tags are upright as seen from
    outside: on the four side faces the tag's top edge points to +Z, on the top face to +Y.
    The bottom label is inlaid in black, flush with the face, and reads correctly from below. By
    default it is the tag id (same tag on all faces), "World frame" for the world-frame cube
    (ids 25-29), or the five ids ("0,1,2,3,4"); long labels are split over two lines when that
    gives a larger font.
    Optionally, short red (+X) and green (+Y) arrows lying on the floor beside the cube show the world frame.

    With several tag ids and the same tag on all faces, one cube per id is generated in the
    smallest square grid (2x2, 3x3, ...), 2 mm apart, still as just two bodies ("white" holding
    every cube's white part and "black" holding every black part).

    Can also be run standalone:  python apriltag_cube_model.py --id 3 --size 40 --out cube.step
"""

from __future__ import annotations

import argparse

import sys
from pathlib import Path

from build123d import Box, Color, Compound, Location, Part, Plane, Polygon, Pos, Rot, extrude, export_step

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cad_common.text import MIN_STROKE, min_font_size, printable_text  # noqa: E402

# Official codes of the AprilTag tag16h5 family (AprilRobotics/apriltag, tag16h5.c).
TAG16H5_CODES = [
    0x27C8, 0x31B6, 0x3859, 0x569C, 0x6C76, 0x7DDB, 0xAF09, 0xF5A1, 0xFB8B, 0x1CB9,
    0x28CA, 0xE8DC, 0x1426, 0x5770, 0x9253, 0xB702, 0x063A, 0x8F34, 0xB4C0, 0x51EC,
    0xE6F0, 0x5FA4, 0xDD43, 0x1AAA, 0xE62F, 0x6DBC, 0xB6EB, 0xDE10, 0x154D, 0xB57A,
]

# (x, y) of each code bit inside the 6x6 black-bordered square; bit 0 is the MSB.
_BIT_XY = [(1, 1), (2, 1), (3, 1), (2, 2), (4, 1), (4, 2), (4, 3), (3, 2),
           (4, 4), (3, 4), (2, 4), (3, 3), (1, 4), (1, 3), (1, 2), (2, 3)]

_ARROW_LENGTH = 0.45  # axis arrow length beyond the cube edge, x cube size
_ARROW_HEIGHT = 2.0  # mm; capped at half the quiet-zone width for small cubes
_ARROW_OVERLAP = 1.0  # mm the arrow tail reaches into the cube so the two touch properly
_BRIDGE_SIZE = 0.1  # mm; width of the bridge joining corner-touching black cells
GRID = 8  # total tag width in cells: 6x6 black-bordered tag + 1 white cell margin


def tag16h5_grid(tag_id: int) -> list[list[bool]]:
    """Return an 8x8 grid [row][col] (row 0 = top) where True means a black cell."""
    if not 0 <= tag_id < len(TAG16H5_CODES):
        raise ValueError(f"tag16h5 id must be between 0 and {len(TAG16H5_CODES) - 1}.")
    code = TAG16H5_CODES[tag_id]
    black = [[False] * GRID for _ in range(GRID)]
    for r in range(1, 7):
        for c in range(1, 7):
            black[r][c] = True  # border ring + data, data bits overwritten below
    for i, (x, y) in enumerate(_BIT_XY):
        is_white = bool(code & (1 << (15 - i)))
        black[y + 1][x + 1] = not is_white
    return black


def _face_cells(tag_id: int, size: float, depth: float) -> list[Part]:
    """Black cells for the +Z face, viewed from outside (x right, y up)."""
    cell = size / GRID
    grid = tag16h5_grid(tag_id)
    boxes = []
    for r in range(GRID):
        for c in range(GRID):
            if grid[r][c]:
                x = -size / 2 + (c + 0.5) * cell
                y = size / 2 - (r + 0.5) * cell
                z = size / 2 - depth / 2
                boxes.append(Pos(x, y, z) * Box(cell, cell, depth))

    # Two black cells that touch only at a corner would join along a zero-width line, which
    # is a non-manifold edge (slicers reject it). Bridge each such corner with a tiny square.
    bridge = min(_BRIDGE_SIZE, cell / 10)
    for r in range(GRID - 1):
        for c in range(GRID - 1):
            if grid[r][c] and grid[r + 1][c + 1] and not grid[r][c + 1] and not grid[r + 1][c]:
                corners = [(r + 1, c + 1)]
            elif grid[r][c + 1] and grid[r + 1][c] and not grid[r][c] and not grid[r + 1][c + 1]:
                corners = [(r + 1, c + 1)]
            else:
                continue
            for cr, cc in corners:
                x = -size / 2 + cc * cell
                y = size / 2 - cr * cell
                boxes.append(Pos(x, y, size / 2 - depth / 2) * Box(bridge, bridge, depth))
    return boxes


# Placement of the tag on each face as (outward normal, direction of the tag's "right" edge as
# seen from outside). The tag's "up" is then normal cross right, which makes every placement a
# proper rotation of the +Z face (no mirroring).
# Order: the four side faces counterclockwise as seen from above, then the top face.
# Orientation: on the four side faces the tag is upright (its top edge points to +Z). On the top
# face its top edge points to +Y.
_FACE_PLANES = [
    ((1, 0, 0), (0, 1, 0)),    # +X
    ((0, 1, 0), (-1, 0, 0)),   # +Y
    ((-1, 0, 0), (0, -1, 0)),  # -X
    ((0, -1, 0), (1, 0, 0)),   # -Y
    ((0, 0, 1), (1, 0, 0)),    # +Z (top)
]
_FACE_PLACEMENTS = [Location(Plane(origin=(0, 0, 0), x_dir=right, z_dir=normal)) for normal, right in _FACE_PLANES]
FACE_NAMES = ["+X", "+Y", "-X", "-Y", "+Z (top)"]
# The bottom face (-Z) carries the label; its top edge points to -Y, as if unfolded from the -Y face.
_BOTTOM_PLACEMENT = Location(Plane(origin=(0, 0, 0), x_dir=(1, 0, 0), z_dir=(0, 0, -1)))

WORLD_FRAME_IDS = (25, 26, 27, 28, 29)  # +X, +Y, -X, -Y, +Z
WORLD_FRAME_LABEL = "World frame"
_LABEL_AREA = 0.8  # label width and height at most this x cube size
_LABEL_MAX_FONT = 0.3  # largest font size, x cube size
_LINE_PITCH = 1.25  # baseline-to-baseline distance, x font size


GRID_SPACING = 2.0  # mm between neighbouring cubes when several cubes are generated
MAX_CUBES = 64


def parse_tag_ids(text: str, per_face: bool | None = None) -> list[int]:
    """Parse '3' or '0,1,2,3,4' into a list of tag ids.

    per_face=True requires exactly five ids (four side faces counterclockwise from +X, then the
    top). per_face=False accepts one or more ids (the same tag on all faces of each cube, one
    cube per id). None accepts either a single id or five per-face ids.
    """
    try:
        ids = [int(part) for part in text.replace(";", ",").split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError("Tag IDs must be integers, separated by commas.") from exc
    n_faces = len(_FACE_PLANES)
    if per_face is False and not ids:
        raise ValueError("Enter at least one tag ID.")
    if per_face is False and len(ids) > MAX_CUBES:
        raise ValueError(f"At most {MAX_CUBES} cubes can be generated at once.")
    if per_face is True and len(ids) != n_faces:
        raise ValueError(f"Enter {n_faces} comma-separated tag IDs: four sides counterclockwise from +X, then the top.")
    if per_face is None and len(ids) not in (1, n_faces):
        raise ValueError(f"Enter one tag ID (used on all faces) or {n_faces} IDs (four sides, then the top).")
    bad = [i for i in ids if not 0 <= i < len(TAG16H5_CODES)]
    if bad:
        raise ValueError(f"Tag IDs must be between 0 and {len(TAG16H5_CODES) - 1}.")
    return ids


def _flat_arrow(size: float, angle: float, start: float) -> Part:
    """Flat arrow on the floor, pointing along +X (then rotated by `angle` degrees about Z).

    Its bottom face is coplanar with the cube's bottom face (z = -size/2) and it rises from
    there, 2 mm high but at most half the width of the white quiet zone along the bottom edge
    of the tag faces, so it stays well clear of the black tag cells. The tail starts
    _ARROW_OVERLAP inside the footprint edge `start`, so it joins the cube (the overlapping
    volume is cut out of the white body, see _cut_arrows); the tip is _ARROW_LENGTH x size
    beyond that edge.

    Each arrow is extruded from scratch (not a rotated copy of another one): colours are stored
    per underlying shape, so copies sharing a shape would also share a colour.
    """
    visible = _ARROW_LENGTH * size
    shaft_w = 0.10 * size
    head_w = 0.24 * size
    head_len = 0.20 * size
    thickness = min(_ARROW_HEIGHT, size / GRID / 2)  # at most half the quiet-zone width
    length = _ARROW_OVERLAP + visible
    shaft_end = length - head_len
    outline = Polygon(
        (0, -shaft_w / 2), (shaft_end, -shaft_w / 2), (shaft_end, -head_w / 2), (length, 0),
        (shaft_end, head_w / 2), (shaft_end, shaft_w / 2), (0, shaft_w / 2),
        align=None,
    )
    arrow = Part(extrude(outline, amount=thickness).wrapped)
    return Part((Rot(0, 0, angle) * Pos(start - _ARROW_OVERLAP, 0, -size / 2) * arrow).wrapped)


def _axis_arrows(size: float, extent: float | None = None) -> list[Part]:
    """Red (+X) and green (+Y) short, flat arrows on the floor beside the cube(s).

    They start at the edge of the footprint (width `extent`, defaults to one cube) on the X and
    Y axes through its centre, which is the world origin, and point away from it.
    """
    start = (extent if extent is not None else size) / 2
    red, green = _flat_arrow(size, 0, start), _flat_arrow(size, 90, start)
    red.label, red.color = "red", Color("red")
    green.label, green.color = "green", Color("green")
    return [red, green]


def default_label(ids: list[int]) -> str:
    """Bottom label for a cube with these tag ids (one id, or one per face)."""
    if tuple(ids) == WORLD_FRAME_IDS:
        return WORLD_FRAME_LABEL
    if len(set(ids)) == 1:
        return str(ids[0])
    return ",".join(map(str, ids))


def _label_line_options(text: str) -> list[list[str]]:
    """Ways to lay out the label: as typed with '|' as line break, or else on one line or
    split over two lines after any space or comma."""
    if "|" in text:
        return [[line.strip() for line in text.split("|")]]
    options = [[text]]
    for i, ch in enumerate(text):
        if ch in " ,":
            first, second = text[: i + 1].strip(), text[i + 1:].strip()
            if first and second:
                options.append([first, second])
    return options


def label_layout(text: str, size: float) -> tuple[list[str], float]:
    """Lines and font size (mm) of the bottom label: the layout with the largest font that fits
    on the face, but never so small that the strokes get thinner than MIN_STROKE (then it is an
    error)."""
    avail = _LABEL_AREA * size
    ref = 10.0  # text widths scale linearly with the font size
    widths: dict[str, float] = {}
    best = None
    for lines in _label_line_options(text):
        for line in lines:
            if line not in widths:
                widths[line] = printable_text(line, ref).bounding_box().size.X if line else 0.0
        width = max(widths[line] for line in lines)
        font = min(_LABEL_MAX_FONT * size, avail / (_LINE_PITCH * (len(lines) - 1) + 1.0))
        if width > 0:
            font = min(font, ref * avail / width)
        # Largest font first; on a tie (font capped) fewer lines, then the most balanced split.
        score = (round(font, 6), -len(lines), -width)
        if best is None or score > best[0]:
            best = (score, lines, font)
    _, lines, font = best
    if font < min_font_size():
        raise ValueError(
            f"Label '{text}' is too long to print with lines of at least {MIN_STROKE:g} mm; "
            "use a shorter label (or | for a line break) or a larger cube."
        )
    return lines, font


def _label_cells(text: str, size: float, depth: float) -> list[Part]:
    """Label text as `depth` deep solids for the +Z face, viewed from outside (x right, y up)."""
    lines, font = label_layout(text, size)
    parts = []
    for i, line in enumerate(lines):
        if not line:
            continue
        y = ((len(lines) - 1) / 2 - i) * _LINE_PITCH * font
        solid = extrude(printable_text(line, font), amount=depth)
        parts.append(Part((Pos(0, y, size / 2 - depth) * solid).wrapped))
    return parts


def _check_dimensions(size: float, depth: float) -> None:
    if size <= 0:
        raise ValueError("Cube size must be greater than 0.")
    if not 0 < depth < size / 2:
        raise ValueError("Tag depth must be positive and smaller than half the cube size.")


def _build_cube_bodies(ids: list[int], size: float, depth: float, label: str = "") -> tuple[Part, Part]:
    """White and black solids of one cube centred on the origin; ids has one tag id per tag
    face, and a non-empty label is inlaid in the bottom face."""
    face_parts = []
    cells_by_id: dict[int, list[Part]] = {}
    for tag_id, placement in zip(ids, _FACE_PLACEMENTS):
        if tag_id not in cells_by_id:
            cells_by_id[tag_id] = _face_cells(tag_id, size, depth)
        for b in cells_by_id[tag_id]:
            face_parts.append(placement * b)
    if label.strip():
        face_parts += [_BOTTOM_PLACEMENT * b for b in _label_cells(label.strip(), size, depth)]

    black = Part(face_parts[0].fuse(*face_parts[1:]).clean().wrapped)
    white = Part(Box(size, size, size).cut(black).clean().wrapped)
    return white, black


def _cut_arrows(white: Part, arrows: list[Part]) -> Part:
    """Remove the volume where the arrow tails overlap the white body.

    The arrows never reach the black tag cells, so only the white body needs trimming; this
    leaves every body disjoint, so no volume is claimed by two filaments.
    """
    if not arrows:
        return white
    return Part(white.cut(*arrows).clean().wrapped)


def _label_bodies(white, black) -> None:
    white.label, black.label = "white", "black"
    white.color, black.color = Color(0.93, 0.93, 0.93), Color(0.07, 0.07, 0.07)


def build_apriltag_cube(
    tag_ids: int | list[int], size: float, depth: float = 1.0, axes: bool = False, label: str | None = None
) -> Compound:
    """Build a compound with two bodies (labels 'white' and 'black').

    tag_ids is either one id (same tag on all faces) or five ids in FACE_NAMES order.
    label is the bottom label: None for default_label(ids), "" for none.
    With axes=True, two extra bodies 'red' (+X) and 'green' (+Y) are added on the floor beside the cube.
    """
    ids = [tag_ids] if isinstance(tag_ids, int) else list(tag_ids)
    if len(ids) == 1:
        ids = ids * len(_FACE_PLANES)
    if len(ids) != len(_FACE_PLANES):
        raise ValueError(f"Provide one tag ID or {len(_FACE_PLANES)} (four sides, then the top).")
    _check_dimensions(size, depth)
    if label is None:
        label = default_label(ids)

    white, black = _build_cube_bodies(ids, size, depth, label)
    arrows = _axis_arrows(size) if axes else []
    white = _cut_arrows(white, arrows)
    _label_bodies(white, black)
    return Compound(children=[white, black] + arrows, label="apriltag_cube")


def grid_dimension(count: int) -> int:
    """Side length n of the smallest square n x n grid that holds `count` cubes."""
    n = 1
    while n * n < count:
        n += 1
    return n


def build_apriltag_cube_grid(
    tag_ids: list[int], size: float, depth: float = 1.0, axes: bool = False, spacing: float = GRID_SPACING,
    labels: bool = True,
) -> Compound:
    """One cube per tag id (same tag on all five tag faces), in the smallest square grid.

    Cubes are `spacing` mm apart, filled row by row starting at the top-left (looking down
    +Z with +X right and +Y up), and the grid is centred on the origin. All white parts form
    one body 'white' and all black parts one body 'black', so a slicer can assign each filament
    once for every cube. With labels=True each cube's bottom face carries its tag id. With a
    single id this is the same as build_apriltag_cube.
    """
    ids = list(tag_ids)
    if not ids:
        raise ValueError("Provide at least one tag ID.")
    if len(ids) > MAX_CUBES:
        raise ValueError(f"At most {MAX_CUBES} cubes can be generated at once.")
    if len(ids) == 1:
        return build_apriltag_cube(ids[0], size, depth, axes, None if labels else "")
    _check_dimensions(size, depth)

    n = grid_dimension(len(ids))
    pitch = size + spacing
    extent = n * size + (n - 1) * spacing
    arrows = _axis_arrows(size, extent) if axes else []
    whites, blacks = [], []
    bodies_by_id: dict[int, tuple[Part, Part]] = {}
    for index, tag_id in enumerate(ids):
        if tag_id not in bodies_by_id:
            bodies_by_id[tag_id] = _build_cube_bodies(
                [tag_id] * len(_FACE_PLANES), size, depth, str(tag_id) if labels else ""
            )
        row, col = divmod(index, n)
        shift = Pos(-extent / 2 + size / 2 + col * pitch, extent / 2 - size / 2 - row * pitch, 0)
        white, black = bodies_by_id[tag_id]
        whites.append(_cut_arrows(Part((shift * white).wrapped), arrows))
        blacks.append(Part((shift * black).wrapped))

    white = Compound(children=whites)
    black = Compound(children=blacks)
    _label_bodies(white, black)
    return Compound(children=[white, black] + arrows, label="apriltag_cubes")


def export_apriltag_cube(cube: Compound, path: str) -> None:
    export_step(cube, path)


def main() -> None:
    ap = argparse.ArgumentParser(description="AprilTag tag16h5 two-colour cube (STEP)")
    ap.add_argument("--id", default="0", help="tag16h5 id 0-29, or 5 comma-separated ids: +X, +Y, -X, -Y (sides, "
                    "counterclockwise from above), then +Z (top)")
    ap.add_argument("--world-frame", action="store_true", help=f"world-frame cube: ids {','.join(map(str, WORLD_FRAME_IDS))}, "
                    f"label '{WORLD_FRAME_LABEL}' and axes; used instead of --id")
    ap.add_argument("--label", help="bottom label (default: the tag id(s), or 'World frame'); '|' is a line break, "
                    "empty for none")
    ap.add_argument("--size", type=float, default=40.0, help="cube edge length (mm)")
    ap.add_argument("--depth", type=float, default=1.0, help="black layer depth (mm)")
    ap.add_argument("--cubes", help="comma-separated tag ids: one cube (same tag on all faces) per id, in a square grid "
                    f"{GRID_SPACING:g} mm apart; used instead of --id")
    ap.add_argument("--axes", action="store_true", help="add red (+X) and green (+Y) world-frame arrows on the floor beside the cube(s)")
    ap.add_argument("--out", default="apriltag_cube.step")
    a = ap.parse_args()
    if a.world_frame:
        cube = build_apriltag_cube(list(WORLD_FRAME_IDS), a.size, a.depth, True, a.label)
    elif a.cubes:
        cube = build_apriltag_cube_grid(parse_tag_ids(a.cubes, per_face=False), a.size, a.depth, a.axes,
                                        labels=a.label != "")
    else:
        cube = build_apriltag_cube(parse_tag_ids(a.id), a.size, a.depth, a.axes, a.label)
    export_apriltag_cube(cube, a.out)
    print(f"Wrote {a.out}")


if __name__ == "__main__":
    main()
