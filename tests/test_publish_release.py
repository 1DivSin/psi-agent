from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

# publish_release.py imports oss2 at module level; CI installs it, but local
# tests don't need the SDK, so stub the module before loading the script.
_OSS2_STUB = types.ModuleType("oss2")
sys.modules.setdefault("oss2", _OSS2_STUB)


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / ".github" / "inno-setup" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publish_release = _load_script("publish_release.py")


def test_build_latest_json(tmp_path: Path) -> None:
    release = tmp_path / "release-1.0.5.zip"
    release.write_bytes(b"release")
    latest = publish_release.build_latest_json(
        version="1.0.5",
        base_url="https://example.com/",
        manifest_sha256="a" * 64,
        release_zip=release,
        deltas=[
            {
                "from": "1.0.4",
                "url": "https://example.com/deltas/delta-1.0.4-1.0.5.zip",
                "sha256": "b" * 64,
                "size": 1,
            }
        ],
        min_supported_version="1.0.0",
        release_notes="fix",
    )
    assert latest["version"] == "1.0.5"
    assert latest["manifest_url"] == "https://example.com/releases/1.0.5/manifest.json"
    assert latest["full_package_url"] == "https://example.com/releases/1.0.5/release-1.0.5.zip"
    assert latest["deltas"][0]["from"] == "1.0.4"
    assert len(latest["full_package_sha256"]) == 64


def test_delta_entries_parses_filename(tmp_path: Path) -> None:
    delta = tmp_path / "delta-1.0.4-1.0.5.zip"
    delta.write_bytes(b"delta")
    entries = publish_release._delta_entries("https://example.com", [delta])
    assert entries[0]["from"] == "1.0.4"
    assert entries[0]["url"] == "https://example.com/deltas/delta-1.0.4-1.0.5.zip"


def test_latest_json_serializes(tmp_path: Path) -> None:
    release = tmp_path / "release.zip"
    release.write_bytes(b"x")
    latest = publish_release.build_latest_json(
        version="1.0.5",
        base_url="https://example.com",
        manifest_sha256="a" * 64,
        release_zip=release,
        deltas=[],
    )
    parsed = json.loads(json.dumps(latest))
    assert parsed["schema_version"] == 1
