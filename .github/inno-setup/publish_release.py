#!/usr/bin/env python3
"""Publish Haitun Agent release objects to Aliyun OSS.

Upload order matters: versioned objects first (manifest, release zip, deltas),
then latest.json, then version.txt -- so clients never observe a
half-published release. The full installer (stable + versioned) is uploaded
too, for new installs and legacy clients.

Required env:
  ALIYUN_ACCESS_KEY_ID, ALIYUN_ACCESS_KEY_SECRET
  ALIYUN_OSS_BUCKET, ALIYUN_OSS_ENDPOINT
  HAITUN_VERSION, HAITUN_DOWNLOAD_BASE_URL
  MANIFEST_PATH, RELEASE_ZIP_PATH

Optional env:
  ALIYUN_OSS_PREFIX
  INSTALLER_PATH, HAITUN_UPDATE_INSTALLER_NAME
  DELTA_PATHS              ';' or newline separated delta-<from>-<to>.zip paths
  MIN_SUPPORTED_VERSION    default 1.0.0
  RELEASE_NOTES
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import oss2  # ty: ignore[unresolved-import]
except ImportError:
    raise SystemExit("oss2 is not installed; run: python -m pip install oss2") from None

DELTA_NAME_RE = re.compile(r"^delta-(.+)-(.+)\.zip$")


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _delta_entries(base_url: str, delta_paths: list[Path]) -> list[dict[str, object]]:
    base = base_url.rstrip("/")
    entries: list[dict[str, object]] = []
    for path in delta_paths:
        match = DELTA_NAME_RE.match(path.name)
        if match is None:
            raise SystemExit(f"delta filename must match delta-<from>-<to>.zip: {path.name}")
        entries.append(
            {
                "from": match.group(1),
                "url": f"{base}/deltas/{path.name}",
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
        )
    return entries


def build_latest_json(
    *,
    version: str,
    base_url: str,
    manifest_sha256: str,
    release_zip: Path,
    deltas: list[dict[str, object]],
    min_supported_version: str = "1.0.0",
    release_notes: str = "",
    released_at: str | None = None,
) -> dict[str, object]:
    base = base_url.rstrip("/")
    return {
        "schema_version": 1,
        "version": version,
        "released_at": released_at or datetime.now(UTC).isoformat(),
        "min_supported_version": min_supported_version,
        "manifest_url": f"{base}/releases/{version}/manifest.json",
        "manifest_sha256": manifest_sha256,
        "full_package_url": f"{base}/releases/{version}/release-{version}.zip",
        "full_package_sha256": _sha256(release_zip),
        "full_package_size": release_zip.stat().st_size,
        "deltas": deltas,
        "release_notes": release_notes,
    }


def _upload(bucket: Any, key: str, source: Path | None = None, *, text: str | None = None) -> None:
    headers = {
        "Cache-Control": "no-cache",
        "x-oss-object-acl": "public-read",
    }
    if source is not None:
        headers.update(
            {
                "Content-Type": "application/octet-stream",
                "Cache-Control": "public, max-age=300",
            }
        )
        bucket.put_object_from_file(key, str(source), headers=headers)
    else:
        bucket.put_object(
            key,
            text,
            headers={
                **headers,
                "Content-Type": "text/plain; charset=utf-8",
            },
        )


def main() -> int:
    access_key_id = _require_env("ALIYUN_ACCESS_KEY_ID")
    access_key_secret = _require_env("ALIYUN_ACCESS_KEY_SECRET")
    bucket_name = _require_env("ALIYUN_OSS_BUCKET")
    endpoint = _require_env("ALIYUN_OSS_ENDPOINT")
    version = _require_env("HAITUN_VERSION")
    base_url = _require_env("HAITUN_DOWNLOAD_BASE_URL").rstrip("/")
    manifest_path = Path(_require_env("MANIFEST_PATH"))
    release_zip = Path(_require_env("RELEASE_ZIP_PATH"))

    if not manifest_path.is_file() or not release_zip.is_file():
        raise SystemExit(f"missing manifest or release zip: {manifest_path} / {release_zip}")

    prefix = os.environ.get("ALIYUN_OSS_PREFIX", "").strip().strip("/")
    if prefix in ("", ".", "-", "root", "ROOT"):
        prefix = ""
    key = lambda suffix: f"{prefix}/{suffix}" if prefix else suffix  # noqa: E731

    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)

    manifest_key = key(f"releases/{version}/manifest.json")
    delta_paths = [Path(p.strip()) for p in re.split(r"[;\n]", os.environ.get("DELTA_PATHS", "")) if p.strip()]
    for path in delta_paths:
        if not path.is_file():
            raise SystemExit(f"delta file not found: {path}")

    latest = build_latest_json(
        version=version,
        base_url=base_url,
        manifest_sha256=_sha256(manifest_path),
        release_zip=release_zip,
        deltas=_delta_entries(base_url, delta_paths),
        min_supported_version=os.environ.get("MIN_SUPPORTED_VERSION") or "1.0.0",
        release_notes=os.environ.get("RELEASE_NOTES", ""),
    )

    _upload(bucket, manifest_key, source=manifest_path)
    sys.stdout.write(f"Uploaded {manifest_key}\n")
    _upload(bucket, key(f"releases/{version}/release-{version}.zip"), source=release_zip)
    sys.stdout.write(f"Uploaded releases/{version}/release-{version}.zip\n")
    for path in delta_paths:
        _upload(bucket, key(f"deltas/{path.name}"), source=path)
        sys.stdout.write(f"Uploaded deltas/{path.name}\n")

    installer = os.environ.get("INSTALLER_PATH", "").strip()
    if installer and Path(installer).is_file():
        installer_path = Path(installer)
        installer_name = os.environ.get("HAITUN_UPDATE_INSTALLER_NAME", "HaiTun_Agent_Setup.exe").strip()
        base_name, ext = os.path.splitext(installer_name)
        stable_key = key(installer_name)
        versioned_key = key(f"{base_name}-{version}{ext}")
        _upload(bucket, stable_key, source=installer_path)
        copy_headers = {
            "Content-Type": "application/octet-stream",
            "Cache-Control": "public, max-age=300",
            "x-oss-object-acl": "public-read",
            "x-oss-metadata-directive": "REPLACE",
        }
        bucket.copy_object(bucket_name, stable_key, versioned_key, headers=copy_headers)
        sys.stdout.write(f"Uploaded {installer_name} and {base_name}-{version}{ext}\n")

    _upload(bucket, key("latest.json"), text=json.dumps(latest, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.write("Uploaded latest.json\n")
    _upload(bucket, key("version.txt"), text=version + "\n")
    sys.stdout.write("Uploaded version.txt\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
