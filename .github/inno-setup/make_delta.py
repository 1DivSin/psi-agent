#!/usr/bin/env python3
"""Build a delta zip between two release manifests.

The delta contains only files added or modified between ``from`` and ``to``,
plus ``deleted.txt`` (paths removed) and the target ``manifest.json``. The
client applies it over a staging copy of its current install directory.

Usage:
  python3 make_delta.py \
    --layout <dir> \
    --manifest <manifest.json> \
    --previous-manifest <previous-manifest.json> \
    --from 1.0.4 --to 1.0.5 \
    --output delta-1.0.4-1.0.5.zip
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import cast


def diff_manifests(
    new_files: dict[str, dict[str, object]],
    previous_files: dict[str, dict[str, object]],
) -> tuple[list[str], list[str]]:
    """Return (changed_or_added, deleted) relative paths."""
    changed: list[str] = []
    for rel, spec in sorted(new_files.items()):
        prev = previous_files.get(rel)
        if prev is None or prev.get("sha256") != spec.get("sha256"):
            changed.append(rel)
    deleted = sorted(rel for rel in previous_files if rel not in new_files)
    return changed, deleted


def make_delta(
    layout: Path,
    manifest: dict[str, object],
    previous_manifest: dict[str, object],
    *,
    from_version: str,
    to_version: str,
    output: Path,
) -> tuple[list[str], list[str]]:
    new_files = manifest["files"]
    previous_files = previous_manifest["files"]
    if not isinstance(new_files, dict) or not isinstance(previous_files, dict):
        raise ValueError("manifest files must be objects")
    new_files = cast(dict[str, dict[str, object]], new_files)
    previous_files = cast(dict[str, dict[str, object]], previous_files)
    changed, deleted = diff_manifests(new_files, previous_files)

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )
        zf.writestr("deleted.txt", "".join(f"{rel}\n" for rel in deleted))
        for rel in changed:
            source = layout / rel
            if not source.is_file():
                raise FileNotFoundError(f"manifest lists {rel!r} but layout has no such file: {source}")
            zf.write(source, rel)
    return changed, deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", required=True, type=Path, help="current release layout directory")
    parser.add_argument("--manifest", required=True, type=Path, help="current manifest.json")
    parser.add_argument("--previous-manifest", required=True, type=Path, help="previous manifest.json")
    parser.add_argument("--from", dest="from_version", required=True, help="source version")
    parser.add_argument("--to", dest="to_version", required=True, help="target version")
    parser.add_argument("--output", required=True, type=Path, help="output delta zip path")
    args = parser.parse_args(argv)

    if not args.layout.is_dir():
        parser.error(f"layout directory not found: {args.layout}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    previous = json.loads(args.previous_manifest.read_text(encoding="utf-8"))
    changed, deleted = make_delta(
        args.layout,
        manifest,
        previous,
        from_version=args.from_version,
        to_version=args.to_version,
        output=args.output,
    )
    sys.stdout.write(
        f"Wrote {args.output}: {len(changed)} changed/added, "
        f"{len(deleted)} deleted ({args.from_version} -> {args.to_version})\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
