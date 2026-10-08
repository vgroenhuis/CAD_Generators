"""API routes for the Powerbank Holder generator: build123d model -> glTF preview, 3MF
and STEP.

All endpoints take the same query parameters (width, height, length, hole_diameter,
outer_margin). Wall thickness, hole spacing, and hole count are derived server-side
(see powerbank_holder_model.py) and returned as response headers alongside
preview.glb, so the frontend can show them without a second request. Built models and
their files are cached (see web_app/model_cache.py); the default holder is made when
the server starts.
"""

from fastapi import APIRouter, Depends, Query

from powerbank_holder_app.powerbank_holder_model import (
	build_powerbank_holder,
	derive_hole_count,
	derive_hole_spacing,
	derive_wall_thickness,
)
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()


def _build(key: tuple):
	width, height, length, hole_diameter, outer_margin = key
	part = build_powerbank_holder(width, height, length=length, hole_diameter=hole_diameter, outer_margin=outer_margin)
	return {
		"part": part,
		"thickness": derive_wall_thickness(width, hole_diameter=hole_diameter, outer_margin=outer_margin),
		"hole_spacing": derive_hole_spacing(width, hole_diameter=hole_diameter, outer_margin=outer_margin),
		"hole_count": derive_hole_count(length, hole_diameter=hole_diameter),
	}


cache = ModelCache("powerbank_holder", _build)
DEFAULT = (25.0, 30.0, 120.0, 2.9, 1.0)  # matches the defaults in powerbank-holder.html
FILES = {
	"glb": lambda m: glb_bytes(m["part"]),
	"3mf": lambda m: threemf_bytes(m["part"], "powerbank_holder"),
	"step": lambda m: step_bytes(m["part"]),
}


def _key(
	width: float = Query(..., gt=0),
	height: float = Query(..., gt=0),
	length: float = Query(..., gt=0),
	hole_diameter: float = Query(..., gt=0),
	outer_margin: float = Query(..., gt=0),
) -> tuple:
	return (width, height, length, hole_diameter, outer_margin)


def warm() -> None:
	warm_entry(cache, DEFAULT, DEFAULT, FILES)


@router.get("/preview.glb")
def preview_glb(key: tuple = Depends(_key)):
	data = cache.file(key, key, "glb", FILES["glb"])
	m = cache.model(key, key)
	return glb_response(data, headers={
		"X-Wall-Thickness": f"{m['thickness']:.3f}",
		"X-Hole-Spacing": f"{m['hole_spacing']:.3f}",
		"X-Hole-Count": str(m["hole_count"]),
	})


@router.get("/export.3mf")
def export_3mf(key: tuple = Depends(_key)):
	return download_response(cache.file(key, key, "3mf", FILES["3mf"]), "powerbank_holder.3mf")


@router.get("/export.step")
def export_step_route(key: tuple = Depends(_key)):
	return download_response(cache.file(key, key, "step", FILES["step"]), "powerbank_holder.step")
