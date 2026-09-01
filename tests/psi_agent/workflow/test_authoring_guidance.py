from __future__ import annotations

from pathlib import Path

_SKILL_PATH = Path(__file__).parents[3] / "examples" / "haitun-workspace" / "skills" / "workflow" / "SKILL.md"


def _section(markdown: str, heading: str) -> str:
    start_marker = f"### {heading}\n"
    start = markdown.index(start_marker) + len(start_marker)
    end = markdown.find("\n### ", start)
    return markdown[start:] if end == -1 else markdown[start:end]


def test_planning_contract_is_domain_neutral_and_complete() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    planning = _section(skill, "Planning contract")

    for required_guidance in (
        "intent and concrete success condition",
        "every external input and final output Artifact",
        "each Step's single responsibility",
        "information dependencies",
        "owner of every material constraint",
        "concurrency, timeout, retry, resource, and user-stated cost limits",
        "mechanically decidable constraints",
        "constraints that require judgment",
        "fan out independent work",
    ):
        assert required_guidance in planning


def test_guidance_excludes_quality_and_repair_policy() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    planning = _section(skill, "Planning contract").lower()

    for excluded_policy in (
        "quality gate",
        "repair",
    ):
        assert excluded_policy not in planning
