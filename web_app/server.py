"""FastAPI app serving the browser-based CAD generators.

Run directly with `ring-web` (after `pip install -e ".[web]"`), the
run_web.bat shortcut at the repo root, or manually with:
	uvicorn web_app.server:app --host 0.0.0.0 --port 8000
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web_app.generators import powerbank_holder, ring

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="CAD Generators")

# Registered before the static mount below, so these specific API paths are
# matched first -- a StaticFiles mount at "/" would otherwise try (and fail)
# to resolve them as files.
app.include_router(ring.router, prefix="/api/ring")
app.include_router(powerbank_holder.router, prefix="/api/powerbank-holder")

app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")


def main() -> None:
	import uvicorn

	print("Starting CAD Generators web server...")
	print("Once ready, open http://127.0.0.1:8000/ in your browser.")
	uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
	main()
