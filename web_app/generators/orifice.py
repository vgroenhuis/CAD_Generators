"""API routes for the Orifice generator (a pneumatic tube connector with an orifice
between two tube sockets): a summary of what will be built, glTF preview, 3MF and STEP.

All endpoints take the socket, orifice and series parameters as query parameters.
Built models and their files are cached (see web_app/model_cache.py); the default
connector is made when the server starts.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from orifice_app.orifice_model import OrificeParams, build_orifice, describe, diameters, section, validate
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()

cache = ModelCache("orifice", build_orifice, size=6)
DEFAULT = OrificeParams()  # matches the defaults in orifice.html
FILES = {
	"glb": lambda part: glb_bytes(part, linear_deflection=0.02, angular_deflection=0.1),
	"3mf": lambda part: threemf_bytes(part, "orifice", tolerance=0.005),
	"step": step_bytes,
}


def _params(
	socket_a_id: float = Query(..., gt=0, le=50),
	socket_a_wall: float = Query(..., gt=0, le=20),
	socket_a_depth: float = Query(..., gt=0, le=100),
	socket_b_id: float = Query(..., gt=0, le=50),
	socket_b_wall: float = Query(..., gt=0, le=20),
	socket_b_depth: float = Query(..., gt=0, le=100),
	orifice_diameter: float = Query(1.0, gt=0),  # not used (and not sent) for a series
	orifice_length: float = Query(..., gt=0, le=100),
	angle: float = Query(..., ge=10, le=90),
	series: bool = Query(False),
	d_min: float = Query(0.4, gt=0),
	d_max: float = Query(1.2, gt=0),
	d_step: float = Query(0.2, gt=0),
) -> OrificeParams:
	p = OrificeParams(
		socket_a_id, socket_a_wall, socket_a_depth, socket_b_id, socket_b_wall, socket_b_depth,
		orifice_diameter, orifice_length, angle, series, d_min, d_max, d_step,
	)
	try:
		validate(p)  # cheap; also limits a series to 50 orifices
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _key(p: OrificeParams) -> tuple:
	values = vars(p).copy()
	if p.series:  # the single diameter does not matter for a series, nor the range for one connector
		values.update(orifice_diameter=None)
	else:
		values.update(d_min=None, d_max=None, d_step=None)
	return tuple(values.values())


def _file(p: OrificeParams, kind: str) -> bytes:
	return cache.file(_key(p), p, kind, FILES[kind])


def _filename(p: OrificeParams, ext: str) -> str:
	ds = diameters(p)
	which = f"{ds[0]:g}-{ds[-1]:g}mm_x{len(ds)}" if len(ds) > 1 else f"{ds[0]:g}mm"
	return f"orifice_{which}.{ext}"


def warm() -> None:
	warm_entry(cache, _key(DEFAULT), DEFAULT, FILES)


@router.get("/info")
def info_route(p: OrificeParams = Depends(_params)) -> dict:
	ds = diameters(p)
	return {"diameters": ds, "length": round(section(p, ds[0]).top, 2), "summary": describe(p)}


@router.get("/preview.glb")
def preview_glb(p: OrificeParams = Depends(_params)):
	return glb_response(_file(p, "glb"))


@router.get("/export.3mf")
def export_3mf(p: OrificeParams = Depends(_params)):
	return download_response(_file(p, "3mf"), _filename(p, "3mf"))


@router.get("/export.step")
def export_step_route(p: OrificeParams = Depends(_params)):
	return download_response(_file(p, "step"), _filename(p, "step"))
