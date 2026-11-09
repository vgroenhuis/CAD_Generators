"""
    Geometry construction for a two-colour cube with an AprilTag (tag16h5) on five faces and a
    label on the bottom face, which the camera never sees, or (bottom_tag=True) a tag on all six faces.

    The cube is split into two solids that together fill the cube exactly:
      * "white": the cube with the black tag cells cut out as shallow pockets
      * "black": the tag cells that fill those pockets
    Both are exported as separate bodies in one STEP file, so a multimaterial
    slicer can assign one filament to each body.

    With five different tags, the first four go on the side faces in counterclockwise order as seen
    from above (+X, +Y, -X, -Y) and the fifth on the top face (+Z). Tags are upright as seen from
    outside: on the four side faces the tag's top edge points to +Z, on the top face to +Y.
    With bottom_tag=True a sixth tag goes on the bottom face (-Z), its top edge pointing to -Y.
    The bottom label is inlaid in black, flush with the face, and reads correctly from below. By
    default it is the tag id (same tag on all faces), or with five different tags the four side ids along the matching bottom edges
    (each reading upright with that edge nearest) and the top id in the centre. A label given as
    text is centred; long labels are split over two lines when that gives a larger font.
    Optionally, short red (+X) and green (+Y) arrows lying on the floor beside the cube show the world frame.
    The world-frame cube (build_world_frame_cube) has tag WORLD_FRAME_ID on all five faces with the
    side tags turned, the label "World frame" and the arrows.
    Optionally (edge_colours=True), a red strip along the bottom edge of the +X face and a green
    one along the bottom edge of the +Y face show the cube's own axes; they are inlaid flush like
    the tag, in the lower part of the white margin below the tag, so the cube keeps its size, with
    their ends cut at 45 degrees so each colour shows on its own face only.

    With the same tag on all faces, rotate_sides=True turns the tag on each side face a further
    quarter turn counterclockwise (as seen from outside): its top edge points up on +X, left on
    +Y, down on -X and right on -Y. A detector reports which way a tag is turned, so for a cube
    standing upright (top face up) it can tell the four sides apart, and with that the cube's
    heading, while each cube still uses just one tag id.

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
FACE_NAMES = ["+X", "+Y", "-X", "-Y", "+Z (top)", "-Z (bottom)"]
# The bottom face (-Z) carries the label, or a sixth tag; its top edge points to -Y, as if unfolded
# from the -Y face. Seen from below, +X is then on the right, -Y at the top.
_BOTTOM_PLACEMENT = Location(Plane(origin=(0, 0, 0), x_dir=(1, 0, 0), z_dir=(0, 0, -1)))
_TAG_FACES = 5  # without a tag on the bottom
# Text rotation (degrees, in the bottom face seen from below) of each side face's id along the
# matching bottom edge, so it reads upright with that edge nearest: +X right, +Y bottom, -X left,
# -Y top.
_EDGE_ROTATIONS = (90, 0, 270, 180)
# Extra counterclockwise turn (degrees, seen from outside) of the tag on each side face with
# rotate_sides, in _FACE_PLANES order (+X, +Y, -X, -Y).
SIDE_TURNS = (0, 90, 180, 270)
_EDGE_FONT = 0.2  # font size of the ids along the edges and in the centre, x cube size
_EDGE_MARGIN = 0.06  # gap between the cube edge and the ids along it, x cube size

WORLD_FRAME_ID = 29  # on all five faces, the side tags turned so the cube's heading can be read
WORLD_FRAME_IDS = (WORLD_FRAME_ID,) * 5  # +X, +Y, -X, -Y, +Z
WORLD_FRAME_LABEL = "World frame"
_STRIP_HEIGHT = 2.0  # mm, height of the red/green bottom-edge strips at most
_STRIP_FRACTION = 1 / 3  # strip height as a fraction of the white margin (one cell)
_LABEL_AREA = 0.8  # label width and height at most this x cube size
_LABEL_MAX_FONT = 0.3  # largest font size, x cube size
_LINE_PITCH = 1.25  # baseline-to-baseline distance, x font size


DEFAULT_DEPTH = 0.7  # mm, depth of the black inlay
GRID_SPACING = 2.0  # mm between neighbouring cubes when several cubes are generated
MAX_CUBES = 64


def face_count(bottom_tag: bool = False) -> int:
    """Number of faces carrying a tag: five, or six with a tag on the bottom."""
    return _TAG_FACES + 1 if bottom_tag else _TAG_FACES


def _faces_text(n_faces: int) -> str:
    return "four sides counterclockwise from +X, then the top" + (" and the bottom" if n_faces > _TAG_FACES else "")


def parse_tag_ids(text: str, per_face: bool | None = None, bottom_tag: bool = False) -> list[int]:
    """Parse '3' or '0,1,2,3,4' into a list of tag ids.

    per_face=True requires exactly one id per tag face (four side faces counterclockwise from
    +X, then the top, and with bottom_tag the bottom). per_face=False accepts one or more ids
    (the same tag on all faces of each cube, one cube per id). None accepts either a single id
    or one id per tag face.
    """
    try:
        ids = [int(part) for part in text.replace(";", ",").split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError("Tag IDs must be integers, separated by commas.") from exc
    n_faces = face_count(bottom_tag)
    if per_face is False and not ids:
        raise ValueError("Enter at least one tag ID.")
    if per_face is False and len(ids) > MAX_CUBES:
        raise ValueError(f"At most {MAX_CUBES} cubes can be generated at once.")
    if per_face is True and len(ids) != n_faces:
        raise ValueError(f"Enter {n_faces} comma-separated tag IDs: {_faces_text(n_faces)}.")
    if per_face is None and len(ids) not in (1, n_faces):
        raise ValueError(f"Enter one tag ID (used on all faces) or {n_faces} IDs ({_faces_text(n_faces)}).")
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


def default_label(ids: list[int]) -> str | None:
    """Bottom label for a cube with these five tag ids (or one id): the id, or None for
    different tags, whose ids go along the bottom edges (see _edge_label_cells)."""
    if len(set(ids)) == 1:
        return str(ids[0])
    return None


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


def _edge_label_cells(ids: list[int], size: float, depth: float) -> list[Part]:
    """The five tag ids as `depth` deep solids for the bottom face (built as the +Z face viewed
    from outside, then placed by _BOTTOM_PLACEMENT): each side id along its own edge, reading
    upright with that edge nearest, and the top id in the centre."""
    font = _EDGE_FONT * size
    if font < min_font_size():
        raise ValueError(
            f"The cube is too small for the tag IDs along the bottom edges (lines at least {MIN_STROKE:g} mm); "
            f"use a cube of at least {min_font_size() / _EDGE_FONT:.0f} mm or enter a label."
        )
    parts = []
    for i, tag_id in enumerate(ids[:_TAG_FACES]):
        text = printable_text(str(tag_id), font)
        box = text.bounding_box()
        # Centre the digits on the origin, then move them to their spot (edge band or centre).
        solid = extrude(text, amount=depth)
        solid = Pos(-box.center().X, -box.center().Y, 0) * solid
        if i < len(_EDGE_ROTATIONS):
            offset = size / 2 - _EDGE_MARGIN * size - box.size.Y / 2
            solid = Rot(0, 0, _EDGE_ROTATIONS[i]) * Pos(0, -offset, 0) * solid
        parts.append(Part((Pos(0, 0, size / 2 - depth) * solid).wrapped))
    return parts


def _edge_strips(size: float, depth: float) -> tuple[Part, Part]:
    """Red (+X) and green (+Y) strips along the bottom edges of those faces, `depth` deep.

    They fill the lowest _STRIP_FRACTION of the white margin below the tag (at most
    _STRIP_HEIGHT), so the tag keeps most of its white border. Seen from above each strip is a
    trapezoid whose ends are cut at 45 degrees through the cube's vertical corner edges: red and
    green meet on that diagonal at their shared corner, and at their other ends the white takes
    over on the diagonal, so no colour shows on a neighbouring face.
    """
    h = min(_STRIP_HEIGHT, _STRIP_FRACTION * size / GRID)
    a, b = size / 2, size / 2 - depth
    red = Polygon((a, -a), (a, a), (b, b), (b, -b), align=None)
    green = Polygon((a, a), (-a, a), (-b, b), (b, b), align=None)
    return tuple(Part((Pos(0, 0, -size / 2) * extrude(outline, amount=h)).wrapped) for outline in (red, green))


def _check_dimensions(size: float, depth: float) -> None:
    if size <= 0:
        raise ValueError("Cube size must be greater than 0.")
    if not 0 < depth < size / 2:
        raise ValueError("Tag depth must be positive and smaller than half the cube size.")


def _build_cube_bodies(ids: list[int], size: float, depth: float, label: str | None = "",
                       rotate_sides: bool = False) -> tuple[Part, Part]:
    """White and black solids of one cube centred on the origin. ids has one tag id per tag
    face (five, or six with a tag on the bottom face). With five, a non-empty label is inlaid in
    the bottom face; label None puts the ids along the bottom edges instead. rotate_sides turns
    the side tags by SIDE_TURNS."""
    face_parts = []
    cells_by_id: dict[int, list[Part]] = {}
    for face, (tag_id, placement) in enumerate(zip(ids, _FACE_PLACEMENTS + [_BOTTOM_PLACEMENT])):
        if tag_id not in cells_by_id:
            cells_by_id[tag_id] = _face_cells(tag_id, size, depth)
        if rotate_sides and face < len(SIDE_TURNS):
            placement = placement * Rot(0, 0, SIDE_TURNS[face])  # turn within the face, about its normal
        for b in cells_by_id[tag_id]:
            face_parts.append(placement * b)
    if len(ids) == _TAG_FACES:
        if label is None:
            face_parts += [_BOTTOM_PLACEMENT * b for b in _edge_label_cells(ids, size, depth)]
        elif label.strip():
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


def _colour_bodies(arrows: list[Part], reds: list[Part], greens: list[Part]) -> list[Part]:
    """The 'red' and 'green' bodies: the floor arrows and the edge strips of each colour, fused
    (an arrow's tail overlaps the strip it starts at), so each colour is one body."""
    bodies = []
    for name, extra in (("red", reds), ("green", greens)):
        parts = [a for a in arrows if a.label == name] + extra
        if not parts:
            continue
        body = Part(parts[0].fuse(*parts[1:]).clean().wrapped) if len(parts) > 1 else Part(parts[0].wrapped)
        body.label, body.color = name, Color(name)
        bodies.append(body)
    return bodies


def build_apriltag_cube(
    tag_ids: int | list[int], size: float, depth: float = DEFAULT_DEPTH, axes: bool = False,
    label: str | None = None, bottom_tag: bool = False, rotate_sides: bool = False, edge_colours: bool = False,
) -> Compound:
    """Build a compound with two bodies (labels 'white' and 'black').

    tag_ids is either one id (same tag on all faces) or one id per tag face in FACE_NAMES order:
    five, or six with bottom_tag=True (a tag instead of the label on the bottom face).
    label is the bottom label: None for the default (see default_label), "" for none.
    With axes=True, two extra bodies 'red' (+X) and 'green' (+Y) are added on the floor beside the cube.
    rotate_sides=True turns the side tags so that they can be told apart (see the module docstring).
    edge_colours=True adds red (+X) and green (+Y) strips along those faces' bottom edges, in the
    same 'red' and 'green' bodies as the arrows.
    """
    ids = [tag_ids] if isinstance(tag_ids, int) else list(tag_ids)
    n_faces = face_count(bottom_tag)
    if len(ids) == 1:
        ids = ids * n_faces
    if len(ids) != n_faces:
        raise ValueError(f"Provide one tag ID or {n_faces} ({_faces_text(n_faces)}).")
    _check_dimensions(size, depth)
    if label is None and not bottom_tag:
        label = default_label(ids)

    white, black = _build_cube_bodies(ids, size, depth, label, rotate_sides)
    arrows = _axis_arrows(size) if axes else []
    strips = _edge_strips(size, depth) if edge_colours else ()
    white = _cut_arrows(white, arrows + list(strips))
    _label_bodies(white, black)
    colours = _colour_bodies(arrows, list(strips[:1]), list(strips[1:]))
    return Compound(children=[white, black] + colours, label="apriltag_cube")


def build_world_frame_cube(size: float, depth: float = DEFAULT_DEPTH, label: str | None = None,
                           edge_colours: bool = False) -> Compound:
    """The world-frame cube: WORLD_FRAME_ID on all five faces with the side tags turned, the
    label "World frame" (or `label`) and the red/green arrows on the floor."""
    return build_apriltag_cube(list(WORLD_FRAME_IDS), size, depth, True, label or WORLD_FRAME_LABEL,
                               rotate_sides=True, edge_colours=edge_colours)


def grid_dimension(count: int) -> int:
    """Side length n of the smallest square n x n grid that holds `count` cubes."""
    n = 1
    while n * n < count:
        n += 1
    return n


def build_apriltag_cube_grid(
    tag_ids: list[int], size: float, depth: float = DEFAULT_DEPTH, axes: bool = False, spacing: float = GRID_SPACING,
    labels: bool = True, bottom_tag: bool = False, rotate_sides: bool = False, edge_colours: bool = False,
) -> Compound:
    """One cube per tag id (same tag on all tag faces), in the smallest square grid.

    Cubes are `spacing` mm apart, filled row by row starting at the top-left (looking down
    +Z with +X right and +Y up), and the grid is centred on the origin. All white parts form
    one body 'white' and all black parts one body 'black', so a slicer can assign each filament
    once for every cube. With labels=True each cube's bottom face carries its tag id; with
    bottom_tag=True it carries the tag instead. rotate_sides turns the side tags as in
    build_apriltag_cube, and edge_colours gives every cube its red and green bottom edges. With a
    single id this is the same as build_apriltag_cube.
    """
    ids = list(tag_ids)
    if not ids:
        raise ValueError("Provide at least one tag ID.")
    if len(ids) > MAX_CUBES:
        raise ValueError(f"At most {MAX_CUBES} cubes can be generated at once.")
    if len(ids) == 1:
        return build_apriltag_cube(ids[0], size, depth, axes, None if labels else "", bottom_tag, rotate_sides,
                                   edge_colours)
    _check_dimensions(size, depth)

    n = grid_dimension(len(ids))
    pitch = size + spacing
    extent = n * size + (n - 1) * spacing
    arrows = _axis_arrows(size, extent) if axes else []
    whites, blacks, reds, greens = [], [], [], []
    strips = _edge_strips(size, depth) if edge_colours else ()
    bodies_by_id: dict[int, tuple[Part, Part]] = {}
    for index, tag_id in enumerate(ids):
        if tag_id not in bodies_by_id:
            bodies_by_id[tag_id] = _build_cube_bodies(
                [tag_id] * face_count(bottom_tag), size, depth, str(tag_id) if labels else "", rotate_sides
            )
        row, col = divmod(index, n)
        shift = Pos(-extent / 2 + size / 2 + col * pitch, extent / 2 - size / 2 - row * pitch, 0)
        white, black = bodies_by_id[tag_id]
        cube_strips = [Part((shift * strip).wrapped) for strip in strips]
        whites.append(_cut_arrows(Part((shift * white).wrapped), arrows + cube_strips))
        blacks.append(Part((shift * black).wrapped))
        reds += cube_strips[:1]
        greens += cube_strips[1:]

    white = Compound(children=whites)
    black = Compound(children=blacks)
    _label_bodies(white, black)
    colours = _colour_bodies(arrows, reds, greens)
    return Compound(children=[white, black] + colours, label="apriltag_cubes")


def export_apriltag_cube(cube: Compound, path: str) -> None:
    export_step(cube, path)


def main() -> None:
    ap = argparse.ArgumentParser(description="AprilTag tag16h5 two-colour cube (STEP)")
    ap.add_argument("--id", default="0", help="tag16h5 id 0-29, or 5 comma-separated ids: +X, +Y, -X, -Y (sides, "
                    "counterclockwise from above), then +Z (top); 6 with --bottom-tag (then -Z)")
    ap.add_argument("--bottom-tag", action="store_true", help="a tag on the bottom face too, instead of the label")
    ap.add_argument("--rotate-sides", action="store_true", help="same tag on all faces: turn the side tags 0, 90, 180 "
                    "and 270 degrees (+X, +Y, -X, -Y) so a camera can tell the sides apart")
    ap.add_argument("--world-frame", action="store_true", help=f"world-frame cube: id {WORLD_FRAME_ID} on all faces, side tags "
                    f"turned, label '{WORLD_FRAME_LABEL}' and axes; used instead of --id")
    ap.add_argument("--label", help="bottom label (default: the tag id, 'World frame', or five different ids along "
                    "the edges); '|' is a line break, empty for none")
    ap.add_argument("--size", type=float, default=40.0, help="cube edge length (mm)")
    ap.add_argument("--depth", type=float, default=DEFAULT_DEPTH, help="black layer depth (mm)")
    ap.add_argument("--cubes", help="comma-separated tag ids: one cube (same tag on all faces) per id, in a square grid "
                    f"{GRID_SPACING:g} mm apart; used instead of --id")
    ap.add_argument("--axes", action="store_true", help="add red (+X) and green (+Y) world-frame arrows on the floor beside the cube(s)")
    ap.add_argument("--edge-colours", action="store_true", help="red (+X) and green (+Y) strips along those faces' "
                    "bottom edges, inlaid within the cube")
    ap.add_argument("--out", default="apriltag_cube.step")
    a = ap.parse_args()
    if a.world_frame:
        cube = build_world_frame_cube(a.size, a.depth, a.label, a.edge_colours)
    elif a.cubes:
        cube = build_apriltag_cube_grid(parse_tag_ids(a.cubes, per_face=False), a.size, a.depth, a.axes,
                                        labels=a.label != "", bottom_tag=a.bottom_tag, rotate_sides=a.rotate_sides,
                                        edge_colours=a.edge_colours)
    else:
        ids = parse_tag_ids(a.id, bottom_tag=a.bottom_tag)
        cube = build_apriltag_cube(ids, a.size, a.depth, a.axes, a.label, a.bottom_tag,
                                   a.rotate_sides and len(set(ids)) == 1, a.edge_colours)
    export_apriltag_cube(cube, a.out)
    print(f"Wrote {a.out}")


if __name__ == "__main__":
    main()
