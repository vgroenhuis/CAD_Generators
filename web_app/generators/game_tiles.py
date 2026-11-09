"""API routes for the Game Tiles generator (game_tiles_app/game_tile_model.py): defaults with
the list of tile types and shapes, a summary with the colours (filaments) needed, glTF
preview, 3MF and STEP, a thumbnail, and the list of stored tiles (/stored).

All endpoints except /defaults take the tile parameters as query parameters: tile_type,
shape, size, length (rectangle only), thickness, inlay_depth, count and seed. The files
hold one body per colour, named after it. Built models and their files are cached (see
web_app/model_cache.py); the default tile is made when the server starts.
"""

import io
import json
import re
import zipfile
from dataclasses import asdict
from functools import lru_cache

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response

from cad_common.mesh_export import meshes_of, meshes_to_3mf, meshes_to_glb
from cad_common.mesh_fuzz import fuzz
from cad_common.thumbnail import render_png
from game_tiles_app.game_tile_model import (
	MAX_COUNT, PALETTE, ROUGHNESS, SHAPES, TILE_TYPES, TileParams, build_tiles, colors_used, describe, validate,
)
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, disk, warm as warm_entry

router = APIRouter()


def _meta(p: TileParams) -> dict:
	"""What the list of stored tiles shows about a tile."""
	return {"params": asdict(p), "title": TILE_TYPES[p.tile_type].title, "colours": colors_used(p)}


cache = ModelCache("game_tiles", build_tiles, size=8, meta=_meta)
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
	thickness: float = Query(..., gt=0),  # no upper limit: a tile can be a block or cube
	inlay_depth: float = Query(..., gt=0, le=100),
	count: int = Query(1, ge=1, le=MAX_COUNT),
	seed: int = Query(1, ge=0, le=1_000_000),
) -> TileParams:
	if shape != "rectangle":
		length = DEFAULT.length  # not used; keeps the cache key unique
	if tile_type == "connector":  # thickness and colour depth don't apply
		thickness, inlay_depth = DEFAULT.thickness, DEFAULT.inlay_depth
	p = TileParams(tile_type, shape, size, length, thickness, inlay_depth, count, seed)
	try:
		validate(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _key(p: TileParams) -> tuple:
	return tuple(vars(p).values())


def _makers(p: TileParams) -> dict:
	"""How to make each file: types with a rough surface get their meshes roughened (3MF and
	preview); the STEP file always has the exact, smooth geometry."""
	rough = ROUGHNESS.get(p.tile_type)

	def meshes(model, tolerance):
		out = meshes_of(model, tolerance, 0.2)
		if rough is not None:
			amplitude, wavelength, mode = rough
			for m in out:  # the same seed for every body, so touching bodies stay together
				m.vertices, m.triangles = fuzz(m.vertices, m.triangles, amplitude, wavelength, mode, top=p.thickness, seed=p.seed)
		return out

	png = lambda model: render_png(meshes(model, 0.05))  # noqa: E731
	if rough is None:
		return {**FILES, "png": png}
	return {
		"png": png,
		"glb": lambda model: meshes_to_glb(meshes(model, 0.02)),
		"3mf": lambda model: meshes_to_3mf("game_tile", meshes(model, 0.01)),
		"step": step_bytes,
	}


def _file(p: TileParams, kind: str) -> bytes:
	return cache.file(_key(p), p, kind, _makers(p)[kind])


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


@router.get("/mesh-stats")
def mesh_stats(p: TileParams = Depends(_params)) -> dict:
	"""Size of the print mesh (the 3MF file, rough surfaces included): triangles and vertices,
	in total and per colour. Makes the 3MF file if needed (it is cached for the download)."""
	model = zipfile.ZipFile(io.BytesIO(_file(p, "3mf"))).read("3D/3dmodel.model").decode()
	per_colour = []
	for name, mesh in re.findall(r'<object id="\d+" type="model" pid="1" pindex="\d+" name="([^"]*)"><mesh>(.*?)</mesh>', model, re.S):
		per_colour.append({"name": name.replace("_", " "), "triangles": mesh.count("<triangle "), "vertices": mesh.count("<vertex ")})
	return {
		"triangles": sum(c["triangles"] for c in per_colour),
		"vertices": sum(c["vertices"] for c in per_colour),
		"colours": per_colour,
	}


@router.get("/preview.glb")
def preview(background: BackgroundTasks, p: TileParams = Depends(_params)):
	data = _file(p, "glb")
	background.add_task(_file, p, "png")  # the thumbnail for the list of stored tiles, after answering
	return glb_response(data)


@router.get("/thumbnail.png")
def thumbnail(p: TileParams = Depends(_params)):
	return Response(content=_file(p, "png"), media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@router.get("/palette")
def palette() -> dict:
	"""Colour name -> preview colour (#rrggbb), for the swatches in the list of stored tiles."""
	return {name: _hex(rgb) for name, rgb in PALETTE.items()}


@lru_cache(maxsize=1)
def _colour_use() -> tuple:
	"""Every colour any tile type uses (in any shape), with the types using it, as the base or
	not. Building every pattern takes about a minute, so this is done once per code version
	(when the server starts, see warm) and kept in the disk cache."""
	stored = disk.get("game_tiles_colours", "all", "list")
	if stored is not None:
		return tuple(json.loads(stored))
	use: dict[str, dict] = {}
	for type_id, t in TILE_TYPES.items():
		for shape in SHAPES:
			for i, name in enumerate(colors_used(TileParams(tile_type=type_id, shape=shape))):
				entry = use.setdefault(name, {"types": {}, "base": set()})
				entry["types"][type_id] = t.title
				if i == 0:
					entry["base"].add(t.title)
	order = list(PALETTE)
	result = tuple(
		{"name": name.replace("_", " "), "id": name, "hex": _hex(PALETTE[name]), "types": list(e["types"].values()),
		 "base_of": sorted(e["base"])}
		for name, e in sorted(use.items(), key=lambda kv: order.index(kv[0]))
	)
	disk.put("game_tiles_colours", "all", "list", json.dumps(result).encode())
	return result


@router.get("/colours")
def colours() -> dict:
	"""All filament colours the tile types use, with the types using each (see _colour_use)."""
	return {"colours": list(_colour_use())}


@router.get("/stored")
def stored() -> dict:
	"""The tiles stored on disk (made by the current code), most recently used first: their
	parameters, title, colours, which files are ready (kind -> bytes) and when they were made
	and last used (Unix time); and the space used on disk (bytes): by the listed tiles, by all
	game tile files (older versions included), by the whole store, and its limit."""
	tiles = []
	for e in disk.entries(cache.name):
		meta = e["meta"]
		if "params" not in meta:
			continue
		tiles.append({**meta, "files": e["files"], "created": e["created"], "used": e["used"]})
	listed = sum(sum(t["files"].values()) for t in tiles)
	return {
		"enabled": disk.enabled, "tiles": tiles,
		"bytes": {"listed": listed, "game_tiles": disk.usage(cache.name), "store": disk.usage(), "limit": disk.limit},
	}


@router.get("/export.3mf")
def export_3mf(p: TileParams = Depends(_params)):
	return download_response(_file(p, "3mf"), _filename(p, "3mf"))


@router.get("/export.step")
def export_step_route(p: TileParams = Depends(_params)):
	return download_response(_file(p, "step"), _filename(p, "step"))


def warm() -> None:
	warm_entry(cache, _key(DEFAULT), DEFAULT, _makers(DEFAULT))
	_colour_use()
