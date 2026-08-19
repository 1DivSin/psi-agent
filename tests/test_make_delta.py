from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path
from typing import cast

import pytest


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / ".github" / "inno-setup" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_delta = _load_script("make_delta.py")
build_manifest = _load_script("build_manifest.py")


def _write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def _manifest(layout: Path, version: str) -> dict[str, object]:
    return build_manifest.build_manifest(layout, version)


@pytest.fixture
def versions(tmp_path: Path) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    v1 = tmp_path / "v1"
    v2 = tmp_path / "v2"
    _write(v1 / "a.txt", "one")
    _write(v1 / "b.txt", "same")
    _write(v1 / "old.txt", "old")
    _write(v2 / "a.txt", "two")
    _write(v2 / "b.txt", "same")
    _write(v2 / "new.txt", "new")
    return v1, v2, _manifest(v1, "1.0.4"), _manifest(v2, "1.0.5")


def test_diff_manifests(versions: tuple[Path, Path, dict[str, object], dict[str, object]]) -> None:
    _, _, prev, new = versions
    changed, deleted = make_delta.diff_manifests(new["files"], prev["files"])
    assert changed == ["a.txt", "new.txt"]
    assert deleted == ["old.txt"]


def test_make_delta_zip_contents(
    versions: tuple[Path, Path, dict[str, object], dict[str, object]],
    tmp_path: Path,
) -> None:
    _, v2, prev, new = versions
    delta = tmp_path / "delta-1.0.4-1.0.5.zip"
    changed, deleted = make_delta.make_delta(
        v2,
        new,
        prev,
        from_version="1.0.4",
        to_version="1.0.5",
        output=delta,
    )
    assert changed == ["a.txt", "new.txt"]
    assert deleted == ["old.txt"]

    with zipfile.ZipFile(delta) as zf:
        names = set(zf.namelist())
        assert {"manifest.json", "deleted.txt", "a.txt", "new.txt"} <= names
        assert "b.txt" not in names
        assert zf.read("a.txt") == b"two"
        deleted_txt = zf.read("deleted.txt").decode()
        assert deleted_txt == "old.txt\n"
        embedded = json.loads(zf.read("manifest.json"))
        assert embedded["version"] == "1.0.5"
        expected = json.dumps(new, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        assert zf.read("manifest.json") == expected.encode()


def test_delta_applies_to_staging_copy(
    versions: tuple[Path, Path, dict[str, object], dict[str, object]],
    tmp_path: Path,
) -> None:
    v1, v2, prev, new = versions
    delta = tmp_path / "delta.zip"
    make_delta.make_delta(v2, new, prev, from_version="1.0.4", to_version="1.0.5", output=delta)

    staging = tmp_path / "staging"
    shutil.copytree(v1, staging)
    with zipfile.ZipFile(delta) as zf:
        for name in zf.namelist():
            if name in ("manifest.json", "deleted.txt"):
                continue
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
        for rel in zf.read("deleted.txt").decode().splitlines():
            (staging / rel).unlink()

    assert (staging / "a.txt").read_text() == "two"
    assert (staging / "b.txt").read_text() == "same"
    assert (staging / "new.txt").read_text() == "new"
    assert not (staging / "old.txt").exists()


def test_make_delta_errors_when_layout_missing_file(
    versions: tuple[Path, Path, dict[str, object], dict[str, object]],
    tmp_path: Path,
) -> None:
    _, v2, prev, new = versions
    broken = copy.deepcopy(new)
    files = cast(dict[str, dict[str, object]], broken["files"])
    files["missing.txt"] = {"sha256": "0" * 64, "size": 1, "policy": "replace"}
    with pytest.raises(FileNotFoundError):
        make_delta.make_delta(
            v2,
            broken,
            prev,
            from_version="1.0.4",
            to_version="1.0.5",
            output=tmp_path / "bad.zip",
        )
