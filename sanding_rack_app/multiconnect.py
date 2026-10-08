"""
    Multiconnect slot back for hanging parts on Multiboard (via Multiconnect connectors).

    Geometry re-implemented in build123d from the reference OpenSCAD module
    `multiconnectSlotDesign.scad` in QuackWorks (Hands on Katie / Andy Levesque):
      * back plate 6.5 mm thick, vertical slots on a 25 mm pitch, centred on the part
      * slot cross-section: 15.3 mm opening at the back face, widening at 45 degrees
        to 20.3 mm, 4.15 mm deep, open at the bottom and rounded at the top
      * top of each slot (centre of the rounded end) 13 mm below the top of the back
      * v2 snap: a small 0.4 mm bump on both sides just below the rounded end
      * optional on-ramps: round entries every 25 mm below the top, so the part can be
        put on connectors at any height instead of only from the bottom of the slot

    Coordinates: the back face lies in the plane y = 0 and the part extends towards +y;
    x runs along the wall, z points up.
"""

from __future__ import annotations

import math

from build123d import Box, Cone, Cylinder, Part, Plane, Polygon, Pos, Rot, extrude

BACK_THICKNESS = 6.5
SLOT_PITCH = 25.0
SLOT_TOP_OFFSET = 13.0  # from the top of the back to the centre of the slot's rounded end

# Half-width of the slot as a function of depth d from the back face (mm).
_OPEN_R = 7.65  # half of the 15.3 mm opening
_WIDE_R = 10.15  # half of the 20.3 mm inner width
_TAPER_START = 0.438  # d where the 45-degree taper starts
_TAPER_END = 2.938  # d where the slot reaches full width
_DEPTH = 4.15  # total slot depth from the back face
_OUTSIDE = 0.85  # the cutting tool extends this far behind the back face

_SNAP_WIDTH = 0.4
_SNAP_LENGTH = 8.0
_RAMP_R_OUTSIDE = 12.0
_RAMP_LENGTH = 5.0


def _slot_profile(scale: float) -> Polygon:
    s = scale
    pts = [
        (-_OPEN_R * s, -_OUTSIDE),
        (-_OPEN_R * s, _TAPER_START * s),
        (-_WIDE_R * s, _TAPER_END * s),
        (-_WIDE_R * s, _DEPTH * s),
        (_WIDE_R * s, _DEPTH * s),
        (_WIDE_R * s, _TAPER_END * s),
        (_OPEN_R * s, _TAPER_START * s),
        (_OPEN_R * s, -_OUTSIDE),
    ]
    return Polygon(*pts, align=None)


def _along_y(solid: Part, y0: float) -> Part:
    """Turn a solid built along +z (centred) so it runs along +y, starting at y0."""
    height = solid.bounding_box().size.Z
    return Pos(0, y0 + height / 2, 0) * (Rot(-90, 0, 0) * solid)


def _round_top(scale: float) -> Part:
    """Solid of revolution of the slot profile around the y axis (the slot's rounded end)."""
    s = scale
    parts = [
        _along_y(Cylinder(_OPEN_R * s, _OUTSIDE + _TAPER_START * s), -_OUTSIDE),
        _along_y(Cone(_OPEN_R * s, _WIDE_R * s, (_TAPER_END - _TAPER_START) * s), _TAPER_START * s),
        _along_y(Cylinder(_WIDE_R * s, (_DEPTH - _TAPER_END) * s), _TAPER_END * s),
    ]
    return parts[0] + parts[1] + parts[2]


def slot_tool(height: float, snap: bool = True, on_ramps: bool = True, scale: float = 1.0) -> Part:
    """Cutting tool for one slot, centred on x = 0, with its rounded end centred at z = 0.

    The straight part runs down to z = -height - 1 so it opens through the bottom of a back
    that is `height` tall below the slot top.
    """
    long_slot = extrude(_slot_profile(scale), amount=height + 1, dir=(0, 0, -1))
    if snap:
        # Triangular bumps left standing in the slot: 0.4 mm wide at the slot top, tapering
        # to nothing 8 mm lower (Multiconnect v2 snap).
        for side in (1, -1):
            r = _WIDE_R * scale
            tri = Polygon((side * r, 0), (side * (r - _SNAP_WIDTH), 0), (side * r, -_SNAP_LENGTH), align=None)
            # Extruded both ways from y = 0, through the full slot depth.
            bump = extrude(Plane.XZ * tri, amount=_DEPTH * scale + 1, both=True)
            long_slot = long_slot - bump
    tool = long_slot + _round_top(scale)
    if on_ramps:
        for k in range(1, int(height // SLOT_PITCH) + 1):
            ramp = _along_y(Cone(_RAMP_R_OUTSIDE * scale, _WIDE_R * scale, _RAMP_LENGTH), -_OUTSIDE)
            tool = tool + Pos(0, 0, -k * SLOT_PITCH) * ramp
    return tool


def slot_positions(width: float, pitch: float = SLOT_PITCH) -> list[float]:
    """x positions of the slot centres on a back `width` wide (starting at x = 0), centred."""
    count = math.floor(max(width, pitch) / pitch)
    first = width / 2 - (count - 1) * pitch / 2
    return [first + i * pitch for i in range(count)]


def cut_slots(part: Part, width: float, back_height: float, snap: bool = True, on_ramps: bool = True,
              scale: float = 1.0) -> Part:
    """Cut Multiconnect slots into the back face (y = 0) of a part spanning x in [0, width]."""
    z_top = back_height - SLOT_TOP_OFFSET
    tool = slot_tool(z_top, snap=snap, on_ramps=on_ramps, scale=scale)
    for x in slot_positions(width):
        part = part - Pos(x, 0, z_top) * tool
    return part


def slot_test_piece(slots: int = 2, height: float = 40.0) -> Part:
    """A small back plate with slots, for checking the fit before printing a large part."""
    width = slots * SLOT_PITCH
    plate = Pos(width / 2, BACK_THICKNESS / 2, height / 2) * Box(width, BACK_THICKNESS, height)
    return cut_slots(plate, width, height)
