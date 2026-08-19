"""Locate the install directory and read haitun-update.conf."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from psi_agent.updater.models import UpdateState

CONF_NAME = "haitun-update.conf"
UPDATES_ROOT_NAME = Path("HaiTun Agent") / "updates"


def updates_root() -> Path:
    """External update directory, deliberately outside the install dir."""
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / UPDATES_ROOT_NAME


def resolve_install_dir(explicit: str | None) -> Path:
    if explicit and explicit.strip():
        return Path(explicit).resolve()
    exe = Path(sys.executable).resolve()
    if exe.name.lower() in ("psi-agent.exe", "psi-agent"):
        return exe.parent
    return Path.cwd().resolve()


def read_conf(install_dir: Path) -> dict[str, str]:
    """Parse the KEY=VALUE file written by build-haitun-launcher.ps1."""
    path = install_dir / CONF_NAME
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def read_local_version(install_dir: Path, state: UpdateState | None) -> str:
    """Local version: applied update state wins, otherwise the conf file."""
    if state is not None and state.status == "applied" and state.to_version:
        return state.to_version
    return read_conf(install_dir).get("HAITUN_VERSION", "")
