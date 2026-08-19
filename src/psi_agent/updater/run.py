"""self-update orchestration entry point."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from psi_agent.updater import apply as apply_mod
from psi_agent.updater.config import (
    read_conf,
    read_local_version,
    resolve_install_dir,
    updates_root,
)
from psi_agent.updater.fetch import download_file, fetch_json
from psi_agent.updater.models import (
    Manifest,
    ReleaseInfo,
    UpdatePlan,
    UpdateState,
)
from psi_agent.updater.semver import compare_versions
from psi_agent.updater.stage import (
    apply_delta,
    apply_full_package,
    copy_install_tree,
    write_conflicts,
)
from psi_agent.updater.verify import verify_files

RESULT_UP_TO_DATE = "up-to-date"
RESULT_TOO_OLD = "too-old"
RESULT_ALREADY_RUNNING = "already-running"
RESULT_NO_BASE_URL = "no-base-url"
RESULT_WOULD_UPDATE = "would-update"
RESULT_PREPARED = "prepared"
RESULT_APPLYING = "applying"


def plan_update(latest: ReleaseInfo, local_version: str) -> UpdatePlan:
    """Pick the delta when it matches the local version, else the full package."""
    for delta in latest.deltas:
        if delta.from_version == local_version:
            return UpdatePlan(
                kind="delta",
                to_version=latest.version,
                url=delta.url,
                sha256=delta.sha256,
                size=delta.size,
                manifest_url=latest.manifest_url,
                manifest_sha256=latest.manifest_sha256,
                from_version=local_version,
            )
    return UpdatePlan(
        kind="full",
        to_version=latest.version,
        url=latest.full_package_url,
        sha256=latest.full_package_sha256,
        size=latest.full_package_size,
        manifest_url=latest.manifest_url,
        manifest_sha256=latest.manifest_sha256,
        from_version=local_version or None,
    )


def _load_manifest(plan: UpdatePlan, archive: Path) -> Manifest:
    """Load the target manifest embedded in the package and verify its sha256."""
    with zipfile.ZipFile(archive) as zf:
        raw = zf.read("manifest.json")
    if hashlib.sha256(raw).hexdigest() != plan.manifest_sha256:
        raise ValueError("manifest sha256 mismatch")
    return Manifest.from_dict(json.loads(raw))


def _load_previous_manifest(updates_root: Path, from_version: str | None) -> Manifest | None:
    if not from_version:
        return None
    path = updates_root / "manifests" / f"{from_version}.json"
    if not path.is_file():
        return None
    return Manifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _save_manifest(updates_root: Path, manifest: Manifest) -> None:
    target = updates_root / "manifests" / f"{manifest.version}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(manifest.to_bytes())


def run_self_update(
    *,
    base_url: str = "",
    install_dir: str = "",
    check_only: bool = False,
    yes: bool = False,
    allow_insecure: bool = False,
) -> str:
    root = updates_root()
    root.mkdir(parents=True, exist_ok=True)

    state = apply_mod.read_state(root)
    if state is not None and state.status in ("prepared", "applying"):
        return RESULT_ALREADY_RUNNING

    install = resolve_install_dir(install_dir)
    conf = read_conf(install)
    base = base_url.strip() or conf.get("HAITUN_UPDATE_BASE_URL", "").strip()
    if not base:
        return RESULT_NO_BASE_URL

    local_version = read_local_version(install, state)
    latest = ReleaseInfo.from_dict(fetch_json(base.rstrip("/") + "/latest.json", allow_insecure=allow_insecure))
    if compare_versions(latest.version, local_version) <= 0:
        return RESULT_UP_TO_DATE
    if compare_versions(local_version, latest.min_supported_version) < 0:
        return RESULT_TOO_OLD

    plan = plan_update(latest, local_version)
    if check_only:
        return RESULT_WOULD_UPDATE

    archive = root / "archives" / f"{plan.kind}-{plan.to_version}.zip"
    download_file(
        plan.url,
        archive,
        expected_sha256=plan.sha256,
        allow_insecure=allow_insecure,
    )
    manifest = _load_manifest(plan, archive)

    staging = root / "stage" / plan.to_version
    copy_install_tree(install, staging)
    previous = _load_previous_manifest(root, plan.from_version)
    if plan.kind == "delta":
        conflicts, applied = apply_delta(staging, archive, manifest, previous=previous)
    else:
        conflicts, applied = apply_full_package(staging, archive, manifest, previous=previous)
    write_conflicts(root, plan.to_version, conflicts)

    # Delta verifies only applied files; a full package must contain every
    # manifest file, so anything not applied is a broken release.
    verify_skip = set(manifest.files) - set(applied) if plan.kind == "delta" else set(conflicts)
    problems = verify_files(manifest, staging, skip=verify_skip)
    if problems:
        shutil.rmtree(staging, ignore_errors=True)
        raise ValueError(f"staging verification failed for: {', '.join(problems[:10])}")

    backup = root / "backups" / f"{local_version}-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    if not yes:
        return RESULT_PREPARED

    backup.parent.mkdir(parents=True, exist_ok=True)
    _save_manifest(root, manifest)
    apply_mod.write_state(
        root,
        UpdateState(
            status="prepared",
            from_version=local_version,
            to_version=plan.to_version,
            staged_dir=str(staging),
            backup_dir=str(backup),
            manifest_sha256=plan.manifest_sha256,
            updated_at=datetime.now(UTC).isoformat(),
        ),
    )
    try:
        apply_mod.launch_bootstrap(root, install, staging, backup)
    except OSError:
        apply_mod.write_state(
            root,
            UpdateState(
                status="failed",
                from_version=local_version,
                to_version=plan.to_version,
                staged_dir=str(staging),
                backup_dir=str(backup),
                manifest_sha256=plan.manifest_sha256,
                updated_at=datetime.now(UTC).isoformat(),
            ),
        )
        raise
    prepared = apply_mod.read_state(root)
    if prepared is not None:
        apply_mod.write_swap_requested(root, prepared)
    return RESULT_APPLYING
