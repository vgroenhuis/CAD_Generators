"""API routes for the Transition Adapter generator (joins two components; each side a plug or
a socket for a round, square or rectangular component): defaults, a summary with warnings,
glTF preview, 3MF and STEP.

The files and the preview hold the adapter in print orientation (side A down). Built models
and their files are cached (see web_app/model_cache.py); the default adapter is made when the
server starts.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from transition_adapter_app.transition_adapter_model import AdapterParams, build_adapter, describe, validate, warnings
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()

cache = ModelCache("transition_adapter", build_adapter, size=8)
DEFAULT = AdapterParams()  # the model's defaults; the page loads them from /defaults
FILES = {
	"glb": lambda part: glb_bytes(part, linear_deflection=0.02, angular_deflection=0.1),
	"3mf": lambda part: threemf_bytes(part, "transition_adapter", tolerance=0.01),
	"step": step_bytes,
}


def _params(
	a_shape: str = Query(..., max_length=12), a_size: float = Query(...), a_length: float = Query(30.0),
	a_kind: str = Query(..., max_length=8), a_depth: float = Query(...), a_tolerance: float = Query(...),
	a_wall: float = Query(...),
	a_chamfer_width: float = Query(0.0), a_chamfer_depth: float = Query(0.0),
	b_shape: str = Query(..., max_length=12), b_size: float = Query(...), b_length: float = Query(20.0),
	b_kind: str = Query(..., max_length=8), b_depth: float = Query(...), b_tolerance: float = Query(...),
	b_wall: float = Query(...),
	b_chamfer_width: float = Query(0.0), b_chamfer_depth: float = Query(0.0),
	distance: float = Query(...), hole: float = Query(0.0),
) -> AdapterParams:
	# A square or round component has no second side: keep the cache key unique.
	if a_shape != "rectangle":
		a_length = DEFAULT.a_length
	if b_shape != "rectangle":
		b_length = DEFAULT.b_length
	# A chamfer with a zero width or depth is none: one cache entry for all of those.
	if a_chamfer_width == 0 or a_chamfer_depth == 0:
		a_chamfer_width = a_chamfer_depth = 0.0
	if b_chamfer_width == 0 or b_chamfer_depth == 0:
		b_chamfer_width = b_chamfer_depth = 0.0
	p = AdapterParams(a_shape, a_size, a_length, a_kind, a_depth, a_tolerance, a_wall, a_chamfer_width, a_chamfer_depth,
	                  b_shape, b_size, b_length, b_kind, b_depth, b_tolerance, b_wall, b_chamfer_width, b_chamfer_depth,
	                  distance, hole)
	try:
		validate(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _key(p: AdapterParams) -> tuple:
	return tuple(vars(p).values())


def _file(p: AdapterParams, kind: str) -> bytes:
	try:
		return cache.file(_key(p), p, kind, FILES[kind])
	except ValueError as exc:  # e.g. nothing left of the adapter
		raise HTTPException(status_code=400, detail=str(exc))


def _filename(p: AdapterParams, ext: str) -> str:
	def part(name: str) -> str:
		shape, size, length, kind = (getattr(p, f"{name}_{f}") for f in ("shape", "size", "length", "kind"))
		dims = f"{size:g}x{length:g}" if shape == "rectangle" else f"{size:g}"
		return f"{kind}_{shape}_{dims}"
	return f"transition_adapter_{part('a')}_to_{part('b')}.{ext}"


def warm() -> None:
	warm_entry(cache, _key(DEFAULT), DEFAULT, FILES)


@router.get("/defaults")
def defaults_route() -> dict:
	"""The page's starting values (by input id), so they are defined only in the model."""
	values = asdict(DEFAULT)
	out = {k: v for k, v in values.items() if not k.endswith(("_shape", "_kind"))}
	for name in ("a", "b"):  # radio buttons, by id
		out[f"{name}_shape_{values[f'{name}_shape']}"] = True
		out[f"{name}_kind_{values[f'{name}_kind']}"] = True
	return out


@router.get("/info")
def info_route(p: AdapterParams = Depends(_params)) -> dict:
	"""A summary and the warnings (components that would overlap, an adapter in pieces)."""
	try:
		adapter = cache.model(_key(p), p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return {"summary": describe(p, adapter), "warnings": warnings(p, adapter)}


@router.get("/preview.glb")
def preview_glb(p: AdapterParams = Depends(_params)):
	return glb_response(_file(p, "glb"))


@router.get("/export.3mf")
def export_3mf(p: AdapterParams = Depends(_params)):
	return download_response(_file(p, "3mf"), _filename(p, "3mf"))


@router.get("/export.step")
def export_step_route(p: AdapterParams = Depends(_params)):
	return download_response(_file(p, "step"), _filename(p, "step"))
