import json

import pytest

from psi_agent.updater.models import (
    Manifest,
    ReleaseInfo,
    UpdateState,
)


def _manifest_dict(version: str = "1.0.5") -> dict[str, object]:
    return {
        "schema_version": 1,
        "version": version,
        "files": {
            "app.txt": {
                "sha256": "0" * 64,
                "size": 3,
                "policy": "replace",
            }
        },
    }


def _latest_dict() -> dict[str, object]:
    return {
        "schema_version": 1,
        "version": "1.0.5",
        "released_at": "2026-08-18T00:00:00Z",
        "min_supported_version": "1.0.0",
        "manifest_url": "https://example.com/releases/1.0.5/manifest.json",
        "manifest_sha256": "1" * 64,
        "full_package_url": "https://example.com/releases/1.0.5/release-1.0.5.zip",
        "full_package_sha256": "2" * 64,
        "full_package_size": 100,
        "deltas": [
            {
                "from": "1.0.4",
                "url": "https://example.com/deltas/1.0.4-1.0.5.zip",
                "sha256": "3" * 64,
                "size": 10,
            }
        ],
    }


def test_manifest_round_trip() -> None:
    manifest = Manifest.from_dict(_manifest_dict())
    assert manifest.version == "1.0.5"
    assert manifest.files["app.txt"].policy == "replace"
    reparsed = Manifest.from_dict(json.loads(manifest.to_bytes()))
    assert reparsed.files["app.txt"].sha256 == manifest.files["app.txt"].sha256


def test_manifest_rejects_bad_schema() -> None:
    with pytest.raises(ValueError):
        Manifest.from_dict({**_manifest_dict(), "schema_version": 2})


def test_release_info_parses_deltas() -> None:
    info = ReleaseInfo.from_dict(_latest_dict())
    assert len(info.deltas) == 1
    assert info.deltas[0].from_version == "1.0.4"


def test_release_info_rejects_bad_sha() -> None:
    raw = _latest_dict()
    raw["manifest_sha256"] = "short"
    with pytest.raises(ValueError):
        ReleaseInfo.from_dict(raw)


def test_update_state_round_trip() -> None:
    state = UpdateState(
        status="prepared",
        from_version="1.0.4",
        to_version="1.0.5",
        staged_dir="C:/x/stage",
    )
    reparsed = UpdateState.from_dict(state.to_dict())
    assert reparsed.status == "prepared"
    assert reparsed.to_version == "1.0.5"
