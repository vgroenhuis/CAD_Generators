"""API routes for the Ring generator: build123d model -> glTF preview / STEP export.

Both endpoints take the same query parameters (od, id, thickness) and are
stateless -- each request rebuilds the model from scratch. build123d is
already fully imported by the time a request server, so a single build is
fast; there's no need to cache the resulting Part across requests.
"""

import tempfile
from pathlib import Path

from build123d import export_gltf, export_step
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ring_app.ring_model import build_ring

router = APIRouter()


def _build_validated_ring(od: float, inner_d: float, thickness: float):
	if od <= 0 or inner_d <= 0 or thickness <= 0:
		raise HTTPException(status_code=400, detail="OD, ID, and thickness must be greater than 0.")
	if od <= inner_d:
		raise HTTPException(status_code=400, detail="OD must be greater than ID.")
	return build_ring(od, inner_d, thickness)


@router.get("/preview.glb")
def preview_glb(
	od: float = Query(..., gt=0),
	id: float = Query(..., gt=0),
	thickness: float = Query(..., gt=0),
) -> Response:
	part = _build_validated_ring(od, id, thickness)
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir) / "ring.glb"
		export_gltf(part, str(tmp_path), binary=True, linear_deflection=0.1, angular_deflection=0.2)
		data = tmp_path.read_bytes()
	return Response(content=data, media_type="model/gltf-binary")


@router.get("/export.step")
def export_step_route(
	od: float = Query(..., gt=0),
	id: float = Query(..., gt=0),
	thickness: float = Query(..., gt=0),
) -> Response:
	part = _build_validated_ring(od, id, thickness)
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir) / "ring.step"
		export_step(part, str(tmp_path))
		data = tmp_path.read_bytes()
	return Response(
		content=data,
		media_type="application/step",
		headers={"Content-Disposition": 'attachment; filename="ring.step"'},
	)
