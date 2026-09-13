"""
Geometry construction helpers for the LynXP robot powerbank holder.

Designs the two side walls that run along the powerbank's long edges and
mount onto a baseplate with a 10 mm rectangular hole grid. Each wall is a
flat plate with a row of vertical mounting holes (2.9 mm diameter by
default, sized for self-tapping screws; 10 mm pitch) running its full
length and full height, so a screw dropped through a hole passes all the
way down into the baseplate's grid.

Wall thickness is not user-specified: it's derived from the powerbank
width. Each wall's inner (powerbank-facing) face sits at exactly
width/2 from center -- an exact fit, never loosened -- and the wall
grows outward only as far as needed for its hole row to land on the
baseplate's absolute hole grid, with at least HOLE_INNER_MARGIN of
material clearing the hole's inner side and `outer_margin` (the
user-adjustable "outer half-wall thickness") clearing its outer side.

It can also be run standalone, with hard-coded parameters. The holder is
then rendered in the OCP_vscode viewer (if available).
"""

import math

from build123d import Box, BuildPart, Cylinder, Locations, Mode, Part, Plane, Pos, mirror
from ocp_vscode import show

WALL_LENGTH = 120.0
HOLE_DIAMETER = 2.9  # default, sized for self-tapping screws
HOLE_PITCH = 10.0
HOLE_INNER_MARGIN = 1.0  # fixed minimum material clearing the hole's inner (powerbank-facing) side, mm
HOLE_OUTER_MARGIN = 1.0  # default minimum material clearing the hole's outer side, mm (user-adjustable)


def _fit_grid_hole(
	inner_face: float,
	hole_diameter: float = HOLE_DIAMETER,
	hole_pitch: float = HOLE_PITCH,
	outer_margin: float = HOLE_OUTER_MARGIN,
	inner_margin: float = HOLE_INNER_MARGIN,
) -> tuple[float, float]:
	"""Given a wall's inner (powerbank-facing) face at absolute position
	`inner_face`, growing outward, find the smallest offset from center (a
	multiple of hole_pitch/2) that clears the inner face by `inner_margin`,
	and the wall thickness needed so the hole also clears the outer face by
	`outer_margin`. Returns (hole_y, thickness).

	Searching in hole_pitch/2 steps (not full hole_pitch steps) is what
	lets the two walls' hole rows land hole_pitch apart instead of always
	2*hole_pitch apart: negation preserves whether a number is a multiple
	of hole_pitch or a multiple of hole_pitch offset by half a pitch, so
	+hole_y and -hole_y always land on the *same* row phase of the
	baseplate's grid -- just not always the phase through the origin."""
	hole_r = hole_diameter / 2.0
	half_pitch = hole_pitch / 2.0
	min_hole_y = inner_face + hole_r + inner_margin
	hole_y = math.ceil(min_hole_y / half_pitch) * half_pitch
	thickness = (hole_y - inner_face) + hole_r + outer_margin
	return hole_y, thickness


def derive_wall_thickness(
	width: float,
	hole_diameter: float = HOLE_DIAMETER,
	hole_pitch: float = HOLE_PITCH,
	outer_margin: float = HOLE_OUTER_MARGIN,
) -> float:
	"""Derive the wall thickness from the powerbank width: the smallest
	thickness such that a vertical mounting hole, positioned as close to the
	inner (powerbank-facing) face as the grid allows, lands exactly on the
	baseplate's absolute `hole_pitch` grid."""
	_, thickness = _fit_grid_hole(width / 2.0, hole_diameter, hole_pitch, outer_margin)
	return thickness


def derive_hole_spacing(
	width: float,
	hole_diameter: float = HOLE_DIAMETER,
	hole_pitch: float = HOLE_PITCH,
	outer_margin: float = HOLE_OUTER_MARGIN,
) -> float:
	"""Derive the center-to-center spacing between the first wall's hole row
	and the second wall's hole row (the two rows are mirrored about center,
	so this is twice the absolute hole grid line each one lands on). Always
	an exact multiple of `hole_pitch` -- but not necessarily 2x `hole_pitch`,
	since the two rows may land on grid lines offset by half a pitch from
	the origin rather than both passing through it."""
	hole_y, _ = _fit_grid_hole(width / 2.0, hole_diameter, hole_pitch, outer_margin)
	return 2.0 * hole_y


def _hole_x_positions(
	length: float,
	hole_diameter: float = HOLE_DIAMETER,
	hole_pitch: float = HOLE_PITCH,
	edge_margin: float = HOLE_INNER_MARGIN,
) -> list[float]:
	"""X positions of the hole row along a wall of the given `length`: spaced
	`hole_pitch` apart, symmetric about center, with each end hole kept
	`edge_margin` clear of the wall's ends (not a full extra hole_pitch/2 --
	only as much room as the hole itself actually needs). The resulting
	count may be even or odd depending on `length`."""
	hole_r = hole_diameter / 2.0
	margin = hole_r + edge_margin
	usable = max(length - 2.0 * margin, 0.0)
	n_intervals = int(usable // hole_pitch)
	span = n_intervals * hole_pitch
	start_x = -span / 2.0
	return [start_x + i * hole_pitch for i in range(n_intervals + 1)]


def derive_hole_count(length: float, hole_diameter: float = HOLE_DIAMETER, hole_pitch: float = HOLE_PITCH) -> int:
	"""Derive how many holes fit along a wall of the given `length` (see
	`_hole_x_positions`); may be even or odd depending on `length`."""
	return len(_hole_x_positions(length, hole_diameter, hole_pitch))


def build_wall(
	length: float,
	height: float,
	width: float,
	hole_diameter: float = HOLE_DIAMETER,
	hole_pitch: float = HOLE_PITCH,
	outer_margin: float = HOLE_OUTER_MARGIN,
) -> Part:
	"""Build a single perforated wall: `length` (mm) long, `height` (mm)
	tall, with its inner (powerbank-facing) face at local Y=0, growing
	outward (+Y) far enough that its vertical mounting-hole row (full
	height, `hole_diameter` wide, spaced `hole_pitch` apart along the
	length) lands on the baseplate's absolute hole grid, given the wall
	sits `width`/2 from center."""
	inner_face = width / 2.0
	hole_y, thickness = _fit_grid_hole(inner_face, hole_diameter, hole_pitch, outer_margin)
	hole_offset = hole_y - inner_face  # local Y of the hole row, inner face at local Y=0

	with BuildPart() as wall:
		with Locations([(0.0, thickness / 2.0, 0.0)]):
			Box(length, thickness, height)

		hole_r = hole_diameter / 2.0
		hole_xs = _hole_x_positions(length, hole_diameter, hole_pitch)

		with Locations([(x, hole_offset, 0.0) for x in hole_xs]):
			Cylinder(radius=hole_r, height=height + 2.0, mode=Mode.SUBTRACT)

	part = wall.part
	if part is None:
		raise RuntimeError("Wall construction failed: no part was generated")
	return part


def build_powerbank_holder(
	width: float,
	height: float,
	length: float = WALL_LENGTH,
	hole_diameter: float = HOLE_DIAMETER,
	hole_pitch: float = HOLE_PITCH,
	outer_margin: float = HOLE_OUTER_MARGIN,
) -> Part:
	"""Build both side walls of the powerbank holder. Each wall's inner face
	sits at exactly `width`/2 (mm) from center -- an exact fit against the
	powerbank -- growing outward only as far as needed to land its hole row
	on the grid (see `build_wall`)."""
	wall = build_wall(length, height, width, hole_diameter, hole_pitch, outer_margin)
	inner_face = width / 2.0
	wall_a = Pos(0, inner_face, 0) * wall
	wall_b = Pos(0, -inner_face, 0) * mirror(wall, about=Plane.XZ)
	return wall_a + wall_b


def build_powerbank_holder_struct(params) -> Part:
	"""Build the powerbank holder from a params dict."""
	return build_powerbank_holder(
		params["width"],
		params["height"],
		length=params.get("length", WALL_LENGTH),
		hole_diameter=params.get("hole_diameter", HOLE_DIAMETER),
		outer_margin=params.get("outer_margin", HOLE_OUTER_MARGIN),
	)


######## Test functions when running this file directly. These can be run by uncommenting the desired test in main().

def test_manual_params() -> None:
	params = {"width": 25, "height": 30}
	holder = build_powerbank_holder_struct(params)
	show(holder)


def main() -> None:
	test_manual_params()


if __name__ == "__main__":
	main()
