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
the model at all. Each cache's files are tied to a fingerprint of the code that cache uses
(its generator module and the build function's module, and what they import from this
repository), so changing one generator leaves the others' files valid.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import sys
import logging
import os
import re
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


# Repository modules that cannot change a model or its files: left out of the fingerprints.
_NOT_MODEL_CODE = {"web_app/model_cache.py", "web_app/code_versions.py", "web_app/pregenerate.py", "web_app/progress.py"}


def _read_file(rel: str) -> bytes | None:
    try:
        return (_REPO / rel).read_bytes()
    except OSError:
        return None


def code_files(roots, read: Callable[[str], bytes | None] = _read_file) -> list[str]:
    """The repository's Python files (paths relative to it, '/'-separated) that the `roots`
    import, directly or through each other, the roots included: found by reading their
    import statements (read(path) gives a file's contents, or None when there is none, so
    this works on a git commit as well)."""
    found: dict[str, bytes] = {}
    todo = list(roots)

    def module_files(name: str) -> list[str]:
        parts = name.split(".")
        out = [f"{'/'.join(parts[:i])}/__init__.py" for i in range(1, len(parts) + 1)]
        return out + [f"{'/'.join(parts)}.py"]

    while todo:
        rel = todo.pop()
        if rel in found or rel in _NOT_MODEL_CODE or rel.startswith((".venv/", "sandbox/", "standalone_test/")):
            continue
        data = read(rel)
        if data is None:
            continue
        found[rel] = data
        try:
            tree = ast.parse(data)
        except SyntaxError:
            continue
        package = rel.rsplit("/", 1)[0].split("/") if "/" in rel else []
        if rel.endswith("/__init__.py"):
            package = rel.split("/")[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    todo += module_files(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative: from the file's package, up level - 1
                    base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                    mod = ".".join(base + ([node.module] if node.module else []))
                else:
                    mod = node.module or ""
                if not mod:
                    continue
                todo += module_files(mod)
                for alias in node.names:  # (a submodule: from package import module)
                    todo.append(f"{mod.replace('.', '/')}/{alias.name}.py")
    return sorted(found)


def code_fingerprint(roots, read: Callable[[str], bytes | None] = _read_file) -> str:
    """Fingerprint of the code the `roots` use (see code_files)."""
    digest = hashlib.sha256()
    for rel in code_files(roots, read):
        digest.update(rel.encode())
        digest.update(read(rel) or b"")
    return digest.hexdigest()[:16]


def _code_version() -> str:
    """Fingerprint of all Python code (the generator packages, cad_common and web_app): for a
    cache without its own scope (see DiskCache.register), and for files made before the
    caches had their own."""
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

    Each cache name has its own code version (see register and version_of).
    Lives in $CAD_CACHE_DIR (default ~/.cache/cad-generators); CAD_DISK_CACHE=0 turns it off.
    Files are written atomically (temp file + rename), so worker processes can share the
    folder. Reading a file refreshes its time stamp; when the folder grows beyond
    $CAD_DISK_CACHE_MB (default 20000) the least recently used files are deleted, which also
    clears out files of older code versions. Files of older code versions are not served for
    a request, but can be listed and fetched as they are (see entries and stored_file).
    """

    def __init__(self) -> None:
        self.enabled = os.environ.get("CAD_DISK_CACHE", "1") != "0"
        self.root = Path(os.environ.get("CAD_CACHE_DIR", Path.home() / ".cache" / "cad-generators"))
        self.limit = int(float(os.environ.get("CAD_DISK_CACHE_MB", "20000")) * 1e6)
        self.version = _code_version() if self.enabled else ""  # of all code: caches without a scope
        self._scopes: dict[str, tuple[str, ...]] = {}
        self._versions: dict[str, str] = {}
        self._lock = threading.Lock()

    def register(self, name: str, roots) -> None:
        """Tie cache `name`'s files to the code the `roots` (repository-relative module files)
        use, rather than to all code."""
        self._scopes[name] = tuple(sorted(set(roots)))
        self._versions.pop(name, None)

    def scope(self, name: str) -> tuple[str, ...] | None:
        return self._scopes.get(name)

    def scopes(self) -> dict[str, tuple[str, ...]]:
        return dict(self._scopes)

    def version_of(self, name: str) -> str:
        """The code version of cache `name`'s files."""
        if not self.enabled:
            return ""
        roots = self._scopes.get(name)
        if roots is None:
            return self.version
        version = self._versions.get(name)
        if version is None:
            version = self._versions[name] = code_fingerprint(roots)
        return version

    def path(self, name: str, key: Hashable, kind: str, version: str | None = None) -> Path:
        version = self.version_of(name) if version is None else version
        digest = hashlib.sha256(f"{version}|{name}|{key!r}".encode()).hexdigest()[:32]
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
            tmp.write_text(json.dumps({"version": self.version_of(name), "created": time.time(), "key": repr(key), "meta": meta}))
            os.replace(tmp, path)
        except OSError:
            log.exception("disk cache: could not write %s", path)

    def entries(self, name: str, all_versions: bool = False) -> list[dict]:
        """The stored entries of one cache made by the current code (or by any code, with
        all_versions), most recently used first: their id, meta data, code version, which files
        are there (kind -> size in bytes) and when they were made and last used."""
        out = []
        if not self.enabled:
            return out
        current = self.version_of(name)
        for meta_path in (self.root / name).glob("*.json"):
            try:
                record = json.loads(meta_path.read_text())
            except (OSError, ValueError):
                continue
            if record.get("version") != current and not all_versions:
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
                out.append({"id": meta_path.stem, "meta": record.get("meta", {}), "files": files, "version": record.get("version"),
                            "created": record.get("created"), "used": used})
        return sorted(out, key=lambda e: e["used"], reverse=True)

    def stored_file(self, name: str, entry_id: str, kind: str) -> bytes | None:
        """A stored file by entry id (see entries) and kind, whatever code made it."""
        if not self.enabled or not re.fullmatch(r"[0-9a-f]{32}", entry_id) or not re.fullmatch(r"[a-z0-9_-]{1,20}", kind) or kind == "json":
            return None
        try:
            return (self.root / name / f"{entry_id}.{kind}").read_bytes()
        except OSError:
            return None

    def delete_entry(self, name: str, entry_id: str) -> int:
        """Delete a stored entry (all its files and its description); returns the bytes freed."""
        if not self.enabled or not re.fullmatch(r"[0-9a-f]{32}", entry_id):
            return 0
        freed = 0
        for f in (self.root / name).glob(entry_id + ".*"):
            try:
                size = f.stat().st_size
                f.unlink()
                freed += size
            except OSError:
                pass
        return freed

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


def _relative(path: str | None) -> str | None:
    """A module file's path relative to the repository ('/'-separated), or None outside it."""
    if not path:
        return None
    try:
        return Path(path).resolve().relative_to(_REPO).as_posix()
    except ValueError:
        return None


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
        """meta(params) describes an entry for the list of stored entries (see DiskCache.entries).
        The cache's files on disk are tied to the code of the module that makes this cache and
        of the build function's module (and what they import)."""
        self.name = name
        roots = {_relative(inspect.currentframe().f_back.f_globals.get("__file__")),
                 _relative(getattr(sys.modules.get(build.__module__), "__file__", None))}
        roots.discard(None)
        if roots:
            disk.register(name, roots)
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
                report(f"Writing the {_LABELS.get(kind.split('-')[0], kind)}")
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
