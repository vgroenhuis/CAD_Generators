"""
    Cable clip, fastened with one countersunk wood screw.

    The clip as mounted (wall = the plane z = 0, cable running along y):
      * a strap that arches over the cable: a half circle for a round cable, a
        rectangular channel with rounded corners for a flat cable
      * on one side a flat tab with a countersunk hole for the screw, whose head ends
        flush with the tab
      * on the other side a small foot, so that side of the strap also rests on the wall

    The channel is made slightly lower than the cable (`squeeze`), so tightening the
    screw clamps the cable. The tab length and hole position follow from the screw head.

    Printing: on its side (the clip profile flat on the bed), so the strap runs along the
    layer lines - much stronger than printing it standing on its tab - and nothing needs
    support. build_print_layout() returns the requested number of clips in that orientation.

    Can also be run standalone:
        python cable_clip_model.py --diameter 6 --count 4 --out clips.step
        python cable_clip_model.py --flat --width 10 --height 3 --out flat_clip.step
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

from build123d import Align, Axis, Box, Color, Cone, Cylinder, Part, Pos, Rot, export_step, fillet

_MIN = (Align.CENTER, Align.CENTER, Align.MIN)
_EDGE = 1.5  # mm of tab beyond the screw head, and clearance between head and strap


@dataclass
class ClipParams:
    flat: bool = False  # False: round cable (diameter); True: flat cable (width x height)
    diameter: float = 6.0
    flat_width: float = 10.0
    flat_height: float = 3.0
    squeeze: float = 0.2  # channel this much lower than the cable, so the screw clamps it
    strap: float = 2.0  # strap thickness
    clip_width: float = 10.0  # along the cable
    tab_thickness: float = 3.0
    foot: float = 2.0  # length of the foot on the far side
    screw_diameter: float = 3.5
    screw_head: float = 7.0  # head diameter
    hole_clearance: float = 0.3  # hole = screw diameter + this
    countersink_angle: float = 90.0  # included angle of the screw head
    count: int = 1  # clips in the print file


def channel(p: ClipParams) -> tuple[float, float]:
    """Inner width and height of the cable channel."""
    if p.flat:
        return p.flat_width, p.flat_height - p.squeeze
    return p.diameter, p.diameter - p.squeeze


def countersink_depth(p: ClipParams) -> float:
    hole = p.screw_diameter + p.hole_clearance
    return (p.screw_head - hole) / 2 / math.tan(math.radians(p.countersink_angle / 2))


def validate(p: ClipParams) -> None:
    sizes = [p.diameter] if not p.flat else [p.flat_width, p.flat_height]
    if min(sizes + [p.strap, p.clip_width, p.tab_thickness, p.screw_diameter, p.screw_head]) <= 0:
        raise ValueError("All dimensions must be greater than 0.")
    if p.squeeze < 0 or p.squeeze >= min(sizes) / 2:
        raise ValueError("Squeeze must be at least 0 and less than half the cable size.")
    if p.foot < 0 or p.hole_clearance < 0:
        raise ValueError("Foot and hole clearance cannot be negative.")
    if p.screw_head <= p.screw_diameter + p.hole_clearance:
        raise ValueError("The screw head must be wider than the screw hole.")
    if not 60 <= p.countersink_angle <= 120:
        raise ValueError("The countersink angle must be between 60 and 120 degrees (wood screws: 90).")
    if p.tab_thickness < countersink_depth(p) + 0.6:
        raise ValueError(
            f"The tab must be at least {countersink_depth(p) + 0.6:.1f} mm thick for this screw head "
            "(countersink plus 0.6 mm)."
        )
    if p.clip_width < p.screw_head + 1.0:
        raise ValueError(f"The clip must be at least {p.screw_head + 1:.1f} mm wide for this screw head.")
    if not 1 <= p.count <= 50:
        raise ValueError("Make between 1 and 50 clips at once.")


def build_clip(p: ClipParams) -> Part:
    """One clip as mounted: wall at z = 0, cable along y, channel centred on x = 0,
    screw tab on the -x side."""
    validate(p)
    w, h = channel(p)
    t, cw = p.strap, p.clip_width
    if p.flat:
        outer = Box(w + 2 * t, cw, h + t, align=_MIN)
        top_edges = outer.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1]
        outer = fillet(top_edges, radius=t * 0.95)
        strap = outer - Box(w, cw + 2, h, align=_MIN)
    else:
        r = w / 2
        zc = h - r  # centre of the arch; below r when squeezed
        outer = Pos(0, 0, zc) * (Rot(90, 0, 0) * Cylinder(r + t, cw))
        inner = Pos(0, 0, zc) * (Rot(90, 0, 0) * Cylinder(r, cw + 2))
        if zc > 0:  # straight legs down to the wall
            outer += Box(w + 2 * t, cw, zc, align=_MIN)
            inner += Box(w, cw + 2, zc, align=_MIN)
        strap = (outer - inner) & Box(4 * (r + t), 2 * cw, 4 * (r + t), align=_MIN)  # above the wall only
    leg = w / 2 + t  # outer face of the strap legs
    # Screw tab on the -x side, the foot on the +x side.
    hole_x = -(leg + _EDGE + p.screw_head / 2)
    tab_start = hole_x - p.screw_head / 2 - _EDGE
    clip = strap + Pos((tab_start - w / 2) / 2, 0, 0) * Box(-w / 2 - tab_start, cw, p.tab_thickness, align=_MIN)
    if p.foot > 0:
        clip += Pos(w / 2 + (t + p.foot) / 2, 0, 0) * Box(t + p.foot, cw, min(t, h), align=_MIN)
    # Countersunk screw hole, the head flush with the top of the tab.
    hole_r = (p.screw_diameter + p.hole_clearance) / 2
    depth = countersink_depth(p)
    clip -= Pos(hole_x, 0, -1) * Cylinder(hole_r, p.tab_thickness + 2, align=_MIN)
    clip -= Pos(hole_x, 0, p.tab_thickness - depth) * Cone(hole_r, p.screw_head / 2, depth, align=_MIN)
    clip -= Pos(hole_x, 0, p.tab_thickness - 0.01) * Cylinder(p.screw_head / 2, 1, align=_MIN)
    part = Part(clip.wrapped)
    part.label, part.color = "cable clip", Color(0.85, 0.85, 0.85)
    return part


def build_print_layout(p: ClipParams) -> Part:
    """`count` clips in print orientation - on their side, profile on the bed - in rows."""
    clip = build_clip(p)
    on_side = Rot(90, 0, 0) * clip  # the cable direction (y) becomes vertical
    bb = on_side.bounding_box()
    on_side = Pos(-bb.min.X, -bb.min.Y, -bb.min.Z) * on_side
    dx, dy = bb.size.X + 3, bb.size.Y + 3
    per_row = max(1, min(p.count, math.ceil(math.sqrt(p.count * dy / dx))))
    pieces = [Pos((i % per_row) * dx, (i // per_row) * dy, 0) * on_side for i in range(p.count)]
    layout = pieces[0]
    for piece in pieces[1:]:
        layout = layout + piece
    part = Part(layout.wrapped)
    part.label, part.color = "cable clips" if p.count > 1 else "cable clip", Color(0.85, 0.85, 0.85)
    return part


def describe(p: ClipParams) -> str:
    cable = f"flat cable {p.flat_width:g} x {p.flat_height:g} mm" if p.flat else f"round cable {p.diameter:g} mm"
    hole = p.screw_diameter + p.hole_clearance
    n = f"{p.count} clips" if p.count > 1 else "1 clip"
    return f"{n} for a {cable}; screw hole {hole:g} mm, countersunk for a {p.screw_head:g} mm head"


def main() -> None:
    d = ClipParams()
    ap = argparse.ArgumentParser(description="Cable clip for one countersunk wood screw")
    ap.add_argument("--flat", action="store_true", help="flat cable (use --width/--height)")
    ap.add_argument("--diameter", type=float, default=d.diameter, help="round cable diameter (mm)")
    ap.add_argument("--width", type=float, default=d.flat_width, help="flat cable width (mm)")
    ap.add_argument("--height", type=float, default=d.flat_height, help="flat cable height (mm)")
    ap.add_argument("--squeeze", type=float, default=d.squeeze)
    ap.add_argument("--strap", type=float, default=d.strap, help="strap thickness (mm)")
    ap.add_argument("--clip-width", type=float, default=d.clip_width, help="along the cable (mm)")
    ap.add_argument("--tab", type=float, default=d.tab_thickness, help="tab thickness (mm)")
    ap.add_argument("--screw", type=float, default=d.screw_diameter, help="screw diameter (mm)")
    ap.add_argument("--head", type=float, default=d.screw_head, help="screw head diameter (mm)")
    ap.add_argument("--count", type=int, default=d.count)
    ap.add_argument("--out", default="cable_clip.step")
    a = ap.parse_args()
    p = ClipParams(flat=a.flat, diameter=a.diameter, flat_width=a.width, flat_height=a.height, squeeze=a.squeeze,
                   strap=a.strap, clip_width=a.clip_width, tab_thickness=a.tab, screw_diameter=a.screw,
                   screw_head=a.head, count=a.count)
    export_step(build_print_layout(p), a.out)
    print(f"Wrote {a.out}: {describe(p)}")


if __name__ == "__main__":
    main()
