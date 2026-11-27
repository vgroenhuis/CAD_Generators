"""API routes for the Box with Holes generator (a round, square, rectangular or hexagonal box
with a snap-in, screwed or screw-on lid that has holes for panel-mount parts): defaults with the
presets, a summary, glTF preview, 3MF and STEP.

Built models and their files are cached (see web_app/model_cache.py); the default box and the
presets' are made when the server starts.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from hole_box_app.hole_box_model import BoxParams, PRESETS, build_hole_box, describe, outer_size, validate
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()

cache = ModelCache("hole_box", build_hole_box, size=8)
DEFAULT = BoxParams()  # the model's defaults; the page loads them from /defaults
FILES = {
	"glb": lambda part: glb_bytes(part, linear_deflection=0.02, angular_deflection=0.1),
	"3mf": lambda part: threemf_bytes(part, "hole_box", tolerance=0.01),
	"step": step_bytes,
}


def _params(
	shape: str = Query(..., max_length=10), width: float = Query(...), depth: float = Query(...),
	height: float = Query(...), wall: float = Query(...), corner_radius: float = Query(...),
	closure: str = Query(..., max_length=8), joint_length: float = Query(...), clearance: float = Query(...),
	holes: int = Query(...), hole_shape: str = Query(..., max_length=8), hole_size: float = Query(...),
	hole_circle: float = Query(...),
) -> BoxParams:
	# Settings that don't matter for this box take their defaults: one cache entry.
	if shape != "rectangle":
		depth = DEFAULT.depth
	if shape == "round":
		corner_radius = DEFAULT.corner_radius
	if closure == "screws":
		joint_length, clearance = DEFAULT.joint_length, DEFAULT.clearance
	if holes == 0:
		hole_shape, hole_size, hole_circle = DEFAULT.hole_shape, DEFAULT.hole_size, DEFAULT.hole_circle
	p = BoxParams(shape, width, depth, height, wall, corner_radius, closure, joint_length, clearance,
	              holes, hole_shape, hole_size, hole_circle)
	try:
		validate(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _key(p: BoxParams) -> tuple:
	return tuple(vars(p).values())


def _file(p: BoxParams, kind: str) -> bytes:
	try:
		return cache.file(_key(p), p, kind, FILES[kind])
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))


def _filename(p: BoxParams, ext: str) -> str:
	size = f"{p.width:g}x{p.depth:g}" if p.shape == "rectangle" else f"{p.width:g}"
	return f"box_{p.shape}_{size}x{p.height:g}mm_{p.closure}_{p.holes}holes.{ext}"


def warm() -> None:
	"""The default box and the presets', so the page shows them at once."""
	for p in (DEFAULT, *PRESETS.values()):
		warm_entry(cache, _key(p), p, FILES)


@router.get("/defaults")
def defaults_route() -> dict:
	"""The page's starting values (by input id) and the presets, so they are defined only in the model."""
	return {**asdict(DEFAULT), "presets": {name: asdict(p) for name, p in PRESETS.items()}}


@router.get("/info")
def info_route(p: BoxParams = Depends(_params)) -> dict:
	# For the page's assembled view: the box's outside width along X and its closed height, mm.
	return {"summary": describe(p), "outer_x": outer_size(p)[0], "height": p.height}


@router.get("/preview.glb")
def preview_glb(p: BoxParams = Depends(_params)):
	return glb_response(_file(p, "glb"))


@router.get("/export.3mf")
def export_3mf(p: BoxParams = Depends(_params)):
	return download_response(_file(p, "3mf"), _filename(p, "3mf"))


@router.get("/export.step")
def export_step_route(p: BoxParams = Depends(_params)):
	return download_response(_file(p, "step"), _filename(p, "step"))
