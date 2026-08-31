from __future__ import annotations

from pathlib import Path

_SKILL_PATH = (
    Path(__file__).parents[3]
    / "examples"
    / "haitun-workspace"
    / "skills"
    / "workflow"
    / "SKILL.md"
)


def test_authoring_keeps_internal_process_silent_without_skipping_checks() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")

    assert "Keep the authoring process silent." in skill
    assert "do not narrate reasoning, alternative graph designs" in skill
    assert "perform every authoring and static-check step in full" in skill
