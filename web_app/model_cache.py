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
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

log = logging.getLogger("cad_generators.cache")


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
    def __init__(self, name: str, build: Callable[[Any], Any], size: int = 6) -> None:
        self.name = name
        self._build = build
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

    def _model_locked(self, entry: _Entry, key: Hashable, params: Any) -> Any:
        if not entry.built:
            start = time.monotonic()
            entry.model = self._build(params)
            entry.built = True
            log.info("%s: built %s in %.1f s", self.name, _short(key), time.monotonic() - start)
        return entry.model

    def model(self, key: Hashable, params: Any) -> Any:
        """The built model for `params` (`key` identifies them)."""
        entry = self._entry(key)
        with entry.lock:
            return self._model_locked(entry, key, params)

    def file(self, key: Hashable, params: Any, kind: str, make: Callable[[Any], bytes]) -> bytes:
        """The file `kind` (e.g. "glb", "3mf", "step") made from the model by `make`."""
        entry = self._entry(key)
        with entry.lock:
            data = entry.files.get(kind)
            if data is None:
                model = self._model_locked(entry, key, params)
                start = time.monotonic()
                data = entry.files[kind] = make(model)
                log.info("%s: wrote %s for %s in %.1f s", self.name, kind, _short(key), time.monotonic() - start)
            return data


def warm(cache: ModelCache, key: Hashable, params: Any, makers: dict[str, Callable[[Any], bytes]]) -> None:
    """Pin an entry (typically the default settings) and make all its files now."""
    cache.pin(key)
    for kind, make in makers.items():
        cache.file(key, params, kind, make)
