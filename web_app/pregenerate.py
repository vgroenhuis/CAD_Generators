"""Pre-generating game tiles while the server has nothing to do.

Every tile type in every shape, with all other settings at their defaults, gets all its files
(thumbnail, 3D preview, 3MF, STEP) in the disk cache, so the list of stored tiles is complete
and those tiles download at once. Older versions of a tile made again are deleted. The code version is part of every cache key, so after an
update the tiles are made again, one by one, in idle time.

How it works:

* ActivityMiddleware keeps, per server worker process, a small file with the number of
  requests that worker is answering; the file's time stamp is that of the last request start
  or end. The server is idle when no worker answers a request and none did for IDLE_SECONDS.
* One worker (whichever gets the lock) starts `python -m web_app.pregenerate` at the lowest
  CPU priority, after the default models are built, and again every RECHECK_SECONDS. That
  process makes the missing tiles one at a time, each only when the server is idle, and exits
  when all are there. A visitor arriving during a tile gets the CPU first (nice 19); the tile
  is finished, the next one waits until the server is idle again.

CAD_PREGENERATE=0 turns it off (by default it is on when CAD_WARM_CACHE is); it also needs the
disk cache. Run `python -m web_app.pregenerate --list` to see what is missing.
"""

from __future__ import annotations

import fcntl
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("cad_generators.pregenerate")

IDLE_SECONDS = 60  # no request for this long: idle
RECHECK_SECONDS = 3600  # look for missing tiles again (e.g. pruned from the disk cache)
MAX_SHARE = 0.6  # stop when the tiles of the current code would take more of the disk cache than this

_DIR = Path(os.environ.get("CAD_ACTIVITY_DIR", Path.home() / ".cache" / "cad-generators-run"))
_lock = threading.Lock()
_active = 0


def _activity_file(pid: int) -> Path:
	return _DIR / f"activity-{pid}"


def _record(delta: int) -> None:
	global _active
	with _lock:
		_active += delta
		try:
			_DIR.mkdir(parents=True, exist_ok=True)
			_activity_file(os.getpid()).write_text(str(_active))
		except OSError:
			pass


class ActivityMiddleware:
	"""Counts the HTTP requests this worker is answering (see the module docstring)."""

	def __init__(self, app) -> None:
		self.app = app

	async def __call__(self, scope, receive, send) -> None:
		if scope["type"] != "http":
			await self.app(scope, receive, send)
			return
		_record(1)
		try:
			await self.app(scope, receive, send)
		finally:
			_record(-1)


def idle() -> bool:
	"""No worker answers a request, and none started or ended one for IDLE_SECONDS."""
	now = time.time()
	for f in _DIR.glob("activity-*"):
		try:
			pid = int(f.name.split("-")[1])
			os.kill(pid, 0)
		except (ValueError, ProcessLookupError):
			f.unlink(missing_ok=True)  # a worker that is gone
			continue
		except PermissionError:
			pass
		try:
			if int(f.read_text() or 0) > 0 or now - f.stat().st_mtime < IDLE_SECONDS:
				return False
		except (OSError, ValueError):
			continue
	return True


def enabled() -> bool:
	from web_app.model_cache import disk

	default = os.environ.get("CAD_WARM_CACHE", "1")
	return os.environ.get("CAD_PREGENERATE", default) != "0" and disk.enabled


def start() -> None:
	"""In one server worker: run the pre-generating process now and every RECHECK_SECONDS."""
	if not enabled():
		return
	try:
		_DIR.mkdir(parents=True, exist_ok=True)
		lock = open(_DIR / "pregenerate.lock", "w")
		fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
	except OSError:
		return  # another worker does it

	def loop() -> None:
		while True:
			try:
				result = subprocess.run([sys.executable, "-m", "web_app.pregenerate"], cwd=Path(__file__).resolve().parent.parent,
										preexec_fn=lambda: os.nice(19))
				if result.returncode:
					log.warning("pre-generating game tiles stopped with code %d", result.returncode)
			except Exception:
				log.exception("pre-generating game tiles failed")
			time.sleep(RECHECK_SECONDS)

	threading.Thread(target=loop, name="pregenerate", daemon=True, args=()).start()
	start.lock = lock  # held as long as this worker lives


def wanted() -> list:
	"""Every tile type in every shape, with all other settings at their defaults (squares first)."""
	from game_tiles_app.game_tile_model import SHAPES, TILE_TYPES, TileParams

	return [TileParams(tile_type=t, shape=s) for s in SHAPES for t in TILE_TYPES]


def missing() -> list:
	from web_app.generators import game_tiles as g
	from web_app.model_cache import disk

	out = []
	for p in wanted():
		key = g._key(p)
		if not all(disk.path(g.cache.name, key, kind).exists() for kind in g._makers(p)):
			out.append(p)
	return out


def _current_bytes() -> int:
	"""Bytes on disk of the game tiles made by the current code."""
	from web_app.model_cache import disk

	return sum(sum(e["files"].values()) for e in disk.entries("game_tiles"))


def main() -> int:
	handler = logging.StreamHandler()
	handler.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s"))
	log.addHandler(handler)
	log.setLevel(logging.INFO)
	logging.getLogger("cad_generators.cache").setLevel(logging.WARNING)  # one line per tile is enough
	from web_app.generators import game_tiles as g
	from web_app.model_cache import disk

	todo = missing()
	if "--list" in sys.argv:
		for p in todo:
			print(p.tile_type, p.shape)
		print(f"{len(todo)} of {len(wanted())} missing")
		return 0
	gone = g.discard_superseded()
	if gone:
		log.info("deleted %d game tiles of older versions that a newer version replaces", gone)
	if not todo:
		return 0
	log.info("%d game tiles to pre-generate", len(todo))
	parent = os.getppid()
	for p in todo:
		while not idle():
			if os.getppid() != parent:
				return 0  # the server is gone
			time.sleep(10)
		if _current_bytes() > MAX_SHARE * disk.limit:
			log.warning("the disk cache is too small for all pre-generated tiles (CAD_DISK_CACHE_MB): stopped")
			return 1
		start = time.monotonic()
		try:
			for kind, make in g._makers(p).items():
				g.cache.file(g._key(p), p, kind, make)
		except Exception:
			log.exception("could not pre-generate %s %s", p.tile_type, p.shape)
			continue
		log.info("pre-generated %s %s in %.0f s", p.tile_type, p.shape, time.monotonic() - start)
		g.discard_superseded()  # its older versions
	return 0


if __name__ == "__main__":
	sys.exit(main())
