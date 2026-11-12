"""API routes for the Game Tiles generator (game_tiles_app/game_tile_model.py): defaults with
the list of tile types and shapes, a summary with the colours (filaments) needed, glTF
preview, 3MF and STEP, a thumbnail, and the list of stored tiles (/stored).

All endpoints except /defaults take the tile parameters as query parameters: tile_type,
shape, size, length (rectangle only), thickness, inlay_depth, count, seed and base_colour
(and wall and clearance for connectors). The files
hold one body per colour, named after it. Built models and their files are cached (see
web_app/model_cache.py); the default tile is made when the server starts.
"""

import io
import json
import re
import zipfile

import numpy as np
from dataclasses import asdict
from functools import lru_cache

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response

from cad_common.bambu import BambuPrinter, PRINTERS, printer as bambu_printer
from cad_common.mesh_export import meshes_of, meshes_to_3mf, meshes_to_glb
from cad_common.mesh_fuzz import fuzz, hills, subdivide
from cad_common.thumbnail import render_png
from game_tiles_app.game_tile_model import (
	DEFAULT_ROUGH_SIZE, HILLS, MAX_COUNT, PALETTE, ROUGHNESS, SMOOTH_ABOVE_TOP, hilliness, roughness, SHAPES, TILE_TYPES, TileParams, _layout, build_tiles, colors_used, describe,
	outline_points, validate,
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
	wall: float = Query(TileParams.wall, gt=0, le=100),  # connectors only
	clearance: float = Query(TileParams.clearance, ge=0, le=100),  # connectors only
	base_colour: str = Query(TileParams.base_colour, max_length=20),  # "" = the tile's own base colour
	rough_depth: float = Query(TileParams.rough_depth, ge=-1, le=100),  # negative: the type's own
	rough_size: float = Query(TileParams.rough_size, ge=-1, le=1000),
	hill_height: float = Query(TileParams.hill_height, ge=-1, le=100),
) -> TileParams:
	if tile_type == "connector":  # the connector with a ledge is gone: old links get the one that replaced it
		tile_type = "connector_corners"
	if shape != "rectangle":
		length = DEFAULT.length  # not used; keeps the cache key unique
	if tile_type.startswith("connector"):  # thickness, colour depth and base colour don't apply
		thickness, inlay_depth, base_colour = DEFAULT.thickness, DEFAULT.inlay_depth, DEFAULT.base_colour
		rough_depth, rough_size, hill_height = DEFAULT.rough_depth, DEFAULT.rough_size, DEFAULT.hill_height
	else:  # wall and clearance only apply to connectors
		wall, clearance = DEFAULT.wall, DEFAULT.clearance
	# The type's own values given explicitly make the same tile: store them as "own" (-1), so
	# it is one cache entry.
	own_rough = ROUGHNESS.get(tile_type, (0.0, DEFAULT_ROUGH_SIZE))
	own_hills = HILLS.get(tile_type, (0.0,))
	if rough_depth < 0 or rough_depth == own_rough[0]:
		rough_depth = -1.0
	if rough_size <= 0 or rough_size == own_rough[1] or rough_depth == 0 or (rough_depth < 0 and own_rough[0] == 0):
		rough_size = -1.0  # also when there is no rough top to size
	if hill_height < 0 or hill_height == own_hills[0]:
		hill_height = -1.0
	p = TileParams(tile_type, shape, size, length, thickness, inlay_depth, count, seed, wall, clearance, base_colour,
				   rough_depth, rough_size, hill_height)
	try:
		validate(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _key(p: TileParams) -> tuple:
	return tuple(vars(p).values())


def _makers(p: TileParams, bambu: BambuPrinter | None = None) -> dict:
	"""How to make each file: types with a rough surface get their meshes roughened (3MF and
	preview); the STEP file always has the exact, smooth geometry. With `bambu` (a printer) the
	3MF is a Bambu Studio project for it, with the filament colours."""
	rough = roughness(p)
	hilly = hilliness(p)

	def meshes(model, tolerance):
		out = meshes_of(model, tolerance, 0.2)
		if hilly is not None:  # gentle hills first, then the rough surface on top of them
			pts = outline_points(p)
			fade = min(8.0, 0.25 * min(float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1]))))
			for m in out:
				m.vertices, m.triangles = hills(m.vertices, m.triangles, *hilly, top=p.thickness, outline=pts,
												centres=_layout(p), fade=fade, seed=p.seed)
		if rough is not None:
			amplitude, wavelength, mode = rough
			smooth = SMOOTH_ABOVE_TOP.get(p.tile_type, ())
			for m in out:  # the same seed for every body, so touching bodies stay together
				m.vertices, m.triangles = fuzz(m.vertices, m.triangles, amplitude, wavelength, mode, top=p.thickness, seed=p.seed,
											   smooth_above=p.thickness if m.name in smooth else None)
		return out

	def png(model):
		# The thumbnail sorts whole triangles by depth: split the large flat ones (e.g. the top of
		# the bottom body, inside the tile) so none is drawn over what stands in front of it.
		out = meshes(model, 0.05)
		for m in out:
			m.vertices, m.triangles = subdivide(np.asarray(m.vertices, dtype=np.float64), np.asarray(m.triangles, dtype=np.int64),
												2.0, lambda v: np.ones(len(v), dtype=bool))
		return render_png(out)

	if rough is None and hilly is None:
		return {**FILES, "png": png, "3mf": lambda part: threemf_bytes(part, "game_tile", tolerance=0.01, bambu=bambu)}
	return {
		"png": png,
		"glb": lambda model: meshes_to_glb(meshes(model, 0.02)),
		"3mf": lambda model: meshes_to_3mf("game_tile", meshes(model, 0.01), bambu),
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
		"types": [{"id": k, "title": t.title, "group": t.group, "description": t.description,
				   # the type's own rough top and hills (mm), shown when those fields are left empty
				   "rough_depth": ROUGHNESS[k][0] if k in ROUGHNESS else 0, "rough_size": ROUGHNESS[k][1] if k in ROUGHNESS else DEFAULT_ROUGH_SIZE,
				   "hill_height": HILLS[k][0] if k in HILLS else 0} for k, t in TILE_TYPES.items()],
		"shapes": list(SHAPES),
		"colours": list(PALETTE),
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
			for i, name in enumerate(colors_used(TileParams(tile_type=type_id, shape=shape, base_colour=""))):
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


@router.get("/printers")
def printers_route() -> list[dict]:
	"""The Bambu Lab printers a 3MF can be a Bambu Studio project for (see export.3mf)."""
	return [{"id": pid, "name": f"Bambu Lab {b.name}"} for pid, b in PRINTERS.items()]


@router.get("/export.3mf")
def export_3mf(p: TileParams = Depends(_params), printer: str = Query("", max_length=20)):
	"""printer: a Bambu Lab printer id (see /printers) makes the file a Bambu Studio project for
	that printer, which opens with the filament colours; empty for a plain 3MF."""
	try:
		bambu = bambu_printer(printer)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	if bambu is None:
		return download_response(_file(p, "3mf"), _filename(p, "3mf"))
	try:
		data = cache.file(_key(p), p, f"3mf-{printer}", _makers(p, bambu)["3mf"])
	except ValueError as exc:  # e.g. too large for the printer's plate
		raise HTTPException(status_code=400, detail=str(exc))
	return download_response(data, _filename(p, "3mf"))


@router.get("/export.step")
def export_step_route(p: TileParams = Depends(_params)):
	return download_response(_file(p, "step"), _filename(p, "step"))


def warm() -> None:
	warm_entry(cache, _key(DEFAULT), DEFAULT, _makers(DEFAULT))
	_colour_use()
