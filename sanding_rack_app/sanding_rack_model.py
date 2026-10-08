"""
    Wall rack for round sanding discs, hanging on Multiboard via Multiconnect.

    The discs stand on edge, like books on a shelf, in a tray that hangs on the wall.
    Each grit gets its own compartment between movable dividers: the tray floor and
    back wall have a row of grooves (default every 5 mm) and a divider drops into any
    groove, so compartments can shrink as a stack is used up and grow when new paper
    arrives. Grit labels are separate clips that slide along the front lip.

    Parts (all print without supports):
      * tray     - print upright (floor on the bed); one or more, side by side on the board
      * divider  - print flat
      * labels   - one clip per grit; print on its side

    The layout planner sizes each compartment from the number of discs, places the
    dividers on grooves and spreads the grits over as many trays as needed.

    Can also be run standalone:
        python sanding_rack_model.py --out-dir rack
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

from build123d import (
    Box, Color, Compound, Cylinder, Part, Plane, Polygon, Pos, Rot, export_step, extrude,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import multiconnect  # noqa: E402
from cad_common.text import MIN_STROKE, min_font_size, printable_text  # noqa: E402

GRID = 25.0  # Multiboard grid

DEFAULT_GRITS = (
    "P40:50, P60:50, P80:50, P100:30, P120:50, P150:20, P180:50, P220:20, P240:30, P280:10, "
    "P320:20, P400:10, P500:5, P600:10, P800:5, P1000:5, P1200:3, P1500:3, P2000:3, P3000:3"
)


@dataclass
class RackParams:
    disc_diameter: float = 150.0
    disc_thickness: float = 1.0
    stack_slack: float = 1.1  # stacks are a little looser than count x thickness
    compartment_clearance: float = 3.0  # extra room per compartment for grabbing a disc
    tray_units: int = 9  # tray width in 25 mm Multiboard units (9 -> 224.6 mm)
    back_height: float = 100.0
    lip_height: float = 25.0  # front lip, above the floor; the cradle is 5 mm less deep
    wall: float = 3.0  # side walls and front lip
    floor: float = 4.0  # below the lowest point of the cradle
    cradle_clearance: float = 1.5  # cradle radius = disc radius + this
    divider_thickness: float = 2.0
    groove_pitch: float = 5.0
    groove_depth: float = 1.5
    groove_clearance: float = 0.4  # groove width = divider thickness + this
    label_width: float = 8.0  # label clips; compartments are made at least this wide
    slot_scale: float = 1.0  # Multiconnect slot tolerance (1.0 = reference size)


@dataclass
class Grit:
    name: str
    count: int


# The layout planner works as seen from the front: x = 0 at the left end of a tray, grooves
# numbered from the left, tray 1 on the left. The parts themselves are built with their back
# face at y = 0 and the front towards +y, which puts +x on the viewer's left, so build_rack
# mirrors the planned positions.


@dataclass
class Placement:
    grit: Grit
    x0: float  # compartment start (inner face of a wall or divider), from the left as seen from the front
    x1: float  # compartment end


@dataclass
class TrayLayout:
    compartments: list[Placement] = field(default_factory=list)
    divider_grooves: list[int] = field(default_factory=list)  # groove index of each divider
    free: float = 0.0  # unused width at the right end (mm)


def parse_grits(text: str) -> list[Grit]:
    """Parse 'P40:50, P60:12, ...' into grits; the count is the number of discs."""
    grits = []
    for item in text.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        name, sep, count = item.rpartition(":")
        if not sep or not name.strip():
            raise ValueError(f"'{item}': use grit:count, e.g. P120:50.")
        try:
            n = int(count)
        except ValueError:
            raise ValueError(f"'{item}': the count must be a whole number.") from None
        if n < 0:
            raise ValueError(f"'{item}': the count cannot be negative.")
        if any(g.name == name.strip() for g in grits):
            raise ValueError(f"{name.strip()} is listed twice; each grit can only be listed once.")
        grits.append(Grit(name.strip(), n))
    if not grits:
        raise ValueError("Enter at least one grit.")
    return grits


# ---------------------------------------------------------------- dimensions

def tray_width(p: RackParams) -> float:
    return p.tray_units * GRID - 0.4  # 0.4 mm gap so neighbouring trays fit on the grid


def back_thickness(p: RackParams) -> float:
    # Multiconnect back plus a layer in front of it for the divider grooves.
    return multiconnect.BACK_THICKNESS + p.groove_depth + 1.0


def inner_depth(p: RackParams) -> float:
    return p.disc_diameter + 4.0


def tray_depth(p: RackParams) -> float:
    return back_thickness(p) + inner_depth(p) + p.wall


# The floor is a cradle: a cylinder segment (axis along x) that matches the discs, so they
# rest in it instead of on one point. It rises up to cradle_top, 5 mm below the top of the
# front lip (room for the label clips' hook); towards the back wall and the lip it ends in
# short flat ledges at that height.

def cradle_radius(p: RackParams) -> float:
    return p.disc_diameter / 2 + p.cradle_clearance


def cradle_centre(p: RackParams) -> tuple[float, float]:
    """(y, z) of the cradle axis: centred between back wall and lip, lowest point on the floor."""
    lip_y = tray_depth(p) - p.wall
    return (back_thickness(p) + lip_y) / 2, p.floor + cradle_radius(p)


def cradle_top(p: RackParams) -> float:
    return p.floor + p.lip_height - 5.0


def _below_cradle(p: RackParams, offset: float, x0: float, x1: float, y0: float, y1: float) -> Part:
    """Everything up to the cradle surface moved up by `offset` (negative = down), within
    x0..x1 and y0..y1: the arc, capped by the flat ledges at cradle_top + offset."""
    yc, zc = cradle_centre(p)
    z_top = cradle_top(p) + offset
    block = Pos((x0 + x1) / 2, (y0 + y1) / 2, (z_top - 1) / 2) * Box(x1 - x0, y1 - y0, z_top + 1)
    hollow = Pos((x0 + x1) / 2, yc, zc) * (Rot(0, 90, 0) * Cylinder(cradle_radius(p) - offset, x1 - x0 + 2))
    return block - hollow


def groove_positions(p: RackParams) -> list[float]:
    """x centres of the divider grooves, centred in the tray, at least 3 mm from the walls."""
    w = tray_width(p)
    inner = w - 2 * p.wall - 2 * 3.0
    n = math.floor(inner / p.groove_pitch) + 1
    first = w / 2 - (n - 1) * p.groove_pitch / 2
    return [first + i * p.groove_pitch for i in range(n)]


def compartment_width(g: Grit, p: RackParams) -> float:
    stack = g.count * p.disc_thickness * p.stack_slack + p.compartment_clearance
    # Room for a label clip: it may reach to the middle of a divider, and must stay 0.3 mm
    # clear of a side wall (see label_centre), leaving gaps between neighbouring labels.
    return max(stack, p.label_width + 0.8 - p.divider_thickness / 2)


def label_centre(t: TrayLayout, i: int, p: RackParams) -> float:
    """x centre of the label of compartment i: centred between the neighbouring divider
    centres, or 0.3 mm in from a side wall."""
    c = t.compartments[i]
    half = p.divider_thickness / 2
    a = c.x0 - half if i > 0 else c.x0 + 0.3
    b = c.x1 + half if i < len(t.compartments) - 1 else c.x1 - 0.3
    return (a + b) / 2


def validate(p: RackParams) -> None:
    if p.tray_units < 2:
        raise ValueError("A tray must be at least 2 Multiboard units (50 mm) wide.")
    if min(p.disc_diameter, p.disc_thickness, p.back_height, p.lip_height, p.wall, p.floor,
           p.divider_thickness, p.groove_pitch, p.groove_depth, p.label_width) <= 0:
        raise ValueError("All dimensions must be greater than 0.")
    if p.back_height < 40:
        raise ValueError("The back must be at least 40 mm tall for the Multiconnect slots.")
    if p.label_width - 2.5 < min_font_size():
        raise ValueError(f"Labels must be at least {min_font_size() + 2.5:.1f} mm wide for printable text.")
    if p.groove_pitch < p.divider_thickness + p.groove_clearance + 1.0:
        raise ValueError("Groove pitch too small for the divider thickness.")
    if p.floor <= p.groove_depth + 1.0:
        raise ValueError("The floor must be at least 1 mm thicker than the groove depth.")
    if p.lip_height < 10:
        raise ValueError("The front lip must be at least 10 mm high.")
    if p.floor + p.lip_height > p.back_height - 10:
        raise ValueError("The front lip must be at least 10 mm lower than the back.")
    if p.lip_height - 5 >= cradle_radius(p):
        raise ValueError("The front lip is too high for the disc size (the cradle would pass its middle).")
    if p.cradle_clearance < 0:
        raise ValueError("The cradle clearance cannot be negative.")


# ---------------------------------------------------------------- layout planner

def plan_layout(grits: list[Grit], p: RackParams) -> list[TrayLayout]:
    """Fill trays left to right; each compartment is at least as wide as its stack needs.

    The first compartment of a tray starts at the left wall; each later compartment starts
    after a divider placed in the first groove that leaves enough room before it. A grit
    that does not fit in the rest of a tray starts the next tray.
    """
    validate(p)
    for g in grits:
        label_font_size(g.name, p)  # rejects names that do not fit on a label
    w = tray_width(p)
    grooves = groove_positions(p)
    half = p.divider_thickness / 2
    trays: list[TrayLayout] = []
    tray = TrayLayout()
    x = p.wall  # start of the next compartment
    for g in grits:
        need = compartment_width(g, p)
        if need > w - 2 * p.wall:
            raise ValueError(f"{g.name}: {g.count} discs need {need:.0f} mm, more than one tray; use wider trays.")
        while True:
            if not tray.compartments:
                x = p.wall
            end = x + need
            if end <= w - p.wall:
                tray.compartments.append(Placement(g, x, end))
                # Divider after this compartment, unless it is the last one that fits.
                k = next((i for i, gx in enumerate(grooves) if gx - half >= end), None)
                tray.divider_grooves.append(k if k is not None else -1)
                x = grooves[k] + half if k is not None else w
                break
            trays.append(tray)
            tray = TrayLayout()
    trays.append(tray)
    for t in trays:
        # The last compartment of each tray runs to the right wall: no divider needed there.
        if t.divider_grooves:
            t.divider_grooves.pop()
        last = t.compartments[-1]
        t.free = (w - p.wall) - last.x1
        last.x1 = w - p.wall
    return trays


def describe_layout(trays: list[TrayLayout], p: RackParams) -> str:
    lines = [f"{len(trays)} tray(s) of {p.tray_units} x 25 mm, "
             f"{sum(len(t.divider_grooves) for t in trays)} dividers, groove pitch {p.groove_pitch:g} mm"]
    for i, t in enumerate(trays, 1):
        names = ", ".join(f"{c.grit.name} ({c.grit.count})" for c in t.compartments)
        lines.append(f"Tray {i}: {names}; dividers in grooves {[k + 1 for k in t.divider_grooves]}; "
                     f"{t.free:.0f} mm spare")
    return "\n".join(lines)


# ---------------------------------------------------------------- parts

def _yz_profile(points: list[tuple[float, float]], x0: float, thickness: float) -> Part:
    """Prism from a (y, z) outline, from x0 to x0 + thickness."""
    face = Plane.YZ * Polygon(*points, align=None)
    return Pos(x0, 0, 0) * extrude(face, amount=thickness, dir=(1, 0, 0))


def _side_profile(p: RackParams) -> list[tuple[float, float]]:
    d, tb = tray_depth(p), back_thickness(p)
    return [(0, 0), (d, 0), (d, p.floor + p.lip_height), (tb, p.back_height), (0, p.back_height)]


def build_tray(p: RackParams) -> Part:
    validate(p)
    w, d, tb = tray_width(p), tray_depth(p), back_thickness(p)
    lip_y = d - p.wall
    tray = Pos(w / 2, tb / 2, p.back_height / 2) * Box(w, tb, p.back_height)
    tray += Pos(w / 2, d / 2, p.floor / 2) * Box(w, d, p.floor)
    tray += Pos(w / 2, lip_y + p.wall / 2, (p.floor + p.lip_height) / 2) * Box(w, p.wall, p.floor + p.lip_height)
    tray += _below_cradle(p, 0.0, 0, w, tb - 0.01, lip_y + 0.01)  # the cradle floor
    tray += _yz_profile(_side_profile(p), 0, p.wall)
    tray += _yz_profile(_side_profile(p), w - p.wall, p.wall)

    # Grooves: a band of constant depth under the cradle surface (continuing a little into
    # the back wall, where it meets the back grooves), cut where the dividers can go.
    gw, gd = p.divider_thickness + p.groove_clearance, p.groove_depth
    band = _below_cradle(p, 0.0, 0, w, tb - gd, lip_y) - _below_cradle(p, -gd, -1, w + 1, tb - gd - 1, lip_y + 1)
    slots = [Pos(x, d / 2, p.back_height / 2) * Box(gw, d, p.back_height) for x in groove_positions(p)]
    tray -= band & Compound(slots)
    back_z0 = cradle_top(p) - gd
    back_len = p.back_height - back_z0 + 1
    for x in groove_positions(p):
        tray -= Pos(x, tb - gd / 2, back_z0 + back_len / 2) * Box(gw, gd + 0.01, back_len)

    return multiconnect.cut_slots(tray, w, p.back_height, scale=p.slot_scale)


def _divider_profile(p: RackParams) -> list[tuple[float, float]]:
    tb, lip_y = back_thickness(p), tray_depth(p) - p.wall
    y_back = tb - p.groove_depth + 0.1  # sits in the back groove
    y_front = lip_y - 2.0  # stops short of the lip, leaving room for the label clips
    z_front_top = p.floor + p.lip_height + 8.0  # finger tab above the lip
    # The bottom edge is cut to the cradle shape by build_divider.
    return [(y_back, 0), (y_front, 0), (y_front, z_front_top), (y_back, p.back_height - 2.0)]


def build_divider(p: RackParams) -> Part:
    """Divider in its installed orientation, centred on x = 0. Its bottom edge follows the
    cradle, sitting in the floor groove with 0.1 mm to spare."""
    t = p.divider_thickness
    blank = _yz_profile(_divider_profile(p), -t / 2, t)
    bb = blank.bounding_box()
    return blank - _below_cradle(p, -p.groove_depth + 0.1, -t, t, bb.min.Y - 1, bb.max.Y + 1)


def _label_profile(p: RackParams) -> list[tuple[float, float]]:
    d = tray_depth(p)
    lip_in, lip_out, z_top = d - p.wall, d, p.floor + p.lip_height
    c, t = 0.25, 1.6
    return [
        (lip_in - c - 1.2, z_top - 4.0), (lip_in - c, z_top - 4.0), (lip_in - c, z_top + c),
        (lip_out + c, z_top + c), (lip_out + c, z_top - 22.0), (lip_out + c + t, z_top - 22.0),
        (lip_out + c + t, z_top + c + t), (lip_in - c - 1.2, z_top + c + t),
    ]


_LABEL_TEXT_LENGTH = 19.0  # mm available along the label's 22 mm tall front face


def label_font_size(name: str, p: RackParams) -> float:
    """Font size for a grit label: as large as the label allows, shrunk for long names,
    but never so small that the strokes get thinner than MIN_STROKE (then it is an error)."""
    font = min(p.label_width - 2.5, 6.0)
    length = printable_text(name, font).bounding_box().size.X
    if length > _LABEL_TEXT_LENGTH:
        font *= _LABEL_TEXT_LENGTH / length
    if font < min_font_size():
        raise ValueError(
            f"Label '{name}' is too long to print with lines of at least {MIN_STROKE:g} mm; "
            "use a shorter name or wider labels."
        )
    return font


LABEL_CLIP_COLOR = Color(0.95, 0.75, 0.2)
LABEL_TEXT_COLOR = Color(0.07, 0.07, 0.07)


def build_label(name: str, p: RackParams) -> Compound:
    """Label clip that hooks over the front lip, centred on x = 0, with the grit text
    standing out 0.6 mm from its front face, reading upwards.

    The clip and the text are separate bodies ("clip" and "text"), so the text can be
    printed in a second colour."""
    wl = p.label_width
    clip = _yz_profile(_label_profile(p), -wl / 2, wl)
    d = tray_depth(p)
    y_face = d + 0.25 + 1.6
    z_mid = p.floor + p.lip_height - 22.0 / 2 + 1.0
    font = label_font_size(name, p)
    # On the front face (normal +y), reading upwards: text x -> +z, text up -> +x.
    face_plane = Plane(origin=(0, y_face, z_mid), x_dir=(0, 0, 1), z_dir=(0, 1, 0))
    raised = extrude(face_plane * printable_text(name, font), amount=0.6)
    clip.label, clip.color = "clip", LABEL_CLIP_COLOR
    raised.label, raised.color = "text", LABEL_TEXT_COLOR
    return Compound(children=[clip, raised], label=f"label {name}")


# ---------------------------------------------------------------- assembly / export

@dataclass
class RackModel:
    trays: list[TrayLayout]
    tray: Part
    divider: Part
    labels: dict[str, Compound]  # per grit: the clip and the text as two bodies
    assembly: Compound


def build_rack(grits: list[Grit], p: RackParams, discs: bool = True) -> RackModel:
    """Build the parts and an assembly of all trays side by side, as on the board."""
    layout = plan_layout(grits, p)
    tray, divider = build_tray(p), build_divider(p)
    labels = {g.name: build_label(g.name, p) for g in grits}
    grooves = groove_positions(p)
    w = tray_width(p)
    children = []
    for i, t in enumerate(layout):
        # Mirror from front-view coordinates (see Placement) to model coordinates.
        x_off = (len(layout) - 1 - i) * p.tray_units * GRID
        def model_x(u: float) -> float:
            return x_off + w - u
        tr = Pos(x_off, 0, 0) * tray
        tr.label, tr.color = f"tray {i + 1}", Color(0.85, 0.85, 0.85)
        children.append(tr)
        for k in t.divider_grooves:
            dv = Pos(model_x(grooves[k]), 0, 0) * divider
            dv.label, dv.color = "divider", Color(0.35, 0.55, 0.8)
            children.append(dv)
        for j, c in enumerate(t.compartments):
            lb = Pos(model_x(label_centre(t, j, p)), 0, 0) * labels[c.grit.name]
            lb.label = f"label {c.grit.name}"  # keeps its two coloured bodies
            children.append(lb)
            if discs and c.grit.count:
                stack = c.grit.count * p.disc_thickness
                r = p.disc_diameter / 2
                cyl = Rot(0, 90, 0) * Cylinder(r, stack)
                # In the cradle, 0.5 mm clear of its lowest line (an exactly tangent preview disc
                # trips up boolean checks on the assembly).
                yc, _ = cradle_centre(p)
                disc = Pos(model_x(c.x0 + 0.5 + stack / 2), yc, p.floor + r + 0.5) * cyl
                disc.label, disc.color = f"discs {c.grit.name}", Color(0.55, 0.35, 0.2, 0.6)
                children.append(disc)
    return RackModel(layout, tray, divider, labels, Compound(children=children, label="sanding_rack"))


def print_parts(model: RackModel) -> dict[str, Part]:
    """Parts in print orientation, on z = 0."""
    out = {"tray": model.tray}
    dv = Rot(0, 90, 0) * model.divider  # lie flat
    out["divider"] = Pos(0, 0, -dv.bounding_box().min.Z) * dv
    for name, lb in model.labels.items():
        lb = Rot(0, 90, 0) * lb  # on its side: the clip profile prints without supports
        out[f"label_{name}"] = Pos(0, 0, -lb.bounding_box().min.Z) * lb
    return out


def main() -> None:
    d = RackParams()
    ap = argparse.ArgumentParser(description="Multiboard (Multiconnect) wall rack for round sanding discs")
    ap.add_argument("--grits", default=DEFAULT_GRITS, help="grit:count list, e.g. 'P80:50, P120:12'")
    ap.add_argument("--disc-diameter", type=float, default=d.disc_diameter)
    ap.add_argument("--disc-thickness", type=float, default=d.disc_thickness)
    ap.add_argument("--tray-units", type=int, default=d.tray_units, help="tray width in 25 mm units")
    ap.add_argument("--back-height", type=float, default=d.back_height)
    ap.add_argument("--lip-height", type=float, default=d.lip_height, help="front lip height (mm)")
    ap.add_argument("--groove-pitch", type=float, default=d.groove_pitch)
    ap.add_argument("--slot-scale", type=float, default=d.slot_scale, help="Multiconnect slot tolerance")
    ap.add_argument("--out-dir", default="sanding_rack")
    ap.add_argument("--slot-test", action="store_true", help="also export a small slot test piece")
    a = ap.parse_args()
    p = RackParams(disc_diameter=a.disc_diameter, disc_thickness=a.disc_thickness, tray_units=a.tray_units,
                   back_height=a.back_height, lip_height=a.lip_height, groove_pitch=a.groove_pitch,
                   slot_scale=a.slot_scale)
    model = build_rack(parse_grits(a.grits), p)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    export_step(model.assembly, str(out / "assembly.step"))
    for name, part in print_parts(model).items():
        export_step(part, str(out / f"{name}.step"))
    if a.slot_test:
        export_step(multiconnect.slot_test_piece(scale=p.slot_scale), str(out / "slot_test.step"))
    print(describe_layout(model.trays, p))
    print(f"Wrote parts to {out}/ (print the tray {len(model.trays)}x, "
          f"the divider {sum(len(t.divider_grooves) for t in model.trays)}x)")


if __name__ == "__main__":
    main()
