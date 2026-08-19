"""Integrity checks for downloads and staged files."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath

from psi_agent.updater.models import Manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_zip_names(zip_path: Path) -> list[str]:
    """Return member names that are safe to extract (no traversal/abs paths)."""
    names: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.startswith("/"):
                raise ValueError(f"unsafe zip member: {info.filename!r}")
            if len(name) >= 2 and name[1] == ":":
                raise ValueError(f"unsafe absolute zip member: {info.filename!r}")
            # A leading "./" is how some zip tools write root entries; strip it
            # for validation but keep the original name for reading members.
            normalized = name[2:] if name.startswith("./") else name
            if ".." in PurePosixPath(normalized).parts or "." in PurePosixPath(normalized).parts:
                raise ValueError(f"unsafe zip member: {info.filename!r}")
            resolved = PurePosixPath(normalized).as_posix()
            if resolved == ".." or resolved.startswith("../"):
                raise ValueError(f"unsafe zip member: {info.filename!r}")
            names.append(name)
    return names


def manifest_from_zip(zip_path: Path) -> Manifest:
    with zipfile.ZipFile(zip_path) as zf:
        raw = json.loads(zf.read("manifest.json"))
    return Manifest.from_dict(raw)


def verify_files(
    manifest: Manifest,
    root: Path,
    *,
    skip: set[str] | None = None,
) -> list[str]:
    """Return relative paths whose sha256 does not match the manifest."""
    skip = skip or set()
    problems: list[str] = []
    for rel, spec in sorted(manifest.files.items()):
        if rel in skip:
            continue
        path = root / rel
        if not path.is_file() or sha256_file(path) != spec.sha256:
            problems.append(rel)
    return problems
