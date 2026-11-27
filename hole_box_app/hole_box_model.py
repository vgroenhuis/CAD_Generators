"""
    Geometry for a box with holes in its lid: a round, square, rectangular or hexagonal box in
    two parts, a base and a lid that closes it, with zero or more identical holes in the lid's
    top (for panel-mount parts: sockets, switches, buttons, LEDs, ...).

      * the box: `width` is the diameter (round), the side (square), the size along X
        (rectangle, `depth` along Y) or the size across flats (hexagon, flats parallel to X);
        `height` is the closed box's outside height; `wall` is the thickness of the walls, the
        floor and the lid's top. Square, rectangular and hexagonal boxes have their vertical
        edges rounded (`corner_radius`)
      * the holes: round (`hole_size` the diameter), square (the side) or hexagonal (across
        flats), arranged (`hole_layout`, always centred on the lid):
          - circle: `holes` of them, their centres on a circle of radius `hole_circle` (one
            hole with radius 0: in the middle), the first at +Y (the back), turned with their
            place on the circle so the pattern is symmetric
          - line: `holes` of them in a row along X, `hole_spacing` apart (centre to centre)
          - grid: `hole_rows` rows (along Y, `hole_row_spacing` apart) of `holes` each (along
            X, `hole_spacing` apart)
      * the closure:
          - snap: a ring (plug) under the lid fits inside the base's opening; a bead around it
            (45 degree flanks) clicks into a groove in the base's inner wall. A notch in the
            base's rim (at -Y) takes a fingernail or a screwdriver to lever the lid off
          - screws: the lid is screwed onto posts in the base's corners (M3 self-tapping
            screws, countersunk heads); 3 posts in a round or hexagonal box, 4 in a square or
            rectangular one
          - thread (round boxes only): the base has a threaded neck, the lid an internal
            thread in its skirt (a rounded profile that prints without supports)
        `joint_length` is the plug's depth (snap) or the thread's length; `clearance` is the
        gap on each side between the parts that slide or screw together
      * text on the bottom (optional): `text`, `text_size` high (the font size), engraved
        `text_depth` deep into the base's underside and filled by a second body in another
        colour, flush with the bottom: printed first, on the bed, in a contrasting filament on
        a multicolour printer. Mirrored, so it reads the right way round on the box's underside

    Both parts print without supports: the base upright, the lid upside down (its top on the
    bed); the files have them side by side in that orientation.

    Can also be run standalone:  python hole_box_model.py --shape square --closure screws --out box.step
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, replace

from build123d import (
    Align, Axis, Box, Circle, Color, Compound, Face, Kind, Part, Plane, Polygon, Pos, Rectangle, RegularPolygon,
    Rot, Solid, Spline, Vector, Wire, export_step, extrude, mirror, offset, revolve,
)

from cad_common.text import min_font_size, printable_text

SHAPES = ("round", "square", "rectangle", "hexagon")
HOLE_SHAPES = ("round", "square", "hexagon")
HOLE_LAYOUTS = ("circle", "line", "grid")
CLOSURES = ("snap", "screws", "thread")
BASE_COLOUR = Color(0.3, 0.55, 0.8)
LID_COLOUR = Color(0.88, 0.88, 0.85)
TEXT_COLOUR = Color(0.08, 0.08, 0.08)
TEXT_MARGIN = 2.0  # mm, least distance from the bottom text to the box's outside edge
MAX_TEXT = 40  # characters
SNAP_BEAD = 0.4  # mm the bead stands out from the plug (the groove is 0.1 mm deeper)
PLUG_WALL = 1.6  # mm, the snap plug's wall
NOTCH_WIDTH = 10.0  # mm, the lever notch in the base's rim (snap)
NOTCH_DEPTH = 1.5
THREAD_PITCH = 3.0  # mm
THREAD_DEPTH = 1.2  # mm, crest to root
NECK_GAP = 0.4  # mm between the neck's top and the lid's top (thread)
SCREW_PILOT = 2.5  # mm, hole for an M3 self-tapping screw
SCREW_CLEAR = 3.4  # mm, the screw's hole in the lid
SCREW_HEAD = 6.0  # mm, the countersunk head (90 degrees)
POST_DIAMETER = 7.0  # mm, the screw posts
SCREW_LENGTHS = (6, 8, 10, 12, 16, 20, 25, 30)
HOLE_MARGIN = 0.5  # mm, least distance from a hole to a wall, plug, post or screw head
# A typical 4 mm panel-mount banana socket for an 8 mm hole, for the page's assembled view only
# (not in the files): shown in round holes of SOCKET_HOLES mm.
SOCKET_HOLES = (7.5, 8.5)
SOCKET_DEPTH = 17.0  # mm it reaches below the lid's top (shank, nut, stud and solder lug)
SOCKET_COLOURS = (Color(0.8, 0.1, 0.1), Color(0.08, 0.08, 0.08))  # red, black, red, ...
BRASS_COLOUR = Color(0.82, 0.68, 0.32)
NICKEL_COLOUR = Color(0.75, 0.76, 0.78)


@dataclass
class BoxParams:
    shape: str = "round"
    width: float = 50.0  # diameter, side, size along X or across flats
    depth: float = 40.0  # rectangle: size along Y
    height: float = 40.0  # the closed box, outside
    wall: float = 2.0
    corner_radius: float = 3.0  # vertical edges (not round boxes)
    closure: str = "thread"
    joint_length: float = 8.0  # the snap plug's depth or the thread's length
    clearance: float = 0.25  # on each side, between the parts that slide or screw together
    holes: int = 3
    hole_shape: str = "round"
    hole_size: float = 8.0  # diameter, side or across flats
    hole_circle: float = 12.0  # radius of the circle the holes' centres are on
    hole_layout: str = "circle"  # or "line" (along X), "grid"
    hole_spacing: float = 12.0  # line and grid: centre to centre along X
    hole_rows: int = 2  # grid: rows of `holes` each
    hole_row_spacing: float = 12.0  # grid: centre to centre along Y
    text: str = ""  # on the bottom, in a second colour; empty: none
    text_size: float = 8.0  # mm, the font size
    text_depth: float = 0.6  # mm, into the bottom


# Named settings the page offers (each a complete set).
PRESETS = {
    "Round box with three panel-mount banana sockets": BoxParams(),
    "Rectangular box 60 x 30 mm with three holes in a line": BoxParams(
        shape="rectangle", width=60.0, depth=30.0, height=20.0, closure="snap",
        hole_layout="line", holes=3, hole_size=8.0, hole_spacing=16.0),
}


# ---- shape ----------------------------------------------------------------------------------

def outer_size(p: BoxParams) -> tuple[float, float]:
    """The box's outside extent along X and Y."""
    if p.shape == "round":
        return p.width, p.width
    if p.shape == "square":
        return p.width, p.width
    if p.shape == "rectangle":
        return p.width, p.depth
    return 2 * p.width / math.sqrt(3), p.width  # hexagon: corners on X


def outline(p: BoxParams, grow: float = 0.0):
    """The box's outline (a 2D face), grown outward by `grow` (negative: shrunk)."""
    if p.shape == "round":
        return Circle(p.width / 2 + grow)
    cr = p.corner_radius
    r = cr + grow
    if p.shape == "hexagon":
        def poly(across):
            return RegularPolygon(across / math.sqrt(3), 6)  # corners on X: flats parallel to X
        size = (p.width,)
    elif p.shape == "square":
        def poly(across):
            return Rectangle(across, across)
        size = (p.width,)
    else:
        def poly(x, y):
            return Rectangle(x, y)
        size = (p.width, p.depth)
    if r > 0.01:  # a sharp core grown with round corners
        return offset(poly(*[s - 2 * cr for s in size]), r, kind=Kind.ARC)
    return poly(*[s + 2 * grow for s in size])


def _prism(face, z0: float, z1: float) -> Part:
    return Part((Pos(0, 0, z0) * extrude(face, amount=z1 - z0)).wrapped)


def _diamond(p: BoxParams, grow: float, bead: float, zc: float) -> Part:
    """A ring-shaped ridge with 45 degree flanks around outline(grow), `bead` high (outward)
    at zc and nothing at zc +- bead (its inside is filled: subtract it where needed)."""
    lower = Pos(0, 0, zc - bead) * extrude(outline(p, grow), amount=bead, taper=-45)
    upper = Pos(0, 0, zc) * extrude(outline(p, grow + bead), amount=bead, taper=45)
    return Part((lower + upper).wrapped)


# ---- thread ---------------------------------------------------------------------------------

def _cam_face(radius, n: int) -> Face:
    pts = [Vector(radius(2 * math.pi * i / n) * math.cos(2 * math.pi * i / n),
                  radius(2 * math.pi * i / n) * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return Face(Wire(Spline(*pts, periodic=True)))


def thread(inner: float, outer: float, z0: float, z1: float) -> Part:
    """A right-hand threaded rod between z0 and z1, a rounded profile between the radii (its
    flanks are at most about 50 degrees from the axis, so it prints upright), cut off flat at
    both ends (the twisted extrusion's own end faces tessellate badly)."""
    depth = outer - inner
    face = _cam_face(lambda t: inner + depth * 0.5 * (1 - math.cos(t)), 120)
    a, b = z0 - 1.0, z1 + 1.0
    # The section at angle t sits at height t / 2pi * pitch: turning it as it rises makes the
    # helix. Its phase is tied to z = 0 (not to the rod's start), so threads made for the base
    # and the lid in their places mesh.
    face = Rot(0, 0, 360 * a / THREAD_PITCH) * face
    solid = Pos(0, 0, a) * Solid.extrude_linear_with_rotation(face, Vector(0, 0, 0), Vector(0, 0, b - a),
                                                              360 * (b - a) / THREAD_PITCH)
    big = 4 * outer
    solid = solid - Pos(0, 0, z1) * Box(big, big, 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    solid = solid - Pos(0, 0, z0) * Box(big, big, 2, align=(Align.CENTER, Align.CENTER, Align.MAX))
    return Part(solid.wrapped)


def thread_radii(p: BoxParams) -> tuple[float, float, float]:
    """The lid's internal thread (crest and root radius) and the neck's bore radius."""
    crest = p.width / 2 - p.wall - THREAD_DEPTH
    bore = crest - p.clearance - p.wall
    return crest, crest + THREAD_DEPTH, bore


# ---- layout ---------------------------------------------------------------------------------

def base_height(p: BoxParams) -> float:
    """The base's rim (snap, screws) or shoulder (thread): where the lid sits on it."""
    if p.closure == "thread":
        return p.height - p.wall - p.joint_length
    return p.height - p.wall


def screw_positions(p: BoxParams) -> list[tuple[float, float]]:
    """The screw posts' centres: in the corners, touching the walls (merged 0.5 mm)."""
    pr = POST_DIAMETER / 2
    if p.shape == "round":
        rc = p.width / 2 - p.wall - pr + 0.5
        return [(rc * math.cos(math.radians(a)), rc * math.sin(math.radians(a))) for a in (30, 150, 270)]
    if p.shape == "hexagon":
        # Alternate corners (0, 120 and 240 degrees); in a 120 degree corner a circle touches
        # both walls at pr / sin(60) from the corner. (The inner corners' rounding, radius
        # corner_radius - wall, is smaller than the posts: it doesn't change this.)
        inner_corner = (p.width / 2 - p.wall) / math.cos(math.radians(30))
        rc = inner_corner - pr / math.sin(math.radians(60)) + 0.5
        return [(rc * math.cos(math.radians(a)), rc * math.sin(math.radians(a))) for a in (0, 120, 240)]
    x, y = outer_size(p)
    cx = x / 2 - p.wall - pr + 0.5
    cy = y / 2 - p.wall - pr + 0.5
    return [(sx * cx, sy * cy) for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]


def hole_count(p: BoxParams) -> int:
    return p.holes * p.hole_rows if p.hole_layout == "grid" else p.holes


def hole_positions(p: BoxParams) -> list[tuple[float, float, float]]:
    """(x, y, angle) of each hole: on the circle from +Y, counter-clockwise; in a line or a grid
    left to right (and from the back), not turned (angle 90)."""
    if p.hole_layout != "circle":
        rows = p.hole_rows if p.hole_layout == "grid" else 1
        return [((i - (p.holes - 1) / 2) * p.hole_spacing, ((rows - 1) / 2 - j) * p.hole_row_spacing, 90.0)
                for j in range(rows) for i in range(p.holes)]
    out = []
    for i in range(p.holes):
        a = 90 + 360 * i / p.holes
        out.append((p.hole_circle * math.cos(math.radians(a)), p.hole_circle * math.sin(math.radians(a)), a))
    return out


def hole_face(p: BoxParams, x: float, y: float, angle: float):
    if p.hole_shape == "round":
        face = Circle(p.hole_size / 2)
    elif p.hole_shape == "square":
        face = Rectangle(p.hole_size, p.hole_size)
    else:
        face = RegularPolygon(p.hole_size / math.sqrt(3), 6)  # a corner on X: flats parallel to X
    return Pos(x, y) * Rot(0, 0, angle - 90) * face


def allowed_area(p: BoxParams):
    """Where the holes may go in the lid's top: clear of the walls, the snap plug, the thread
    and the screw posts' heads."""
    if p.closure == "thread":
        return Circle(thread_radii(p)[0] - HOLE_MARGIN)
    if p.closure == "snap":
        return outline(p, -p.wall - p.clearance - PLUG_WALL - HOLE_MARGIN)
    area = outline(p, -p.wall - HOLE_MARGIN)
    for x, y in screw_positions(p):
        area = area - Pos(x, y) * Circle(max(SCREW_HEAD, POST_DIAMETER) / 2 + HOLE_MARGIN)
    return area


def screw_length(p: BoxParams) -> int:
    """The longest standard screw that fits: through the lid, into the post (not the floor)."""
    reach = p.wall + (base_height(p) - p.wall - 1.0)
    fits = [n for n in SCREW_LENGTHS if n <= reach]
    return fits[-1] if fits else 0


# ---- checks ---------------------------------------------------------------------------------

def bottom_text(p: BoxParams):
    """The bottom text's 2D outline, centred and mirrored (it reads right seen from below), or None."""
    if not p.text.strip():
        return None
    return mirror(printable_text(p.text.strip(), p.text_size, align=(Align.CENTER, Align.CENTER)), Plane.YZ)


def validate(p: BoxParams) -> None:
    if p.shape not in SHAPES:
        raise ValueError(f"The shape must be one of {', '.join(SHAPES)}.")
    if p.hole_shape not in HOLE_SHAPES:
        raise ValueError(f"The holes' shape must be one of {', '.join(HOLE_SHAPES)}.")
    if p.closure not in CLOSURES:
        raise ValueError(f"The closure must be one of {', '.join(CLOSURES)}.")
    if p.closure == "thread" and p.shape != "round":
        raise ValueError("A screw thread only fits a round box: choose snap-in or screws.")
    if not 15 <= p.width <= 300:
        raise ValueError("The box's width (diameter, side or across flats) must be between 15 and 300 mm.")
    if p.shape == "rectangle" and not 15 <= p.depth <= 300:
        raise ValueError("The box's depth must be between 15 and 300 mm.")
    if not 10 <= p.height <= 300:
        raise ValueError("The box's height must be between 10 and 300 mm.")
    if not 1.2 <= p.wall <= 10:
        raise ValueError("The wall thickness must be between 1.2 and 10 mm.")
    if p.shape != "round":
        least = min(outer_size(p)) if p.shape != "hexagon" else p.width
        if not 0 <= p.corner_radius <= least / 2 - 1:
            raise ValueError(f"The corner radius must be between 0 and {least / 2 - 1:g} mm.")
    if not 0 <= p.clearance <= 1:
        raise ValueError("The clearance must be between 0 and 1 mm.")
    if p.closure != "screws" and not 3 <= p.joint_length <= 50:
        raise ValueError(f"The {'thread' if p.closure == 'thread' else 'plug'} length must be between 3 and 50 mm.")
    if p.hole_layout not in HOLE_LAYOUTS:
        raise ValueError(f"The holes' arrangement must be one of {', '.join(HOLE_LAYOUTS)}.")
    if not 0 <= p.holes <= 36:
        raise ValueError(f"The number of holes{' per row' if p.hole_layout == 'grid' else ''} must be between 0 and 36.")
    if p.holes:
        if not 1 <= p.hole_size <= 200:
            raise ValueError("The hole size must be between 1 and 200 mm.")
        if p.hole_layout == "circle":
            if not 0 <= p.hole_circle <= 150:
                raise ValueError("The holes' circle radius must be between 0 and 150 mm.")
            if p.holes > 1 and p.hole_circle == 0:
                raise ValueError("Several holes need a circle radius above 0 (they would all be in the middle).")
        else:
            if not 0 <= p.hole_spacing <= 300:
                raise ValueError("The holes' spacing must be between 0 and 300 mm.")
            if p.holes > 1 and p.hole_spacing == 0:
                raise ValueError("Several holes in a row need a spacing above 0 (they would all be in one place).")
        if p.hole_layout == "grid":
            if not 1 <= p.hole_rows <= 36:
                raise ValueError("The number of rows must be between 1 and 36.")
            if hole_count(p) > 144:
                raise ValueError("A grid can have at most 144 holes.")
            if not 0 <= p.hole_row_spacing <= 300:
                raise ValueError("The row spacing must be between 0 and 300 mm.")
            if p.hole_rows > 1 and p.hole_row_spacing == 0:
                raise ValueError("Several rows need a row spacing above 0 (they would all be in one place).")
    inner = min(outer_size(p)) - 2 * p.wall if p.shape != "hexagon" else p.width - 2 * p.wall
    hb = base_height(p)
    if p.closure == "snap":
        if p.joint_length < 2 * (SNAP_BEAD + 0.1) + 2:
            raise ValueError(f"The plug must be at least {2 * (SNAP_BEAD + 0.1) + 2:g} mm deep.")
        if inner - 2 * (p.clearance + PLUG_WALL) < 4:
            raise ValueError("The box is too small inside for the snap-in lid's plug: make it wider or the wall thinner.")
        if hb - p.joint_length < p.wall + 1:
            raise ValueError(f"The box is too low for a {p.joint_length:g} mm plug: make it at least "
                             f"{math.ceil(2 * p.wall + p.joint_length + 1)} mm high, or the plug shorter.")
    elif p.closure == "screws":
        if inner < 2 * POST_DIAMETER + 2:
            raise ValueError(f"The box is too small inside for the screw posts: make it at least "
                             f"{math.ceil(2 * POST_DIAMETER + 2 + 2 * p.wall)} mm wide.")
        if hb - p.wall < 6:
            raise ValueError(f"The box is too low for the screw posts: make it at least {math.ceil(3 * p.wall + 6)} mm high.")
    else:
        crest, root, bore = thread_radii(p)
        if bore < 3:
            raise ValueError("The box is too narrow for the thread: make it wider or the wall thinner.")
        chamfer = p.width / 2 - p.wall - bore
        if hb - chamfer < p.wall + 1:
            raise ValueError(f"The box is too low for a {p.joint_length:g} mm thread: make it at least "
                             f"{math.ceil(p.height - (hb - chamfer) + p.wall + 1)} mm high, or the thread shorter.")
    if p.holes:
        faces = [hole_face(p, x, y, a) for x, y, a in hole_positions(p)]
        union = faces[0]
        for f in faces[1:]:
            union = union + f
        if len(faces) > 1 and union.area < sum(f.area for f in faces) - 1e-3:
            what = "the circle larger" if p.hole_layout == "circle" else "the spacing larger"
            raise ValueError(f"The holes overlap: make {what}, the holes smaller or fewer.")
        if (union - allowed_area(p)).area > 1e-3:
            where = {"thread": "the lid's thread", "snap": "the lid's plug",
                     "screws": "the walls or the screws"}[p.closure]
            what = {"circle": "the circle smaller", "line": "the spacing smaller", "grid": "the spacings smaller"}[p.hole_layout]
            raise ValueError(f"The holes reach {where}: make {what}, the holes smaller or fewer, or the box larger.")
    if p.text.strip():
        if len(p.text) > MAX_TEXT:
            raise ValueError(f"The bottom text can be at most {MAX_TEXT} characters.")
        least = math.ceil(min_font_size() * 10) / 10
        if not least <= p.text_size <= 100:
            raise ValueError(f"The text size must be between {least:g} mm (thinner strokes don't print) and 100 mm.")
        if not 0.2 <= p.text_depth <= p.wall - 0.6:
            raise ValueError(f"The text depth must be between 0.2 mm and {p.wall - 0.6:g} mm "
                             "(the wall thickness less 0.6 mm).")
        text = bottom_text(p)
        if text is None or not text.faces():
            raise ValueError("The bottom text has no characters the font can draw.")
        size = text.bounding_box().size
        if (Rectangle(size.X, size.Y) - outline(p, -TEXT_MARGIN)).area > 1e-3:
            raise ValueError(f"The bottom text is too large for the box: it must stay {TEXT_MARGIN:g} mm from the edge. "
                             "Make the text smaller or shorter.")


# ---- parts ----------------------------------------------------------------------------------

def build_base(p: BoxParams) -> Part:
    """The base, upright, in its place in the closed box."""
    hb = base_height(p)
    w = p.wall
    base = _prism(outline(p), 0, hb)
    if p.closure == "thread":
        crest, root, bore = thread_radii(p)
        c = p.clearance
        top = hb + p.joint_length - NECK_GAP
        base = base + thread(crest - c, root - c, hb - 0.01, top)
        # Inside: the full width below a 45 degree shoulder up to the neck's bore (no overhangs).
        r = p.width / 2 - w
        chamfer = r - bore
        cavity = revolve(Plane.XZ * Polygon((0, w), (r, w), (r, hb - chamfer), (bore, hb), (bore, top + 1),
                                            (0, top + 1), align=None), Axis.Z)
        base = base - cavity
    elif p.closure == "snap":
        base = base - _prism(outline(p, -w), w, hb + 1)
        zc = hb - p.joint_length / 2
        base = base - _diamond(p, -w, SNAP_BEAD + 0.1, zc)
        y = outer_size(p)[1] / 2
        base = base - Pos(0, -y, hb) * Box(NOTCH_WIDTH, 2 * w + 2, 2 * NOTCH_DEPTH)
    else:
        base = base - _prism(outline(p, -w), w, hb + 1)
        posts = [_prism(Pos(x, y) * Circle(POST_DIAMETER / 2), w - 0.01, hb) for x, y in screw_positions(p)]
        base = base + posts
        base = base - [_prism(Pos(x, y) * Circle(SCREW_PILOT / 2), w + 1, hb + 1) for x, y in screw_positions(p)]
    text = bottom_text(p)
    if text is not None:
        base = base - _prism(text, -1, p.text_depth)
    return Part(base.wrapped)


def build_lid(p: BoxParams) -> Part:
    """The lid, in its place on the closed box (top up)."""
    hb = base_height(p)
    w = p.wall
    top = p.height
    if p.closure == "thread":
        crest, root, _ = thread_radii(p)
        lid = _prism(outline(p), hb, top) - thread(crest, root, hb - 1.0, top - w)
        plate_bottom = top - w
    else:
        lid = _prism(outline(p), hb, top)
        plate_bottom = hb
        if p.closure == "snap":
            g = -w - p.clearance
            ring = _prism(outline(p, g), hb - p.joint_length, hb + 0.01) + _diamond(p, g, SNAP_BEAD, hb - p.joint_length / 2)
            ring = ring - _prism(outline(p, g - PLUG_WALL), hb - p.joint_length - 1, hb)
            lid = lid + ring
        else:
            for x, y in screw_positions(p):
                lid = lid - _prism(Pos(x, y) * Circle(SCREW_CLEAR / 2), hb - 1, top + 1)
                sink = (SCREW_HEAD - SCREW_CLEAR) / 2
                lid = lid - Pos(x, y, top - sink) * extrude(Circle(SCREW_CLEAR / 2), amount=sink + 0.01, taper=-45)
    if p.holes:
        lid = lid - [_prism(hole_face(p, x, y, a), plate_bottom - 0.01, top + 1) for x, y, a in hole_positions(p)]
    return Part(lid.wrapped)


def build_hole_box(p: BoxParams) -> Compound:
    """Base and lid side by side in print orientation: the base upright, the lid upside down
    (its top on the bed)."""
    validate(p)
    base = build_base(p)
    lid = build_lid(p)
    x = outer_size(p)[0]
    lid = Part((Pos(x + 10, 0, p.height) * Rot(180, 0, 0) * lid).wrapped)
    base.label, base.color = "base", BASE_COLOUR
    lid.label, lid.color = "lid", LID_COLOUR
    children = [base, lid]
    text = bottom_text(p)
    if text is not None:
        filling = _prism(text, 0, p.text_depth)
        filling = Part(Compound([s for s in filling.solids()]).wrapped)
        filling.label, filling.color = "bottom text", TEXT_COLOUR
        children.append(filling)
    return Compound(children=children, label="hole_box")


def shows_sockets(p: BoxParams) -> bool:
    """Whether the holes take the banana sockets of the page's assembled view."""
    return bool(p.holes) and p.hole_shape == "round" and SOCKET_HOLES[0] <= p.hole_size <= SOCKET_HOLES[1]


def socket_room(p: BoxParams) -> float:
    """Room (mm) left between the sockets' lowest point and the base's floor (negative: they hit it)."""
    return p.height - p.wall - SOCKET_DEPTH


def _revolved(points) -> Part:
    """A solid of revolution about Z from (radius, z) points."""
    return Part(revolve(Plane.XZ * Polygon(*points, align=None), Axis.Z).wrapped)


def banana_socket() -> tuple[Part, Part, Part]:
    """One socket, its collar's base on the panel at z = 0, the panel below it (the nut's top at
    -wall is placed by the caller: here the nut is returned separately at z 0..-3).
    Returns (plastic: collar and threaded shank, brass: contact sleeve, stud, lug and its nut,
    nickel: the panel nut)."""
    plastic = _revolved([(0, -11), (3.8, -11), (3.8, 0), (6, 0), (6, 8.2), (5.2, 9), (3, 9), (3, 1), (0, 1)])
    sleeve = _revolved([(2, 0.5), (3, 0.5), (3, 8.7), (2, 8.7)])
    stud = Pos(0, 0, -17) * Solid.make_cylinder(2, 6.02)
    lug = Pos(0, 0, -12.5) * Solid.make_cylinder(4, 0.5) + Pos(4.5, 0, -12.5) * Box(7, 5, 0.5, align=(Align.CENTER, Align.CENTER, Align.MIN))
    lug = lug - Pos(5.5, 0, -13) * Solid.make_cylinder(1, 2)
    small_nut = Pos(0, 0, -15.7) * extrude(RegularPolygon(7 / math.sqrt(3), 6), amount=3.2)
    brass = Part((sleeve + stud + lug + small_nut).wrapped)
    nut = Pos(0, 0, -3) * extrude(RegularPolygon(11 / math.sqrt(3), 6) - Circle(3.8), amount=3)
    return plastic, brass, Part(nut.wrapped)


def build_sockets(p: BoxParams) -> Compound:
    """Banana sockets in the lid's holes, the box closed, for the page's assembled view (not in
    the files); red and black by turns, the solder lugs pointing along the circle (or to the
    back, in a line or grid), away from the walls. Empty when the holes don't take them."""
    if not shows_sockets(p):
        return Compound(children=[], label="sockets")
    plastic, brass, nut = banana_socket()
    lift = 0.02  # mm off the faces they rest on, so they don't z-fight on the page
    groups = {"red": [], "black": [], "brass": [], "nickel": []}
    for i, (x, y, a) in enumerate(hole_positions(p)):
        a = a + 90 if p.hole_layout == "circle" else a
        top = Pos(x, y, p.height + lift) * Rot(0, 0, a)
        groups["red" if i % 2 == 0 else "black"].append(top * plastic)
        groups["brass"].append(top * brass)
        groups["nickel"].append(Pos(x, y, p.height - p.wall - 2 * lift) * Rot(0, 0, a) * nut)
    colours = {"red": SOCKET_COLOURS[0], "black": SOCKET_COLOURS[1], "brass": BRASS_COLOUR, "nickel": NICKEL_COLOUR}
    children = []
    for name, parts in groups.items():
        if parts:
            part = Part(Compound([s for q in parts for s in q.solids()]).wrapped)
            part.label, part.color = f"sockets {name}", colours[name]
            children.append(part)
    return Compound(children=children, label="sockets")


def describe(p: BoxParams) -> str:
    shape = {"round": f"Round box Ø{p.width:g}", "square": f"Square box {p.width:g} x {p.width:g}",
             "rectangle": f"Rectangular box {p.width:g} x {p.depth:g}",
             "hexagon": f"Hexagonal box {p.width:g} across flats"}[p.shape]
    text = f"{shape} x {p.height:g} mm (closed), walls {p.wall:g} mm."
    hb = base_height(p)
    if p.closure == "thread":
        crest, root, bore = thread_radii(p)
        text += (f" Screw-on lid: a {p.joint_length:g} mm thread (pitch {THREAD_PITCH:g} mm); the neck's opening is "
                 f"Ø{2 * bore:.1f} mm.")
        inside = p.height - 2 * p.wall
    elif p.closure == "snap":
        text += (f" Snap-in lid: a {p.joint_length:g} mm deep plug with a bead that clicks into a groove; "
                 f"lever it off at the notch in the rim.")
        inside = p.height - 2 * p.wall
    else:
        n = len(screw_positions(p))
        length = screw_length(p)
        text += (f" Lid screwed on with {n} M3 countersunk self-tapping screws"
                 f"{f', up to {length} mm long' if length else ''}.")
        inside = p.height - 2 * p.wall
    text += f" Inside height {inside:g} mm."
    if p.text.strip():
        text_ = f" \"{p.text.strip()}\" on the bottom, {p.text_size:g} mm high and {p.text_depth:g} mm deep, in a second colour."
        text += text_
    if p.holes:
        what = {"round": f"Ø{p.hole_size:g} mm", "square": f"{p.hole_size:g} mm square",
                "hexagon": f"{p.hole_size:g} mm hexagonal (across flats)"}[p.hole_shape]
        n = hole_count(p)
        if p.hole_layout == "grid" and n > 1:
            where = (f" in a grid, {p.hole_rows} row{'s' if p.hole_rows > 1 else ''} of {p.holes}, {p.hole_spacing:g} mm apart"
                     + (f" and the rows {p.hole_row_spacing:g} mm apart" if p.hole_rows > 1 else ""))
        elif p.hole_layout != "circle" and n > 1:
            where = f" in a line, {p.hole_spacing:g} mm apart"
        elif n == 1 and (p.hole_layout != "circle" or p.hole_circle == 0):
            where = " in the middle"
        else:
            where = f" on a circle of radius {p.hole_circle:g} mm"
        text += f" {n} {what} hole{'s' if n > 1 else ''} in the lid{where}."
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description="Box with holes in its lid (STEP)")
    d = BoxParams()
    ap.add_argument("--shape", choices=SHAPES, default=d.shape)
    ap.add_argument("--closure", choices=CLOSURES, default=d.closure)
    ap.add_argument("--hole-shape", choices=HOLE_SHAPES, default=d.hole_shape)
    ap.add_argument("--hole-layout", choices=HOLE_LAYOUTS, default=d.hole_layout)
    ap.add_argument("--hole-rows", type=int, default=d.hole_rows)
    for name in ("width", "depth", "height", "wall", "corner_radius", "joint_length", "clearance", "hole_size", "hole_circle",
                 "hole_spacing", "hole_row_spacing"):
        ap.add_argument(f"--{name.replace('_', '-')}", type=float, default=getattr(d, name))
    ap.add_argument("--holes", type=int, default=d.holes)
    ap.add_argument("--text", default=d.text)
    for name in ("text_size", "text_depth"):
        ap.add_argument(f"--{name.replace('_', '-')}", type=float, default=getattr(d, name))
    ap.add_argument("--out", default="hole_box.step")
    args = vars(ap.parse_args())
    out = args.pop("out")
    p = replace(d, **args)
    export_step(build_hole_box(p), out)
    print(describe(p))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
