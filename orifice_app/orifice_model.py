"""
    Pneumatic tube connector with an orifice (flow restriction) between two tube sockets.

    One connection, along its axis (z up, as printed):
      * socket A: a bore for the first tube, open at the bottom (z = 0)
      * a conical shoulder from socket A down to the orifice
      * the orifice: a short cylindrical bore of the given diameter and length
      * a conical shoulder from the orifice up to socket B
      * socket B: a bore for the second tube, open at the top

    The sockets can be tapered: each bore narrows from its opening towards the orifice
    (the given inner diameter is the one at the opening), so a pushed-in tube wedges
    tighter the further it goes. The taper angle is measured between the socket wall and
    the axis, like the shoulder angle; 0 gives straight sockets.

    The shoulder angle applies to both shoulders and is measured between the socket axis
    and the cone wall: 90 degrees is a flat step, smaller angles give a longer, steeper
    shoulder (the default 30 degrees prints well as an overhang).

    Series mode tries several orifice diameters at once (min to max in steps): one
    connection per diameter, smallest on the left, side by side and joined into a single
    part by a thin wall that stands on the build plate and reaches up to the top of the
    orifice section. All bores are cut after joining, so the wall never blocks a bore.

    Can also be run standalone:
        python orifice_model.py --out orifice.step
        python orifice_model.py --series --d-min 0.4 --d-max 1.2 --step 0.2 --out orifices.step
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

from build123d import Axis, Box, Color, Part, Plane, Polygon, Pos, export_step, revolve


@dataclass
class OrificeParams:
    socket_a_id: float = 4.0  # inner diameter of socket A (fit to the tube's outer diameter)
    socket_a_wall: float = 1.5
    socket_a_depth: float = 10.0
    socket_b_id: float = 4.0
    socket_b_wall: float = 1.5
    socket_b_depth: float = 10.0
    orifice_diameter: float = 1.0
    orifice_length: float = 2.0
    angle: float = 30.0  # degrees between the socket axis and both conical shoulders (90 = flat)
    series: bool = False
    d_min: float = 0.4
    d_max: float = 1.2
    d_step: float = 0.2
    spacing: float = 2.0  # gap between neighbouring connections in a series
    beam_width: float = 2.0  # thickness of the wall that joins a series
    taper: float = 2.0  # degrees between each socket wall and the axis (0 = straight); narrows towards the orifice
    chamfer: float = 0.5  # 45-degree lead-in at each socket opening, this wide (0 = none); eases inserting the tube


@dataclass
class Section:
    """z levels of one connection (all from the open end of socket A)."""
    a_end: float  # bottom of socket A's straight bore
    orifice_start: float
    orifice_end: float
    b_start: float  # start of socket B's straight bore
    top: float


def validate(p: OrificeParams) -> None:
    for name in ("socket_a_id", "socket_a_wall", "socket_a_depth", "socket_b_id", "socket_b_wall",
                 "socket_b_depth", "orifice_length"):
        if getattr(p, name) <= 0:
            raise ValueError(f"{name.replace('_', ' ').capitalize()} must be greater than 0.")
    if not 10 <= p.angle <= 90:
        raise ValueError("The shoulder angle must be between 10 and 90 degrees.")
    if not 0 <= p.taper <= 10:
        raise ValueError("The socket taper must be between 0 and 10 degrees.")
    if p.chamfer < 0 or p.chamfer >= min(p.socket_a_wall, p.socket_b_wall):
        raise ValueError("The entrance chamfer must be at least 0 and smaller than the socket wall thickness.")
    if p.chamfer > min(p.socket_a_depth, p.socket_b_depth) / 2:
        raise ValueError("The entrance chamfer must not exceed half the socket depth.")
    end_a, end_b = socket_end_diameters(p)
    if min(end_a, end_b) <= 0:
        raise ValueError("The taper is too steep for the socket depth: the socket would close up.")
    for d in diameters(p):
        if d <= 0:
            raise ValueError("Orifice diameters must be greater than 0.")
        if d >= min(end_a, end_b):
            raise ValueError(f"Orifice diameter {d:g} mm must be smaller than both sockets, also at their tapered "
                             f"bottom ({end_a:.2f} and {end_b:.2f} mm).")
    if p.series and (p.spacing < 0 or p.beam_width <= 0):
        raise ValueError("Spacing must be >= 0 and the joining wall thickness > 0.")
    if p.series and p.beam_width > p.socket_a_id + 2 * p.socket_a_wall:
        raise ValueError("The joining wall must not be thicker than the connections.")


def diameters(p: OrificeParams) -> list[float]:
    """The orifice diameter(s) to make: one, or min..max in steps (max included when it
    falls on a step)."""
    if not p.series:
        return [p.orifice_diameter]
    if p.d_step <= 0 or p.d_max < p.d_min:
        raise ValueError("For a series, the step must be > 0 and max >= min.")
    n = math.floor((p.d_max - p.d_min) / p.d_step + 1e-9) + 1
    if n > 50:
        raise ValueError(f"That is {n} orifices; at most 50 at once.")
    return [round(p.d_min + i * p.d_step, 6) for i in range(n)]


def socket_end_diameters(p: OrificeParams) -> tuple[float, float]:
    """Inner diameter at the bottom of socket A and of socket B (where the shoulders start)."""
    shrink = 2 * math.tan(math.radians(p.taper))
    return p.socket_a_id - shrink * p.socket_a_depth, p.socket_b_id - shrink * p.socket_b_depth


def section(p: OrificeParams, d: float) -> Section:
    t = math.tan(math.radians(p.angle))
    end_a, end_b = socket_end_diameters(p)
    cone_a = 0.0 if p.angle >= 90 else (end_a - d) / 2 / t
    cone_b = 0.0 if p.angle >= 90 else (end_b - d) / 2 / t
    a_end = p.socket_a_depth
    o0 = a_end + cone_a
    o1 = o0 + p.orifice_length
    b0 = o1 + cone_b
    return Section(a_end, o0, o1, b0, b0 + p.socket_b_depth)


def _outer_radii(p: OrificeParams) -> tuple[float, float, float]:
    ra = p.socket_a_id / 2 + p.socket_a_wall
    rb = p.socket_b_id / 2 + p.socket_b_wall
    return ra, rb, max(ra, rb)


def _revolved(points: list[tuple[float, float]]) -> Part:
    """Solid of revolution of an (r, z) outline around the z axis."""
    clean = [pt for i, pt in enumerate(points) if i == 0 or pt != points[i - 1]]
    return revolve(Plane.XZ * Polygon(*clean, align=None), axis=Axis.Z)


def _outer(p: OrificeParams, s: Section) -> Part:
    """The outside of one connection: each socket with its own wall; the shoulders and
    orifice inside the larger of the two, with 45-degree steps (no overhang) in between."""
    ra, rb, rm = _outer_radii(p)
    step_a = min(rm - ra, s.a_end)  # 45-degree step down to socket A's outside
    step_b = min(rm - rb, s.top - s.b_start)
    return _revolved([
        (0, 0), (ra, 0), (ra, s.a_end - step_a), (rm, s.a_end), (rm, s.b_start),
        (rb, s.b_start + step_b), (rb, s.top), (0, s.top),
    ])


def _bore(p: OrificeParams, s: Section, d: float) -> Part:
    """The inside of one connection, a little longer than the part at both ends."""
    a, b, r = p.socket_a_id / 2, p.socket_b_id / 2, d / 2  # at the socket openings
    end_a, end_b = (e / 2 for e in socket_end_diameters(p))
    c, t = p.chamfer, math.tan(math.radians(p.taper))
    return _revolved([
        (0, -1), (a + c + 1, -1), (a + c, 0), (a - c * t, c), (end_a, s.a_end), (r, s.orifice_start),
        (r, s.orifice_end), (end_b, s.b_start), (b - c * t, s.top - c), (b + c, s.top), (b + c + 1, s.top + 1),
        (0, s.top + 1),
    ])


def build_orifice(p: OrificeParams) -> Part:
    """One connection, or a joined series of connections (one per orifice diameter)."""
    validate(p)
    ds = diameters(p)
    _, _, rm = _outer_radii(p)
    pitch = 2 * rm + p.spacing
    sections = [section(p, d) for d in ds]
    body = None
    for i, s in enumerate(sections):
        piece = Pos(i * pitch, 0, 0) * _outer(p, s)
        body = piece if body is None else body + piece
    if len(ds) > 1:
        # A wall from the build plate up to the highest orifice section joins the series.
        top = max(s.b_start for s in sections)
        length = (len(ds) - 1) * pitch
        body += Pos(length / 2, 0, top / 2) * Box(length, p.beam_width, top)
    for i, (s, d) in enumerate(zip(sections, ds)):
        body -= Pos(i * pitch, 0, 0) * _bore(p, s, d)
    part = Part(body.wrapped)
    part.label, part.color = "orifice", Color(0.85, 0.85, 0.85)
    return part


def describe(p: OrificeParams) -> str:
    ds = diameters(p)
    s = section(p, ds[0])
    which = (f"{len(ds)} orifices: " + ", ".join(f"{d:g}" for d in ds) + " mm (smallest on the left)"
             if len(ds) > 1 else f"orifice {ds[0]:g} mm")
    return f"{which}; length {s.top:.1f} mm, shoulders {p.angle:g} deg; {socket_summary(p)}"


def socket_summary(p: OrificeParams) -> str:
    """Inner diameter of each socket at its opening and at its bottom."""
    end_a, end_b = socket_end_diameters(p)
    if p.taper == 0:
        return f"sockets {p.socket_a_id:g} / {p.socket_b_id:g} mm (straight)"
    return (f"socket A {p.socket_a_id:.2f} -> {end_a:.2f} mm, socket B {p.socket_b_id:.2f} -> {end_b:.2f} mm "
            f"(opening -> bottom, {p.taper:g} deg taper)")


def main() -> None:
    d = OrificeParams()
    ap = argparse.ArgumentParser(description="Pneumatic tube connector with an orifice")
    ap.add_argument("--a-id", type=float, default=d.socket_a_id, help="socket A inner diameter (mm)")
    ap.add_argument("--a-wall", type=float, default=d.socket_a_wall)
    ap.add_argument("--a-depth", type=float, default=d.socket_a_depth)
    ap.add_argument("--b-id", type=float, default=d.socket_b_id, help="socket B inner diameter (mm)")
    ap.add_argument("--b-wall", type=float, default=d.socket_b_wall)
    ap.add_argument("--b-depth", type=float, default=d.socket_b_depth)
    ap.add_argument("--orifice", type=float, default=d.orifice_diameter, help="orifice diameter (mm)")
    ap.add_argument("--orifice-length", type=float, default=d.orifice_length)
    ap.add_argument("--angle", type=float, default=d.angle, help="shoulder angle to the axis (deg, 90 = flat)")
    ap.add_argument("--taper", type=float, default=d.taper, help="socket taper (deg per side, 0 = straight)")
    ap.add_argument("--chamfer", type=float, default=d.chamfer, help="entrance chamfer width (mm, 0 = none)")
    ap.add_argument("--series", action="store_true", help="one connection per diameter from --d-min to --d-max")
    ap.add_argument("--d-min", type=float, default=d.d_min)
    ap.add_argument("--d-max", type=float, default=d.d_max)
    ap.add_argument("--step", type=float, default=d.d_step)
    ap.add_argument("--out", default="orifice.step")
    a = ap.parse_args()
    p = OrificeParams(a.a_id, a.a_wall, a.a_depth, a.b_id, a.b_wall, a.b_depth, a.orifice, a.orifice_length,
                      a.angle, a.series, a.d_min, a.d_max, a.step, taper=a.taper, chamfer=a.chamfer)
    export_step(build_orifice(p), a.out)
    print(f"Wrote {a.out}: {describe(p)}")


if __name__ == "__main__":
    main()
