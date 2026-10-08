"""FastAPI app serving the browser-based CAD generators.

Run directly with `ring-web` (after `pip install -e ".[web]"`), the
run_web.bat shortcut at the repo root, or manually with:
	uvicorn web_app.server:app --host 0.0.0.0 --port 8000

At startup the default model of every generator is built in the background (with its
preview, 3MF and STEP file) and kept in the cache, so a visitor who opens a page with
its default settings gets them immediately. Set CAD_WARM_CACHE=0 to skip that.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from web_app import progress
from web_app.generators import apriltag_cube, calibration_plate, powerbank_holder, ring, sanding_rack

_STATIC_DIR = Path(__file__).parent / "static"

log = logging.getLogger("cad_generators")
if not log.handlers:
	_handler = logging.StreamHandler()
	_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s"))
	log.addHandler(_handler)
	log.setLevel(logging.INFO)


def warm_defaults() -> None:
	"""Build the default model of every generator, one after another."""
	for module in (ring, powerbank_holder, apriltag_cube, calibration_plate, sanding_rack):
		try:
			module.warm()
		except Exception:
			log.exception("warming the default %s failed", module.__name__)
	log.info("default models are ready")


@asynccontextmanager
async def lifespan(_app: FastAPI):
	if os.environ.get("CAD_WARM_CACHE", "1") != "0":
		threading.Thread(target=warm_defaults, name="warm-defaults", daemon=True).start()
	yield


app = FastAPI(title="CAD Generators", lifespan=lifespan)
app.add_middleware(progress.ProgressMiddleware)

# Registered before the static mount below, so these specific API paths are
# matched first -- a StaticFiles mount at "/" would otherwise try (and fail)
# to resolve them as files.
app.include_router(ring.router, prefix="/api/ring")
app.include_router(powerbank_holder.router, prefix="/api/powerbank-holder")
app.include_router(apriltag_cube.router, prefix="/api/apriltag-cube")
app.include_router(calibration_plate.router, prefix="/api/calibration-plate")
app.include_router(sanding_rack.router, prefix="/api/sanding-rack")


@app.get("/api/progress/{job}")
def progress_route(job: str) -> dict:
	"""What the request tagged with `job` is doing; pages poll this while they wait."""
	if not progress.valid_job(job):
		raise HTTPException(status_code=400, detail="Invalid job id.")
	return progress.read(job)

app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")


def main() -> None:
	import uvicorn

	print("Starting CAD Generators web server...")
	print("Once ready, open http://127.0.0.1:8000/ in your browser.")
	uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
	main()
