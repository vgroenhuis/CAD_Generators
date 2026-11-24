"""
    Geometry for a tolerance test piece: one flat plate with a series of holes, or of pegs
    standing on it, of one shape (round, hexagon or square) and growing size, each with its
    size engraved next to it.

      * the size is the diameter (round), the size across flats (hexagon, its flats parallel
        to X) or the side (square)
      * sizes: `start`, `start + step`, ... (`count` of them), left to right and then row by
        row from the back (`per_row` in a row)
      * holes go through the plate (no overhangs, and the printed hole is open at both ends to
        measure); pegs are `height` tall on the plate
      * the labels are engraved `label_depth` deep into the plate's top, below each hole/peg,
        in a bold font that prints (see cad_common/text.py), and filled by a second body in
        another colour, flush with the top: in a multicolour printer the sizes print in a
        contrasting filament (with one filament they simply fill the engravings)

    Prints flat as it is, without supports.

    Can also be run standalone:  python tolerance_test_model.py --shape hexagon --start 6.3 --out test.step
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

from build123d import Align, Box, Circle, Color, Compound, Part, Pos, Rectangle, RegularPolygon, export_step, extrude

from cad_common.text import min_font_size, printable_text

SHAPES = ("round", "hexagon", "square")
KINDS = ("holes", "pegs")
COLOUR = Color(0.35, 0.6, 0.85)
LABEL_COLOUR = Color(0.08, 0.08, 0.08)
LABEL_GAP = 1.5  # mm between a hole/peg and its label
MAX_COUNT = 40


@dataclass
class ToleranceParams:
    kind: str = "holes"
    shape: str = "round"
    start: float = 5.0  # mm: diameter, across flats or side
    step: float = 0.1  # mm, added for each next hole/peg
    count: int = 10
    per_row: int = 5
    thickness: float = 4.0  # the plate (the holes' depth)
    height: float = 10.0  # the pegs, above the plate
    gap: float = 4.0  # mm between neighbouring holes/pegs (and their labels) and around them
    font_size: float = 5.0
    label_depth: float = 0.6


def sizes(p: ToleranceParams) -> list[float]:
    return [round(p.start + i * p.step, 6) for i in range(p.count)]


def decimals(p: ToleranceParams) -> int:
    """Decimals that show every size exactly (at least one), at most 3."""
    for d in range(1, 4):
        if all(abs(round(s, d) - s) < 1e-6 for s in sizes(p)):
            return d
    return 3


def label(p: ToleranceParams, size: float) -> str:
    return f"{size:.{decimals(p)}f}"


def footprint(p: ToleranceParams, size: float) -> tuple[float, float]:
    """Width (X) and depth (Y) of a hole/peg."""
    return (2 * size / math.sqrt(3), size) if p.shape == "hexagon" else (size, size)


def validate(p: ToleranceParams) -> None:
    if p.kind not in KINDS:
        raise ValueError(f"Kind must be one of {', '.join(KINDS)}.")
    if p.shape not in SHAPES:
        raise ValueError(f"Shape must be one of {', '.join(SHAPES)}.")
    if not 1 <= p.count <= MAX_COUNT:
        raise ValueError(f"The number of {p.kind} must be between 1 and {MAX_COUNT}.")
    if not 1 <= p.per_row <= MAX_COUNT:
        raise ValueError(f"The number per row must be between 1 and {MAX_COUNT}.")
    if not 0.5 <= p.start <= 100:
        raise ValueError("The first size must be between 0.5 and 100 mm.")
    if not -10 <= p.step <= 10:
        raise ValueError("The step must be between -10 and 10 mm.")
    if min(sizes(p)) < 0.5:
        raise ValueError("Every size must be at least 0.5 mm: the step makes the last one smaller.")
    if max(sizes(p)) > 100:
        raise ValueError("Every size must be at most 100 mm.")
    if not 1 <= p.thickness <= 50:
        raise ValueError("The plate thickness must be between 1 and 50 mm.")
    if p.kind == "pegs" and not 1 <= p.height <= 100:
        raise ValueError("The peg height must be between 1 and 100 mm.")
    if not 1.2 <= p.gap <= 50:
        raise ValueError("The gap must be between 1.2 and 50 mm.")
    least = math.ceil(min_font_size() * 10) / 10
    if not least <= p.font_size <= 20:
        raise ValueError(f"The font size must be between {least:g} mm (thinner strokes don't print) and 20 mm.")
    if not 0.2 <= p.label_depth <= p.thickness - 0.6:
        raise ValueError(f"The label depth must be between 0.2 mm and {p.thickness - 0.6:g} mm "
                         "(the plate thickness less 0.6 mm).")


def _text(p: ToleranceParams, size: float):
    return printable_text(label(p, size), p.font_size, align=(Align.CENTER, Align.CENTER))


def _section(p: ToleranceParams, size: float):
    if p.shape == "round":
        return Circle(size / 2)
    if p.shape == "square":
        return Rectangle(size, size)
    return RegularPolygon(size / math.sqrt(3), 6)  # a corner on X: flats parallel to X


def build_tolerance_test(p: ToleranceParams) -> Compound:
    """Two bodies: 'plate' (with the engravings) and 'labels' (filling them)."""
    validate(p)
    ss = sizes(p)
    texts = [_text(p, s) for s in ss]
    text_w = max(t.bounding_box().size.X for t in texts)
    text_h = max(t.bounding_box().size.Y for t in texts)
    foot_w = max(footprint(p, s)[0] for s in ss)
    foot_d = max(footprint(p, s)[1] for s in ss)
    cols = min(p.per_row, p.count)
    rows = math.ceil(p.count / cols)
    col_w = max(foot_w, text_w)
    row_h = foot_d + LABEL_GAP + text_h
    width = cols * col_w + (cols + 1) * p.gap
    depth = rows * row_h + (rows + 1) * p.gap
    plate = Box(width, depth, p.thickness, align=(Align.CENTER, Align.CENTER, Align.MIN))
    cuts, pegs, labels = [], [], []
    for i, (s, t) in enumerate(zip(ss, texts)):
        row, col = divmod(i, cols)
        x = -width / 2 + p.gap + col_w / 2 + col * (col_w + p.gap)
        top = depth / 2 - p.gap - row * (row_h + p.gap)  # the row's top edge
        y = top - foot_d / 2
        if p.kind == "holes":
            cuts.append(Pos(x, y, -1) * extrude(_section(p, s), amount=p.thickness + 2))
        else:
            pegs.append(Pos(x, y, p.thickness - 0.01) * extrude(_section(p, s), amount=p.height + 0.01))
        ty = top - foot_d - LABEL_GAP - text_h / 2
        at = Pos(x, ty, p.thickness - p.label_depth)
        cuts.append(at * extrude(t, amount=p.label_depth + 1))
        labels.append(at * extrude(t, amount=p.label_depth))
    part = plate
    if pegs:
        part = part.fuse(*pegs)
    plate = Part(part.cut(*cuts).wrapped)
    text = Part(Compound([s for lab in labels for s in lab.solids()]).wrapped)
    plate.label, plate.color = "plate", COLOUR
    text.label, text.color = "labels", LABEL_COLOUR
    return Compound(children=[plate, text], label="tolerance_test")


def describe(p: ToleranceParams) -> str:
    ss = sizes(p)
    what = {"round": "diameter", "hexagon": "across flats", "square": "side"}[p.shape]
    shape = {"round": "Round", "hexagon": "Hexagonal", "square": "Square"}[p.shape]
    cols = min(p.per_row, p.count)
    rows = math.ceil(p.count / cols)
    text = (f"{shape} {p.kind}, {what} {label(p, ss[0])} to {label(p, ss[-1])} mm in steps of "
            f"{abs(p.step):g} mm ({p.count}, {rows} row{'s' if rows > 1 else ''} of up to {cols}).")
    if p.kind == "holes":
        text += f" The holes go through the {p.thickness:g} mm plate."
    else:
        text += f" The pegs are {p.height:g} mm tall on a {p.thickness:g} mm plate."
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description="Tolerance test piece: holes or pegs of growing size, labelled (STEP)")
    d = ToleranceParams()
    ap.add_argument("--kind", choices=KINDS, default=d.kind)
    ap.add_argument("--shape", choices=SHAPES, default=d.shape)
    for name in ("start", "step", "thickness", "height", "gap", "font_size", "label_depth"):
        ap.add_argument(f"--{name.replace('_', '-')}", type=float, default=getattr(d, name))
    ap.add_argument("--count", type=int, default=d.count)
    ap.add_argument("--per-row", type=int, default=d.per_row)
    ap.add_argument("--out", default="tolerance_test.step")
    args = vars(ap.parse_args())
    out = args.pop("out")
    p = ToleranceParams(**args)
    export_step(build_tolerance_test(p), out)
    print(describe(p))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
