"""HTTPS fetch helpers with sha256 verification."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from collections.abc import Callable
from pathlib import Path

ProgressCallback = Callable[[int, int | None], None]


def require_https(url: str) -> None:
    if not url.startswith("https://"):
        raise ValueError(f"update URLs must be https, got: {url!r}")


def fetch_json(
    url: str,
    *,
    timeout: float = 30,
    max_bytes: int = 2_000_000,
    allow_insecure: bool = False,
) -> dict[str, object]:
    if not allow_insecure:
        require_https(url)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response too large from {url!r}")
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON from {url!r}: {e}") from None
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object from {url!r}")
    return parsed


def fetch_bytes(
    url: str,
    *,
    timeout: float = 30,
    max_bytes: int = 10_000_000,
    allow_insecure: bool = False,
) -> bytes:
    if not allow_insecure:
        require_https(url)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response too large from {url!r}")
    return data


def download_file(
    url: str,
    dest: Path,
    *,
    expected_sha256: str,
    timeout: float = 300,
    chunk_size: int = 256 * 1024,
    progress: ProgressCallback | None = None,
    allow_insecure: bool = False,
) -> Path:
    if not allow_insecure:
        require_https(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        length = resp.headers.get("Content-Length") or ""
        total_size = int(length) if length.isdigit() else None
        with dest.open("wb") as fh:
            while True:
                block = resp.read(chunk_size)
                if not block:
                    break
                fh.write(block)
                digest.update(block)
                total += len(block)
                if progress is not None:
                    progress(total, total_size)
    actual = digest.hexdigest()
    if actual != expected_sha256:
        dest.unlink(missing_ok=True)
        raise ValueError(f"sha256 mismatch for {url!r}: expected {expected_sha256}, got {actual}")
    return dest
