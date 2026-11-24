"""API routes for the Screwdriver Handle generator (a knurled handle for 1/4" hex bits with a
magnet pocket, storage holes for spare bits and a screw cap): defaults, a summary, glTF preview,
3MF and STEP.

The files and the preview hold the handle and its cap side by side, each in print orientation.
Built models and their files are cached (see web_app/model_cache.py); the default handle is made
when the server starts.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from screwdriver_handle_app.screwdriver_handle_model import PRESETS, HandleParams, build_screwdriver_handle, describe, validate
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()

cache = ModelCache("screwdriver_handle", build_screwdriver_handle, size=6)
DEFAULT = HandleParams()  # the model's defaults; the page loads them from /defaults
FILES = {
	"glb": lambda part: glb_bytes(part, linear_deflection=0.05, angular_deflection=0.2),
	"3mf": lambda part: threemf_bytes(part, "screwdriver_handle", tolerance=0.01),
	"step": step_bytes,
}


def _params(
	diameter: float = Query(...), min_length: float = Query(...), taper_length: float = Query(0.0),
	tip_diameter: float = Query(12.0), knurl: bool = Query(True), knurl_depth: float = Query(...),
	knurl_count: int = Query(...),
	socket_size: float = Query(...), socket_depth: float = Query(...),
	magnet_diameter: float = Query(...), magnet_height: float = Query(...), magnet_gap: float = Query(...),
	holes: int = Query(...), hole_size: float = Query(...), hole_length: float = Query(...),
	storage_gap: float = Query(...),
	thread_length: float = Query(...), thread_clearance: float = Query(...),
) -> HandleParams:
	if not knurl:  # its settings don't matter: one cache entry
		knurl_depth, knurl_count = DEFAULT.knurl_depth, DEFAULT.knurl_count
	if holes == 0:
		hole_size, hole_length, storage_gap = DEFAULT.hole_size, DEFAULT.hole_length, DEFAULT.storage_gap
	if magnet_diameter == 0 or magnet_height == 0:
		magnet_diameter = magnet_height = 0.0
	if taper_length == 0:
		tip_diameter = DEFAULT.tip_diameter
	p = HandleParams(diameter, min_length, taper_length, tip_diameter, knurl, knurl_depth, knurl_count, socket_size, socket_depth, magnet_diameter,
	                 magnet_height, magnet_gap, holes, hole_size, hole_length, storage_gap, thread_length, thread_clearance)
	try:
		validate(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _key(p: HandleParams) -> tuple:
	return tuple(vars(p).values())


def _file(p: HandleParams, kind: str) -> bytes:
	try:
		return cache.file(_key(p), p, kind, FILES[kind])
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))


def _filename(p: HandleParams, ext: str) -> str:
	return f"screwdriver_handle_{p.diameter:g}mm_{p.holes}holes.{ext}"


def warm() -> None:
	warm_entry(cache, _key(DEFAULT), DEFAULT, FILES)


@router.get("/defaults")
def defaults_route() -> dict:
	"""The page's starting values (by input id) and the presets, so they are defined only in the model."""
	return {**asdict(DEFAULT), "presets": {name: asdict(p) for name, p in PRESETS.items()}}


@router.get("/info")
def info_route(p: HandleParams = Depends(_params)) -> dict:
	"""A summary, with the height to pause the print at for the magnet."""
	return {"summary": describe(p)}


@router.get("/preview.glb")
def preview_glb(p: HandleParams = Depends(_params)):
	return glb_response(_file(p, "glb"))


@router.get("/export.3mf")
def export_3mf(p: HandleParams = Depends(_params)):
	return download_response(_file(p, "3mf"), _filename(p, "3mf"))


@router.get("/export.step")
def export_step_route(p: HandleParams = Depends(_params)):
	return download_response(_file(p, "step"), _filename(p, "step"))
