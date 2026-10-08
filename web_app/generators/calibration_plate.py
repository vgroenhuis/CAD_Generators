"""API routes for the Calibration Plate generator: build123d model -> glTF
preview, 3MF and STEP, plus the pattern layout (counts and Kalibr target YAML).

All endpoints take the plate parameters as query parameters. The 3MF and STEP files
hold two bodies ("white" and "black") as separate parts; the glTF preview keeps them
as separate nodes so the frontend can colour them.

Building a plate takes several seconds and writing its STEP file even longer, so
built plates and their files are cached (see web_app/model_cache.py) and the default
plate is made when the server starts. Size limits keep a public server from being
asked for arbitrarily large builds.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from calibration_plate_app.calibration_plate_model import PlateParams, build_calibration_plate, compute_layout, pattern_warning
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()

_MAX_SIDE = 600.0  # mm
_MAX_THICKNESS = 50.0  # mm
_MAX_SQUARES = 1000
_MAX_TAGS = 200

cache = ModelCache("calibration_plate", build_calibration_plate, size=4)
DEFAULT = PlateParams()  # matches the defaults in calibration-plate.html
FILES = {
	"glb": lambda m: glb_bytes(m[0]),
	"3mf": lambda m: threemf_bytes(m[0], "calibration_plate"),
	"step": lambda m: step_bytes(m[0]),
}


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


def _key(p: PlateParams) -> tuple:
	return tuple(vars(p).values())


def _file(p: PlateParams, kind: str) -> bytes:
	_validated_layout(p)  # cheap checks before the expensive build
	return cache.file(_key(p), p, kind, FILES[kind])


def _filename(p: PlateParams, ext: str) -> str:
	return f"calibration_plate_{p.width:g}x{p.length:g}x{p.thickness:g}.{ext}"


def warm() -> None:
	warm_entry(cache, _key(DEFAULT), DEFAULT, FILES)


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
def preview_glb(p: PlateParams = Depends(_params)):
	return glb_response(_file(p, "glb"))


@router.get("/export.3mf")
def export_3mf(p: PlateParams = Depends(_params)):
	return download_response(_file(p, "3mf"), _filename(p, "3mf"))


@router.get("/export.step")
def export_step_route(p: PlateParams = Depends(_params)):
	return download_response(_file(p, "step"), _filename(p, "step"))
