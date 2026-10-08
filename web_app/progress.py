"""Progress of slow requests, so a page can show what the server is working on.

A page adds a random `job=<id>` to a request's query string and, while it waits,
polls GET /api/progress/<id>. Code serving the request calls `report("Building the
model")` and so on; it needs no job id of its own, because ProgressMiddleware keeps the
request's job in a context variable (which Starlette copies into the threadpool that
runs the sync routes).

Progress is kept in small files in a shared directory rather than in memory: with
several uvicorn workers, the poll is often answered by a different worker than the one
doing the work.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import parse_qs

_DIR = Path(os.environ.get("CAD_PROGRESS_DIR", Path(tempfile.gettempdir()) / "cad_generators_progress"))
_JOB = re.compile(r"[A-Za-z0-9_-]{8,64}")
_MAX_AGE = 3600  # seconds; older progress files are removed

_current: ContextVar[str | None] = ContextVar("cad_progress_job", default=None)


def valid_job(job: str) -> bool:
    return bool(_JOB.fullmatch(job))


def _write(job: str, stage: str, done: bool = False) -> None:
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        path = _DIR / f"{job}.json"
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"stage": stage, "since": time.time(), "done": done}))
        os.replace(tmp, path)
    except OSError:
        pass  # progress is a nicety; never fail the request over it


def report(stage: str) -> None:
    """Record what the current request is doing now (no-op without a job id)."""
    job = _current.get()
    if job is not None:
        _write(job, stage)


def read(job: str) -> dict:
    """{"stage", "elapsed" (seconds in this stage), "done"}; stage is None if unknown."""
    try:
        state = json.loads((_DIR / f"{job}.json").read_text())
    except (OSError, ValueError):
        return {"stage": None, "elapsed": 0.0, "done": False}
    return {"stage": state["stage"], "elapsed": round(time.time() - state["since"], 1), "done": state["done"]}


def _cleanup() -> None:
    cutoff = time.time() - _MAX_AGE
    try:
        for path in _DIR.iterdir():
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        pass


class ProgressMiddleware:
    """Makes the request's `job` query parameter the target of `report()`."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        job = None
        if scope["type"] == "http":
            job = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("job", [None])[0]
        if job is None or not valid_job(job):
            await self.app(scope, receive, send)
            return
        _cleanup()
        _write(job, "Starting")
        token = _current.set(job)
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)
            _write(job, "Done", done=True)
