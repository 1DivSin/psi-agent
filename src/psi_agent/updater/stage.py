"""Staging copy and delta/full-package application."""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from psi_agent.updater.models import Manifest
from psi_agent.updater.verify import safe_zip_names, sha256_file

# Mirrors .github/inno-setup/build_manifest.py DEFAULT_EXCLUDES: these paths
# are never shipped and must never be overwritten or deleted by an update.
PROTECTED_PATTERNS: list[str] = [
    "updates/**",
    "logs/**",
    "state/**",
    "histories/**",
    "generated/**",
    "charts/**",
    ".psi/**",
    ".fusion-memory/**",
    "__pycache__/**",
    "**/__pycache__/**",
    "**/*.pyc",
    ".env",
    ".env.*",
    ".skills_prompt_snapshot.json",
    "skills/.curator_state.json",
    "skills/.curator_report.md",
    "skills/fusion-flow-legacy/node_modules/**",
    "skills/fusion-flow-legacy/runs/**",
    "skills/fusion-flow-legacy/.env",
    "skills/workflow/.pytest_cache/**",
    "bin/apply_multimodal_test_api.ps1",
    "flows/**/runs/**",
]


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    regex = ""
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    regex += "(?:[^/]+/)*"
                    i += 3
                else:
                    regex += ".*"
                    i += 2
            else:
                regex += "[^/]*"
                i += 1
        elif c == "?":
            regex += "[^/]"
            i += 1
        elif c == "/":
            regex += "/"
            i += 1
        elif c == ".":
            regex += "\\."
            i += 1
        else:
            regex += re.escape(c)
            i += 1
    return re.compile("^" + regex + "$")


_PROTECTED = [_glob_to_regex(p) for p in PROTECTED_PATTERNS]


def is_protected(rel: str) -> bool:
    return any(pattern.match(rel) for pattern in _PROTECTED)


def _is_safe_rel(rel: str) -> bool:
    if not rel:
        return False
    if len(rel) >= 2 and rel[1] == ":":
        return False
    rel = rel.replace("\\", "/")
    if rel.startswith("/"):
        return False
    if rel.startswith("./"):
        rel = rel[2:]
    if ".." in PurePosixPath(rel).parts or "." in PurePosixPath(rel).parts:
        return False
    resolved = PurePosixPath(rel).as_posix()
    return resolved != ".." and not resolved.startswith("../")


def copy_install_tree(install_dir: Path, staging: Path) -> None:
    """Copy the current install dir into the external staging directory."""
    if staging.exists():
        shutil.rmtree(staging)
    staging.parent.mkdir(parents=True, exist_ok=True)

    def _ignore(dirpath: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            if name == "logs":
                ignored.add(name)
        return ignored

    shutil.copytree(install_dir, staging, ignore=_ignore, dirs_exist_ok=False)


def _merge_conflict(rel: str, staging: Path, manifest: Manifest, previous: Manifest | None) -> bool:
    """True when a merge-if-unchanged template was locally modified."""
    if previous is None:
        return False
    spec = manifest.files.get(rel)
    prev = previous.files.get(rel)
    if spec is None or prev is None or spec.policy != "merge-if-unchanged":
        return False
    local = staging / rel
    return local.is_file() and sha256_file(local) != prev.sha256


def _write_member(staging: Path, rel: str, data: bytes) -> None:
    target = staging / rel
    if not target.resolve().is_relative_to(staging.resolve()):
        raise ValueError(f"member escapes staging: {rel!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)


def apply_delta(
    staging: Path,
    delta_zip: Path,
    manifest: Manifest,
    *,
    previous: Manifest | None = None,
) -> tuple[list[str], list[str]]:
    """Apply a delta zip over staging; returns (conflicts, applied) paths."""
    conflicts: list[str] = []
    applied: list[str] = []
    with zipfile.ZipFile(delta_zip) as zf:
        deleted = zf.read("deleted.txt").decode("utf-8").splitlines()
        for raw in deleted:
            rel = raw.strip()
            if not _is_safe_rel(rel) or is_protected(rel):
                continue
            target = staging / rel
            if not target.resolve().is_relative_to(staging.resolve()):
                raise ValueError(f"deleted path escapes staging: {rel!r}")
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        names = [name for name in safe_zip_names(delta_zip) if name not in ("manifest.json", "deleted.txt")]
        for name in names:
            rel = PurePosixPath(name).as_posix()
            if is_protected(rel):
                continue
            spec = manifest.files.get(rel)
            if spec is None:
                continue
            if _merge_conflict(rel, staging, manifest, previous):
                conflicts.append(rel)
                continue
            _write_member(staging, rel, zf.read(name))
            applied.append(rel)
    return conflicts, applied


def apply_full_package(
    staging: Path,
    release_zip: Path,
    manifest: Manifest,
    *,
    previous: Manifest | None = None,
) -> tuple[list[str], list[str]]:
    """Extract a full release zip; returns (conflicts, applied) paths."""
    conflicts: list[str] = []
    applied: list[str] = []
    with zipfile.ZipFile(release_zip) as zf:
        for name in safe_zip_names(release_zip):
            rel = PurePosixPath(name).as_posix()
            if rel == "manifest.json" or is_protected(rel):
                continue
            spec = manifest.files.get(rel)
            if spec is None:
                continue
            if _merge_conflict(rel, staging, manifest, previous):
                conflicts.append(rel)
                continue
            _write_member(staging, rel, zf.read(name))
            applied.append(rel)
    return conflicts, applied


def write_conflicts(root: Path, version: str, conflicts: list[str]) -> None:
    if not conflicts:
        return
    root.mkdir(parents=True, exist_ok=True)
    payload = {"version": version, "conflicts": sorted(conflicts)}
    (root / f"conflicts-{version}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
