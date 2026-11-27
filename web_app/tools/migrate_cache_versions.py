"""One-off: re-tag stored game tiles with the game tiles' own code version.

Until 2026-11-27 every cached file carried the fingerprint of ALL code, so any change to any
generator made every stored tile "old" and the pre-generator made them all again. Now each
cache has its own fingerprint (model_cache.code_fingerprint). This moves the stored tiles (and
the tile colour list) made by code whose tile code is the same as now to the new version, so
they are not made again.

A stored version counts as the same tile code when, at the commit that made it (see
code_versions), every file the tiles use is identical to now, except
web_app/generators/game_tiles.py, which must then be identical to it at BASE (the last
commit before that file was changed for the new fingerprints: those changes don't change any
tile).

    python -m web_app.tools.migrate_cache_versions BASE [--apply]
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict

from web_app import code_versions
from web_app.generators import game_tiles as g
from web_app.model_cache import _REPO, _read_file, code_files, disk

ROUTES = "web_app/generators/game_tiles.py"


def git_read(commit: str):
	def read(rel: str) -> bytes | None:
		r = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=_REPO, capture_output=True)
		return r.stdout if r.returncode == 0 else None
	return read


def same_tile_code(commit: str, base: str, roots) -> bool:
	read = git_read(commit)
	now = code_files(roots)
	then = code_files(roots, read)
	if now != then:
		return False
	for rel in now:
		if rel == ROUTES:
			if read(rel) != git_read(base)(rel):
				return False
		elif read(rel) != _read_file(rel):
			return False
	return True


def main() -> int:
	base = sys.argv[1]
	apply = "--apply" in sys.argv
	roots = disk.scope(g.cache.name)
	new = disk.version_of(g.cache.name)
	commits = code_versions.commits()
	versions = {}
	for meta_path in (disk.root / g.cache.name).glob("*.json"):
		try:
			record = json.loads(meta_path.read_text())
		except (OSError, ValueError):
			continue
		versions.setdefault(record.get("version"), []).append((meta_path, record))
	ok = {}
	for v in versions:
		c = commits.get(v)
		ok[v] = v == new or (c is not None and same_tile_code(c["full"], base, roots))
		print(f"version {v}: {len(versions[v])} entries, commit {c and c['commit']}, same tile code: {ok[v]}")
	moved = 0
	for v, entries in versions.items():
		if not ok[v] or v == new:
			continue
		for meta_path, record in entries:
			try:
				p = g.TileParams(**record["meta"]["params"])
			except (TypeError, KeyError):
				continue
			key = g._key(p)
			old_stem = hashlib.sha256(f"{v}|{g.cache.name}|{key!r}".encode()).hexdigest()[:32]
			if old_stem != meta_path.stem:
				print("  key mismatch, skipped:", meta_path.name)
				continue
			new_json = disk.path(g.cache.name, key, "json", version=new)
			if new_json.exists():
				continue  # already made by the new code
			moved += 1
			if not apply:
				continue
			for f in meta_path.parent.glob(old_stem + ".*"):
				if f.suffix != ".json":
					f.rename(disk.path(g.cache.name, key, f.suffix[1:], version=new))
			record["version"], record["key"] = new, repr(key)
			new_json.write_text(json.dumps(record))
			meta_path.unlink()
	print(f"{moved} tiles {'moved' if apply else 'to move'} to version {new}")
	# The colour list of all tile types (one file).
	colours_new = disk.path("game_tiles_colours", "all", "list", version=new)
	for v in ok:
		if ok[v] and not colours_new.exists():
			old = disk.path("game_tiles_colours", "all", "list", version=v)
			if old.exists():
				print("colour list from version", v)
				if apply:
					colours_new.parent.mkdir(parents=True, exist_ok=True)
					colours_new.write_bytes(old.read_bytes())
	return 0


if __name__ == "__main__":
	sys.exit(main())
