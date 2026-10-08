"""API routes for the Sanding Disc Rack generator: layout plan, glTF preview of the
assembly, all printable parts as a zip of 3MF or STEP files, and the Multiconnect slot
test piece.

All endpoints take the grit list (`grits`, e.g. "P80:50, P120:12") and the rack
parameters as query parameters. Built racks and their files are cached (see
web_app/model_cache.py) and the default rack is made when the server starts. Limits
keep a public server from being asked for arbitrarily large builds.
"""

import io
import zipfile

from build123d import Pos
from fastapi import APIRouter, Depends, HTTPException, Query

from cad_common.mesh_export import MeshObject, MeshPart, to_3mf
from sanding_rack_app import multiconnect
from sanding_rack_app.sanding_rack_model import (
	DEFAULT_GRITS, RackParams, build_rack, compartment_width, parse_grits, plan_layout, print_parts,
)
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes
from web_app.model_cache import ModelCache, warm as warm_entry
from web_app.progress import report

router = APIRouter()

_MAX_GRITS = 40
_MAX_COUNT = 500
_MAX_TRAYS = 10
_TOLERANCE = 0.02  # mm, for the 3MF meshes (only the curved cradle and the slots are affected)


def _params(
	grits: str = Query(..., max_length=2000),
	disc_diameter: float = Query(150.0, ge=50, le=300),
	disc_thickness: float = Query(1.0, ge=0.2, le=5),
	tray_units: int = Query(9, ge=2, le=12),
	back_height: float = Query(100.0, ge=40, le=200),
	lip_height: float = Query(25.0, ge=10, le=70),
	groove_pitch: float = Query(5.0, ge=3, le=20),
	slot_scale: float = Query(1.0, ge=0.9, le=1.1),
):
	p = RackParams(
		disc_diameter=disc_diameter, disc_thickness=disc_thickness, tray_units=tray_units,
		back_height=back_height, lip_height=lip_height, groove_pitch=groove_pitch, slot_scale=slot_scale,
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


def _readme(model) -> str:
	n_div = sum(len(t.divider_grooves) for t in model.trays)
	return (
		f"Print the tray {len(model.trays)}x, the divider {n_div}x and the labels once.\n"
		"Tray: upright (floor on the bed). Divider: flat. Labels: on their side.\n"
		"Print the slot test piece first if you have not checked the Multiconnect fit yet.\n"
	)


def _label_sheet(parts: dict) -> list[MeshObject]:
	"""All label clips (already in print orientation) side by side, as separate objects."""
	objects, x, y, row_h = [], 0.0, 0.0, 0.0
	for name, part in parts.items():
		if not name.startswith("label_"):
			continue
		bb = part.bounding_box()
		if x and x + bb.size.X > 200:
			x, y, row_h = 0.0, y + row_h + 4, 0.0
		placed = Pos(x - bb.min.X, y - bb.min.Y, 0) * part
		objects.append(MeshObject(name, [MeshPart(name[len("label_"):], placed, (0.95, 0.75, 0.2))]))
		x += bb.size.X + 4
		row_h = max(row_h, bb.size.Y)
	return objects


def _zip_3mf(args, model) -> bytes:
	parts = print_parts(model)
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
		report("Writing the 3MF files (1 of 4: tray)")
		zf.writestr("sanding_rack_tray.3mf", to_3mf([MeshObject("tray", [MeshPart("tray", parts["tray"])])], _TOLERANCE))
		report("Writing the 3MF files (2 of 4: divider)")
		zf.writestr("sanding_rack_divider.3mf", to_3mf([MeshObject("divider", [MeshPart("divider", parts["divider"])])], _TOLERANCE))
		report("Writing the 3MF files (3 of 4: labels)")
		zf.writestr("sanding_rack_labels.3mf", to_3mf(_label_sheet(parts), _TOLERANCE))
		report("Writing the 3MF files (4 of 4: slot test)")
		test = multiconnect.slot_test_piece(scale=args[1].slot_scale)
		zf.writestr("sanding_rack_slot_test.3mf", to_3mf([MeshObject("slot test", [MeshPart("slot test", test)])], _TOLERANCE))
		zf.writestr("README.txt", _readme(model))
	return buf.getvalue()


def _zip_step(args, model) -> bytes:
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
		parts = {"assembly": model.assembly, **print_parts(model)}
		for i, (name, part) in enumerate(parts.items(), 1):
			report(f"Writing the STEP files ({i} of {len(parts) + 1}: {name})")
			zf.writestr(f"sanding_rack_{name}.step", step_bytes(part))
		report(f"Writing the STEP files ({len(parts) + 1} of {len(parts) + 1}: slot test)")
		zf.writestr("sanding_rack_slot_test.step", step_bytes(multiconnect.slot_test_piece(scale=args[1].slot_scale)))
		zf.writestr("README.txt", _readme(model))
	return buf.getvalue()


def _key(args) -> tuple:
	grits, p = args
	return (tuple((g.name, g.count) for g in grits), tuple(vars(p).values()))


def _makers(args) -> dict:
	return {
		"glb": lambda m: glb_bytes(m.assembly, linear_deflection=0.2, angular_deflection=0.3),
		"3mf_zip": lambda m: _zip_3mf(args, m),
		"step_zip": lambda m: _zip_step(args, m),
	}


cache = ModelCache("sanding_rack", lambda args: build_rack(*args), size=4)


def _file(args, kind: str) -> bytes:
	_plan(args)  # cheap checks before the expensive build
	return cache.file(_key(args), args, kind, _makers(args)[kind])


def warm() -> None:
	args = (parse_grits(DEFAULT_GRITS), RackParams())  # matches the defaults in sanding-rack.html
	warm_entry(cache, _key(args), args, _makers(args))


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
def preview_glb(args=Depends(_params)):
	return glb_response(_file(args, "glb"))


@router.get("/export-3mf.zip")
def export_3mf_zip(args=Depends(_params)):
	return download_response(_file(args, "3mf_zip"), "sanding_rack_3mf.zip")


@router.get("/export.zip")
def export_step_zip(args=Depends(_params)):
	return download_response(_file(args, "step_zip"), "sanding_rack_step.zip")


@router.get("/slot-test.3mf")
def slot_test_3mf(slot_scale: float = Query(1.0, ge=0.9, le=1.1)):
	test = multiconnect.slot_test_piece(scale=slot_scale)
	return download_response(to_3mf([MeshObject("slot test", [MeshPart("slot test", test)])], _TOLERANCE), "multiconnect_slot_test.3mf")


@router.get("/slot-test.step")
def slot_test_step(slot_scale: float = Query(1.0, ge=0.9, le=1.1)):
	return download_response(step_bytes(multiconnect.slot_test_piece(scale=slot_scale)), "multiconnect_slot_test.step")
