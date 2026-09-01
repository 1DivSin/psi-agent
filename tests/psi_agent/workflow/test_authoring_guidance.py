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


def test_bounded_workflow_defaults_preserve_the_dynamic_carrier_limits() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    bounded = _section(skill, "Bounded workflow defaults")

    for required_guidance in (
        "at most 3 logical execution phases",
        "at most 5 Agent Steps",
        "at most 5 tool calls",
        "try one alternative and then move on",
        "workflow_timeout(workflow_id) == 600",
        "good-enough result",
        "Parallelize only independent work",
    ):
        assert required_guidance in bounded


def test_bounded_defaults_are_domain_neutral_for_document_review() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    bounded = _section(skill, "Bounded workflow defaults")

    assert "document-review workflow" in bounded
    assert "independent reviews" in bounded
    assert "dependent synthesis Step" in bounded
    for domain_term in (
        "TravelPlanner",
        "flight",
        "accommodation",
        "restaurant",
        "attraction",
        "itinerary",
    ):
        assert domain_term not in bounded
