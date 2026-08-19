"""Data models for the Haitun Agent incremental updater."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

SCHEMA_VERSION = 1


def _require(raw: dict[str, Any], key: str, type_: type) -> Any:
    value = raw.get(key)
    if not isinstance(value, type_):
        raise ValueError(f"{key!r} must be {type_.__name__}, got {type(value).__name__}")
    return value


@dataclass(frozen=True)
class FileSpec:
    """One file entry in a release manifest."""

    sha256: str
    size: int
    policy: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FileSpec:
        if not isinstance(raw, dict):
            raise ValueError("file spec must be a JSON object")
        sha256 = _require(raw, "sha256", str)
        if len(sha256) != 64:
            raise ValueError("sha256 must be 64 hex characters")
        policy = _require(raw, "policy", str)
        if policy not in ("replace", "merge-if-unchanged"):
            raise ValueError(f"unsupported file policy: {policy!r}")
        return cls(sha256=sha256, size=_require(raw, "size", int), policy=policy)


@dataclass(frozen=True)
class Manifest:
    """Fingerprint list for one release layout."""

    schema_version: int
    version: str
    files: dict[str, FileSpec]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Manifest:
        if not isinstance(raw, dict):
            raise ValueError("manifest must be a JSON object")
        schema = _require(raw, "schema_version", int)
        if schema != SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest schema_version: {schema}")
        raw_files = _require(raw, "files", dict)
        files = {str(rel): FileSpec.from_dict(spec) for rel, spec in raw_files.items()}
        return cls(
            schema_version=schema,
            version=_require(raw, "version", str),
            files=files,
        )

    def to_bytes(self) -> bytes:
        data = {
            "schema_version": self.schema_version,
            "version": self.version,
            "files": {
                rel: {
                    "sha256": spec.sha256,
                    "size": spec.size,
                    "policy": spec.policy,
                }
                for rel, spec in sorted(self.files.items())
            },
        }
        return json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")


@dataclass(frozen=True)
class DeltaInfo:
    """One from -> to delta advertised by latest.json."""

    from_version: str
    url: str
    sha256: str
    size: int

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DeltaInfo:
        if not isinstance(raw, dict):
            raise ValueError("delta must be a JSON object")
        sha256 = _require(raw, "sha256", str)
        if len(sha256) != 64:
            raise ValueError("delta sha256 must be 64 hex characters")
        return cls(
            from_version=_require(raw, "from", str),
            url=_require(raw, "url", str),
            sha256=sha256,
            size=_require(raw, "size", int),
        )


@dataclass(frozen=True)
class ReleaseInfo:
    """Parsed latest.json payload."""

    schema_version: int
    version: str
    released_at: str
    min_supported_version: str
    manifest_url: str
    manifest_sha256: str
    full_package_url: str
    full_package_sha256: str
    full_package_size: int
    deltas: tuple[DeltaInfo, ...]
    release_notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ReleaseInfo:
        if not isinstance(raw, dict):
            raise ValueError("latest.json must be a JSON object")
        schema = _require(raw, "schema_version", int)
        if schema != SCHEMA_VERSION:
            raise ValueError(f"unsupported latest.json schema_version: {schema}")
        manifest_sha256 = _require(raw, "manifest_sha256", str)
        full_sha256 = _require(raw, "full_package_sha256", str)
        if len(manifest_sha256) != 64 or len(full_sha256) != 64:
            raise ValueError("sha256 fields must be 64 hex characters")
        raw_deltas = raw.get("deltas", [])
        if not isinstance(raw_deltas, list):
            raise ValueError("deltas must be a JSON array")
        deltas = tuple(DeltaInfo.from_dict(item) for item in raw_deltas if isinstance(item, dict))
        return cls(
            schema_version=schema,
            version=_require(raw, "version", str),
            released_at=_require(raw, "released_at", str),
            min_supported_version=_require(raw, "min_supported_version", str),
            manifest_url=_require(raw, "manifest_url", str),
            manifest_sha256=manifest_sha256,
            full_package_url=_require(raw, "full_package_url", str),
            full_package_sha256=full_sha256,
            full_package_size=_require(raw, "full_package_size", int),
            deltas=deltas,
            release_notes=str(raw.get("release_notes", "")),
        )


@dataclass(frozen=True)
class UpdatePlan:
    """What the client should download for this update."""

    kind: Literal["delta", "full"]
    to_version: str
    url: str
    sha256: str
    size: int
    manifest_url: str
    manifest_sha256: str
    from_version: str | None = None


@dataclass
class UpdateState:
    """Persisted update state under the external updates root."""

    status: str
    from_version: str = ""
    to_version: str = ""
    staged_dir: str = ""
    backup_dir: str = ""
    manifest_sha256: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> UpdateState:
        if not isinstance(raw, dict):
            raise ValueError("update state must be a JSON object")
        return cls(
            status=_require(raw, "status", str),
            from_version=str(raw.get("from", "")),
            to_version=str(raw.get("to", "")),
            staged_dir=str(raw.get("staged_dir", "")),
            backup_dir=str(raw.get("backup_dir", "")),
            manifest_sha256=str(raw.get("manifest_sha256", "")),
            updated_at=str(raw.get("updated_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "from": self.from_version,
            "to": self.to_version,
            "staged_dir": self.staged_dir,
            "backup_dir": self.backup_dir,
            "manifest_sha256": self.manifest_sha256,
            "updated_at": self.updated_at,
        }
