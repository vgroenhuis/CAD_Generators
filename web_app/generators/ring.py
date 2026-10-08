"""API routes for the Ring generator: build123d model -> glTF preview, 3MF and STEP.

All endpoints take the same query parameters (od, id, thickness). Built models and
their files are cached (see web_app/model_cache.py); the default ring is made when
the server starts.
"""

from fastapi import APIRouter, HTTPException, Query

from ring_app.ring_model import build_ring
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()
cache = ModelCache("ring", lambda key: build_ring(*key))
DEFAULT = (20.0, 10.0, 5.0)  # matches the defaults in ring.html
FILES = {
	"glb": glb_bytes,
	"3mf": lambda part: threemf_bytes(part, "ring"),
	"step": step_bytes,
}


def _key(
	od: float = Query(..., gt=0),
	id: float = Query(..., gt=0),
	thickness: float = Query(..., gt=0),
) -> tuple:
	if od <= id:
		raise HTTPException(status_code=400, detail="OD must be greater than ID.")
	return (od, id, thickness)


def warm() -> None:
	warm_entry(cache, DEFAULT, DEFAULT, FILES)


@router.get("/preview.glb")
def preview_glb(od: float = Query(..., gt=0), id: float = Query(..., gt=0), thickness: float = Query(..., gt=0)):
	key = _key(od, id, thickness)
	return glb_response(cache.file(key, key, "glb", FILES["glb"]))


@router.get("/export.3mf")
def export_3mf(od: float = Query(..., gt=0), id: float = Query(..., gt=0), thickness: float = Query(..., gt=0)):
	key = _key(od, id, thickness)
	return download_response(cache.file(key, key, "3mf", FILES["3mf"]), "ring.3mf")


@router.get("/export.step")
def export_step_route(od: float = Query(..., gt=0), id: float = Query(..., gt=0), thickness: float = Query(..., gt=0)):
	key = _key(od, id, thickness)
	return download_response(cache.file(key, key, "step", FILES["step"]), "ring.step")
