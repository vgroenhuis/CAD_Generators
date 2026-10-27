"""
    Male part, female part and clips of the 3D printed pneumatic connectors
    (https://www.printables.com/model/148215-pneumatic-connectors).

    Male part: a plate with a row of through holes for 3 mm tubes, which are glued in and stick
    out about 4 mm on the mating face. On the other face each hole has a 45-degree chamfer and a
    cross-shaped pocket that fills with glue. Both ends have a T-shaped tab (neck and head) on
    which a clip hinges; the clips hook over the lip of the female part to hold the two together.
    The defaults reproduce Male_3.1mm_4x (August 2025): 4 ports 8 mm apart, 3.1 mm holes.

    Female part (Connector_Socket__4x_3mm_4mm, October 2026): a block with a socket per port. From
    the mating face: a 3.5 mm entry for the male part's tube, a groove for a 3x1 mm O-ring
    (5 mm outer diameter), a 45-degree overhang that covers the O-ring, a 45-degree stop where the
    tube ends, a 2.8 mm passage, and at the back a socket for a 4 mm tube (4.05 mm, with a chamfer
    and a glue cross). It is printed on its mating face; the print is paused at the top of the
    grooves (ORING_PAUSE_Z) to put the O-rings in. Both ends have a lip that the clips' latches
    catch; one end also has a ridge that only the notched clip clears, so the connector closes
    one way round only.

    Clips (as in the October 2026 assembly, a refinement of Clip_set_v3): the tab's neck snaps
    into a window in the clip (a narrowing holds it), its head slides in a pocket above, and the
    far end has a hook (45-degree chamfer) that closes over the female part and a slanted slot
    that clears the tube when the clip is fully open. A set is two clips, one with a notch (and
    its head pocket running through to the hook end) that clears the female part's ridge.

    Geometry is built in the coordinates of the original SolidWorks parts (male: holes along y,
    mating face at y = -0.15; clips: profile in the xy plane, bottom face at y = 0) and then
    turned into print orientation: the male part on its mating face, the clips on their flat
    side, all with z up from z = 0.

    build_assembly() shows the connector as used: male and female part with their tubes, the O-rings,
    and the clips on the male part's tabs (the neck through the clip's window, the head in its
    pocket), positioned as in the October 2026 assembly. Each clip turns about a hinge line along
    the neck's edge on the glue-face side, where the neck enters the clip (of the lines tried,
    the one where the turning clip overlaps the tab least: the real clip also slides a little); assembly_info() gives the hinge lines, the largest opening angle before a
    clip hits the plate or a tube, and how far the male part moves out of the female part.

    Can also be run standalone:  python connector_model.py --parts male,female,clips --ports 4 --out connector_4x.step
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from build123d import (
    Axis, Box, Circle, Color, Compound, Cone, Cylinder, Line, Location, Part, Plane, Polygon, Pos, Rectangle,
    Rot, ThreePointArc, Torus, Wire, export_step, extrude, make_face, revolve,
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
    hole: float = 3.1  # male part: hole diameter for a 3 mm tube (3.1 since August 2025, was 3.0)
    clips: bool = True  # print a clip set (one plain clip, one with notch)
    back_bore: float = 4.05  # female part: socket at the back, for a 4 mm tube
    male: bool = True  # print the male part
    female: bool = True  # print the female part


def validate(p: ConnectorParams) -> None:
    if not (p.male or p.female or p.clips):
        raise ValueError("Select at least one part: male, female or clip set.")
    if not 1 <= p.ports <= 8:
        raise ValueError("The number of ports must be between 1 and 8.")
    if not 2.0 <= p.hole <= 3.6:
        raise ValueError("The hole diameter must be between 2.0 and 3.6 mm.")
    if p.pitch < _FEMALE_CROSS[0] + 1.0 or p.pitch > 30:
        raise ValueError(f"The pitch must be between {_FEMALE_CROSS[0] + 1.0:g} and 30 mm, so the glue crosses stay apart.")
    if not 2 * _PASSAGE_R + 0.1 <= p.back_bore <= 4.6:
        raise ValueError(f"The back socket diameter must be between {2 * _PASSAGE_R + 0.1:g} and 4.6 mm.")


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


def _plate_solid(length: float) -> Part:
    return extrude(Plane.XY * _plate_profile(length), amount=_HALF_WIDTH, both=True)


def build_male_native(p: ConnectorParams) -> Part:
    """Male part in the coordinates of Male_3.1mm_4x (first hole on the y axis)."""
    validate(p)
    length = plate_length(p)
    plate = _plate_solid(length) + _tab(-_END, -1) + _tab(length - _END, 1)
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
# Window: the latch side (half width 2.15, a narrowing that the neck, half width 2.2, snaps past) and
# beyond a diagonal step the pivot side (half width 2.3) ending in the clip's rounded nose.
# (Clip_set_v3 had a straight step at x = 13.05.)
_STEP = ((11.05, 2.0), (12.717, 0.0))  # the diagonal between the two
_SNAP = [(9.7, 0), (10.109, 0.7), (10.109, 1.3), (9.7, 2), _STEP[0], _STEP[1]]  # latch side of the window
_SNAP_HALF = 2.15
_PIVOT = (2.3, (17.25, 1.0), 2.0)  # pivot side of the window: half width, nose arc centre, radius
_TUBE_SLOT = (21.25, 2.5, (4.5, 6.0))  # tube clearance slot: centre of its rounded end at y = 0, radius, slant (dx per dy)
_NOTCH = [(8.073, 0), (6.919, 2)]  # notch edge (30 degrees), notch half width 2.0
_NOTCH_HALF = 2.0


def build_clip_native(notch: bool) -> Part:
    """One clip in the coordinates of Clip_set_v3, centred on z = 0. The notched clip's head
    pocket runs on to the hook end, around the female part's ridge."""
    hw = _CLIP_HALF_WIDTH
    clip = extrude(Polygon(*_CLIP_PROFILE, align=None), amount=hw, both=True)
    cuts = []
    x0, x1, y0, ph = _POCKET
    cuts.append(Pos((x0 + x1) / 2, (y0 + 4.1) / 2, 0) * Box(x1 - x0, 4.1 - y0, 2 * ph))
    # The latch side of the window, extended 0.1 beyond the bottom and the pocket for a clean cut
    # (along the diagonal step where it meets the pivot side).
    (sx0, sy0), (sx1, sy1) = _STEP
    k = (sx1 - sx0) / (sy1 - sy0)  # dx per dy along the diagonal
    (ax, _), *latch, (bx, _), _, _ = _SNAP
    snap = [(ax, -0.1), (ax, 0), *latch, (bx, 2), (bx, 2.1), (sx0 + 0.1 * k, 2.1), (sx1 - 0.1 * k, -0.1)]
    cuts.append(extrude(Polygon(*snap, align=None), amount=_SNAP_HALF, both=True))
    phw, (cx, cy), cr = _PIVOT
    pivot = Polygon((sx1 - 0.1 * k, -0.1), (cx, -0.1), (cx, 2.1), (sx0 + 0.1 * k, 2.1), align=None) - Pos(cx, cy) * Circle(cr)
    cuts.append(extrude(pivot, amount=phw, both=True))
    cuts.append(_tube_slot())
    if notch:
        (ax, ay), (bx, by) = _NOTCH
        k = (bx - ax) / (by - ay)
        outline = [(0, -0.1), (ax - 0.1 * k, -0.1), (bx, by), (bx, 4.1), (0, 4.1)]
        cuts.append(extrude(Polygon(*outline, align=None), amount=_NOTCH_HALF, both=True))
        cuts.append(Pos((x0 - 0.1) / 2, (y0 + 4.1) / 2, 0) * Box(x0 + 0.1, 4.1 - y0, 2 * ph))
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


# --- Female part (coordinates of Connector_Socket__4x_3mm_4mm: mating face at y = 0, back at y = 10.25) ---

_FEMALE_HEIGHT = 10.25
_ORING = (3.0, 1.0)  # O-ring inner diameter and cross-section
_GROOVE = (1.0, 2.5)  # O-ring groove: from y (to y + cross-section), radius
_ENTRY_R = 1.75  # entry for the male part's 3 mm tube, and above the groove
_STOP_Y = 3.8  # 45-degree stop where the male part's tube ends
_PASSAGE_R = 1.4
_BACK_Y = 4.8  # bottom of the back socket
_BACK_CHAMFER = 0.4
_FEMALE_CROSS = (6.0, 1.0, 2.0)  # glue cross on the back: arm length, arm width, depth
# Lip at each end (outward = -x, from the end face), caught by the clips' latches; half width 2.
_LIP = [(0, 0), (-1.5, 0), (-3, 2), (-3, 2.343), (-2.535, 2.747), (-1.006, 2.747), (0, 2.591)]
_LIP_HALF = 2.0
# Ridge at the left end only, which the notched clip's notch clears; half width 1.75.
_RIDGE = [(0, 5.2), (-2, 6.355), (-2, 8.0), (0, 9.155)]
_RIDGE_HALF = 1.75
ORING_PAUSE_Z = _GROOVE[0] + _ORING[1]  # print height (mating face down) at which the O-rings go in


def _socket_profile(back_r: float):
    """Half profile (x = radius, y = height from the mating face) of one socket, for revolving."""
    g0, gr = _GROOVE
    g1 = g0 + _ORING[1]
    cover = g1 + (gr - _ENTRY_R)  # the 45-degree overhang ends here
    stop = _STOP_Y + (_ENTRY_R - _PASSAGE_R)
    top = _FEMALE_HEIGHT
    pts = [
        (0, -0.1), (_ENTRY_R, -0.1), (_ENTRY_R, g0), (gr, g0), (gr, g1), (_ENTRY_R, cover), (_ENTRY_R, _STOP_Y),
        (_PASSAGE_R, stop), (_PASSAGE_R, _BACK_Y), (back_r, _BACK_Y), (back_r, top - _BACK_CHAMFER),
        (back_r + _BACK_CHAMFER + 0.1, top + 0.1), (0, top + 0.1),
    ]
    return Polygon(*pts, align=None)


def _end_feature(points, half: float, x_end: float, direction: int) -> Part:
    """A lip or ridge outline (outward = -x) at the end x_end, pointing in `direction` (-1 left, +1 right),
    reaching 0.1 into the body so it fuses cleanly."""
    inner = [(0.1, points[0][1]), *points, (0.1, points[-1][1])]
    pts = [(x_end - direction * x, y) for x, y in inner]
    return extrude(Polygon(*pts, align=None), amount=half, both=True)


def build_female_native(p: ConnectorParams) -> Part:
    """Female part in the coordinates of Connector_Socket__4x_3mm_4mm (first socket on the y axis)."""
    validate(p)
    length = plate_length(p)
    x0, x1 = -_END, length - _END
    body = Pos((x0 + x1) / 2, _FEMALE_HEIGHT / 2, 0) * Box(length, _FEMALE_HEIGHT, 2 * _HALF_WIDTH)
    body += _end_feature(_LIP, _LIP_HALF, x0, -1) + _end_feature(_LIP, _LIP_HALF, x1, 1)
    body += _end_feature(_RIDGE, _RIDGE_HALF, x0, -1)
    socket = revolve(_socket_profile(p.back_bore / 2), Axis.Y)
    arm, arm_w, depth = _FEMALE_CROSS
    cuts = []
    for i in range(p.ports):
        x = i * p.pitch
        cuts.append(Pos(x, 0, 0) * socket)
        for size in ((arm, depth, arm_w), (arm_w, depth, arm)):
            cuts.append(Pos(x, _FEMALE_HEIGHT - depth / 2 + 0.05, 0) * Box(size[0], size[1] + 0.1, size[2]))
    return Part(body.cut(*cuts).clean().wrapped)


# --- Print layout ---

MALE_COLOR = Color(0.35, 0.75, 0.4)  # as in the published pictures
FEMALE_COLOR = Color(0.75, 0.55, 0.4)
CLIP_COLOR = Color(0.4, 0.4, 0.85)
ORING_COLOR = Color(0.12, 0.12, 0.12)
CLIP_GAP = 3.0  # mm between the parts on the bed


def _male_print(p: ConnectorParams) -> Part:
    """Male part on its mating face, the row of holes along x, centred on the origin."""
    m = build_male_native(p)
    m = Rot(-90, 0, 0) * m  # (x, y, z) -> (x, z, -y): mating face (y = -0.15) down
    return Pos(-((p.ports - 1) * p.pitch) / 2, 0, _TOP) * m


def _clip_print(notch: bool) -> Part:
    return Rot(90, 0, 0) * build_clip_native(notch)  # (x, y, z) -> (x, -z, y): flat side down


def build_print_layout(p: ConnectorParams) -> Compound:
    """The selected parts in print orientation, side by side on the bed (CLIP_GAP apart, each
    centred on x = 0): the female part on its mating face, the male part on its mating face,
    and the two clips lying flat."""
    parts = []
    if p.female:
        female = Part((Pos(-_row_centre(p), 0, 0) * Rot(90, 0, 0) * build_female_native(p)).wrapped)  # (x, y, z) -> (x, -z, y)
        female.label, female.color = "female", FEMALE_COLOR
        parts.append(female)
    if p.male:
        male = _male_print(p)
        male.label, male.color = "male", MALE_COLOR
        parts.append(male)
    if p.clips:
        for notch in (False, True):
            clip = _clip_print(notch)
            bb = clip.bounding_box()
            clip = Pos(-(bb.min.X + bb.max.X) / 2, 0, 0) * clip
            clip.label, clip.color = ("clip_notch" if notch else "clip"), CLIP_COLOR
            parts.append(clip)
    # Stack the parts along -y, then centre the whole layout on y = 0.
    placed, y = [], 0.0
    for part in parts:
        bb = part.bounding_box()
        part = Pos(0, y - bb.max.Y, 0) * part
        y -= bb.max.Y - bb.min.Y + CLIP_GAP
        placed.append(part)
    shift = -(y + CLIP_GAP) / 2
    for part in placed:
        part.position += (0, shift, 0)
    return Compound(children=placed, label="pneumatic_connector")


# --- Assembly (male part with tubes, clips on its tabs, female part with tubes and O-rings) ---

TUBE_BORES = {3.0: 2.0, 4.0: 2.5}  # tube outer diameter -> inner diameter (mm)
TUBE_OD = 3.0  # the male part's tube
BACK_TUBE_OD = 4.0  # the tube in the female part's back socket
TUBE_COLOR = Color(0.75, 0.77, 0.8)
TUBE_OUT = 4.0  # tube length beyond the mating face
TUBE_BELOW = 12.0  # tube length shown beyond the glue face / the female part's back
INSERT_TRAVEL = 12.0  # how far the male part is pulled out of the female part in the animation
_CLIP_CLEARANCE = 0.1  # closed clip's bottom face to the plate end (October 2026 assembly)
_CLIP_SEAT = 13.25  # clip x at the male part's mating face (y = _TOP) when closed


def _row_centre(p: ConnectorParams) -> float:
    return (p.ports - 1) * p.pitch / 2


def _left_clip_location() -> Location:
    """Closed left clip in the male part's frame: clip x runs down along the tab (hook end up,
    over the female part), clip y runs outward along the neck."""
    origin = (-_END - _CLIP_CLEARANCE, _TOP + _CLIP_SEAT, 0)
    return Location(Plane(origin=origin, x_dir=(0, -1, 0), z_dir=(0, 0, -1)))


def _left_pivot() -> tuple[float, float]:
    """Hinge line of the left clip (along z) in the male part's frame: the neck's edge on the
    glue-face side, at the clip's bottom face."""
    return (-_END - _CLIP_CLEARANCE, _TOP - _NECK[1])


def _to_assembly(p: ConnectorParams):
    """Male frame -> assembly frame: tubes vertical (z up), mating face at z = 0, row centred on x = 0."""
    return Pos(-_row_centre(p), 0, -_TOP) * Rot(90, 0, 0)  # (x, y, z) -> (x, -z, y)


def _tubes(p: ConnectorParams, od: float, y_from: float, y_to: float) -> Part:
    length = y_to - y_from
    tube = Cylinder(od / 2, length) - Cylinder(TUBE_BORES[od] / 2, length + 0.2)
    return Part(Compound(children=[
        Pos(i * p.pitch, (y_from + y_to) / 2, 0) * Rot(90, 0, 0) * tube for i in range(p.ports)
    ]).wrapped)


def _female_parts(p: ConnectorParams) -> dict[str, Part]:
    """Female part, its tubes and the O-rings, in the male part's frame (connected)."""
    oring_id, cs = _ORING
    oring = Rot(90, 0, 0) * Torus((oring_id + cs) / 2, cs / 2)
    y = _GROOVE[0] + cs / 2
    return {
        "female": build_female_native(p),
        "female_tubes": _tubes(p, BACK_TUBE_OD, _BACK_Y, _FEMALE_HEIGHT + TUBE_BELOW),
        "orings": Part(Compound(children=[Pos(i * p.pitch, y, 0) * oring for i in range(p.ports)]).wrapped),
    }


def _assembly_parts(p: ConnectorParams, angle_left: float = 0.0, angle_right: float = 0.0) -> dict[str, Part]:
    """Male part, tubes and clips in the male part's frame, the clips opened by the given angles."""
    xc = _row_centre(p)
    px, py = _left_pivot()
    left = Pos(px, py, 0) * Rot(0, 0, angle_left) * Pos(-px, -py, 0) * _left_clip_location()
    # The right clip is the left one turned half a turn about the row's centre line (y axis).
    right = Pos(2 * xc, 0, 0) * Rot(0, 180, 0) * Pos(px, py, 0) * Rot(0, 0, angle_right) * Pos(-px, -py, 0) * _left_clip_location()
    # The notched clip goes on the left, the end with the female part's ridge.
    return {
        "male": build_male_native(p),
        "tubes": _tubes(p, TUBE_OD, _BOTTOM - TUBE_BELOW, _TOP + TUBE_OUT),
        "clip_left": left * build_clip_native(True),
        "clip_right": right * build_clip_native(False),
    }


MOVING_PARTS = ("male", "tubes", "clip_left", "clip_right")  # what moves when the male part is pulled out


def build_assembly(p: ConnectorParams) -> Compound:
    """The connected connector, clips closed, in the assembly frame (see _to_assembly)."""
    colors = {
        "male": MALE_COLOR, "tubes": TUBE_COLOR, "clip_left": CLIP_COLOR, "clip_right": CLIP_COLOR,
        "female": FEMALE_COLOR, "female_tubes": TUBE_COLOR, "orings": ORING_COLOR,
    }
    to_asm = _to_assembly(p)
    children = []
    for name, part in {**_assembly_parts(p), **_female_parts(p)}.items():
        part = Part((to_asm * part).wrapped)
        part.label, part.color = name, colors[name]
        children.append(part)
    return Compound(children=children, label="pneumatic_connector_assembly")


def _common_volume(a: Part, b: Part) -> float:
    """Volume shared by two shapes. (OCP directly: build123d's intersect() returns None for
    these located parts.)"""
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(BRepAlgoAPI_Common(a.wrapped, b.wrapped).Shape(), props)
    return props.Mass()


def max_opening(p: ConnectorParams, limit: float = 90.0, tolerance: float = 0.5) -> float:
    """Largest opening angle (degrees) before the left clip hits the plate or a tube."""
    parts = _assembly_parts(p)
    obstacles = _plate_solid(plate_length(p)) + parts["tubes"]
    px, py = _left_pivot()
    clip = _left_clip_location() * build_clip_native(True)

    def hits(angle: float) -> bool:
        turned = Pos(px, py, 0) * Rot(0, 0, angle) * Pos(-px, -py, 0) * clip
        return _common_volume(turned, obstacles) > 0.01

    lo, hi = 0.0, limit
    if not hits(hi):
        return hi
    while hi - lo > tolerance:
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if hits(mid) else (mid, hi)
    return lo


def assembly_info(p: ConnectorParams) -> dict:
    """Hinge lines of the clips in the assembly frame (mm), and how far they open."""
    px, py = _left_pivot()
    to_asm = _to_assembly(p)
    xc = _row_centre(p)
    hinges = {}
    # Opening turns the left clip about +z of the male frame (hook end outward), the right one about -z;
    # (x, y, z) -> (x, -z, y) takes those directions into the assembly frame.
    for name, x, (ax, ay, az) in (("clip_left", px, (0, 0, 1)), ("clip_right", 2 * xc - px, (0, 0, -1))):
        pt = (to_asm * Pos(x, py, 0)).position
        hinges[name] = {"point": [round(v, 4) for v in pt], "axis": [ax, -az, ay]}
    # Pulling the male part out moves it along -y of the male frame: -z in the assembly frame.
    return {
        "hinges": hinges, "max_angle": round(max_opening(p), 1),
        "insert": {"parts": list(MOVING_PARTS), "direction": [0, 0, -1], "travel": INSERT_TRAVEL},
    }


def describe(p: ConnectorParams) -> str:
    """One sentence per selected part."""
    n = f"{p.ports} {'port' if p.ports == 1 else 'ports'} {p.pitch:g} mm apart"
    out = []
    if p.male:
        out.append(f"Male part: {n}, \u2300{p.hole:g} mm holes for 3 mm tube, {plate_length(p):g} x {2 * _HALF_WIDTH:g} mm.")
    if p.female:
        out.append(
            f"Female part: {n}, \u2300{p.back_bore:g} mm socket at the back, "
            f"{plate_length(p):g} x {2 * _HALF_WIDTH:g} x {_FEMALE_HEIGHT:g} mm. Needs {p.ports} O-ring"
            f"{'s' if p.ports > 1 else ''} {_ORING[0]:g}x{_ORING[1]:g} mm: pause the print at Z = {ORING_PAUSE_Z:g} mm "
            "(before the first layer above it) and press them into the grooves."
        )
    if p.clips:
        out.append("Clip set: one plain clip and one with a notch (it goes on the end with the female part's ridge).")
    return " ".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Male part and clips of the printable pneumatic connector (STEP)")
    ap.add_argument("--ports", type=int, default=4)
    ap.add_argument("--hole", type=float, default=3.1, help="hole diameter (mm)")
    ap.add_argument("--pitch", type=float, default=8.0, help="hole centre distance (mm)")
    ap.add_argument("--parts", default="male,female,clips", help="comma-separated: male, female, clips")
    ap.add_argument("--back-bore", type=float, default=4.05, help="female part: back socket diameter (mm)")
    ap.add_argument("--out", default="pneumatic_connector.step")
    a = ap.parse_args()
    parts = {s.strip() for s in a.parts.split(",") if s.strip()}
    if parts - {"male", "female", "clips"}:
        ap.error("--parts takes male, female and/or clips")
    p = ConnectorParams(a.ports, a.pitch, a.hole, "clips" in parts, a.back_bore, "male" in parts, "female" in parts)
    export_step(build_print_layout(p), a.out)
    print(f"Wrote {a.out}: {describe(p)}")


if __name__ == "__main__":
    main()
