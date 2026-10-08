"""Printable text for 3D-printed labels.

Text is drawn with a bundled bold sans-serif font (DejaVu Sans Bold, see
fonts/DejaVu-LICENSE.txt) rather than a system font: the strokes are thick enough to
print, and the result is the same on every machine (a system without the requested
font would otherwise silently fall back to another, possibly hairline, font).
"""

from __future__ import annotations

from pathlib import Path

from build123d import Text

FONT = Path(__file__).resolve().parent / "fonts" / "DejaVuSans-Bold.ttf"

# The thinnest strokes of DejaVu Sans Bold are about 0.127 x the font size (measured:
# 0.70 mm at 5.5 mm, 5th percentile of the stroke widths); 0.12 leaves some margin.
STROKE_PER_FONT_SIZE = 0.12
MIN_STROKE = 0.5  # mm; a 0.4 mm nozzle cannot print narrower lines


def min_font_size(min_stroke: float = MIN_STROKE) -> float:
    """Smallest font size (mm) whose strokes are still at least `min_stroke` wide."""
    return min_stroke / STROKE_PER_FONT_SIZE


def printable_text(txt: str, font_size: float, **kwargs) -> Text:
    return Text(txt, font_size, font_path=str(FONT), **kwargs)
