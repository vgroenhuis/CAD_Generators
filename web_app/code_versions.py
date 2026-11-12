"""Which git commit made a stored file: the disk cache knows each file's code version (a hash
of the code, see model_cache._code_version) but not the commit. This module computes that hash
for recent commits from git itself and remembers the result, so the list of stored tiles can
show e.g. "88d544e, 12 Nov 2026" instead of a bare hash. Versions made from uncommitted code
have no commit."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import threading
from pathlib import Path, PurePosixPath

log = logging.getLogger("cad_generators.versions")

_REPO = Path(__file__).resolve().parent.parent
MAX_COMMITS = 400
_lock = threading.Lock()
_known: dict[str, dict] = {}
_scanned_head = ""


def _included(path: PurePosixPath) -> bool:
	"""The files model_cache._code_version hashes: Python files in a folder (*/**/*.py), not in
	.venv, sandbox, standalone_test or any tools folder."""
	return (path.suffix == ".py" and len(path.parts) > 1 and path.parts[0] not in (".venv", "sandbox", "standalone_test")
			and "tools" not in path.parts)


def _git(*args: str, data: bytes | None = None) -> bytes:
	return subprocess.run(["git", *args], cwd=_REPO, input=data, capture_output=True, check=True, timeout=120).stdout


def _version_of(commit: str, cat) -> str:
	files = sorted(PurePosixPath(line.split("\t", 1)[1]) for line in _git("ls-tree", "-r", commit).decode().splitlines()
				   if line.split()[1] == "blob" and _included(PurePosixPath(line.split("\t", 1)[1])))
	digest = hashlib.sha256()
	for path in files:
		digest.update(str(path).encode())
		digest.update(cat(f"{commit}:{path}"))
	return digest.hexdigest()[:16]


def _scan() -> None:
	"""Hash the code of the last MAX_COMMITS commits (once per HEAD; kept in a file)."""
	global _scanned_head
	head = _git("rev-parse", "HEAD").decode().strip()
	if head == _scanned_head:
		return
	from web_app.model_cache import disk

	store = disk.root / "code_versions.json"  # (not in a cache folder: never pruned or listed)
	try:
		_known.update(json.loads(store.read_text()))
	except (OSError, ValueError):
		pass
	done = {v["full"] for v in _known.values()}
	log_lines = _git("log", f"-{MAX_COMMITS}", "--format=%H %h %ct").decode().split("\n")
	todo = [line.split() for line in log_lines if line and line.split()[0] not in done]
	if todo:
		proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=_REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

		def cat(spec: str) -> bytes:
			proc.stdin.write(spec.encode() + b"\n")
			proc.stdin.flush()
			header = proc.stdout.readline().split()
			size = int(header[2])
			data = proc.stdout.read(size)
			proc.stdout.read(1)  # the newline after the contents
			return data

		try:
			for full, short, when in reversed(todo):  # oldest first: a version keeps its first commit
				_known.setdefault(_version_of(full, cat), {"full": full, "commit": short, "date": int(when)})
		finally:
			proc.stdin.close()
			proc.wait()
		try:
			store.write_text(json.dumps(_known))
		except OSError:
			pass
	_scanned_head = head


def commits() -> dict[str, dict]:
	"""Code version -> {"commit": short hash, "date": commit time (Unix)}, for recent commits.
	(The first commit with that code, when later commits did not change it.)"""
	with _lock:
		try:
			_scan()
		except Exception:
			log.exception("could not match code versions to git commits")
		return dict(_known)
