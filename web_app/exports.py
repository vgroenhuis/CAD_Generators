"""File exports shared by the generator routes, returning bytes for the model cache."""

from __future__ import annotations

import tempfile
from pathlib import Path

from build123d import export_gltf, export_step
from fastapi.responses import Response

from cad_common.mesh_export import shape_to_3mf


def glb_bytes(shape, linear_deflection: float = 0.1, angular_deflection: float = 0.2) -> bytes:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "model.glb"
        export_gltf(shape, str(path), binary=True, linear_deflection=linear_deflection, angular_deflection=angular_deflection)
        return path.read_bytes()


def step_bytes(shape) -> bytes:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "model.step"
        export_step(shape, str(path))
        return path.read_bytes()


def threemf_bytes(shape, name: str, tolerance: float = 0.01) -> bytes:
    return shape_to_3mf(shape, name, tolerance)


def glb_response(data: bytes, headers: dict | None = None) -> Response:
    return Response(content=data, media_type="model/gltf-binary", headers=headers)


def download_response(data: bytes, filename: str) -> Response:
    media = {
        ".step": "application/step",
        ".3mf": "model/3mf",
        ".zip": "application/zip",
    }[Path(filename).suffix]
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
