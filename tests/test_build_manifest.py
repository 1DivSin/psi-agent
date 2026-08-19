from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / ".github" / "inno-setup" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_manifest = _load_script("build_manifest.py")


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())


@pytest.fixture
def layout(tmp_path: Path) -> Path:
    root = tmp_path / "layout"
    _write(root / "psi-agent.exe", b"exe")
    _write(root / "haitun.exe", b"launcher")
    _write(root / "haitun-update.conf", "HAITUN_VERSION=1.0.5\n")
    _write(root / "haitun.ico", b"ico")
    _write(root / "USER.md", "user template")
    _write(root / "skills" / "sample" / "SKILL.md", "# skill")
    _write(root / "msys64" / "usr" / "bin" / "bash.exe", b"bash")
    _write(root / ".env", "SECRET=1")
    _write(root / "state" / "latest.json", "{}")
    _write(root / "logs" / "out.log", "log")
    _write(root / "updates" / "stage-1.0.5" / "x", "x")
    _write(root / "__pycache__" / "x.pyc", b"pyc")
    return root


def test_build_manifest_lists_official_files_with_policies(layout: Path) -> None:
    manifest = build_manifest.build_manifest(layout, "1.0.5")

    assert manifest["schema_version"] == 1
    assert manifest["version"] == "1.0.5"
    files = manifest["files"]
    assert files["psi-agent.exe"]["policy"] == "replace"
    assert files["haitun.exe"]["policy"] == "replace"
    assert files["haitun-update.conf"]["policy"] == "replace"
    assert files["haitun.ico"]["policy"] == "replace"
    assert files["msys64/usr/bin/bash.exe"]["policy"] == "replace"
    assert files["USER.md"]["policy"] == "merge-if-unchanged"
    assert files["skills/sample/SKILL.md"]["policy"] == "merge-if-unchanged"


def test_build_manifest_excludes_runtime_paths(layout: Path) -> None:
    files = build_manifest.build_manifest(layout, "1.0.5")["files"]
    for rel in (
        ".env",
        "state/latest.json",
        "logs/out.log",
        "updates/stage-1.0.5/x",
        "__pycache__/x.pyc",
    ):
        assert rel not in files


def test_build_manifest_sha256_matches_file(layout: Path) -> None:
    files = build_manifest.build_manifest(layout, "1.0.5")["files"]
    expected = hashlib.sha256(b"exe").hexdigest()
    assert files["psi-agent.exe"]["sha256"] == expected
    assert files["psi-agent.exe"]["size"] == 3


def test_build_manifest_policy_file_override(layout: Path, tmp_path: Path) -> None:
    policy = tmp_path / "release-policy.json"
    policy.write_text(
        json.dumps({"policies": {"skills/**": "replace"}}),
        encoding="utf-8",
    )
    files = build_manifest.build_manifest(layout, "1.0.5", policy_file=policy)["files"]
    assert files["skills/sample/SKILL.md"]["policy"] == "replace"


def test_build_manifest_cli_writes_json(layout: Path, tmp_path: Path) -> None:
    output = tmp_path / "out" / "manifest.json"
    rc = build_manifest.main(["--layout", str(layout), "--version", "1.0.5", "--output", str(output)])
    assert rc == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["version"] == "1.0.5"
