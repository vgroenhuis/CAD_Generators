"""API routes for the Calibration Plate generator: build123d model -> glTF
preview / STEP export, plus the pattern layout (counts and Kalibr target YAML).

All endpoints take the plate parameters as query parameters and are stateless.
The STEP file holds two bodies ("white" and "black"); the glTF preview keeps
them as separate nodes so the frontend can colour them.

Building a plate takes several seconds, so the last few built plates are cached:
the STEP download right after a preview reuses the preview's model. Size limits
keep a public server from being asked for arbitrarily large builds.
"""

import tempfile
import threading
from collections import OrderedDict
from pathlib import Path

from build123d import export_gltf, export_step
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from calibration_plate_app.calibration_plate_model import PlateParams, build_calibration_plate, compute_layout, pattern_warning

router = APIRouter()

_MAX_SIDE = 600.0  # mm
_MAX_THICKNESS = 50.0  # mm
_MAX_SQUARES = 1000
_MAX_TAGS = 200
_CACHE_SIZE = 4

_cache: "OrderedDict[tuple, tuple]" = OrderedDict()
_cache_lock = threading.Lock()


def _params(
	width: float = Query(..., gt=0, le=_MAX_SIDE),
	length: float = Query(..., gt=0, le=_MAX_SIDE),
	thickness: float = Query(..., gt=0, le=_MAX_THICKNESS),
	depth: float = Query(..., gt=0),
	margin: float = Query(..., ge=0),
	square_size: float = Query(..., gt=0),
	tag_size: float = Query(..., gt=0),
	tag_spacing: float = Query(..., gt=0, le=1),
	border_bits: int = Query(..., ge=1, le=2),
	corner_squares: bool = Query(True),
	first_tag_id: int = Query(0, ge=0),
) -> PlateParams:
	return PlateParams(
		width, length, thickness, depth, margin, square_size, tag_size, tag_spacing, border_bits, corner_squares, first_tag_id
	)


def _validated_layout(p: PlateParams):
	try:
		layout = compute_layout(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	if layout.checker_cols * layout.checker_rows > _MAX_SQUARES:
		raise HTTPException(status_code=400, detail=f"At most {_MAX_SQUARES} checkerboard squares; increase the square size.")
	if layout.tag_cols * layout.tag_rows > _MAX_TAGS:
		raise HTTPException(status_code=400, detail=f"At most {_MAX_TAGS} AprilTags; increase the tag size.")
	return layout


def _build(p: PlateParams):
	_validated_layout(p)  # cheap checks before the expensive build
	key = tuple(vars(p).values())
	with _cache_lock:
		if key in _cache:
			_cache.move_to_end(key)
			return _cache[key]
	result = build_calibration_plate(p)
	with _cache_lock:
		_cache[key] = result
		while len(_cache) > _CACHE_SIZE:
			_cache.popitem(last=False)
	return result


@router.get("/layout")
def layout_route(p: PlateParams = Depends(_params)) -> dict:
	layout = _validated_layout(p)
	return {
		"checker_cols": layout.checker_cols,
		"checker_rows": layout.checker_rows,
		"tag_cols": layout.tag_cols,
		"tag_rows": layout.tag_rows,
		"first_tag_id": p.first_tag_id,
		"last_tag_id": p.first_tag_id + layout.tag_cols * layout.tag_rows - 1,
		"aprilgrid_yaml": layout.kalibr_yaml(p),
		"checkerboard_yaml": layout.checkerboard_yaml(p),
		"warning": pattern_warning(p),
	}


@router.get("/preview.glb")
def preview_glb(p: PlateParams = Depends(_params)) -> Response:
	plate, _ = _build(p)
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir) / "calibration_plate.glb"
		export_gltf(plate, str(tmp_path), binary=True, linear_deflection=0.1, angular_deflection=0.2)
		data = tmp_path.read_bytes()
	return Response(content=data, media_type="model/gltf-binary")


@router.get("/export.step")
def export_step_route(p: PlateParams = Depends(_params)) -> Response:
	plate, _ = _build(p)
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir) / "calibration_plate.step"
		export_step(plate, str(tmp_path))
		data = tmp_path.read_bytes()
	name = f"calibration_plate_{p.width:g}x{p.length:g}x{p.thickness:g}.step"
	return Response(
		content=data,
		media_type="application/step",
		headers={"Content-Disposition": f'attachment; filename="{name}"'},
	)
