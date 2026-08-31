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


def test_large_search_artifacts_have_one_full_payload_consumer() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")

    assert "Artifact to exactly one\ndownstream Agent" in skill
    assert "instead of attaching the candidate Artifact to several Agent Steps" in skill
    assert "Preserve\nthe complete source result in its Artifact" in skill


def test_valid_results_bypass_repair_in_the_deciding_agent() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")

    assert "give the same\nAgent the validator tool" in skill
    assert "perform no repair work on the\nvalid path" in skill
    assert "Do not author an always-executed validator Agent" in skill
