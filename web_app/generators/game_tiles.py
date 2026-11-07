"""API routes for the Game Tiles generator (game_tiles_app/game_tile_model.py): defaults with
the list of tile types and shapes, a summary with the colours (filaments) needed, glTF
preview, 3MF and STEP.

All endpoints except /defaults take the tile parameters as query parameters: tile_type,
shape, size, length (rectangle only), thickness, inlay_depth, count and seed. The files
hold one body per colour, named after it. Built models and their files are cached (see
web_app/model_cache.py); the default tile is made when the server starts.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from game_tiles_app.game_tile_model import (
	MAX_COUNT, PALETTE, SHAPES, TILE_TYPES, TileParams, build_tiles, colors_used, describe, validate,
)
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()

cache = ModelCache("game_tiles", build_tiles, size=8)
DEFAULT = TileParams()
FILES = {
	"glb": lambda part: glb_bytes(part, linear_deflection=0.02, angular_deflection=0.2),
	"3mf": lambda part: threemf_bytes(part, "game_tile", tolerance=0.01),
	"step": step_bytes,
}


def _params(
	tile_type: str = Query(..., max_length=20),
	shape: str = Query(..., max_length=20),
	size: float = Query(..., gt=0, le=1000),
	length: float = Query(60.0, gt=0, le=1000),
	thickness: float = Query(..., gt=0, le=100),
	inlay_depth: float = Query(..., gt=0, le=100),
	count: int = Query(1, ge=1, le=MAX_COUNT),
	seed: int = Query(1, ge=0, le=1_000_000),
) -> TileParams:
	if shape != "rectangle":
		length = DEFAULT.length  # not used; keeps the cache key unique
	p = TileParams(tile_type, shape, size, length, thickness, inlay_depth, count, seed)
	try:
		validate(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _key(p: TileParams) -> tuple:
	return tuple(vars(p).values())


def _file(p: TileParams, kind: str) -> bytes:
	return cache.file(_key(p), p, kind, FILES[kind])


def _filename(p: TileParams, ext: str) -> str:
	count = f"_x{p.count}" if p.count > 1 else ""
	return f"game_tile_{p.tile_type}_{p.shape}_{p.size:g}mm{count}.{ext}"


def _hex(rgb) -> str:
	return "#" + "".join(f"{round(255 * c):02x}" for c in rgb)


@router.get("/defaults")
def defaults_route() -> dict:
	"""Starting values (by input id), plus the tile types (grouped) and shapes for the drop-downs."""
	return {
		**asdict(DEFAULT),
		"types": [{"id": k, "title": t.title, "group": t.group, "description": t.description} for k, t in TILE_TYPES.items()],
		"shapes": list(SHAPES),
	}


@router.get("/info")
def info(p: TileParams = Depends(_params)) -> dict:
	return {
		"summary": describe(p),
		"colors": [{"name": name.replace("_", " "), "hex": _hex(PALETTE[name])} for name in colors_used(p)],
	}


@router.get("/preview.glb")
def preview(p: TileParams = Depends(_params)):
	return glb_response(_file(p, "glb"))


@router.get("/export.3mf")
def export_3mf(p: TileParams = Depends(_params)):
	return download_response(_file(p, "3mf"), _filename(p, "3mf"))


@router.get("/export.step")
def export_step_route(p: TileParams = Depends(_params)):
	return download_response(_file(p, "step"), _filename(p, "step"))


def warm() -> None:
	warm_entry(cache, _key(DEFAULT), DEFAULT, FILES)
