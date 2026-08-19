#!/usr/bin/env python3
"""Build a release manifest for the Haitun Agent install layout.

The manifest is the fingerprint list the client uses to verify downloads and
the publisher uses to compute deltas. Only files shipped in the release
layout are listed; runtime/user paths (.env, state, logs, updates, ...) are
excluded and enforced client-side by the same rule list.

Usage:
  python3 build_manifest.py --layout <dir> --version <ver> --output manifest.json
  python3 build_manifest.py --layout <dir> --version <ver> --policy release-policy.json --output manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import TypedDict

MANIFEST_SCHEMA_VERSION = 1

# Runtime/user paths that must never be shipped or listed. Mirrored by
# src/psi_agent/updater/stage.py's protected path rules.
DEFAULT_EXCLUDES: list[str] = [
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

DEFAULT_POLICIES: dict[str, str] = {
    "psi-agent.exe": "replace",
    "haitun.exe": "replace",
    "haitun-update.conf": "replace",
    "haitun.ico": "replace",
    "msys64/**": "replace",
    "USER.md": "merge-if-unchanged",
    "SOUL.md": "merge-if-unchanged",
    "AGENTS.md": "merge-if-unchanged",
    "README.md": "merge-if-unchanged",
    "IDENTITY.md": "merge-if-unchanged",
    "HEARTBEAT.md": "merge-if-unchanged",
    "BOOTSTRAP.md": "merge-if-unchanged",
}
DEFAULT_POLICY = "merge-if-unchanged"


class ManifestData(TypedDict):
    schema_version: int
    version: str
    files: dict[str, dict[str, object]]


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a small glob dialect (``**``, ``*``, ``?``) into a regex.

    ``**`` matches across directories (including zero directories); ``*`` and
    ``?`` never cross a ``/``. Patterns are anchored to the relative root.
    """
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


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [glob_to_regex(p) for p in patterns]


def matches_any(rel: str, compiled: list[re.Pattern[str]]) -> bool:
    return any(p.match(rel) for p in compiled)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_policy(rel: str, policy_entries: list[tuple[str, str]]) -> str:
    for pattern, policy in policy_entries:
        if glob_to_regex(pattern).match(rel):
            return policy
    return DEFAULT_POLICY


def build_manifest(
    layout: Path,
    version: str,
    *,
    policy_file: Path | None = None,
) -> ManifestData:
    exclude_patterns = compile_patterns(DEFAULT_EXCLUDES)
    policy_entries: list[tuple[str, str]] = list(DEFAULT_POLICIES.items())

    if policy_file is not None:
        raw = json.loads(policy_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"policy file {policy_file} must be a JSON object")
        for extra in raw.get("exclude", []):
            if isinstance(extra, str):
                exclude_patterns.append(glob_to_regex(extra))
        for pattern, policy in raw.get("policies", {}).items():
            if not isinstance(pattern, str) or policy not in ("replace", "merge-if-unchanged"):
                raise ValueError(f"invalid policy entry: {pattern!r} -> {policy!r}")
            policy_entries.append((pattern, policy))

    files: dict[str, dict[str, object]] = {}
    for path in sorted(layout.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(layout).as_posix()
        if matches_any(rel, exclude_patterns):
            continue
        files[rel] = {
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
            "policy": classify_policy(rel, policy_entries),
        }
    return ManifestData(
        schema_version=MANIFEST_SCHEMA_VERSION,
        version=version,
        files=files,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", required=True, type=Path, help="assembled install layout directory")
    parser.add_argument("--version", required=True, help="release version, e.g. 1.0.5")
    parser.add_argument("--policy", type=Path, default=None, help="optional release-policy.json")
    parser.add_argument("--output", required=True, type=Path, help="output manifest.json path")
    args = parser.parse_args(argv)

    if not args.layout.is_dir():
        parser.error(f"layout directory not found: {args.layout}")
    manifest = build_manifest(args.layout, args.version, policy_file=args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sys.stdout.write(f"Wrote {args.output} ({len(manifest['files'])} files)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
