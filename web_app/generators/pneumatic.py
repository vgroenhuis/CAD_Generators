"""API routes for the Pneumatic Components page: one sub-router per component, each with
defaults (and presets), a summary, glTF preview, 3MF and STEP.

  /blind-plug/...      blind plug for a push-in fitting (pneumatic_app/blind_plug_model.py)
  /connector-male/...  male part and clip set of the printable connector (pneumatic_app/connector_model.py)

All endpoints of a component take its parameters as query parameters. Built models and
their files are cached (see web_app/model_cache.py); each component's default model is
made when the server starts.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from pneumatic_app.blind_plug_model import (
	MAX_COUNT, PRESETS as BLIND_PLUG_PRESETS, BlindPlugParams, build_print_layout as build_blind_plugs,
	describe as describe_blind_plug, total_length, validate as validate_blind_plug,
)
from pneumatic_app.connector_model import (
	ConnectorParams, build_print_layout as build_connector_male, describe as describe_connector_male,
	validate as validate_connector_male,
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


# --- Connector, male part and clips ---

connector_male_cache = ModelCache("connector_male", build_connector_male, size=6)
CONNECTOR_MALE_DEFAULT = ConnectorParams()
CONNECTOR_MALE_FILES = _files("pneumatic_connector_male")


def _connector_male_params(
	ports: int = Query(..., ge=1, le=100),  # validate() gives the friendly limit
	pitch: float = Query(..., gt=0, le=30),
	hole: float = Query(..., gt=0, le=10),
	clips: bool = Query(True),
) -> ConnectorParams:
	p = ConnectorParams(ports, pitch, hole, clips)
	try:
		validate_connector_male(p)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc))
	return p


def _connector_male_file(p: ConnectorParams, kind: str) -> bytes:
	return connector_male_cache.file(tuple(vars(p).values()), p, kind, CONNECTOR_MALE_FILES[kind])


def _connector_male_filename(p: ConnectorParams, ext: str) -> str:
	clips = "_clips" if p.clips else ""
	return f"connector_male_{p.ports}x_{p.hole:g}mm{clips}.{ext}"


@router.get("/connector-male/defaults")
def connector_male_defaults() -> dict:
	return asdict(CONNECTOR_MALE_DEFAULT)


@router.get("/connector-male/info")
def connector_male_info(p: ConnectorParams = Depends(_connector_male_params)) -> dict:
	return {"summary": describe_connector_male(p)}


@router.get("/connector-male/preview.glb")
def connector_male_preview(p: ConnectorParams = Depends(_connector_male_params)):
	return glb_response(_connector_male_file(p, "glb"))


@router.get("/connector-male/export.3mf")
def connector_male_3mf(p: ConnectorParams = Depends(_connector_male_params)):
	return download_response(_connector_male_file(p, "3mf"), _connector_male_filename(p, "3mf"))


@router.get("/connector-male/export.step")
def connector_male_step(p: ConnectorParams = Depends(_connector_male_params)):
	return download_response(_connector_male_file(p, "step"), _connector_male_filename(p, "step"))


def warm() -> None:
	warm_entry(blind_plug_cache, tuple(vars(BLIND_PLUG_DEFAULT).values()), BLIND_PLUG_DEFAULT, BLIND_PLUG_FILES)
	warm_entry(
		connector_male_cache, tuple(vars(CONNECTOR_MALE_DEFAULT).values()), CONNECTOR_MALE_DEFAULT, CONNECTOR_MALE_FILES,
	)
