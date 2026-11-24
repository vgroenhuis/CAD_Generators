"""
    Screwdriver handle for 1/4" (6.35 mm) hex bits, with a magnet behind the bit, storage for
    spare bits and a screw cap.

    The handle stands on its bottom end (z = 0) and is printed that way:
      * at the top a hex socket for the bit (`socket_size` across flats, `socket_depth` deep),
        with a small lead-in chamfer
      * `magnet_gap` mm below the socket's floor a closed pocket for a round magnet
        (`magnet_diameter` x `magnet_height`, plus clearance). The magnet goes in while the
        print is paused just before the pocket's roof: describe() gives that height.
      * from the bottom up, `holes` hexagonal storage holes (`hole_size` across flats,
        `hole_length` long, up to 3 in a honeycomb around the axis), each for a stack of
        spare bits, with a pointed (45 degree) roof, ending `storage_gap` mm below the magnet so
        that it doesn't hold the topmost spare bits
      * at the bottom a threaded opening with a shallow conical (20 degree) ceiling, closed by a
        separate screw cap (a plug with a flange) that the bits rest on. No chamfers at the
        bottom of the handle or the cap: their whole bottom faces hold on to the print bed.
      * everything prints without supports (overhangs at most 45 degrees, except the magnet
        pocket's short flat roof and the opening's shallow ceiling, a short span)
      * a diamond knurl on the grip between smooth collars at both ends, and on the cap's flange

    The handle is `min_length` long, or longer when the parts stacked along the axis need it:
    thread, storage holes, the storage gap, the magnet pocket, the gap and the socket. Extra length is
    solid, below the magnet.

    The threads have a rounded (sinusoidal) profile; they are made by extruding their cross-
    section while turning it (one turn per pitch), which is exact and fast. The knurl is built
    as a polyhedron (flat triangles), so the booleans on the handle stay fast.

    Can also be run standalone:  python screwdriver_handle_model.py --out handle.step
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, replace

from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing,
)
from OCP.gp import gp_Pnt
from OCP.ShapeFix import ShapeFix_Solid
from OCP.TopoDS import TopoDS
from build123d import (
    Align, Box, Axis, Plane, Polygon, revolve, Circle, Color, Compound, Face, Part, Pos, RegularPolygon, Rot, Shell, Solid, Spline, Vector, Wire,
    export_step, extrude,
)

COLOUR = Color(0.85, 0.35, 0.2)
CAP_COLOUR = Color(0.3, 0.3, 0.32)
HOLE_WEB = 1.0  # mm between neighbouring storage holes
MIN_WALL = 1.2  # mm, least wall anywhere around a cavity
MAGNET_CLEARANCE = 0.1  # mm on the magnet's radius
MAGNET_HEADROOM = 0.2  # mm above the magnet in its pocket
THREAD_DEPTH = 0.8  # mm, crest to root
THREAD_PITCH = 2.0  # mm
THREAD_GAP = 0.4  # mm between the cap's plug and the opening's top
SOCKET_CHAMFER = 0.6  # mm, lead-in at the socket's mouth
ENTRY_ANGLE = 20.0  # degrees between the opening's conical ceiling and the horizontal
COLLAR_BOTTOM = 3.0  # mm of smooth grip above the thread
COLLAR_TOP = 5.0  # mm of smooth grip below the top
TOP_ROUND = 3.0  # radius of the rounded top edge
TIP_ROUND = 1.2  # radius of the rounded top edge of a tapered handle
TAPER_COLLAR = 2.0  # mm of smooth grip between the knurl and the taper
CAP_FLANGE = 3.0  # mm, the cap's flange height
CAP_OVERSIZE = 1.0  # mm, the cap's flange is this much larger in radius than the handle (easy to grab)
KNURL_ANGLE = 30.0  # degrees between the knurl's lines and the axis
SEGMENTS = 72  # around the smooth parts of the handle (an even number)


@dataclass
class HandleParams:
    diameter: float = 22.0
    min_length: float = 100.0  # longer when what is stacked inside needs it
    taper_length: float = 20.0  # the top narrows over this length (0: no taper), for tight spaces
    tip_diameter: float = 12.0  # where the cone would meet the top face (its edge is rounded)
    knurl: bool = True
    knurl_depth: float = 0.7
    knurl_count: int = 24  # diamonds around
    socket_size: float = 6.5  # across flats, for 6.35 mm (1/4") bits
    socket_depth: float = 8.0
    magnet_diameter: float = 8.0
    magnet_height: float = 3.0
    magnet_gap: float = 1.0  # material between the socket's floor and the magnet
    holes: int = 3
    hole_size: float = 6.7  # across flats
    hole_length: float = 76.0  # three 25 mm bits
    storage_gap: float = 6.0  # material between the storage holes and the magnet: keeps its pull off the spare bits
    thread_length: float = 6.0  # the cap's plug, into the handle
    thread_clearance: float = 0.3  # on the radius


# Named settings the page offers (each a complete set; the defaults are the page's start).
PRESETS = {
    "Screwdriver handle with embedded 8x3 mm magnet and space for nine bits":
        replace(HandleParams(), socket_size=6.6, hole_size=6.8),
}


def hole_centre_radius(p: HandleParams) -> float:
    """Distance of the storage holes' centres from the axis (0 for a single hole)."""
    if p.holes <= 1:
        return 0.0
    return (p.hole_size + HOLE_WEB) / math.sqrt(3) if p.holes == 3 else (p.hole_size + HOLE_WEB) / 2


def holes_radius(p: HandleParams) -> float:
    """Radius of the circle around all storage holes."""
    if p.holes == 0:
        return 0.0
    return hole_centre_radius(p) + p.hole_size / math.sqrt(3)


def thread_radii(p: HandleParams) -> tuple[float, float]:
    """The opening's thread: inner (crest) and outer (root) radius."""
    inner = max(holes_radius(p) + 0.3, p.magnet_diameter / 2, 5.0)
    return inner, inner + THREAD_DEPTH


@dataclass
class Layout:
    """Heights along the axis (mm, from the bottom)."""
    holes_bottom: float
    holes_top: float
    pocket_bottom: float
    pocket_top: float
    socket_bottom: float
    length: float
    knurl_bottom: float
    knurl_top: float


def layout(p: HandleParams) -> Layout:
    holes_bottom = p.thread_length
    holes_top = holes_bottom + (p.hole_length if p.holes else 0.0)
    pocket_bottom = holes_top + (p.storage_gap if p.holes else 0.0)
    above = p.magnet_height + MAGNET_HEADROOM + p.magnet_gap + p.socket_depth if p.magnet_height > 0 else p.socket_depth
    pocket_bottom += max(0.0, p.min_length - (pocket_bottom + above))  # solid below the magnet up to min_length
    pocket_top = pocket_bottom + p.magnet_height + MAGNET_HEADROOM
    socket_bottom = pocket_top + p.magnet_gap if p.magnet_height > 0 else pocket_bottom
    length = socket_bottom + p.socket_depth
    return Layout(holes_bottom, holes_top, pocket_bottom, pocket_top, socket_bottom, length,
                  p.thread_length + COLLAR_BOTTOM,
                  length - (p.taper_length + TAPER_COLLAR if p.taper_length > 0 else COLLAR_TOP))


def radius_at(p: HandleParams, z: float, length: float) -> float:
    """The handle's outer radius at height z (without the knurl and the rounded top edge)."""
    r = p.diameter / 2
    if p.taper_length <= 0 or z <= length - p.taper_length:
        return r
    rt = p.tip_diameter / 2
    return r + (rt - r) * min(1.0, (z - (length - p.taper_length)) / p.taper_length)


def validate(p: HandleParams) -> None:
    if not 12 <= p.diameter <= 60:
        raise ValueError("The diameter must be between 12 and 60 mm.")
    if not 20 <= p.min_length <= 400:
        raise ValueError("The length must be between 20 and 400 mm.")
    if not 0 <= p.knurl_depth <= 2:
        raise ValueError("The knurl depth must be between 0 and 2 mm.")
    if not 8 <= p.knurl_count <= 80:
        raise ValueError("The number of diamonds around must be between 8 and 80.")
    if not 2 <= p.socket_size <= 20 or not 2 <= p.socket_depth <= 40:
        raise ValueError("The socket must be 2 to 20 mm across flats and 2 to 40 mm deep.")
    if not 0 <= p.magnet_diameter <= 30 or not 0 <= p.magnet_height <= 20:
        raise ValueError("The magnet must be at most 30 mm in diameter and 20 mm high (0: none).")
    if not 0.4 <= p.magnet_gap <= 10:
        raise ValueError("The gap between the socket and the magnet must be between 0.4 and 10 mm.")
    if p.holes not in (0, 1, 2, 3):
        raise ValueError("The number of storage holes must be 0, 1, 2 or 3.")
    if not 2 <= p.hole_size <= 20 or not 5 <= p.hole_length <= 300:
        raise ValueError("The storage holes must be 2 to 20 mm across flats and 5 to 300 mm long.")
    if not p.hole_size / 2 + 1 <= p.storage_gap <= 50:
        raise ValueError(f"The distance between the storage holes and the magnet must be between "
                         f"{p.hole_size / 2 + 1:g} mm (the holes' pointed roofs and 1 mm) and 50 mm.")
    if not 3 <= p.thread_length <= 20:
        raise ValueError("The cap's thread must be 3 to 20 mm long.")
    if not 0 <= p.thread_clearance <= 1:
        raise ValueError("The thread clearance must be between 0 and 1 mm.")
    r = p.diameter / 2
    grip = r - (p.knurl_depth if p.knurl else 0)  # the knurl's grooves
    widest = max(p.socket_size / math.sqrt(3), p.magnet_diameter / 2 + MAGNET_CLEARANCE)
    if widest > grip - MIN_WALL:
        raise ValueError(f"The socket or the magnet is too wide for the handle: use a diameter of at least "
                         f"{math.ceil(2 * (widest + MIN_WALL + r - grip))} mm.")
    if holes_radius(p) > grip - MIN_WALL:
        raise ValueError(f"The storage holes don't fit in the handle: use a diameter of at least "
                         f"{math.ceil(2 * (holes_radius(p) + MIN_WALL + r - grip))} mm, smaller holes or fewer.")
    if thread_radii(p)[1] > r - MIN_WALL:
        raise ValueError(f"The cap's thread doesn't fit in the handle: use a diameter of at least "
                         f"{math.ceil(2 * (thread_radii(p)[1] + MIN_WALL))} mm.")
    lay = layout(p)
    if p.taper_length > 0:
        if not 2 * TIP_ROUND + 2 <= p.tip_diameter <= p.diameter:
            raise ValueError(f"The tip's diameter must be between {2 * TIP_ROUND + 2:g} mm and the handle's diameter.")
        if not 3 <= p.taper_length <= lay.length - lay.knurl_bottom - TAPER_COLLAR - 5:
            raise ValueError(f"The taper must be 3 to {lay.length - lay.knurl_bottom - TAPER_COLLAR - 5:g} mm long, "
                             "or 0 for none.")
        socket = p.socket_size / math.sqrt(3) + SOCKET_CHAMFER
        if p.tip_diameter / 2 < socket + MIN_WALL:
            raise ValueError(f"The tip is too narrow for the bit socket: use a tip diameter of at least "
                             f"{math.ceil(2 * (socket + MIN_WALL))} mm.")
        if p.magnet_diameter > 0 and p.magnet_height > 0 and \
                radius_at(p, lay.pocket_top, lay.length) < p.magnet_diameter / 2 + MAGNET_CLEARANCE + MIN_WALL:
            raise ValueError("The taper leaves too little wall around the magnet: use a wider tip or a shorter taper.")
        if p.holes and radius_at(p, lay.holes_top, lay.length) < holes_radius(p) + MIN_WALL:
            raise ValueError("The taper leaves too little wall around the storage holes: use a wider tip or a shorter taper.")
    elif p.taper_length < 0:
        raise ValueError("The taper's length must be 0 or more.")
    if lay.knurl_top - lay.knurl_bottom < 5 and p.knurl:
        raise ValueError("The handle is too short for a knurl: turn it off or use longer storage holes.")


def _cam_face(radius, n: int) -> Face:
    """A closed smooth outline through n points at the given radius(angle)."""
    pts = [Vector(radius(2 * math.pi * i / n) * math.cos(2 * math.pi * i / n),
                  radius(2 * math.pi * i / n) * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return Face(Wire(Spline(*pts, periodic=True)))


def thread(inner: float, outer: float, z0: float, z1: float) -> Part:
    """A right-hand threaded rod from z0 to z1 with a rounded profile between the radii (its
    thread's flanks are at most about 50 degrees from the axis, so it prints upright)."""
    depth = outer - inner
    face = _cam_face(lambda t: inner + depth * 0.5 * (1 - math.cos(t)), 96)
    turns = 360 * (z1 - z0) / THREAD_PITCH
    # The section at angle t sits at height t / 2pi * pitch: turning it as it rises makes the helix.
    solid = Solid.extrude_linear_with_rotation(face, Vector(0, 0, 0), Vector(0, 0, z1 - z0), turns)
    return Part((Pos(0, 0, z0) * solid).wrapped)


def _top_edge(p: HandleParams, r: float, length: float, top_round: float, smooth) -> None:
    """Rings for the handle's top: the taper (if any) and the rounded edge, an arc tangent to the
    side and the top face."""
    side_start, tip = length - top_round, r
    if p.taper_length > 0:
        side_start, tip, top_round = length - p.taper_length, p.tip_diameter / 2, TIP_ROUND
        smooth(side_start, r)
    up = Vector(tip - r, length - side_start).normalized()  # along the side, upward
    nx, nz = up.Y, -up.X  # the side's outward normal (radius, height)
    cx, cz = tip - top_round * (1 - nz) / nx, length - top_round  # the arc's centre
    start = math.atan2(nz, nx)
    steps = 6
    for i in range(steps + 1):
        a = start + (math.pi / 2 - start) * i / steps
        smooth(cz + top_round * math.sin(a), cx + top_round * math.cos(a))


def _outer_rings(p: HandleParams, start: float, length: float, knurl: tuple[float, float] | None,
                 top_round: float | None, radius: float | None = None) -> Part:
    """The handle's outside from z = start up, as one polyhedron: smooth (many-sided) collars, a
    rounded top edge and, between knurl[0] and knurl[1], a diamond knurl. With top_round None (the
    cap's flange): a plain disc from start to length, knurled all the way when knurl is given.
    radius: the outermost radius (default: the handle's)."""
    r = radius or p.diameter / 2
    m = p.knurl_count
    n = 2 * m * max(1, round(SEGMENTS / (2 * m)))  # a multiple of the knurl's points per ring
    knurled = knurl is not None and p.knurl and p.knurl_depth > 0
    rings: list[tuple[float, list[float]]] = []  # (z, radius at each of its equally spaced angles)

    def smooth(z: float, radius: float) -> None:
        rings.append((z, [radius] * n))

    if not (knurled and knurl[0] <= start):
        smooth(start, r)
    first_knurl = rows = None
    if knurled:
        k0, k1 = knurl
        dz_nominal = 2 * math.pi * r / m / math.tan(math.radians(KNURL_ANGLE))
        rows = max(2, 2 * round((k1 - k0) / dz_nominal))  # even: apexes at both ends
        # Points (a, b): angle a * pi / m, height k0 + b * (k1 - k0) / rows; a + b odd: a diamond's
        # apex (radius r), even: a corner between diamonds (in the grooves).
        first_knurl = len(rings)
        for b in range(rows + 1):
            rings.append((k0 + (k1 - k0) * b / rows,
                          [r if (a + b) % 2 else r - p.knurl_depth for a in range(2 * m)]))
    if top_round is None:
        if not (knurled and knurl[1] >= length):
            smooth(length, r)
    else:
        _top_edge(p, r, length, top_round, smooth)

    def point(ring, i) -> Vector:
        z, radii = ring
        a = 2 * math.pi * i / len(radii)
        return Vector(radii[i] * math.cos(a), radii[i] * math.sin(a), z)

    faces: list[Face] = []

    def tri(a: Vector, b: Vector, c: Vector) -> None:  # counterclockwise seen from outside
        faces.append(_polygon_face([a, b, c]))

    def band(lo, hi) -> None:
        """Triangles between two rings; one's number of points is a multiple of the other's."""
        nl, nh = len(lo[1]), len(hi[1])
        if nl == nh:
            for i in range(nl):
                j = (i + 1) % nl
                tri(point(lo, i), point(lo, j), point(hi, j))
                tri(point(lo, i), point(hi, j), point(hi, i))
            return
        fine, coarse, fine_is_lo = (lo, hi, True) if nl > nh else (hi, lo, False)
        nf, nc = len(fine[1]), len(coarse[1])
        step, mid = nf // nc, nf // nc // 2
        for c in range(nc):
            c2 = (c + 1) % nc
            for k in range(step):
                f, f2 = c * step + k, (c * step + k + 1) % nf
                pts = (point(fine, f), point(fine, f2), point(coarse, c if k < mid else c2))
                tri(*pts) if fine_is_lo else tri(pts[1], pts[0], pts[2])
            pts = (point(coarse, c), point(coarse, c2), point(fine, c * step + mid))
            tri(pts[1], pts[0], pts[2]) if fine_is_lo else tri(*pts)

    for i in range(len(rings) - 1):
        lo, hi = rings[i], rings[i + 1]
        if first_knurl is not None and first_knurl <= i < first_knurl + rows:
            # The diamonds: each quad is split along the groove between its two corner points, so
            # every apex gets four triangles.
            m2 = 2 * m
            b = i - first_knurl
            for a in range(m2):
                a2 = (a + 1) % m2
                if (a + b) % 2:  # (a, b) and (a2, b + 1) are apexes
                    tri(point(lo, a), point(lo, a2), point(hi, a))
                    tri(point(lo, a2), point(hi, a2), point(hi, a))
                else:  # (a2, b) and (a, b + 1) are apexes
                    tri(point(lo, a), point(lo, a2), point(hi, a2))
                    tri(point(lo, a), point(hi, a2), point(hi, a))
        else:
            band(lo, hi)
    bottom, top = rings[0], rings[-1]
    faces.append(_polygon_face([point(bottom, i) for i in reversed(range(len(bottom[1])))]))
    faces.append(_polygon_face([point(top, i) for i in range(len(top[1]))]))
    return _sew(faces)


def _polygon_face(points: list[Vector]):
    """A flat face (an OCCT TopoDS_Face) through the points, in order."""
    poly = BRepBuilderAPI_MakePolygon()
    for v in points:
        poly.Add(gp_Pnt(v.X, v.Y, v.Z))
    poly.Close()
    return BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()


def _sew(faces: list) -> Part:
    """A closed solid from faces that meet edge to edge."""
    sewing = BRepBuilderAPI_Sewing(1e-6)
    for f in faces:
        sewing.Add(f)
    sewing.Perform()
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell(sewing.SewedShape())).Solid()
    fix = ShapeFix_Solid(solid)
    fix.Perform()
    return Part(Solid(fix.Solid()).wrapped)


def _hex(size: float, z0: float, z1: float, angle: float = 0.0) -> Part:
    """A hexagonal prism `size` across flats, a corner at `angle` degrees."""
    return Part((Pos(0, 0, z0) * extrude(Rot(0, 0, angle) * RegularPolygon(size / math.sqrt(3), 6), amount=z1 - z0)).wrapped)


def build_handle(p: HandleParams) -> Part:
    validate(p)
    lay = layout(p)
    r = p.diameter / 2
    # Two parts, joined at the end: a smooth bottom collar (a true solid of revolution) with the
    # threaded opening, and above it the knurled polyhedron. (Cutting the thread from the
    # polyhedron takes many times longer: its curved face is tested against many triangles.)
    split = lay.knurl_bottom - 1.5
    # No chamfer at the bottom: the whole bottom face holds on to the print bed.
    collar = Part(revolve(Plane.XZ * Polygon((0, 0), (r, 0), (r, split), (0, split), align=None), Axis.Z).wrapped)
    upper = _outer_rings(p, split, lay.length, (lay.knurl_bottom, lay.knurl_top), TOP_ROUND)
    inner, outer = thread_radii(p)
    # The opening for the cap: a threaded rod's shape, a little longer than the plug; the thread
    # starts right at the bottom.
    if p.holes:  # (without storage holes the bottom is solid, and there is no cap)
        # Longer and cut off with a plane: faces bounded by the twisted extrusion's own end
        # curve are tessellated wrongly (or not at all).
        z = lay.holes_bottom
        rod = thread(inner, outer, -1.0, z + 1.0) - (Pos(0, 0, z) * Box(4 * r, 4 * r, 2, align=(Align.CENTER, Align.CENTER, Align.MIN)))
        collar = collar.cut(rod)
    tools = []
    if p.holes:
        # The opening's ceiling: a shallow cone, so the walls between the storage holes don't
        # start in mid-air, while the holes' mouths stay close to the opening (easy to reach).
        z = lay.holes_bottom
        rise = (outer + 0.3) * math.tan(math.radians(ENTRY_ANGLE))
        tools.append(Part(revolve(Plane.XZ * Polygon((0, z), (outer + 0.3, z), (0, z + rise), align=None),
                                  Axis.Z).wrapped))
    # Storage holes, a corner of each pointing outward (a honeycomb around the axis), each with a
    # 45 degree roof so they print without supports.
    rc = hole_centre_radius(p)
    roof = p.hole_size / 2 - 0.05
    for i in range(p.holes):
        a = 90 + 360 * i / p.holes
        at = Pos(rc * math.cos(math.radians(a)), rc * math.sin(math.radians(a)), 0)
        tools.append(Part((at * _hex(p.hole_size, lay.holes_bottom - 0.01, lay.holes_top, a)).wrapped))
        tools.append(Part((at * Pos(0, 0, lay.holes_top - 0.01) * extrude(
            Rot(0, 0, a) * RegularPolygon(p.hole_size / math.sqrt(3), 6), amount=roof, taper=45)).wrapped))
    if p.magnet_diameter > 0 and p.magnet_height > 0:
        tools.append(Part((Pos(0, 0, lay.pocket_bottom) * extrude(
            Circle(p.magnet_diameter / 2 + MAGNET_CLEARANCE), amount=lay.pocket_top - lay.pocket_bottom)).wrapped))
    tools.append(_hex(p.socket_size, lay.socket_bottom, lay.length + 1))
    # The lead-in: a 45 degree countersink starting at the socket's flats, so it only bevels the
    # socket's mouth and the top face stays flat around it.
    tools.append(Part((Pos(0, 0, lay.length - SOCKET_CHAMFER) * extrude(
        Circle(p.socket_size / 2), amount=SOCKET_CHAMFER + 0.1, taper=-45)).wrapped))
    # One boolean per part: the knurled outside has thousands of faces.
    holes = tools[:2 * p.holes + 1] if p.holes else []  # the cone and the holes reach into the collar
    return Part((collar.cut(*holes) + upper.cut(*tools)).wrapped) if holes else Part((collar + upper.cut(*tools)).wrapped)


def build_cap(p: HandleParams) -> Part:
    """The screw cap: a flange with a threaded plug on it, printed flange down."""
    validate(p)
    r = p.diameter / 2
    # A disc, knurled like the handle for grip and a little larger than it (even its grooves
    # stand out), so it is easy to grab: no chamfers, so it sits flush against the handle's
    # flat bottom.
    flange = _outer_rings(p, 0.0, CAP_FLANGE, (0.0, CAP_FLANGE), None, r + CAP_OVERSIZE)
    inner, outer = thread_radii(p)
    c = p.thread_clearance
    top = CAP_FLANGE + p.thread_length - THREAD_GAP
    # The thread made longer and cut off with a plane: the end face of the twisted extrusion
    # itself is tessellated wrongly (folded triangles, a gap in the 3MF).
    plug = thread(inner - c, outer - c, CAP_FLANGE - 1.0, top + 1.0)
    plug = plug - (Pos(0, 0, top) * Box(4 * r, 4 * r, 2, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    plug = plug - (Pos(0, 0, CAP_FLANGE - 1.0) * Box(4 * r, 4 * r, 0.99, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    return Part((flange + plug).wrapped)


def build_screwdriver_handle(p: HandleParams) -> Compound:
    """The handle and its cap (when it has storage holes), side by side, each in print orientation."""
    handle = Part(build_handle(p).wrapped)
    handle.label, handle.color = "handle", COLOUR
    parts = [handle]
    if p.holes:
        cap = Part((Pos(p.diameter + 8, 0, 0) * build_cap(p)).wrapped)
        cap.label, cap.color = "cap", CAP_COLOUR
        parts.append(cap)
    return Compound(children=parts, label="screwdriver_handle")


def describe(p: HandleParams) -> str:
    lay = layout(p)
    longer = f" (longer than {p.min_length:g} mm, to fit what is inside)" if lay.length > p.min_length + 0.5 else ""
    cap = f", plus the cap's {CAP_FLANGE:g} mm flange" if p.holes else ""
    text = (f"Handle Ø{p.diameter:g} x {lay.length:.1f} mm{longer}{cap}; "
            f"{'diamond knurl' if p.knurl and p.knurl_depth > 0 else 'smooth'}"
            f"{f', the top {p.taper_length:g} mm tapered to Ø{p.tip_diameter:g} mm' if p.taper_length > 0 else ''}. "
            f"Bit socket {p.socket_size:g} mm across flats, {p.socket_depth:g} mm deep.")
    if p.holes:
        text += (f" {p.holes} storage hole{'s' if p.holes > 1 else ''} {p.hole_size:g} mm across flats, "
                 f"{p.hole_length:g} mm long (from the cap's plug), closed by the screw cap, "
                 f"{p.storage_gap:g} mm below the magnet.")
    if p.magnet_diameter > 0 and p.magnet_height > 0:
        text += (f" Magnet Ø{p.magnet_diameter:g} x {p.magnet_height:g} mm, {p.magnet_gap:g} mm below the socket: "
                 f"its pocket runs from Z = {lay.pocket_bottom:.2f} to {lay.pocket_top:.2f} mm. In the slicer, pause "
                 f"the print at the first layer above Z = {lay.pocket_top:.2f} mm, drop the magnet in, and resume.")
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description="Screwdriver handle for hex bits (STEP)")
    d = HandleParams()
    for name, value in vars(d).items():
        if isinstance(value, bool):
            ap.add_argument(f"--{name.replace('_', '-')}", type=lambda s: s.lower() in ("1", "true", "yes"), default=value)
        else:
            ap.add_argument(f"--{name.replace('_', '-')}", type=type(value), default=value)
    ap.add_argument("--out", default="screwdriver_handle.step")
    args = vars(ap.parse_args())
    out = args.pop("out")
    p = HandleParams(**args)
    export_step(build_screwdriver_handle(p), out)
    print(describe(p))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
