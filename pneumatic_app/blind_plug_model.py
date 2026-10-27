"""
    Blind plug for a push-in pneumatic fitting: a solid pin that is pushed into the fitting
    instead of a tube, closing that port.

    Profile (revolved about the axis), from the tip up:
      * a chamfered tip, so the pin slides past the fitting's O-ring
      * the pin, with the outer diameter of the tube it replaces
      * a 45-degree collar up to the head diameter, which stops the pin at the insertion depth
      * a cylindrical head to grip it by (pulled out after pressing the fitting's release ring)

    The presets reproduce the plugs used in the lab (Blind1_4mm and Blind1_6mm STEP files):
      4 mm: tip chamfer 0.6, insertion length 20, head diameter 8, head length 2 (24 long)
      6 mm: tip chamfer 1.0, insertion length 20, head diameter 10, head length 3 (25 long)

    The plug is built in print orientation: standing on its flat head (z = 0), tip up, so
    nothing needs support. Several plugs are laid out in a square grid.

    Can also be run standalone:  python blind_plug_model.py --preset 6 --count 4 --out plugs.step
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, replace

from build123d import Axis, Compound, Part, Plane, Polygon, Pos, export_step, revolve

GRID_SPACING = 3.0  # mm between neighbouring plugs
MAX_COUNT = 50


@dataclass
class BlindPlugParams:
    tube_od: float = 4.0  # pin diameter = outer diameter of the tube it replaces
    insert_length: float = 20.0  # from the tip to where the collar starts
    tip_chamfer: float = 0.6  # 45-degree chamfer on the tip
    head_diameter: float = 8.0
    head_length: float = 2.0  # cylindrical part of the head, beyond the 45-degree collar
    count: int = 1  # plugs in the print file


PRESETS = {
    "4": BlindPlugParams(),
    "6": BlindPlugParams(tube_od=6.0, tip_chamfer=1.0, head_diameter=10.0, head_length=3.0),
}


def collar_length(p: BlindPlugParams) -> float:
    """Axial length of the 45-degree collar between the pin and the head."""
    return (p.head_diameter - p.tube_od) / 2


def total_length(p: BlindPlugParams) -> float:
    return p.insert_length + collar_length(p) + p.head_length


def validate(p: BlindPlugParams) -> None:
    if p.tube_od <= 0 or p.insert_length <= 0 or p.head_length <= 0:
        raise ValueError("Tube diameter, insertion length and head length must be greater than 0.")
    if p.head_diameter <= p.tube_od:
        raise ValueError("The head diameter must be larger than the tube diameter.")
    if not 0 <= p.tip_chamfer < p.tube_od / 2:
        raise ValueError("The tip chamfer must be at least 0 and less than half the tube diameter.")
    if p.tip_chamfer >= p.insert_length:
        raise ValueError("The tip chamfer must be shorter than the insertion length.")
    if not 1 <= p.count <= MAX_COUNT:
        raise ValueError(f"The number of plugs must be between 1 and {MAX_COUNT}.")


def describe(p: BlindPlugParams) -> str:
    plugs = f"{p.count} plugs" if p.count > 1 else "Plug"
    return (
        f"{plugs} for ⌀{p.tube_od:g} mm tube: inserts {p.insert_length:g} mm, "
        f"head ⌀{p.head_diameter:g} mm, {total_length(p):g} mm long in total."
    )


def build_blind_plug(p: BlindPlugParams) -> Part:
    """One plug, standing on its head on z = 0 with the tip up, centred on the z axis."""
    validate(p)
    r, rh, c = p.tube_od / 2, p.head_diameter / 2, p.tip_chamfer
    z_collar = p.head_length  # head cylinder ends, 45-degree collar starts
    z_pin = z_collar + collar_length(p)  # pin starts
    z_tip = total_length(p)
    # Half profile in the XZ plane (x = radius), revolved about the z axis.
    pts = [(0, 0), (rh, 0), (rh, z_collar), (r, z_pin), (r, z_tip - c), (r - c, z_tip), (0, z_tip)]
    profile = Polygon(*[(x, z) for x, z in _dedupe(pts)], align=None)
    plug = revolve(Plane.XZ * profile, Axis.Z)
    return Part(plug.wrapped)


def _dedupe(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop consecutive duplicate points (e.g. a tip without chamfer)."""
    out = []
    for pt in pts:
        if not out or math.dist(out[-1], pt) > 1e-9:
            out.append(pt)
    return out


def build_print_layout(p: BlindPlugParams) -> Part | Compound:
    """`p.count` plugs in the smallest square grid, centred on the origin."""
    plug = build_blind_plug(p)
    if p.count == 1:
        return plug
    n = math.ceil(math.sqrt(p.count))
    rows = math.ceil(p.count / n)
    pitch = p.head_diameter + GRID_SPACING
    plugs = []
    for i in range(p.count):
        row, col = divmod(i, n)
        plugs.append(Pos((col - (n - 1) / 2) * pitch, ((rows - 1) / 2 - row) * pitch, 0) * plug)
    return Compound(children=plugs, label="blind_plugs")


def main() -> None:
    ap = argparse.ArgumentParser(description="Blind plug for a push-in pneumatic fitting (STEP)")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="4", help="tube size to start from (mm)")
    ap.add_argument("--tube", type=float, help="tube outer diameter = pin diameter (mm)")
    ap.add_argument("--length", type=float, help="insertion length (mm)")
    ap.add_argument("--chamfer", type=float, help="tip chamfer (mm)")
    ap.add_argument("--head", type=float, help="head diameter (mm)")
    ap.add_argument("--head-length", type=float, help="length of the cylindrical head (mm)")
    ap.add_argument("--count", type=int, default=1, help="number of plugs in a square grid")
    ap.add_argument("--out", default="blind_plug.step")
    a = ap.parse_args()
    overrides = {
        "tube_od": a.tube, "insert_length": a.length, "tip_chamfer": a.chamfer,
        "head_diameter": a.head, "head_length": a.head_length, "count": a.count,
    }
    p = replace(PRESETS[a.preset], **{k: v for k, v in overrides.items() if v is not None})
    export_step(build_print_layout(p), a.out)
    print(f"Wrote {a.out}: {describe(p)}")


if __name__ == "__main__":
    main()
