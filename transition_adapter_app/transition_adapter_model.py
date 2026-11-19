"""
    Transition adapter: joins two components, which may be different or the same.

    Each side (A and B) is set up on its own:
      * the component's shape: round (diameter), square (side) or rectangle (width x length)
      * a socket, which the component goes into: a cavity of the component's outside size
        plus the tolerance on every side, `wall` thick around it
      * or a plug, which goes into the component's opening: the opening's size minus the
        tolerance on every side, standing on a shoulder `wall` wide that the component's end
        rests against
      * the depth: how far the component goes into the socket, or the plug into the component

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

import numpy as np
from build123d import (
    Align, Box, Circle, Color, Compound, Part, Plane, Polygon, Pos, Rectangle, Sketch, export_step, extrude, loft,
)

SHAPES = ("round", "square", "rectangle")
KINDS = ("socket", "plug")
MIN_PLUG = 1.0  # mm, smallest plug cross-section
_LOFT_POINTS = 96  # points around a tapered middle part between two different shapes
COLOUR = Color(0.35, 0.55, 0.82)
_C, _MIN = Align.CENTER, Align.MIN


@dataclass
class AdapterParams:
    a_shape: str = "round"
    a_size: float = 20.0  # diameter, side or width (mm)
    a_length: float = 30.0  # rectangle only: the other side (mm)
    a_kind: str = "socket"
    a_depth: float = 15.0
    a_tolerance: float = 0.2  # gap on every side (mm)
    a_wall: float = 2.0  # socket wall, or plug shoulder (mm)
    b_shape: str = "round"
    b_size: float = 12.0
    b_length: float = 20.0
    b_kind: str = "plug"
    b_depth: float = 12.0
    b_tolerance: float = 0.2
    b_wall: float = 2.0
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

    def dims(self, offset: float) -> tuple[float, float]:
        """Width and length (x, y; the diameter twice for round) of the outline grown by `offset`."""
        width = self.size + 2 * offset
        return width, (self.length + 2 * offset if self.shape == "rectangle" else width)

    def outline(self, offset: float) -> Sketch:
        """The component's outline (outside for a socket, opening for a plug), grown by `offset`
        on every side (negative: shrunk)."""
        w, h = self.dims(offset)
        return Circle(w / 2) if self.shape == "round" else Rectangle(w, h)

    @property
    def fit(self) -> float:
        """Offset of the socket's cavity or the plug from the component's outline."""
        return self.tolerance if self.kind == "socket" else -self.tolerance

    @property
    def outer(self) -> float:
        """Offset of the outside of the adapter at this side's end: socket wall or plug shoulder."""
        return self.fit + self.wall if self.kind == "socket" else self.wall


def side(p: AdapterParams, name: str) -> Side:
    return Side(*(getattr(p, f"{name}_{field}") for field in ("shape", "size", "length", "kind", "depth", "tolerance", "wall")))


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
    if not -500 <= p.distance <= 500:
        raise ValueError("The distance must be between -500 and 500 mm.")


def _prism(sketch: Sketch, z0: float, z1: float) -> Part:
    return Pos(0, 0, z0) * extrude(sketch, amount=z1 - z0)


def _ring_points(s: Side, offset: float, n: int = _LOFT_POINTS) -> list[tuple[float, float]]:
    """n points around the outline, at the same angles for every shape (so a loft from one shape to
    another runs straight up, without twisting)."""
    w, h = s.dims(offset)
    pts = []
    for a in np.linspace(0, 2 * math.pi, n, endpoint=False):
        c, si = math.cos(a), math.sin(a)
        if s.shape == "round":
            r = w / 2
        else:  # where the ray at this angle leaves the rectangle
            r = min(w / 2 / abs(c) if abs(c) > 1e-12 else math.inf, h / 2 / abs(si) if abs(si) > 1e-12 else math.inf)
        pts.append((r * c, r * si))
    return pts


def _middle(a: Side, b: Side, d: float) -> Part:
    """From side A's outside at z = 0 to side B's at z = d: straight when they are the same,
    tapered otherwise."""
    if (a.shape, *a.dims(a.outer)) == (b.shape, *b.dims(b.outer)):
        return _prism(a.outline(a.outer), 0, d)
    if a.shape == b.shape == "round":
        sections = [a.outline(a.outer), Plane.XY.offset(d) * b.outline(b.outer)]
    else:
        sections = [Polygon(*_ring_points(a, a.outer), align=None),
                    Plane.XY.offset(d) * Polygon(*_ring_points(b, b.outer), align=None)]
    return Part(loft(sections, ruled=True).wrapped)


def build_adapter_raw(p: AdapterParams) -> Part:
    """The adapter with component A's end face at z = 0 (see the module docstring)."""
    validate(p)
    a, b, d = side(p, "a"), side(p, "b"), p.distance
    big = a.depth + b.depth + abs(d) + 10
    reach = 2 * max(a.size, a.length, b.size, b.length) + 2 * max(a.wall, b.wall) + 20  # wider than everything
    shapes = [
        _prism(a.outline(a.outer if a.kind == "socket" else a.fit), -a.depth, 0),
        _prism(b.outline(b.outer if b.kind == "socket" else b.fit), d, d + b.depth),
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
    else:
        w, h = s.dims(0)
        fw, fh = s.dims(s.fit)
        size, made = (f"{w:g} x {h:g} mm", f"{fw:g} x {fh:g} mm")
    if s.kind == "socket":
        return (f"Side {label}: socket for a {s.shape} component of {size}, {s.depth:g} mm deep: cavity {made}, "
                f"wall {s.wall:g} mm.")
    return (f"Side {label}: plug into a {s.shape} opening of {size}, {s.depth:g} mm long: plug {made}, "
            f"shoulder {s.wall:g} mm.")


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
        for field in ("size", "length", "depth", "tolerance", "wall"):
            ap.add_argument(f"--{name}-{field}", type=float, default=getattr(defaults, f"{name}_{field}"))
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
