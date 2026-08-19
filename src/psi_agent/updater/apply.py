"""Update state persistence and bootstrap launch."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from psi_agent.updater.models import UpdateState

STATE_FILE = "update-state.json"
SWAP_FILE = "swap-requested.json"
BOOTSTRAP_NAME = "haitun-updater.exe"


def read_state(updates_root: Path) -> UpdateState | None:
    path = updates_root / STATE_FILE
    if not path.is_file():
        return None
    try:
        return UpdateState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except ValueError, OSError:
        return None


def write_state(updates_root: Path, state: UpdateState) -> None:
    updates_root.mkdir(parents=True, exist_ok=True)
    path = updates_root / STATE_FILE
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def write_swap_requested(updates_root: Path, state: UpdateState) -> None:
    updates_root.mkdir(parents=True, exist_ok=True)
    path = updates_root / SWAP_FILE
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def launch_bootstrap(
    updates_root: Path,
    install_dir: Path,
    staging: Path,
    backup: Path,
) -> subprocess.Popen[bytes]:
    exe = updates_root / BOOTSTRAP_NAME
    if not exe.is_file():
        raise FileNotFoundError(f"bootstrap not found: {exe}")
    cmd = [str(exe), str(install_dir), str(staging), str(backup), str(updates_root)]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(cmd, creationflags=creationflags)
