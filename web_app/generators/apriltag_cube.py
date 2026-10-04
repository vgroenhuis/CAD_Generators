"""API routes for the AprilTag Cube generator: build123d model -> glTF
preview / STEP export.

Both endpoints take tag_ids (one id, or six comma-separated ids), size, and depth query parameters and are
stateless. The STEP file holds two bodies ("white" and "black"); the glTF
preview keeps them as separate nodes so the frontend can colour them.
"""

import tempfile
from pathlib import Path

from build123d import export_gltf, export_step
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from apriltag_cube_app.apriltag_cube_model import TAG16H5_CODES, build_apriltag_cube, parse_tag_ids

router = APIRouter()


def _build_validated_cube(tag_ids: str, size: float, depth: float):
	try:
		ids = parse_tag_ids(tag_ids)
		bad = [i for i in ids if not 0 <= i < len(TAG16H5_CODES)]
		if bad:
			raise ValueError(f"Tag IDs must be between 0 and {len(TAG16H5_CODES) - 1}.")
		return build_apriltag_cube(ids, size, depth), ids
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))


@router.get("/preview.glb")
def preview_glb(
	tag_ids: str = Query(...),
	size: float = Query(..., gt=0),
	depth: float = Query(..., gt=0),
) -> Response:
	cube, ids = _build_validated_cube(tag_ids, size, depth)
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir) / "apriltag_cube.glb"
		export_gltf(cube, str(tmp_path), binary=True, linear_deflection=0.1, angular_deflection=0.2)
		data = tmp_path.read_bytes()
	return Response(content=data, media_type="model/gltf-binary")


@router.get("/export.step")
def export_step_route(
	tag_ids: str = Query(...),
	size: float = Query(..., gt=0),
	depth: float = Query(..., gt=0),
) -> Response:
	cube, ids = _build_validated_cube(tag_ids, size, depth)
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir) / "apriltag_cube.step"
		export_step(cube, str(tmp_path))
		data = tmp_path.read_bytes()
	return Response(
		content=data,
		media_type="application/step",
		headers={"Content-Disposition": f'attachment; filename="apriltag_cube_{"-".join(f"{i:02d}" for i in ids)}.step"'},
	)
