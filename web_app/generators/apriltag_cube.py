"""API routes for the AprilTag Cube generator: build123d model -> glTF
preview / STEP export.

Both endpoints take tag_ids, size, depth, and optional axes and per_face flags as query
parameters and are stateless. With per_face=true, tag_ids must hold six comma-separated ids in
die order (faces 1, 2, 3 along +X, +Y, +Z and 4, 5, 6 opposite to 3, 2, 1) for one cube.
Otherwise it holds one or more ids, each giving a cube with that tag on all faces; several
cubes are laid out in the smallest square grid, 2 mm apart. axes adds red +X / green +Y
arrows on the floor beside the cube(s). The STEP file holds two bodies ("white" and "black"); the glTF
preview keeps them as separate nodes so the frontend can colour them.
"""

import tempfile
from pathlib import Path

from build123d import export_gltf, export_step
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from apriltag_cube_app.apriltag_cube_model import build_apriltag_cube, build_apriltag_cube_grid, parse_tag_ids

router = APIRouter()


def _build_validated_cube(tag_ids: str, size: float, depth: float, axes: bool, per_face: bool):
	try:
		ids = parse_tag_ids(tag_ids, per_face=per_face)  # also validates the ID range
		if per_face:
			return build_apriltag_cube(ids, size, depth, axes=axes), ids
		return build_apriltag_cube_grid(ids, size, depth, axes=axes), ids
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))


@router.get("/preview.glb")
def preview_glb(
	tag_ids: str = Query(...),
	size: float = Query(..., gt=0),
	depth: float = Query(..., gt=0),
	axes: bool = Query(False),
	per_face: bool = Query(False),
) -> Response:
	cube, ids = _build_validated_cube(tag_ids, size, depth, axes, per_face)
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
	axes: bool = Query(False),
	per_face: bool = Query(False),
) -> Response:
	cube, ids = _build_validated_cube(tag_ids, size, depth, axes, per_face)
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir) / "apriltag_cube.step"
		export_step(cube, str(tmp_path))
		data = tmp_path.read_bytes()
	return Response(
		content=data,
		media_type="application/step",
		headers={"Content-Disposition": f'attachment; filename="apriltag_cube_{"-".join(f"{i:02d}" for i in ids)}.step"'},
	)
