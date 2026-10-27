"""
    Male part and clips of the 3D printed pneumatic connectors
    (https://www.printables.com/model/148215-pneumatic-connectors).

    Male part: a plate with a row of through holes for 3 mm tubes, which are glued in and stick
    out about 4 mm on the mating face. On the other face each hole has a 45-degree chamfer and a
    cross-shaped pocket that fills with glue. Both ends have a T-shaped tab (neck and head) on
    which a clip hinges; the clips hook over the lip of the female part to hold the two together.
    The defaults reproduce Male_3.1mm_4x (August 2025): 4 ports 8 mm apart, 3.1 mm holes.

    Clips (Clip_set_v3, August 2025, easier to open): the tab's neck snaps into a window in the
    clip (a narrowing holds it), its head slides in a pocket above, and the far end has a hook
    (45-degree chamfer) for the female part and a slanted slot that clears the tube when the clip
    is fully open. A set is two clips, one
    with a notch, so the connector can only be closed one way round.

    Geometry is built in the coordinates of the original SolidWorks parts (male: holes along y,
    mating face at y = -0.15; clips: profile in the xy plane, bottom face at y = 0) and then
    turned into print orientation: the male part on its mating face, the clips on their flat
    side, all with z up from z = 0.

    Can also be run standalone:  python connector_model.py --ports 4 --hole 3.1 --out male_4x.step
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

from build123d import (
    Box, Circle, Color, Compound, Cone, Cylinder, Line, Location, Part, Plane, Polygon, Pos, Rectangle, Rot,
    ThreePointArc, Wire, export_step, extrude, make_face,
)

# --- Male part (coordinates of Male_3.1mm_4x: x along the row, y through the plate, z across) ---

_TOP = -0.15  # mating face
_BOTTOM = -4.2  # glue face
_HALF_WIDTH = 5.0  # plate width 10
_END = 5.0  # plate end beyond the first/last hole centre
_ARC_R = 3.0  # rounded end: radius, centre _ARC_R in from the end and _ARC_DY below the mating face
_ARC_DY = 0.498
_ARC_TANGENT = (-2.343, -1.874)  # tangent point of the bevel, relative to the arc centre
_BEVEL_X = 2.0  # the bevel meets the glue face this far in from the end
_NECK = (3.0, 2.0, 4.4)  # tab neck beyond the plate end: length, thickness (from the mating face), width
_HEAD = (1.0, 2.5, 5.2)  # tab head: length, thickness, width
_CHAMFER = 0.4  # 45-degree chamfer of the holes on the glue face
_CROSS = (5.0, 1.0, 2.0)  # glue cross: arm length, arm width, depth from the glue face


@dataclass
class ConnectorParams:
    ports: int = 4
    pitch: float = 8.0  # hole centre distance; must match the female part
    hole: float = 3.1  # hole diameter for a 3 mm tube (3.1 since August 2025, was 3.0)
    clips: bool = True  # add a clip set (one plain clip, one with notch)


def validate(p: ConnectorParams) -> None:
    if not 1 <= p.ports <= 8:
        raise ValueError("The number of ports must be between 1 and 8.")
    if not 2.0 <= p.hole <= 3.6:
        raise ValueError("The hole diameter must be between 2.0 and 3.6 mm.")
    if p.pitch < _CROSS[0] + 1.0 or p.pitch > 30:
        raise ValueError(f"The pitch must be between {_CROSS[0] + 1.0:g} and 30 mm, so the glue crosses stay apart.")


def plate_length(p: ConnectorParams) -> float:
    return (p.ports - 1) * p.pitch + 2 * _END


def _plate_profile(length: float):
    """Side view of the plate (xy, x from -_END), with rounded and bevelled ends."""
    x0, x1 = -_END, length - _END
    yc = _TOP - _ARC_DY
    tx, ty = _ARC_TANGENT
    # A point halfway along each end arc (from the end, pointing outward, to the bevel's tangent point).
    half = (math.pi + math.atan2(ty, tx) % (2 * math.pi)) / 2
    mx, my = _ARC_R * math.cos(half), _ARC_R * math.sin(half)
    left_arc = ThreePointArc((x0, yc), (x0 + _ARC_R + mx, yc + my), (x0 + _ARC_R + tx, yc + ty))
    right_arc = ThreePointArc((x1 - _ARC_R - tx, yc + ty), (x1 - _ARC_R - mx, yc + my), (x1, yc))
    edges = [
        Line((x0, _TOP), (x0, yc)),
        left_arc,
        Line((x0 + _ARC_R + tx, yc + ty), (x0 + _BEVEL_X, _BOTTOM)),
        Line((x0 + _BEVEL_X, _BOTTOM), (x1 - _BEVEL_X, _BOTTOM)),
        Line((x1 - _BEVEL_X, _BOTTOM), (x1 - _ARC_R - tx, yc + ty)),
        right_arc,
        Line((x1, yc), (x1, _TOP)),
        Line((x1, _TOP), (x0, _TOP)),
    ]
    return make_face(Wire(edges))


def _tab(x_end: float, direction: int) -> Part:
    """T-shaped tab (neck and head) beyond the plate end at x_end, pointing in `direction` (+1/-1)."""
    nl, nt, nw = _NECK
    hl, ht, hw = _HEAD
    overlap = _ARC_R  # the neck starts inside the rounded end
    neck_len = nl + overlap
    neck = Pos(x_end + direction * (nl - overlap) / 2, _TOP - nt / 2, 0) * Box(neck_len, nt, nw)
    head = Pos(x_end + direction * (nl + hl / 2), _TOP - ht / 2, 0) * Box(hl, ht, hw)
    return neck + head


def build_male_native(p: ConnectorParams) -> Part:
    """Male part in the coordinates of Male_3.1mm_4x (first hole on the y axis)."""
    validate(p)
    length = plate_length(p)
    plate = extrude(Plane.XY * _plate_profile(length), amount=_HALF_WIDTH, both=True)
    plate += _tab(-_END, -1) + _tab(length - _END, 1)
    r = p.hole / 2
    thickness = _TOP - _BOTTOM
    arm, arm_w, depth = _CROSS
    cuts = []
    for i in range(p.ports):
        x = i * p.pitch
        # Hole along y, from the glue face through the mating face.
        cuts.append(Pos(x, (_TOP + _BOTTOM) / 2, 0) * Rot(90, 0, 0) * Cylinder(r, thickness + 0.2))
        # 45-degree chamfer on the glue face (cone from r + chamfer at the face to r).
        cuts.append(Pos(x, _BOTTOM, 0) * Rot(-90, 0, 0) * Cone(r + _CHAMFER + 0.1, r, _CHAMFER + 0.1, align=None)
                    .moved(Location((0, 0, -0.1))))
        # Glue cross on the glue face.
        for size in ((arm, depth, arm_w), (arm_w, depth, arm)):
            cuts.append(Pos(x, _BOTTOM + depth / 2 - 0.05, 0) * Box(size[0], size[1] + 0.1, size[2]))
    return Part(plate.cut(*cuts).clean().wrapped)


# --- Clip (coordinates of Clip_set_v3: profile in xy with the bottom face at y = 0, z across) ---

_CLIP_PROFILE = [(5.1, 0), (23.25, 0), (23.25, 6), (20.25, 6), (20.25, 4), (1.6, 4), (1.6, 3.5)]
_CLIP_HALF_WIDTH = 5.0
_POCKET = (5.1, 15.75, 2.0, 2.62)  # head pocket: x range, from y up to the top, half width
_SNAP = [(9.7, 0), (10.109, 0.7), (10.109, 1.3), (9.7, 2), (13.05, 2), (13.05, 0)]  # latch side of the window
_SNAP_HALF = 2.15  # narrowing that the neck (half width 2.2) snaps past
_PIVOT = (13.05, 2.3, (17.25, 1.0), 2.0)  # pivot part of the window: from x, half width, arc centre, radius
_TUBE_SLOT = (21.25, 2.5, (4.5, 6.0))  # tube clearance slot: centre of its rounded end at y = 0, radius, slant (dx per dy)
_NOTCH = [(8.073, 0), (6.919, 2)]  # notch edge (30 degrees), notch half width 2.0
_NOTCH_HALF = 2.0


def build_clip_native(notch: bool) -> Part:
    """One clip in the coordinates of Clip_set_v3, centred on z = 0."""
    hw = _CLIP_HALF_WIDTH
    clip = extrude(Polygon(*_CLIP_PROFILE, align=None), amount=hw, both=True)
    cuts = []
    x0, x1, y0, ph = _POCKET
    cuts.append(Pos((x0 + x1) / 2, (y0 + 4.1) / 2, 0) * Box(x1 - x0, 4.1 - y0, 2 * ph))
    # The latch side of the window, extended 0.1 beyond the bottom and the pocket for a clean cut.
    (ax, _), *latch, (bx, _), (cx_, _), (dx_, _) = _SNAP
    snap = [(ax, -0.1), (ax, 0), *latch, (bx, 2), (bx, 2.1), (cx_, 2.1), (dx_, -0.1)]
    cuts.append(extrude(Polygon(*snap, align=None), amount=_SNAP_HALF, both=True))
    px, phw, (cx, cy), cr = _PIVOT
    pivot = Pos((px + cx) / 2, 1.0) * Rectangle(cx - px, 2.2) - Pos(cx, cy) * Circle(cr)
    cuts.append(extrude(pivot, amount=phw, both=True))
    cuts.append(_tube_slot())
    if notch:
        (ax, ay), (bx, by) = _NOTCH
        k = (bx - ax) / (by - ay)
        outline = [(0, -0.1), (ax - 0.1 * k, -0.1), (bx, by), (bx, 4.1), (0, 4.1)]
        cuts.append(extrude(Polygon(*outline, align=None), amount=_NOTCH_HALF, both=True))
    return Part(clip.cut(*cuts).clean().wrapped)


def _tube_slot() -> Part:
    """Slanted slot at the hook end, so the fully opened clip clears the tube: 5 mm wide with a
    rounded end, running upward and outward."""
    gx, gr, (sx, sy) = _TUBE_SLOT
    y0, y1 = -0.1, 6.1
    x0 = gx + y0 * sx / sy
    slot = Pos(x0, 0) * Circle(gr) + Pos(x0 + 5, 0) * Rectangle(10, 2 * gr)
    base = Plane(origin=(0, y0, 0), x_dir=(1, 0, 0), z_dir=(0, 1, 0))
    n = math.hypot(sx / sy, 1.0)
    return extrude(base * slot, amount=(y1 - y0) * n, dir=(sx / sy / n, 1 / n, 0))


# --- Print layout ---

MALE_COLOR = Color(0.35, 0.75, 0.4)  # as in the published pictures
CLIP_COLOR = Color(0.4, 0.4, 0.85)
CLIP_GAP = 3.0  # mm between the parts on the bed


def _male_print(p: ConnectorParams) -> Part:
    """Male part on its mating face, the row of holes along x, centred on the origin."""
    m = build_male_native(p)
    m = Rot(-90, 0, 0) * m  # (x, y, z) -> (x, z, -y): mating face (y = -0.15) down
    return Pos(-((p.ports - 1) * p.pitch) / 2, 0, _TOP) * m


def _clip_print(notch: bool) -> Part:
    return Rot(90, 0, 0) * build_clip_native(notch)  # (x, y, z) -> (x, -z, y): flat side down


def build_print_layout(p: ConnectorParams) -> Compound:
    """Male part, and optionally a clip set beside it, in print orientation."""
    male = _male_print(p)
    male.label, male.color = "male", MALE_COLOR
    parts = [male]
    if p.clips:
        y = -_HALF_WIDTH - CLIP_GAP - _CLIP_HALF_WIDTH
        for notch in (False, True):
            clip = _clip_print(notch)
            bb = clip.bounding_box()
            clip = Pos(-(bb.min.X + bb.max.X) / 2, y, 0) * clip
            clip.label, clip.color = ("clip_notch" if notch else "clip"), CLIP_COLOR
            parts.append(clip)
            y -= 2 * _CLIP_HALF_WIDTH + CLIP_GAP
    return Compound(children=parts, label="pneumatic_connector_male")


def describe(p: ConnectorParams) -> str:
    clips = " plus a clip set (one with notch)" if p.clips else ""
    return (f"Male part, {p.ports} {'port' if p.ports == 1 else 'ports'} for 3 mm tube, ⌀{p.hole:g} mm holes "
            f"{p.pitch:g} mm apart, {plate_length(p):g} x {2 * _HALF_WIDTH:g} mm{clips}.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Male part and clips of the printable pneumatic connector (STEP)")
    ap.add_argument("--ports", type=int, default=4)
    ap.add_argument("--hole", type=float, default=3.1, help="hole diameter (mm)")
    ap.add_argument("--pitch", type=float, default=8.0, help="hole centre distance (mm)")
    ap.add_argument("--no-clips", action="store_true", help="male part only")
    ap.add_argument("--out", default="pneumatic_connector_male.step")
    a = ap.parse_args()
    p = ConnectorParams(a.ports, a.pitch, a.hole, not a.no_clips)
    export_step(build_print_layout(p), a.out)
    print(f"Wrote {a.out}: {describe(p)}")


if __name__ == "__main__":
    main()
