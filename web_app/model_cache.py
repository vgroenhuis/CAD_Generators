"""Cache of built models and their exported files, shared by the generator routes.

Building a model and writing its STEP file can take tens of seconds, and visitors
usually ask for the same model several times (preview, then 3MF, then maybe STEP), or
just open a page with its default settings. So each set of parameters keeps its built
model plus every file made from it (glTF preview, 3MF, STEP, ...), and:

* a request that finds its entry ready is answered from memory;
* two requests for the same parameters share one build (single flight) instead of
  building twice;
* work on one entry is serialised: OpenCascade stores the triangulation inside the
  shape, so exporting the same shape from two threads at once is not safe;
* entries are evicted least-recently-used, except pinned ones (the default settings),
  which are built when the server starts (see warm_defaults in server.py) and kept.

Each step is logged when it starts and when it ends, and reported to the requesting
page (see web_app/progress.py), so a slow build can be followed in either place.

Files are also kept on disk (see DiskCache below), so they survive restarts and are
shared by the server's worker processes: a file found there is served without building
the model at all.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Hashable

from web_app.progress import report

log = logging.getLogger("cad_generators.cache")


# What each file kind is called in progress messages ("Writing the 3D preview").
_LABELS = {
    "glb": "3D preview",
    "3mf": "3MF file",
    "step": "STEP file",
    "3mf_zip": "3MF files",
    "step_zip": "STEP files",
}


_REPO = Path(__file__).resolve().parent.parent


def _code_version() -> str:
    """Fingerprint of all Python code that can affect a model or its files (the generator
    packages, cad_common and web_app), so files made by older code are never served."""
    digest = hashlib.sha256()
    for path in sorted(_REPO.glob("*/**/*.py")):
        rel = path.relative_to(_REPO)
        if rel.parts[0] in (".venv", "sandbox", "standalone_test") or "tools" in rel.parts:
            continue
        digest.update(str(rel).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


class DiskCache:
    """Exported files on disk, one per (cache name, parameters, kind, code version).

    Lives in $CAD_CACHE_DIR (default ~/.cache/cad-generators); CAD_DISK_CACHE=0 turns it off.
    Files are written atomically (temp file + rename), so worker processes can share the
    folder. Reading a file refreshes its time stamp; when the folder grows beyond
    $CAD_DISK_CACHE_MB (default 2000) the least recently used files are deleted, which also
    clears out files of older code versions.
    """

    def __init__(self) -> None:
        self.enabled = os.environ.get("CAD_DISK_CACHE", "1") != "0"
        self.root = Path(os.environ.get("CAD_CACHE_DIR", Path.home() / ".cache" / "cad-generators"))
        self.limit = int(float(os.environ.get("CAD_DISK_CACHE_MB", "2000")) * 1e6)
        self.version = _code_version() if self.enabled else ""
        self._lock = threading.Lock()

    def path(self, name: str, key: Hashable, kind: str) -> Path:
        digest = hashlib.sha256(f"{self.version}|{name}|{key!r}".encode()).hexdigest()[:32]
        return self.root / name / f"{digest}.{kind}"

    def get(self, name: str, key: Hashable, kind: str) -> bytes | None:
        if not self.enabled:
            return None
        path = self.path(name, key, kind)
        try:
            data = path.read_bytes()
            os.utime(path)  # recently used
            return data
        except OSError:
            return None

    def put(self, name: str, key: Hashable, kind: str, data: bytes) -> None:
        if not self.enabled:
            return
        path = self.path(name, key, kind)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            self._prune()
        except OSError:
            log.exception("disk cache: could not write %s", path)

    def put_meta(self, name: str, key: Hashable, meta: dict) -> None:
        """Store what an entry is (e.g. its parameters), once, next to its files, so that the
        stored entries can be listed (see entries)."""
        if not self.enabled:
            return
        path = self.path(name, key, "json")
        if path.exists():
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"version": self.version, "created": time.time(), "meta": meta}))
            os.replace(tmp, path)
        except OSError:
            log.exception("disk cache: could not write %s", path)

    def entries(self, name: str) -> list[dict]:
        """The stored entries of one cache made by the current code, most recently used first:
        their meta data, which files are there (kind -> size in bytes) and when they were made
        and last used."""
        out = []
        if not self.enabled:
            return out
        for meta_path in (self.root / name).glob("*.json"):
            try:
                record = json.loads(meta_path.read_text())
            except (OSError, ValueError):
                continue
            if record.get("version") != self.version:
                continue
            files, used = {}, 0.0
            for f in meta_path.parent.glob(meta_path.stem + ".*"):
                kind = f.suffix[1:]
                if kind in ("json", "tmp") or f.name.endswith(".tmp"):
                    continue
                st = f.stat()
                files[kind] = st.st_size
                used = max(used, st.st_mtime)
            if files:
                out.append({"id": meta_path.stem, "meta": record.get("meta", {}), "files": files,
                            "created": record.get("created"), "used": used})
        return sorted(out, key=lambda e: e["used"], reverse=True)

    def usage(self, name: str | None = None) -> int:
        """Bytes on disk, of one cache (all code versions) or of the whole store."""
        if not self.enabled:
            return 0
        pattern = f"{name}/*" if name else "*/*"
        return sum(f.stat().st_size for f in self.root.glob(pattern) if f.is_file())

    def _prune(self) -> None:
        with self._lock:
            files = [(f.stat().st_mtime, f.stat().st_size, f) for f in self.root.glob("*/*") if f.is_file() and f.suffix != ".json"]
            total = sum(size for _, size, _ in files)
            for _, size, f in sorted(files):
                if total <= self.limit:
                    break
                try:
                    f.unlink()
                    total -= size
                except OSError:
                    pass
            # Drop the description of entries that have no files left.
            for meta_path in self.root.glob("*/*.json"):
                if not any(f.suffix != ".json" for f in meta_path.parent.glob(meta_path.stem + ".*")):
                    try:
                        meta_path.unlink()
                    except OSError:
                        pass


disk = DiskCache()


def _short(key: Hashable) -> str:
    text = repr(key)
    return text if len(text) <= 70 else text[:67] + "..."


class _Entry:
    def __init__(self) -> None:
        self.lock = threading.Lock()  # held while building or exporting this entry
        self.model: Any = None
        self.built = False
        self.files: dict[str, bytes] = {}


class ModelCache:
    def __init__(self, name: str, build: Callable[[Any], Any], size: int = 6,
                 meta: Callable[[Any], dict] | None = None) -> None:
        """meta(params) describes an entry for the list of stored entries (see DiskCache.entries)."""
        self.name = name
        self._build = build
        self._meta = meta
        self._size = size
        self._entries: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._pinned: set[Hashable] = set()
        self._lock = threading.Lock()

    def _entry(self, key: Hashable) -> _Entry:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = self._entries[key] = _Entry()
            self._entries.move_to_end(key)
            unpinned = [k for k in self._entries if k not in self._pinned]
            for k in unpinned[: max(0, len(unpinned) - self._size)]:
                del self._entries[k]
            return entry

    def pin(self, key: Hashable) -> None:
        with self._lock:
            self._pinned.add(key)

    @contextmanager
    def _locked(self, entry: _Entry, key: Hashable):
        """Hold the entry's lock, saying so if another request has it first."""
        if not entry.lock.acquire(blocking=False):
            log.info("%s: waiting for %s, busy in another request", self.name, _short(key))
            report("Waiting for the same model, which is already being built")
            entry.lock.acquire()
        try:
            yield
        finally:
            entry.lock.release()

    def _model_locked(self, entry: _Entry, key: Hashable, params: Any) -> Any:
        if not entry.built:
            log.info("%s: building %s", self.name, _short(key))
            report("Building the model")
            start = time.monotonic()
            entry.model = self._build(params)
            entry.built = True
            log.info("%s: built %s in %.1f s", self.name, _short(key), time.monotonic() - start)
        return entry.model

    def model(self, key: Hashable, params: Any) -> Any:
        """The built model for `params` (`key` identifies them)."""
        entry = self._entry(key)
        with self._locked(entry, key):
            return self._model_locked(entry, key, params)

    def file(self, key: Hashable, params: Any, kind: str, make: Callable[[Any], bytes]) -> bytes:
        """The file `kind` (e.g. "glb", "3mf", "step") made from the model by `make`."""
        entry = self._entry(key)
        with self._locked(entry, key):
            data = entry.files.get(kind)
            if data is None:
                data = disk.get(self.name, key, kind)
                if data is not None:
                    log.info("%s: %s for %s from disk", self.name, kind, _short(key))
                    entry.files[kind] = data
            if data is None:
                model = self._model_locked(entry, key, params)
                log.info("%s: writing %s for %s", self.name, kind, _short(key))
                report(f"Writing the {_LABELS.get(kind, kind)}")
                start = time.monotonic()
                data = entry.files[kind] = make(model)
                log.info("%s: wrote %s for %s in %.1f s", self.name, kind, _short(key), time.monotonic() - start)
                disk.put(self.name, key, kind, data)
                if self._meta is not None:
                    disk.put_meta(self.name, key, self._meta(params))
            return data


def warm(cache: ModelCache, key: Hashable, params: Any, makers: dict[str, Callable[[Any], bytes]]) -> None:
    """Pin an entry (typically the default settings) and make all its files now."""
    cache.pin(key)
    for kind, make in makers.items():
        cache.file(key, params, kind, make)
