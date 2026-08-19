import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from psi_agent.updater.models import ReleaseInfo
from psi_agent.updater.run import (
    RESULT_NO_BASE_URL,
    RESULT_PREPARED,
    RESULT_TOO_OLD,
    RESULT_WOULD_UPDATE,
    plan_update,
    run_self_update,
)


def _latest(version: str = "1.0.5") -> ReleaseInfo:
    return ReleaseInfo.from_dict(
        {
            "schema_version": 1,
            "version": version,
            "released_at": "2026-08-18T00:00:00Z",
            "min_supported_version": "1.0.0",
            "manifest_url": "https://example.com/manifest.json",
            "manifest_sha256": "1" * 64,
            "full_package_url": "https://example.com/release.zip",
            "full_package_sha256": "2" * 64,
            "full_package_size": 10,
            "deltas": [
                {
                    "from": "1.0.4",
                    "url": "https://example.com/delta.zip",
                    "sha256": "3" * 64,
                    "size": 5,
                }
            ],
        }
    )


def test_plan_update_picks_delta_when_matching() -> None:
    plan = plan_update(_latest(), "1.0.4")
    assert plan.kind == "delta"
    assert plan.from_version == "1.0.4"


def test_plan_update_falls_back_to_full() -> None:
    plan = plan_update(_latest(), "1.0.2")
    assert plan.kind == "full"


def test_run_without_base_url(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    assert run_self_update(install_dir=str(install)) == RESULT_NO_BASE_URL


def test_run_rejects_http_without_override(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    (install / "haitun-update.conf").write_text(
        "HAITUN_VERSION=1.0.4\nHAITUN_UPDATE_BASE_URL=http://example.com/\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        run_self_update(install_dir=str(install))


def _make_server(tmp_path: Path) -> Path:
    server = tmp_path / "server"
    server.mkdir()
    app_bytes = b"new"
    manifest_data = {
        "schema_version": 1,
        "version": "1.0.5",
        "files": {
            "app.txt": {
                "sha256": hashlib.sha256(app_bytes).hexdigest(),
                "size": len(app_bytes),
                "policy": "replace",
            }
        },
    }
    manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, sort_keys=True).encode()
    (server / "manifest.json").write_bytes(manifest_bytes)

    release = server / "release-1.0.5.zip"
    with zipfile.ZipFile(release, "w") as zf:
        zf.writestr("app.txt", app_bytes)
        zf.writestr("manifest.json", manifest_bytes)
    zip_bytes = release.read_bytes()

    (server / "latest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": "1.0.5",
                "released_at": "2026-08-18T00:00:00Z",
                "min_supported_version": "1.0.0",
                "manifest_url": (server / "manifest.json").as_uri(),
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "full_package_url": release.as_uri(),
                "full_package_sha256": hashlib.sha256(zip_bytes).hexdigest(),
                "full_package_size": len(zip_bytes),
                "deltas": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return server


def _make_install(tmp_path: Path, server: Path) -> Path:
    install = tmp_path / "install"
    install.mkdir()
    (install / "app.txt").write_text("old")
    (install / "haitun-update.conf").write_text(
        "HAITUN_VERSION=1.0.4\nHAITUN_UPDATE_BASE_URL=" + server.as_uri() + "\n",
        encoding="utf-8",
    )
    return install


def test_full_flow_check_only(tmp_path: Path, monkeypatch) -> None:
    server = _make_server(tmp_path)
    install = _make_install(tmp_path, server)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    assert run_self_update(install_dir=str(install), check_only=True, allow_insecure=True) == RESULT_WOULD_UPDATE


def test_full_flow_stages_new_version(tmp_path: Path, monkeypatch) -> None:
    server = _make_server(tmp_path)
    install = _make_install(tmp_path, server)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))

    result = run_self_update(install_dir=str(install), yes=False, allow_insecure=True)
    assert result == RESULT_PREPARED

    root = tmp_path / "appdata" / "HaiTun Agent" / "updates"
    staged = root / "stage" / "1.0.5"
    assert (staged / "app.txt").read_text() == "new"
    assert not (root / "update-state.json").exists()
    assert not (root / "manifests" / "1.0.5.json").exists()


def test_full_flow_delta(tmp_path: Path, monkeypatch) -> None:
    server = tmp_path / "server"
    server.mkdir()
    app_bytes = b"new"
    manifest_data = {
        "schema_version": 1,
        "version": "1.0.5",
        "files": {
            "app.txt": {
                "sha256": hashlib.sha256(app_bytes).hexdigest(),
                "size": len(app_bytes),
                "policy": "replace",
            }
        },
    }
    manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, sort_keys=True).encode()

    delta = server / "delta-1.0.4-1.0.5.zip"
    with zipfile.ZipFile(delta, "w") as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("deleted.txt", "")
        zf.writestr("app.txt", app_bytes)
    delta_bytes = delta.read_bytes()

    (server / "latest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": "1.0.5",
                "released_at": "2026-08-18T00:00:00Z",
                "min_supported_version": "1.0.0",
                "manifest_url": (server / "manifest.json").as_uri(),
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "full_package_url": (server / "unused.zip").as_uri(),
                "full_package_sha256": "0" * 64,
                "full_package_size": 0,
                "deltas": [
                    {
                        "from": "1.0.4",
                        "url": delta.as_uri(),
                        "sha256": hashlib.sha256(delta_bytes).hexdigest(),
                        "size": len(delta_bytes),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    install = tmp_path / "install"
    install.mkdir()
    (install / "app.txt").write_text("old")
    (install / "haitun-update.conf").write_text(
        "HAITUN_VERSION=1.0.4\nHAITUN_UPDATE_BASE_URL=" + server.as_uri() + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))

    result = run_self_update(install_dir=str(install), yes=False, allow_insecure=True)
    assert result == RESULT_PREPARED
    staged = tmp_path / "appdata" / "HaiTun Agent" / "updates" / "stage" / "1.0.5"
    assert (staged / "app.txt").read_text() == "new"
    assert not (staged / "unused.txt").exists()


def test_run_reports_too_old(tmp_path: Path, monkeypatch) -> None:
    server = _make_server(tmp_path)
    install = _make_install(tmp_path, server)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    latest_path = server / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest["min_supported_version"] = "1.0.5"
    latest_path.write_text(json.dumps(latest), encoding="utf-8")
    assert run_self_update(install_dir=str(install), allow_insecure=True) == RESULT_TOO_OLD


def test_full_flow_rejects_missing_manifest_file(tmp_path: Path, monkeypatch) -> None:
    server = tmp_path / "server"
    server.mkdir()
    manifest_data = {
        "schema_version": 1,
        "version": "1.0.5",
        "files": {
            "app.txt": {
                "sha256": hashlib.sha256(b"new").hexdigest(),
                "size": 3,
                "policy": "replace",
            },
            "missing.txt": {
                "sha256": hashlib.sha256(b"x").hexdigest(),
                "size": 1,
                "policy": "replace",
            },
        },
    }
    manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, sort_keys=True).encode()
    release = server / "release-1.0.5.zip"
    with zipfile.ZipFile(release, "w") as zf:
        zf.writestr("app.txt", b"new")
        zf.writestr("manifest.json", manifest_bytes)
    zip_bytes = release.read_bytes()
    (server / "latest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": "1.0.5",
                "released_at": "2026-08-18T00:00:00Z",
                "min_supported_version": "1.0.0",
                "manifest_url": (server / "manifest.json").as_uri(),
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "full_package_url": release.as_uri(),
                "full_package_sha256": hashlib.sha256(zip_bytes).hexdigest(),
                "full_package_size": len(zip_bytes),
                "deltas": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    install = tmp_path / "install"
    install.mkdir()
    (install / "haitun-update.conf").write_text(
        "HAITUN_VERSION=1.0.4\nHAITUN_UPDATE_BASE_URL=" + server.as_uri() + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))

    with pytest.raises(ValueError, match="staging verification failed"):
        run_self_update(install_dir=str(install), allow_insecure=True)
