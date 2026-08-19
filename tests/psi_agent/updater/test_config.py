from pathlib import Path

from psi_agent.updater.config import (
    read_conf,
    read_local_version,
    updates_root,
)
from psi_agent.updater.models import UpdateState


def test_read_conf_parses_key_values(tmp_path: Path) -> None:
    conf = tmp_path / "haitun-update.conf"
    conf.write_text(
        '# comment\nHAITUN_VERSION=1.0.4\nHAITUN_UPDATE_BASE_URL="https://x/"\n\n',
        encoding="utf-8",
    )
    parsed = read_conf(tmp_path)
    assert parsed["HAITUN_VERSION"] == "1.0.4"
    assert parsed["HAITUN_UPDATE_BASE_URL"] == "https://x/"


def test_updates_root_honors_localappdata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert updates_root() == tmp_path / "HaiTun Agent" / "updates"


def test_local_version_prefers_applied_state(tmp_path: Path) -> None:
    conf = tmp_path / "haitun-update.conf"
    conf.write_text("HAITUN_VERSION=1.0.4\n", encoding="utf-8")
    state = UpdateState(status="applied", from_version="1.0.4", to_version="1.0.5")
    assert read_local_version(tmp_path, state) == "1.0.5"
    assert read_local_version(tmp_path, None) == "1.0.4"
