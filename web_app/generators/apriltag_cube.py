"""API routes for the AprilTag Cube generator: build123d model -> glTF preview, 3MF and
STEP.

All endpoints take tag_ids, size, depth, and optional axes, per_face, bottom_label and
label as query parameters. With per_face=true, tag_ids must hold five comma-separated ids
for one cube: the four side faces counterclockwise as seen from above (+X, +Y, -X, -Y),
then the top. Otherwise it holds one or more ids, each giving a cube with that tag on all
five tag faces; several cubes are laid out in the smallest square grid, 2 mm apart. axes
adds red +X / green +Y arrows on the floor beside the cube(s). bottom_label inlays a label
in the bottom face: label, or when that is empty the default (the tag id, "World frame"
for ids 25-29, or the five ids); in a grid each cube gets its own id. The STEP and 3MF files hold the bodies
("white", "black", and "red"/"green" with axes) as separate parts; the glTF preview
keeps them as separate nodes so the frontend can colour them. Built models and their
files are cached (see web_app/model_cache.py); the default cube is made when the
server starts.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from apriltag_cube_app.apriltag_cube_model import (
	WORLD_FRAME_IDS, WORLD_FRAME_LABEL, build_apriltag_cube, build_apriltag_cube_grid, parse_tag_ids,
)
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()


def _build(key: tuple):
	ids, size, depth, axes, per_face, bottom_label, label = key
	if not bottom_label:
		label = ""
	if per_face or len(ids) == 1:
		return build_apriltag_cube(list(ids), size, depth, axes=axes, label=label)
	return build_apriltag_cube_grid(list(ids), size, depth, axes=axes, labels=bottom_label)


cache = ModelCache("apriltag_cube", _build)
# tag ids, size, depth, axes, per face, bottom label on, label text (None: default label);
# the page loads them from /defaults
DEFAULT = ((0,), 40.0, 1.0, False, False, True, None)
DEFAULT_FACE_IDS = (0, 1, 2, 3, 4)  # starting value of the page's "five different tags" field
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
	bottom_label: bool = Query(True),
	label: str = Query("", max_length=40),
) -> tuple:
	try:
		ids = parse_tag_ids(tag_ids, per_face=per_face)  # also validates the ID range
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	if not bottom_label or (not per_face and len(ids) > 1):
		label = ""  # not used; keeps the cache key unique
	return (tuple(ids), size, depth, axes, per_face, bottom_label, label.strip() or None)


def _filename(key: tuple, ext: str) -> str:
	return f'apriltag_cube_{"-".join(f"{i:02d}" for i in key[0])}.{ext}'


def _file(key: tuple, kind: str) -> bytes:
	try:
		return cache.file(key, key, kind, FILES[kind])
	except ValueError as exc:  # e.g. depth too large for the size
		raise HTTPException(status_code=400, detail=str(exc))


def warm() -> None:
	warm_entry(cache, DEFAULT, DEFAULT, FILES)


@router.get("/defaults")
def defaults_route() -> dict:
	"""The page's starting values (by input id), so they are defined only here."""
	ids, size, depth, axes, per_face, bottom_label, label = DEFAULT
	return {
		"tag_id": ",".join(map(str, ids)) if not per_face else "0",
		"tag_ids": ",".join(map(str, ids if per_face else DEFAULT_FACE_IDS)),
		"size": size, "depth": depth, "axes": axes, "mode_same": not per_face, "mode_faces": per_face,
		"mode_world": False, "bottom_label": bottom_label, "label": label or "",
		"world_frame_ids": ",".join(map(str, WORLD_FRAME_IDS)), "world_frame_label": WORLD_FRAME_LABEL,
	}


@router.get("/preview.glb")
def preview_glb(key: tuple = Depends(_key)):
	return glb_response(_file(key, "glb"))


@router.get("/export.3mf")
def export_3mf(key: tuple = Depends(_key)):
	return download_response(_file(key, "3mf"), _filename(key, "3mf"))


@router.get("/export.step")
def export_step_route(key: tuple = Depends(_key)):
	return download_response(_file(key, "step"), _filename(key, "step"))
