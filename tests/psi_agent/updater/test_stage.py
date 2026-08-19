import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from psi_agent.updater.models import FileSpec, Manifest
from psi_agent.updater.stage import (
    apply_delta,
    apply_full_package,
    copy_install_tree,
    is_protected,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(files: dict[str, tuple[bytes, str]]) -> Manifest:
    return Manifest(
        schema_version=1,
        version="1.0.5",
        files={
            rel: FileSpec(sha256=_sha(data), size=len(data), policy=policy) for rel, (data, policy) in files.items()
        },
    )


def test_copy_install_tree_skips_logs(tmp_path: Path) -> None:
    install = tmp_path / "install"
    (install / "logs").mkdir(parents=True)
    (install / "logs" / "x.log").write_text("log")
    (install / "app.txt").write_text("app")
    staging = tmp_path / "updates" / "stage-1.0.5"
    copy_install_tree(install, staging)
    assert (staging / "app.txt").read_text() == "app"
    assert not (staging / "logs").exists()


def test_apply_delta_writes_changes_and_deletes(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    (install / "a.txt").write_text("one")
    (install / "b.txt").write_text("same")
    (install / "old.txt").write_text("old")
    staging = tmp_path / "stage"
    copy_install_tree(install, staging)

    target = _manifest(
        {
            "a.txt": (b"two", "replace"),
            "b.txt": (b"same", "replace"),
            "new.txt": (b"new", "replace"),
        }
    )
    delta = tmp_path / "delta.zip"
    with zipfile.ZipFile(delta, "w") as zf:
        zf.writestr("manifest.json", json.dumps(target.to_bytes().decode()))
        zf.writestr("deleted.txt", "old.txt\n")
        zf.writestr("a.txt", b"two")
        zf.writestr("new.txt", b"new")

    conflicts, applied = apply_delta(staging, delta, target)
    assert conflicts == []
    assert applied == ["a.txt", "new.txt"]
    assert (staging / "a.txt").read_text() == "two"
    assert (staging / "b.txt").read_text() == "same"
    assert (staging / "new.txt").read_text() == "new"
    assert not (staging / "old.txt").exists()


def test_apply_delta_keeps_modified_templates(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    (install / "c.txt").write_text("user edit")
    staging = tmp_path / "stage"
    copy_install_tree(install, staging)

    previous = _manifest({"c.txt": (b"template-v1", "merge-if-unchanged")})
    target = _manifest({"c.txt": (b"template-v2", "merge-if-unchanged")})
    delta = tmp_path / "delta.zip"
    with zipfile.ZipFile(delta, "w") as zf:
        zf.writestr("manifest.json", json.dumps(target.to_bytes().decode()))
        zf.writestr("deleted.txt", "")
        zf.writestr("c.txt", b"template-v2")

    conflicts, applied = apply_delta(staging, delta, target, previous=previous)
    assert conflicts == ["c.txt"]
    assert applied == []
    assert (staging / "c.txt").read_text() == "user edit"


def test_apply_delta_rejects_middle_dotdot_member(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    (install / "app.txt").write_text("old")
    staging = tmp_path / "stage"
    copy_install_tree(install, staging)

    target = _manifest({"app.txt": (b"new", "replace")})
    delta = tmp_path / "delta.zip"
    with zipfile.ZipFile(delta, "w") as zf:
        zf.writestr("manifest.json", json.dumps(target.to_bytes().decode()))
        zf.writestr("deleted.txt", "")
        zf.writestr("dir/../evil.txt", b"x")

    with pytest.raises(ValueError):
        apply_delta(staging, delta, target)


def test_apply_delta_accepts_leading_dot_slash_member(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    (install / "app.txt").write_text("old")
    staging = tmp_path / "stage"
    copy_install_tree(install, staging)

    target = _manifest({"app.txt": (b"new", "replace")})
    delta = tmp_path / "delta.zip"
    with zipfile.ZipFile(delta, "w") as zf:
        zf.writestr("manifest.json", json.dumps(target.to_bytes().decode()))
        zf.writestr("deleted.txt", "")
        zf.writestr("./app.txt", b"new")

    conflicts, applied = apply_delta(staging, delta, target)
    assert conflicts == []
    assert applied == ["app.txt"]
    assert (staging / "app.txt").read_text() == "new"


def test_deleted_path_with_dotdot_cannot_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("safe")
    install = tmp_path / "install"
    install.mkdir()
    (install / "app.txt").write_text("old")
    staging = tmp_path / "stage"
    copy_install_tree(install, staging)

    target = _manifest({"app.txt": (b"new", "replace")})
    delta = tmp_path / "delta.zip"
    with zipfile.ZipFile(delta, "w") as zf:
        zf.writestr("manifest.json", json.dumps(target.to_bytes().decode()))
        zf.writestr("deleted.txt", "dir/../outside.txt\n")

    apply_delta(staging, delta, target)
    assert outside.read_text() == "safe"


def test_protected_paths_never_touched(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    (install / ".env").write_text("SECRET=1")
    staging = tmp_path / "stage"
    copy_install_tree(install, staging)

    target = _manifest({"app.txt": (b"new", "replace")})
    delta = tmp_path / "delta.zip"
    with zipfile.ZipFile(delta, "w") as zf:
        zf.writestr("manifest.json", json.dumps(target.to_bytes().decode()))
        zf.writestr("deleted.txt", ".env\n")
        zf.writestr("app.txt", b"new")

    _, applied = apply_delta(staging, delta, target)
    assert (staging / ".env").read_text() == "SECRET=1"
    assert applied == ["app.txt"]
    assert is_protected(".env")


def test_apply_full_package_overwrites_staging(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    (install / "app.txt").write_text("old")
    staging = tmp_path / "stage"
    copy_install_tree(install, staging)

    target = _manifest({"app.txt": (b"new", "replace")})
    release = tmp_path / "release.zip"
    with zipfile.ZipFile(release, "w") as zf:
        zf.writestr("app.txt", b"new")

    conflicts, applied = apply_full_package(staging, release, target)
    assert conflicts == []
    assert applied == ["app.txt"]
    assert (staging / "app.txt").read_text() == "new"
