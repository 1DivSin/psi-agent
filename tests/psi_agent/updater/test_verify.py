import hashlib
import zipfile
from pathlib import Path

import pytest

from psi_agent.updater.models import FileSpec, Manifest
from psi_agent.updater.verify import (
    safe_zip_names,
    sha256_file,
    verify_files,
)


def test_sha256_file_matches_content(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"abc")
    assert sha256_file(path) == hashlib.sha256(b"abc").hexdigest()


def test_safe_zip_names_rejects_traversal(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        safe_zip_names(bad)


def test_safe_zip_names_rejects_middle_dotdot(tmp_path: Path) -> None:
    bad = tmp_path / "middle.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("dir/../evil.txt", "x")
    with pytest.raises(ValueError):
        safe_zip_names(bad)


def test_safe_zip_names_accepts_normal(tmp_path: Path) -> None:
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("skills/a.txt", "x")
    assert safe_zip_names(good) == ["skills/a.txt"]


def test_safe_zip_names_accepts_leading_dot_slash(tmp_path: Path) -> None:
    good = tmp_path / "dot.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("./app.txt", "x")
    assert safe_zip_names(good) == ["./app.txt"]


def test_verify_files_reports_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_bytes(b"ok")
    manifest = Manifest(
        schema_version=1,
        version="1.0.5",
        files={
            "a.txt": FileSpec(
                sha256=hashlib.sha256(b"ok").hexdigest(),
                size=2,
                policy="replace",
            ),
            "missing.txt": FileSpec(
                sha256=hashlib.sha256(b"x").hexdigest(),
                size=1,
                policy="replace",
            ),
        },
    )
    assert verify_files(manifest, root) == ["missing.txt"]
