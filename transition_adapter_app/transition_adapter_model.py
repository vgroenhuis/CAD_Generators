"""
    Transition adapter: joins two components, which may be different or the same.

    Each side (A and B) is set up on its own:
      * the component's shape: round (diameter), square (side), rectangle (width x length) or
        hexagon (across flats, e.g. a nut or a hex bar; two flats parallel to the X axis)
      * a socket, which the component goes into: a cavity of the component's outside size
        plus the tolerance on every side, `wall` thick around it
      * or a plug, which goes into the component's opening: the opening's size minus the
        tolerance on every side, standing on a shoulder `wall` wide that the component's end
        rests against
      * the depth: how far the component goes into the socket, or the plug into the component
      * a chamfer that makes mounting easier: at a socket's mouth it widens the opening, at a
        plug's tip it narrows the plug, `chamfer_width` across and `chamfer_depth` along the axis
        (0 for none; a width no larger than the depth prints without supports)

    The adapter's axis is Z. Component A comes from below, its end face at z = 0; component B
    from above, its end face at z = `distance`. A positive distance leaves a gap between the two
    ends, filled by the adapter (a straight or tapered middle part from one side's outside to the
    other's); zero makes the ends meet; a negative distance makes them reach into each other
    (e.g. a component that slides into the other's opening). The adapter is the union of both
    sides' outer shapes and the middle part, minus the space each component takes (with its
    tolerance), so it never cuts into a component. warnings() reports when the two components
    themselves would overlap, or when the adapter would fall apart.

    The model lies in print orientation: side A down, its lowest point at z = 0.

    Can also be run standalone:
        python transition_adapter_model.py --a-shape round --a-size 20 --a-kind socket \\
            --b-shape square --b-size 12 --b-kind plug --distance 5 --out adapter.step
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

from build123d import (
    Align, Box, Circle, Color, Compound, Face, Line, Part, Plane, Polygon, Pos, Rectangle, Shell, Sketch, Solid,
    ThreePointArc, Vector, Wire, export_step, extrude, loft,
)

SHAPES = ("round", "square", "rectangle", "hexagon")
ADJECTIVES = {"round": "round", "square": "square", "rectangle": "rectangular", "hexagon": "hexagonal"}
KINDS = ("socket", "plug")
MIN_PLUG = 1.0  # mm, smallest plug cross-section
COLOUR = Color(0.35, 0.55, 0.82)
_C, _MIN = Align.CENTER, Align.MIN


@dataclass
class AdapterParams:
    a_shape: str = "round"
    a_size: float = 20.0  # diameter, side, width or across flats (mm)
    a_length: float = 30.0  # rectangle only: the other side (mm)
    a_kind: str = "socket"
    a_depth: float = 15.0
    a_tolerance: float = 0.2  # gap on every side (mm)
    a_wall: float = 2.0  # socket wall, or plug shoulder (mm)
    a_chamfer_width: float = 1.0  # lead-in at the socket's mouth or the plug's tip (mm; 0: none)
    a_chamfer_depth: float = 1.0
    b_shape: str = "round"
    b_size: float = 12.0
    b_length: float = 20.0
    b_kind: str = "plug"
    b_depth: float = 12.0
    b_tolerance: float = 0.2
    b_wall: float = 2.0
    b_chamfer_width: float = 1.0
    b_chamfer_depth: float = 1.0
    distance: float = 5.0  # between the components' end faces (mm); may be zero or negative


@dataclass
class Side:
    shape: str
    size: float
    length: float
    kind: str
    depth: float
    tolerance: float
    wall: float
    chamfer_width: float = 0.0
    chamfer_depth: float = 0.0

    @property
    def chamfered(self) -> bool:
        return self.chamfer_width > 0 and self.chamfer_depth > 0

    def dims(self, offset: float) -> tuple[float, float]:
        """Width and length (x, y) of the outline grown by `offset`: the diameter twice for round;
        for a hexagon across corners (x) and across flats (y)."""
        width = self.size + 2 * offset
        if self.shape == "hexagon":
            return width * 2 / math.sqrt(3), width
        return width, (self.length + 2 * offset if self.shape == "rectangle" else width)

    def corners(self, offset: float, z: float = 0.0) -> list[Vector]:
        """A polygon's corners (not round), counter-clockwise, starting with the first one counter-
        clockwise from the X axis (inclusive)."""
        w, h = self.dims(offset)
        if self.shape == "hexagon":
            r = w / 2
            return [Vector(r * math.cos(i * math.pi / 3), r * math.sin(i * math.pi / 3), z) for i in range(6)]
        return [Vector(w / 2, h / 2, z), Vector(-w / 2, h / 2, z), Vector(-w / 2, -h / 2, z), Vector(w / 2, -h / 2, z)]

    def outline(self, offset: float) -> Sketch:
        """The component's outline (outside for a socket, opening for a plug), grown by `offset`
        on every side (negative: shrunk)."""
        w, h = self.dims(offset)
        if self.shape == "round":
            return Circle(w / 2)
        if self.shape == "hexagon":
            return Polygon(*[(v.X, v.Y) for v in self.corners(offset)], align=None)
        return Rectangle(w, h)

    @property
    def fit(self) -> float:
        """Offset of the socket's cavity or the plug from the component's outline."""
        return self.tolerance if self.kind == "socket" else -self.tolerance

    @property
    def outer(self) -> float:
        """Offset of the outside of the adapter at this side's end: socket wall or plug shoulder."""
        return self.fit + self.wall if self.kind == "socket" else self.wall


def side(p: AdapterParams, name: str) -> Side:
    return Side(*(getattr(p, f"{name}_{field}") for field in SIDE_FIELDS))


SIDE_FIELDS = ("shape", "size", "length", "kind", "depth", "tolerance", "wall", "chamfer_width", "chamfer_depth")


def validate(p: AdapterParams) -> None:
    for name in ("a", "b"):
        s, label = side(p, name), name.upper()
        if s.shape not in SHAPES:
            raise ValueError(f"Side {label}: the shape must be one of {', '.join(SHAPES)}.")
        if s.kind not in KINDS:
            raise ValueError(f"Side {label}: choose socket or plug.")
        if not 0 < s.size <= 500 or (s.shape == "rectangle" and not 0 < s.length <= 500):
            raise ValueError(f"Side {label}: the component's size must be greater than 0 and at most 500 mm.")
        if not 0 < s.depth <= 500:
            raise ValueError(f"Side {label}: the depth must be greater than 0 and at most 500 mm.")
        if not 0 <= s.tolerance <= 5:
            raise ValueError(f"Side {label}: the tolerance must be between 0 and 5 mm.")
        if not 0 < s.wall <= 100:
            raise ValueError(f"Side {label}: the {'wall' if s.kind == 'socket' else 'shoulder'} must be greater than 0 "
                             "and at most 100 mm.")
        if s.kind == "plug" and min(s.dims(s.fit)) < MIN_PLUG:
            raise ValueError(f"Side {label}: the plug would be thinner than {MIN_PLUG:g} mm; use a larger size or a "
                             "smaller tolerance.")
        if s.chamfer_width < 0 or s.chamfer_depth < 0:
            raise ValueError(f"Side {label}: the chamfer's width and depth must be 0 or more.")
        if s.chamfered:
            if s.chamfer_depth > s.depth:
                raise ValueError(f"Side {label}: the chamfer can be at most as deep as the "
                                 f"{'socket' if s.kind == 'socket' else 'plug'} ({s.depth:g} mm).")
            if s.kind == "socket" and s.chamfer_width > s.wall - 0.4:
                raise ValueError(f"Side {label}: the chamfer must leave at least 0.4 mm of the wall: at most "
                                 f"{s.wall - 0.4:g} mm wide.")
            if s.kind == "plug" and min(s.dims(s.fit - s.chamfer_width)) < MIN_PLUG / 2:
                raise ValueError(f"Side {label}: the chamfer is too wide for the plug: its tip would be thinner than "
                                 f"{MIN_PLUG / 2:g} mm.")
    if not -500 <= p.distance <= 500:
        raise ValueError("The distance must be between -500 and 500 mm.")


def _prism(sketch: Sketch, z0: float, z1: float) -> Part:
    return Pos(0, 0, z0) * extrude(sketch, amount=z1 - z0)


def _frustum(s: Side, offset0: float, z0: float, offset1: float, z1: float) -> Part:
    """From the outline grown by offset0 at height z0 to the one grown by offset1 at z1."""
    return Part(loft([Plane.XY.offset(z0) * s.outline(offset0), Plane.XY.offset(z1) * s.outline(offset1)],
                     ruled=True).wrapped)


def _plug(s: Side, root: float, tip: float) -> Part:
    """The plug from its root (the shoulder) to its tip, which is chamfered if asked."""
    if not s.chamfered:
        return _prism(s.outline(s.fit), min(root, tip), max(root, tip))
    start = tip - math.copysign(s.chamfer_depth, tip - root)  # where the chamfer begins
    body = _frustum(s, s.fit, start, s.fit - s.chamfer_width, tip)
    if abs(start - root) > 1e-6:
        body = body + _prism(s.outline(s.fit), min(root, start), max(root, start))
    return body


def _mouth(s: Side, mouth: float, inward: float) -> Part:
    """The socket's chamfer, cut at its mouth (height `mouth`; `inward` +1 or -1 points into the
    socket), with a sliver beyond the mouth so the cut is clean."""
    inner = mouth + inward * s.chamfer_depth
    out = mouth - inward * 0.1
    return _frustum(s, s.fit + s.chamfer_width, mouth, s.fit, inner) + _prism(
        s.outline(s.fit + s.chamfer_width), min(mouth, out), max(mouth, out))


def _section(s: Side, offset: float, z: float, angles: list[float]) -> Wire:
    """The outline at height z as edges that start at the given angles (seen from the axis): a
    polygon's sides, or a circle cut into arcs at its partner polygon's corner angles, so that a
    ruled loft joins each arc to one straight side with a single smooth surface."""
    if s.shape == "round":
        r = s.dims(offset)[0] / 2
        ends = angles + [angles[0] + 2 * math.pi]
        point = lambda t: Vector(r * math.cos(t), r * math.sin(t), z)  # noqa: E731
        edges = [ThreePointArc(point(t0), point((t0 + t1) / 2), point(t1)) for t0, t1 in zip(ends, ends[1:])]
    else:
        corners = s.corners(offset, z)
        edges = [Line(p, q) for p, q in zip(corners, corners[1:] + corners[:1])]
    return Wire(edges)


def _hull(points: list[Vector]) -> Part:
    """The convex hull of the points, with flat faces (coplanar triangles merged)."""
    from scipy.spatial import ConvexHull

    xyz = [(v.X, v.Y, v.Z) for v in points]
    hull = ConvexHull(xyz)
    centre = sum(points, Vector()) / len(points)
    faces = []
    for tri in hull.simplices:
        a, b, c = (points[i] for i in tri)
        if (b - a).cross(c - a).dot(a - centre) < 0:  # outward normals
            b, c = c, b
        faces.append(Face(Wire([Line(a, b), Line(b, c), Line(c, a)])))
    return Part(Solid(Shell(faces)).clean().wrapped)


def _middle(a: Side, b: Side, d: float) -> Part:
    """From side A's outside at z = 0 to side B's at z = d: straight when they are the same,
    tapered otherwise. Between a round and a rectangular side the taper is like a sheet-metal
    square-to-round transition: each side of the rectangle joins a quarter (or so) of the circle
    with one smooth surface, with a crease from each corner of the rectangle down to the circle."""
    if (a.shape, *a.dims(a.outer)) == (b.shape, *b.dims(b.outer)):
        return _prism(a.outline(a.outer), 0, d)
    if a.shape == b.shape == "round":
        return Part(loft([a.outline(a.outer), Plane.XY.offset(d) * b.outline(b.outer)], ruled=True).wrapped)
    if a.shape != "round" and b.shape != "round":
        if (a.shape == "hexagon") == (b.shape == "hexagon"):  # two rectangles or two hexagons: flat faces
            return Part(loft([a.outline(a.outer), Plane.XY.offset(d) * b.outline(b.outer)], ruled=True).wrapped)
        return _hull(a.corners(a.outer, 0) + b.corners(b.outer, d))  # hexagon to rectangle: flat faces
    poly = a if a.shape != "round" else b
    angles = [math.atan2(v.Y, v.X) % (2 * math.pi) for v in poly.corners(poly.outer)]
    return Part(loft([Face(_section(a, a.outer, 0, angles)), Face(_section(b, b.outer, d, angles))], ruled=True).wrapped)


def build_adapter_raw(p: AdapterParams) -> Part:
    """The adapter with component A's end face at z = 0 (see the module docstring)."""
    validate(p)
    a, b, d = side(p, "a"), side(p, "b"), p.distance
    big = a.depth + b.depth + abs(d) + 10
    reach = 2 * max(a.size, a.length, b.size, b.length) + 2 * max(a.wall, b.wall) + 20  # wider than everything
    shapes = [
        _prism(a.outline(a.outer), -a.depth, 0) if a.kind == "socket" else _plug(a, 0, -a.depth),
        _prism(b.outline(b.outer), d, d + b.depth) if b.kind == "socket" else _plug(b, d, d + b.depth),
    ]
    if d > 0:
        shapes.append(_middle(a, b, d))
    body = shapes[0]
    for extra in shapes[1:]:
        body = body + extra
    # The space each component takes, with its tolerance: inside a socket's cavity, or outside a plug.
    for s, z0, z1 in ((a, -big, 0.0), (b, d, d + big)):
        if s.kind == "socket":
            body = body - _prism(s.outline(s.fit), z0, z1)
        else:
            body = body - (Pos(0, 0, z0) * Box(reach, reach, z1 - z0, align=(_C, _C, _MIN)) - _prism(s.outline(s.fit), z0, z1))
    # Lead-in chamfers at the sockets' mouths (a plug's is part of the plug).
    for s, mouth, inward in ((a, -a.depth, 1), (b, d + b.depth, -1)):
        if s.kind == "socket" and s.chamfered:
            body = body - _mouth(s, mouth, inward)
    return Part(body.wrapped) if body.wrapped is not None else Part()


def build_adapter(p: AdapterParams) -> Compound:
    """The adapter in print orientation (side A down, lowest point at z = 0), as one body."""
    raw = build_adapter_raw(p)
    if raw.wrapped is None or not raw.solids():
        raise ValueError("Nothing is left of the adapter: the two components take up all of it. "
                         "Use a larger distance or a thicker wall.")
    part = Part((Pos(0, 0, -raw.bounding_box().min.Z) * raw).wrapped)
    part.label, part.color = "adapter", COLOUR
    return Compound(children=[part], label="transition_adapter")


def _component_region(s: Side) -> Sketch:
    """Where the component's material is, seen along the axis: all of its outline for a socket's
    component; for a plug's, a tube around the opening, assumed as thick as the shoulder."""
    if s.kind == "socket":
        return s.outline(0)
    return s.outline(s.wall) - s.outline(0)


def warnings(p: AdapterParams, adapter: Compound | None = None) -> list[str]:
    """Problems that don't stop the adapter from being made: components that would overlap, and an
    adapter that falls apart into pieces."""
    out = []
    if p.distance < 0:
        overlap = _component_region(side(p, "a")) & _component_region(side(p, "b"))
        area = sum(f.area for f in overlap.faces()) if overlap is not None else 0.0
        if area > 0.01:
            out.append(f"The components would overlap: their ends reach {-p.distance:g} mm into each other, and in that "
                       f"length their outlines cross ({area:.0f} mm²). Use a distance of 0 or more, or sizes where one "
                       "component fits inside the other's opening.")
    if adapter is not None:
        pieces = sum(len(c.solids()) for c in adapter.children)
        if pieces > 1:
            out.append(f"The adapter falls apart into {pieces} pieces: nothing joins the two sides. "
                       "Use a larger distance or a thicker wall.")
    return out


def _side_text(s: Side, label: str) -> str:
    if s.shape == "round":
        size, made = f"Ø{s.size:g} mm", f"Ø{s.dims(s.fit)[0]:g} mm"
    elif s.shape == "hexagon":
        size, made = f"{s.size:g} mm across flats", f"{s.dims(s.fit)[1]:g} mm across flats"
    else:
        w, h = s.dims(0)
        fw, fh = s.dims(s.fit)
        size, made = (f"{w:g} x {h:g} mm", f"{fw:g} x {fh:g} mm")
    chamfer = f", chamfer {s.chamfer_width:g} x {s.chamfer_depth:g} mm" if s.chamfered else ""
    if s.kind == "socket":
        return (f"Side {label}: socket for a {ADJECTIVES[s.shape]} component of {size}, {s.depth:g} mm deep: cavity {made}, "
                f"wall {s.wall:g} mm{chamfer}.")
    return (f"Side {label}: plug into a {ADJECTIVES[s.shape]} opening of {size}, {s.depth:g} mm long: plug {made}, "
            f"shoulder {s.wall:g} mm{chamfer}.")


def describe(p: AdapterParams, adapter: Compound | None = None) -> str:
    text = f"{_side_text(side(p, 'a'), 'A')} {_side_text(side(p, 'b'), 'B')} Distance between the components' ends: {p.distance:g} mm."
    if adapter is not None:
        box = adapter.bounding_box()
        text += f" Adapter {box.size.X:.1f} x {box.size.Y:.1f} x {box.size.Z:.1f} mm, {adapter.volume / 1000:.1f} cm³."
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description="Transition adapter between two components (STEP)")
    defaults = AdapterParams()
    for name in ("a", "b"):
        ap.add_argument(f"--{name}-shape", choices=SHAPES, default=getattr(defaults, f"{name}_shape"))
        ap.add_argument(f"--{name}-kind", choices=KINDS, default=getattr(defaults, f"{name}_kind"))
        for field in ("size", "length", "depth", "tolerance", "wall", "chamfer_width", "chamfer_depth"):
            ap.add_argument(f"--{name}-{field.replace('_', '-')}", type=float, default=getattr(defaults, f"{name}_{field}"))
    ap.add_argument("--distance", type=float, default=defaults.distance)
    ap.add_argument("--out", default="transition_adapter.step")
    args = vars(ap.parse_args())
    out = args.pop("out")
    p = AdapterParams(**args)
    adapter = build_adapter(p)
    for w in warnings(p, adapter):
        print("Warning:", w)
    export_step(adapter, out)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
