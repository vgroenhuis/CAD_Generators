"""API routes for the Powerbank Holder generator: build123d model -> glTF
preview / STEP export.

All endpoints take the same query parameters (width, height, length,
hole_diameter, outer_margin) and are stateless -- each request rebuilds the
model from scratch. Wall thickness, hole spacing, and hole count are all
derived server-side (see powerbank_holder_model.py) and returned as response
headers alongside preview.glb, so the frontend can show them without a
second request.
"""

import tempfile
from pathlib import Path

from build123d import export_gltf, export_step
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from powerbank_holder_app.powerbank_holder_model import (
	build_powerbank_holder,
	derive_hole_count,
	derive_hole_spacing,
	derive_wall_thickness,
)

router = APIRouter()


def _build_validated_holder(width: float, height: float, length: float, hole_diameter: float, outer_margin: float):
	if width <= 0 or height <= 0 or length <= 0 or hole_diameter <= 0 or outer_margin <= 0:
		raise HTTPException(
			status_code=400,
			detail="Width, height, length, hole diameter, and outer wall thickness must be greater than 0.",
		)
	part = build_powerbank_holder(
		width, height, length=length, hole_diameter=hole_diameter, outer_margin=outer_margin
	)
	thickness = derive_wall_thickness(width, hole_diameter=hole_diameter, outer_margin=outer_margin)
	hole_spacing = derive_hole_spacing(width, hole_diameter=hole_diameter, outer_margin=outer_margin)
	hole_count = derive_hole_count(length, hole_diameter=hole_diameter)
	return part, thickness, hole_spacing, hole_count


@router.get("/preview.glb")
def preview_glb(
	width: float = Query(..., gt=0),
	height: float = Query(..., gt=0),
	length: float = Query(..., gt=0),
	hole_diameter: float = Query(..., gt=0),
	outer_margin: float = Query(..., gt=0),
) -> Response:
	part, thickness, hole_spacing, hole_count = _build_validated_holder(
		width, height, length, hole_diameter, outer_margin
	)
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir) / "powerbank_holder.glb"
		export_gltf(part, str(tmp_path), binary=True, linear_deflection=0.1, angular_deflection=0.2)
		data = tmp_path.read_bytes()
	return Response(
		content=data,
		media_type="model/gltf-binary",
		headers={
			"X-Wall-Thickness": f"{thickness:.3f}",
			"X-Hole-Spacing": f"{hole_spacing:.3f}",
			"X-Hole-Count": str(hole_count),
		},
	)


@router.get("/export.step")
def export_step_route(
	width: float = Query(..., gt=0),
	height: float = Query(..., gt=0),
	length: float = Query(..., gt=0),
	hole_diameter: float = Query(..., gt=0),
	outer_margin: float = Query(..., gt=0),
) -> Response:
	part, _, _, _ = _build_validated_holder(width, height, length, hole_diameter, outer_margin)
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir) / "powerbank_holder.step"
		export_step(part, str(tmp_path))
		data = tmp_path.read_bytes()
	return Response(
		content=data,
		media_type="application/step",
		headers={"Content-Disposition": 'attachment; filename="powerbank_holder.step"'},
	)
