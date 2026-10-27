"""API routes for the Pneumatic Components page: one sub-router per component, each with
defaults (and presets), a summary, glTF preview, 3MF and STEP.

  /blind-plug/...      blind plug for a push-in fitting (pneumatic_app/blind_plug_model.py)
  /connector/...       male part (with clip set) and female part of the printable connector
                       (pneumatic_app/connector_model.py), and the two assembled

All endpoints of a component take its parameters as query parameters. Built models and
their files are cached (see web_app/model_cache.py); each component's default model is
made when the server starts.
"""

from dataclasses import asdict

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from pneumatic_app.blind_plug_model import (
	MAX_COUNT, PRESETS as BLIND_PLUG_PRESETS, BlindPlugParams, build_print_layout as build_blind_plugs,
	describe as describe_blind_plug, total_length, validate as validate_blind_plug,
)
from pneumatic_app.connector_model import (
	ConnectorParams, assembly_info as connector_assembly_info, build_assembly as build_connector_assembly,
	build_print_layout as build_connector, describe as describe_connector, validate as validate_connector,
)
from web_app.exports import download_response, glb_bytes, glb_response, step_bytes, threemf_bytes
from web_app.model_cache import ModelCache, warm as warm_entry

router = APIRouter()

def _files(name: str) -> dict:
	return {
		"glb": lambda part: glb_bytes(part, linear_deflection=0.01, angular_deflection=0.1),
		"3mf": lambda part: threemf_bytes(part, name, tolerance=0.005),
		"step": step_bytes,
	}


# --- Blind plug ---

blind_plug_cache = ModelCache("blind_plug", build_blind_plugs, size=6)
BLIND_PLUG_DEFAULT = BlindPlugParams()  # the model's defaults; the page loads them from /defaults
BLIND_PLUG_FILES = _files("blind_plug")


def _blind_plug_params(
	tube_od: float = Query(..., gt=0, le=30),
	insert_length: float = Query(..., gt=0, le=100),
	tip_chamfer: float = Query(..., ge=0, le=10),
	head_diameter: float = Query(..., gt=0, le=50),
	head_length: float = Query(..., gt=0, le=50),
	count: int = Query(1, ge=1, le=MAX_COUNT),
) -> BlindPlugParams:
	p = BlindPlugParams(tube_od, insert_length, tip_chamfer, head_diameter, head_length, count)
	try:
		validate_blind_plug(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _blind_plug_file(p: BlindPlugParams, kind: str) -> bytes:
	return blind_plug_cache.file(tuple(vars(p).values()), p, kind, BLIND_PLUG_FILES[kind])


def _blind_plug_filename(p: BlindPlugParams, ext: str) -> str:
	count = f"_x{p.count}" if p.count > 1 else ""
	return f"blind_plug_{p.tube_od:g}mm{count}.{ext}"


@router.get("/blind-plug/defaults")
def blind_plug_defaults() -> dict:
	"""The starting values (by input id) and the presets, so they are defined only in the model."""
	presets = {name: {k: v for k, v in asdict(p).items() if k != "count"} for name, p in BLIND_PLUG_PRESETS.items()}
	return {**asdict(BLIND_PLUG_DEFAULT), "presets": presets}


@router.get("/blind-plug/info")
def blind_plug_info(p: BlindPlugParams = Depends(_blind_plug_params)) -> dict:
	return {"summary": describe_blind_plug(p), "length": total_length(p)}


@router.get("/blind-plug/preview.glb")
def blind_plug_preview(p: BlindPlugParams = Depends(_blind_plug_params)):
	return glb_response(_blind_plug_file(p, "glb"))


@router.get("/blind-plug/export.3mf")
def blind_plug_3mf(p: BlindPlugParams = Depends(_blind_plug_params)):
	return download_response(_blind_plug_file(p, "3mf"), _blind_plug_filename(p, "3mf"))


@router.get("/blind-plug/export.step")
def blind_plug_step(p: BlindPlugParams = Depends(_blind_plug_params)):
	return download_response(_blind_plug_file(p, "step"), _blind_plug_filename(p, "step"))


# --- Connector: male part (with clips) and female part ---

CONNECTOR_PARTS = ("male", "female")
connector_cache = ModelCache("connector", lambda pp: build_connector(*pp), size=8)
CONNECTOR_DEFAULT = ConnectorParams()
CONNECTOR_FILES = {part: _files(f"pneumatic_connector_{part}") for part in CONNECTOR_PARTS}


def _connector_params(
	ports: int = Query(..., ge=1, le=100),  # validate() gives the friendly limits
	pitch: float = Query(..., gt=0, le=30),
	hole: float = Query(3.1, gt=0, le=10),
	clips: bool = Query(True),
	back_bore: float = Query(4.05, gt=0, le=10),
) -> ConnectorParams:
	p = ConnectorParams(ports, pitch, hole, clips, back_bore)
	try:
		validate_connector(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _part(part: str = Query("male")) -> str:
	if part not in CONNECTOR_PARTS:
		raise HTTPException(status_code=400, detail="part must be 'male' or 'female'.")
	return part


def _connector_key(p: ConnectorParams, part: str) -> tuple:
	"""Only what the part depends on, so e.g. the female part is shared across hole sizes."""
	if part == "male":
		return (part, p.ports, p.pitch, p.hole, p.clips)
	return (part, p.ports, p.pitch, p.back_bore)


def _connector_file(p: ConnectorParams, part: str, kind: str) -> bytes:
	return connector_cache.file(_connector_key(p, part), (p, part), kind, CONNECTOR_FILES[part][kind])


def _connector_filename(p: ConnectorParams, part: str, ext: str) -> str:
	if part == "male":
		clips = "_clips" if p.clips else ""
		return f"connector_male_{p.ports}x_{p.hole:g}mm{clips}.{ext}"
	return f"connector_female_{p.ports}x_3mm_{p.back_bore:g}mm.{ext}"


# The assembled connector (preview only), keyed without the clips flag (both clips are always shown).
connector_assembly_cache = ModelCache("connector_assembly", build_connector_assembly, size=6)


def _assembly_key(p: ConnectorParams) -> tuple:
	return (p.ports, p.pitch, p.hole, p.back_bore)


@lru_cache(maxsize=32)
def _assembly_info(key: tuple) -> dict:
	"""Hinge lines, opening limit and insertion (a collision search of a second or two, so cached)."""
	ports, pitch, hole, back_bore = key
	return connector_assembly_info(ConnectorParams(ports, pitch, hole, True, back_bore))


@router.get("/connector/defaults")
def connector_defaults() -> dict:
	return {**asdict(CONNECTOR_DEFAULT), "part_male": True, "part_female": False}


@router.get("/connector/info")
def connector_info(p: ConnectorParams = Depends(_connector_params), part: str = Depends(_part)) -> dict:
	return {"summary": describe_connector(p, part)}


@router.get("/connector/preview.glb")
def connector_preview(p: ConnectorParams = Depends(_connector_params), part: str = Depends(_part)):
	return glb_response(_connector_file(p, part, "glb"))


@router.get("/connector/assembly")
def connector_assembly(p: ConnectorParams = Depends(_connector_params)) -> dict:
	"""For animating assembly.glb: the clips' hinge lines (assembly frame, mm, as in the glTF
	before its Z-up to Y-up turn), their largest opening angle (degrees), and which nodes move,
	in which direction and how far, when the male part is pulled out of the female part."""
	return _assembly_info(_assembly_key(p))


@router.get("/connector/assembly.glb")
def connector_assembly_glb(p: ConnectorParams = Depends(_connector_params)):
	return glb_response(connector_assembly_cache.file(_assembly_key(p), p, "glb", CONNECTOR_FILES["male"]["glb"]))


@router.get("/connector/export.3mf")
def connector_3mf(p: ConnectorParams = Depends(_connector_params), part: str = Depends(_part)):
	return download_response(_connector_file(p, part, "3mf"), _connector_filename(p, part, "3mf"))


@router.get("/connector/export.step")
def connector_step(p: ConnectorParams = Depends(_connector_params), part: str = Depends(_part)):
	return download_response(_connector_file(p, part, "step"), _connector_filename(p, part, "step"))


def warm() -> None:
	warm_entry(blind_plug_cache, tuple(vars(BLIND_PLUG_DEFAULT).values()), BLIND_PLUG_DEFAULT, BLIND_PLUG_FILES)
	for part in CONNECTOR_PARTS:
		warm_entry(connector_cache, _connector_key(CONNECTOR_DEFAULT, part), (CONNECTOR_DEFAULT, part), CONNECTOR_FILES[part])
	key = _assembly_key(CONNECTOR_DEFAULT)
	connector_assembly_cache.file(key, CONNECTOR_DEFAULT, "glb", CONNECTOR_FILES["male"]["glb"])
	_assembly_info(key)
