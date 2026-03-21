"""Geometry construction helpers for ring creation."""

from build123d import BuildPart, Cylinder, Mode, Part


def build_ring(od: float, inner_d: float, thickness: float) -> Part:
    """Build and return a ring part from outer/inner diameter and thickness."""
    with BuildPart() as ring:
        Cylinder(radius=od / 2.0, height=thickness)
        Cylinder(radius=inner_d / 2.0, height=thickness, mode=Mode.SUBTRACT)
    return ring.part
