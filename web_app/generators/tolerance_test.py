"""API routes for the Tolerance Test generator (a plate with a series of holes or pegs of growing
size, their sizes inlaid in another colour): defaults, a summary, glTF preview, 3MF and STEP.

Built models and their files are cached (see web_app/model_cache.py); the default test piece is
made when the server starts.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from tolerance_test_app.tolerance_test_model import ToleranceParams, build_tolerance_test, describe, validate
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()

cache = ModelCache("tolerance_test", build_tolerance_test, size=8)
DEFAULT = ToleranceParams()  # the model's defaults; the page loads them from /defaults
FILES = {
	"glb": lambda part: glb_bytes(part, linear_deflection=0.02, angular_deflection=0.1),
	"3mf": lambda part: threemf_bytes(part, "tolerance_test", tolerance=0.005),
	"step": step_bytes,
}


def _params(
	kind: str = Query(..., max_length=8), shape: str = Query(..., max_length=8),
	start: float = Query(...), step: float = Query(...), count: int = Query(...), per_row: int = Query(...),
	thickness: float = Query(...), height: float = Query(...), gap: float = Query(...),
	font_size: float = Query(...), label_depth: float = Query(...),
) -> ToleranceParams:
	if kind == "holes":  # the peg height doesn't matter: one cache entry
		height = DEFAULT.height
	p = ToleranceParams(kind, shape, start, step, count, per_row, thickness, height, gap, font_size, label_depth)
	try:
		validate(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _key(p: ToleranceParams) -> tuple:
	return tuple(vars(p).values())


def _file(p: ToleranceParams, kind: str) -> bytes:
	try:
		return cache.file(_key(p), p, kind, FILES[kind])
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))


def _filename(p: ToleranceParams, ext: str) -> str:
	last = p.start + (p.count - 1) * p.step
	return f"tolerance_test_{p.shape}_{p.kind}_{p.start:g}-{round(last, 3):g}mm.{ext}"


def warm() -> None:
	warm_entry(cache, _key(DEFAULT), DEFAULT, FILES)


@router.get("/defaults")
def defaults_route() -> dict:
	"""The page's starting values (by input id), so they are defined only in the model."""
	return asdict(DEFAULT)


@router.get("/info")
def info_route(p: ToleranceParams = Depends(_params)) -> dict:
	return {"summary": describe(p)}


@router.get("/preview.glb")
def preview_glb(p: ToleranceParams = Depends(_params)):
	return glb_response(_file(p, "glb"))


@router.get("/export.3mf")
def export_3mf(p: ToleranceParams = Depends(_params)):
	return download_response(_file(p, "3mf"), _filename(p, "3mf"))


@router.get("/export.step")
def export_step_route(p: ToleranceParams = Depends(_params)):
	return download_response(_file(p, "step"), _filename(p, "step"))
