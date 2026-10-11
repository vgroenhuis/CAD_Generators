"""API routes for the Cable Clip generator (a clip for a round or flat cable, fastened
with one countersunk wood screw): defaults, a summary, glTF preview, 3MF and STEP.

The files and the preview hold the requested number of clips in print orientation (on
their side). Built models and their files are cached (see web_app/model_cache.py); the
default clip is made when the server starts.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from cable_clip_app.cable_clip_model import ClipParams, build_print_layout, describe, validate
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()

cache = ModelCache("cable_clip", build_print_layout, size=6)
DEFAULT = ClipParams()  # the model's defaults; the page loads them from /defaults
FILES = {
	"glb": lambda part: glb_bytes(part, linear_deflection=0.02, angular_deflection=0.1),
	"3mf": lambda part: threemf_bytes(part, "cable_clip", tolerance=0.01),
	"step": step_bytes,
}


def _params(
	flat: bool = Query(False),
	diameter: float = Query(6.0, gt=0, le=60),  # used for a round cable
	flat_width: float = Query(10.0, gt=0, le=100),  # used for a flat cable
	flat_height: float = Query(3.0, gt=0, le=60),
	squeeze: float = Query(..., ge=0),
	strap: float = Query(..., gt=0, le=10),
	clip_width: float = Query(..., gt=0, le=100),
	tab_thickness: float = Query(..., gt=0, le=20),
	foot: float = Query(..., ge=0, le=20),
	screw_diameter: float = Query(..., gt=0, le=12),
	screw_head: float = Query(..., gt=0, le=25),
	hole_clearance: float = Query(..., ge=0, le=2),
	countersink_angle: float = Query(..., ge=60, le=120),
	count: int = Query(..., ge=1, le=50),
) -> ClipParams:
	p = ClipParams(
		flat, diameter, flat_width, flat_height, squeeze, strap, clip_width, tab_thickness, foot,
		screw_diameter, screw_head, hole_clearance, countersink_angle, count,
	)
	try:
		validate(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _key(p: ClipParams) -> tuple:
	values = vars(p).copy()
	if p.flat:  # the size of the other cable type does not matter
		values.update(diameter=None)
	else:
		values.update(flat_width=None, flat_height=None)
	return tuple(values.values())


def _file(p: ClipParams, kind: str) -> bytes:
	return cache.file(_key(p), p, kind, FILES[kind])


def _filename(p: ClipParams, ext: str) -> str:
	size = f"flat_{p.flat_width:g}x{p.flat_height:g}" if p.flat else f"{p.diameter:g}mm"
	count = f"_x{p.count}" if p.count > 1 else ""
	return f"cable_clip_{size}{count}.{ext}"


def warm() -> None:
	warm_entry(cache, _key(DEFAULT), DEFAULT, FILES)


@router.get("/defaults")
def defaults_route() -> dict:
	"""The page's starting values (by input id), so they are defined only in the model."""
	return {**asdict(DEFAULT), "cable_round": not DEFAULT.flat, "cable_flat": DEFAULT.flat}


@router.get("/info")
def info_route(p: ClipParams = Depends(_params)) -> dict:
	return {"summary": describe(p)}


@router.get("/preview.glb")
def preview_glb(p: ClipParams = Depends(_params)):
	return glb_response(_file(p, "glb"))


@router.get("/export.3mf")
def export_3mf(p: ClipParams = Depends(_params)):
	return download_response(_file(p, "3mf"), _filename(p, "3mf"))


@router.get("/export.step")
def export_step_route(p: ClipParams = Depends(_params)):
	return download_response(_file(p, "step"), _filename(p, "step"))
