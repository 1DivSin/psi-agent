from pathlib import Path

import pytest

from psi_agent.updater.apply import (
    launch_bootstrap,
    read_state,
    write_state,
    write_swap_requested,
)
from psi_agent.updater.models import UpdateState


def test_state_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "updates"
    state = UpdateState(status="prepared", from_version="1.0.4", to_version="1.0.5")
    write_state(root, state)
    loaded = read_state(root)
    assert loaded is not None
    assert loaded.to_version == "1.0.5"


def test_swap_requested_written(tmp_path: Path) -> None:
    root = tmp_path / "updates"
    state = UpdateState(status="prepared")
    write_swap_requested(root, state)
    assert (root / "swap-requested.json").is_file()


def test_launch_bootstrap_requires_exe(tmp_path: Path) -> None:
    root = tmp_path / "updates"
    with pytest.raises(FileNotFoundError):
        launch_bootstrap(root, tmp_path / "install", tmp_path / "stage", tmp_path / "backup")
