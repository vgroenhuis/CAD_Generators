"""API routes for the AprilTag Cube generator: build123d model -> glTF preview, 3MF and
STEP.

All endpoints take tag_ids, size, depth, and optional axes and per_face flags as query
parameters. With per_face=true, tag_ids must hold six comma-separated ids in die order
(faces 1, 2, 3 along +X, +Y, +Z and 4, 5, 6 opposite to 3, 2, 1) for one cube.
Otherwise it holds one or more ids, each giving a cube with that tag on all faces;
several cubes are laid out in the smallest square grid, 2 mm apart. axes adds red +X /
green +Y arrows on the floor beside the cube(s). The STEP and 3MF files hold the bodies
("white", "black", and "red"/"green" with axes) as separate parts; the glTF preview
keeps them as separate nodes so the frontend can colour them. Built models and their
files are cached (see web_app/model_cache.py); the default cube is made when the
server starts.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from apriltag_cube_app.apriltag_cube_model import build_apriltag_cube, build_apriltag_cube_grid, parse_tag_ids
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()


def _build(key: tuple):
	ids, size, depth, axes, per_face = key
	if per_face:
		return build_apriltag_cube(list(ids), size, depth, axes=axes)
	return build_apriltag_cube_grid(list(ids), size, depth, axes=axes)


cache = ModelCache("apriltag_cube", _build)
DEFAULT = ((0,), 40.0, 1.0, False, False)  # matches the defaults in apriltag-cube.html
FILES = {
	"glb": glb_bytes,
	"3mf": lambda cube: threemf_bytes(cube, "apriltag_cube"),
	"step": step_bytes,
}


def _key(
	tag_ids: str = Query(...),
	size: float = Query(..., gt=0),
	depth: float = Query(..., gt=0),
	axes: bool = Query(False),
	per_face: bool = Query(False),
) -> tuple:
	try:
		ids = parse_tag_ids(tag_ids, per_face=per_face)  # also validates the ID range
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return (tuple(ids), size, depth, axes, per_face)


def _filename(key: tuple, ext: str) -> str:
	return f'apriltag_cube_{"-".join(f"{i:02d}" for i in key[0])}.{ext}'


def _file(key: tuple, kind: str) -> bytes:
	try:
		return cache.file(key, key, kind, FILES[kind])
	except ValueError as exc:  # e.g. depth too large for the size
		raise HTTPException(status_code=400, detail=str(exc))


def warm() -> None:
	warm_entry(cache, DEFAULT, DEFAULT, FILES)


@router.get("/preview.glb")
def preview_glb(key: tuple = Depends(_key)):
	return glb_response(_file(key, "glb"))


@router.get("/export.3mf")
def export_3mf(key: tuple = Depends(_key)):
	return download_response(_file(key, "3mf"), _filename(key, "3mf"))


@router.get("/export.step")
def export_step_route(key: tuple = Depends(_key)):
	return download_response(_file(key, "step"), _filename(key, "step"))
