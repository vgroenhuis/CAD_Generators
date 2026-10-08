"""API routes for the Sanding Disc Rack generator: layout plan, glTF preview of the
assembly, a zip with all parts as STEP files, and the Multiconnect slot test piece.

All endpoints take the grit list (`grits`, e.g. "P80:50, P120:12") and the rack
parameters as query parameters and are stateless. Built racks are cached so the
download right after a preview reuses the preview's model. Limits keep a public
server from being asked for arbitrarily large builds.
"""

import io
import tempfile
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path

from build123d import export_gltf, export_step
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from sanding_rack_app import multiconnect
from sanding_rack_app.sanding_rack_model import (
	RackParams, build_rack, compartment_width, parse_grits, plan_layout, print_parts,
)

router = APIRouter()

_MAX_GRITS = 40
_MAX_COUNT = 500
_MAX_TRAYS = 10
_CACHE_SIZE = 4

_cache: "OrderedDict[tuple, object]" = OrderedDict()
_cache_lock = threading.Lock()


def _params(
	grits: str = Query(..., max_length=2000),
	disc_diameter: float = Query(150.0, ge=50, le=300),
	disc_thickness: float = Query(1.0, ge=0.2, le=5),
	tray_units: int = Query(9, ge=2, le=12),
	back_height: float = Query(100.0, ge=40, le=200),
	groove_pitch: float = Query(5.0, ge=3, le=20),
	slot_scale: float = Query(1.0, ge=0.9, le=1.1),
):
	p = RackParams(
		disc_diameter=disc_diameter, disc_thickness=disc_thickness, tray_units=tray_units,
		back_height=back_height, groove_pitch=groove_pitch, slot_scale=slot_scale,
	)
	try:
		parsed = parse_grits(grits)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	if len(parsed) > _MAX_GRITS:
		raise HTTPException(status_code=400, detail=f"At most {_MAX_GRITS} grits.")
	if any(g.count > _MAX_COUNT for g in parsed):
		raise HTTPException(status_code=400, detail=f"At most {_MAX_COUNT} discs per grit.")
	return parsed, p


def _plan(args):
	grits, p = args
	try:
		trays = plan_layout(grits, p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	if len(trays) > _MAX_TRAYS:
		raise HTTPException(status_code=400, detail=f"This needs {len(trays)} trays; at most {_MAX_TRAYS} at once.")
	return trays


def _build(args):
	_plan(args)  # cheap checks before the expensive build
	grits, p = args
	key = (tuple((g.name, g.count) for g in grits), tuple(vars(p).values()))
	with _cache_lock:
		if key in _cache:
			_cache.move_to_end(key)
			return _cache[key]
	model = build_rack(grits, p)
	with _cache_lock:
		_cache[key] = model
		while len(_cache) > _CACHE_SIZE:
			_cache.popitem(last=False)
	return model


@router.get("/layout")
def layout_route(args=Depends(_params)) -> dict:
	grits, p = args
	trays = _plan(args)
	return {
		"trays": [
			{
				"compartments": [
					{"grit": c.grit.name, "count": c.grit.count, "width": round(c.x1 - c.x0, 1),
					 "needed": round(compartment_width(c.grit, p), 1)}
					for c in t.compartments
				],
				"divider_grooves": [k + 1 for k in t.divider_grooves],
				"spare": round(t.free, 1),
			}
			for t in trays
		],
		"tray_count": len(trays),
		"divider_count": sum(len(t.divider_grooves) for t in trays),
		"tray_width": round(p.tray_units * 25 - 0.4, 1),
	}


@router.get("/preview.glb")
def preview_glb(args=Depends(_params)) -> Response:
	model = _build(args)
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir) / "sanding_rack.glb"
		export_gltf(model.assembly, str(tmp_path), binary=True, linear_deflection=0.2, angular_deflection=0.3)
		data = tmp_path.read_bytes()
	return Response(content=data, media_type="model/gltf-binary")


@router.get("/export.zip")
def export_zip(args=Depends(_params)) -> Response:
	model = _build(args)
	buf = io.BytesIO()
	with tempfile.TemporaryDirectory() as tmp_dir, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
		files = {"assembly": model.assembly, **print_parts(model)}
		for name, part in files.items():
			path = Path(tmp_dir) / f"sanding_rack_{name}.step"
			export_step(part, str(path))
			zf.write(path, path.name)
		n_div = sum(len(t.divider_grooves) for t in model.trays)
		zf.writestr(
			"README.txt",
			f"Print the tray {len(model.trays)}x, the divider {n_div}x and each label once.\n"
			"Tray: upright (floor on the bed). Divider: flat. Labels: on their side.\n"
			"Print sanding_rack_slot_test first if you have not checked the Multiconnect fit yet.\n",
		)
		test_path = Path(tmp_dir) / "sanding_rack_slot_test.step"
		export_step(multiconnect.slot_test_piece(scale=args[1].slot_scale), str(test_path))
		zf.write(test_path, test_path.name)
	return Response(
		content=buf.getvalue(),
		media_type="application/zip",
		headers={"Content-Disposition": 'attachment; filename="sanding_rack.zip"'},
	)


@router.get("/slot-test.step")
def slot_test(slot_scale: float = Query(1.0, ge=0.9, le=1.1)) -> Response:
	with tempfile.TemporaryDirectory() as tmp_dir:
		path = Path(tmp_dir) / "multiconnect_slot_test.step"
		export_step(multiconnect.slot_test_piece(scale=slot_scale), str(path))
		data = path.read_bytes()
	return Response(
		content=data,
		media_type="application/step",
		headers={"Content-Disposition": 'attachment; filename="multiconnect_slot_test.step"'},
	)

