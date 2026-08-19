import hashlib
from pathlib import Path

import pytest

from psi_agent.updater.fetch import (
    download_file,
    fetch_bytes,
    fetch_json,
    require_https,
)


def test_require_https_rejects_http() -> None:
    with pytest.raises(ValueError):
        require_https("http://example.com/latest.json")


def test_fetch_json_via_file_uri(tmp_path: Path) -> None:
    payload = {"version": "1.0.5"}
    path = tmp_path / "latest.json"
    path.write_text('{"version": "1.0.5"}', encoding="utf-8")
    assert fetch_json(path.as_uri(), allow_insecure=True) == payload


def test_download_file_verifies_sha(tmp_path: Path) -> None:
    source = tmp_path / "pkg.bin"
    source.write_bytes(b"hello")
    dest = tmp_path / "out" / "pkg.bin"
    download_file(
        source.as_uri(),
        dest,
        expected_sha256=hashlib.sha256(b"hello").hexdigest(),
        allow_insecure=True,
    )
    assert dest.read_bytes() == b"hello"


def test_download_file_deletes_on_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "pkg.bin"
    source.write_bytes(b"hello")
    dest = tmp_path / "out" / "pkg.bin"
    with pytest.raises(ValueError):
        download_file(
            source.as_uri(),
            dest,
            expected_sha256="0" * 64,
            allow_insecure=True,
        )
    assert not dest.exists()


def test_fetch_bytes_caps_size(tmp_path: Path) -> None:
    path = tmp_path / "big.json"
    path.write_bytes(b"x" * 64)
    with pytest.raises(ValueError):
        fetch_bytes(path.as_uri(), max_bytes=16, allow_insecure=True)
