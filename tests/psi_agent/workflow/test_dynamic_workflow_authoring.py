from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
import types
from pathlib import Path

import anyio
from fusion_flow.workflow_graph import ConsumesEdge, ProducesEdge
from fusion_flow.workflow_runner import compile_workflow

_ROOT = Path(__file__).parents[3]
_WORKFLOW_SKILL = _ROOT / "examples" / "haitun-workspace" / "skills" / "workflow"
_SKILL_PATH = _WORKFLOW_SKILL / "SKILL.md"
_AUTHORING_REFERENCE_PATH = _WORKFLOW_SKILL / "references" / "dynamic-workflow-authoring.md"
_PIEBALD_NOTICE_PATH = _WORKFLOW_SKILL / "references" / "PIEBALD_LICENSE.md"
_AUTHORING_REFERENCE = "references/dynamic-workflow-authoring.md"
_SYSTEM_PATH = _ROOT / "examples" / "haitun-workspace" / "systems" / "system.py"


def _normalized(markdown: str) -> str:
    return " ".join(markdown.lower().split())


def _paragraphs(markdown: str) -> tuple[str, ...]:
    return tuple(_normalized(paragraph) for paragraph in re.split(r"\n\s*\n", markdown) if paragraph.strip())


def _assert_terms_share_paragraph(
    paragraphs: tuple[str, ...],
    concept: str,
    *alternatives: tuple[str, ...],
) -> None:
    assert any(all(term in paragraph for term in terms) for paragraph in paragraphs for terms in alternatives), (
        f"missing authoring guidance for {concept}"
    )


def _boundary_sections(markdown: str) -> tuple[str, ...]:
    lines = markdown.splitlines()
    sections: list[str] = []
    for index, line in enumerate(lines):
        heading = re.fullmatch(r"(#{1,6})\s+(.+)", line.strip())
        if heading is None or "boundar" not in heading.group(2).lower():
            continue
        level = len(heading.group(1))
        end = len(lines)
        for candidate_index in range(index + 1, len(lines)):
            candidate = re.fullmatch(r"(#{1,6})\s+(.+)", lines[candidate_index].strip())
            if candidate is not None and len(candidate.group(1)) <= level:
                end = candidate_index
                break
        sections.append(_normalized("\n".join(lines[index:end])))
    return tuple(sections)


def _load_haitun_system() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_dynamic_workflow_system", _SYSTEM_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_path = sys.path.copy()
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
        sys.modules.pop(spec.name, None)
    return module


def test_skill_requires_dynamic_authoring_reference() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    lines = skill.splitlines()
    reference_lines = [index for index, line in enumerate(lines) if _AUTHORING_REFERENCE in line]

    assert reference_lines, f"SKILL.md must link {_AUTHORING_REFERENCE}"
    context = _normalized(
        "\n".join("\n".join(lines[max(0, index - 2) : min(len(lines), index + 3)]) for index in reference_lines)
    )
    assert "read" in context
    assert any(
        marker in context
        for marker in (
            "must",
            "required",
            "mandatory",
            "before authoring",
            "before writing",
            "before modeling",
        )
    )


def test_workflow_execution_requires_explicit_user_opt_in() -> None:
    skill = _normalized(_SKILL_PATH.read_text(encoding="utf-8"))
    system = _normalized(_SYSTEM_PATH.read_text(encoding="utf-8"))

    for prompt in (skill, system):
        assert "explicit" in prompt
        assert "opt" in prompt or "authorization" in prompt
        assert "merely benefit" in prompt
        assert "does not" in prompt
        assert "before authoring or running" in prompt

    assert "describes any task that needs" not in skill
    assert "by default for multi-agent or multi-step work" not in system
    assert "does not by itself authorize execution" in skill
    assert "management-only" in system
    assert "do not call `run_flow` unless the user also asks" in system


def test_skills_index_routes_workflow_only_after_explicit_opt_in(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "workflow"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_bytes(_SKILL_PATH.read_bytes())

    system_module = _load_haitun_system()
    system_module._GLOBAL_AGENT_SKILLS_DIR = anyio.Path(tmp_path / "global-skills")
    skills_index = anyio.run(system_module._build_skills_index, anyio.Path(tmp_path))
    workflow_entry = skills_index.split('<skill name="workflow"', 1)[1].split("/>", 1)[0]
    normalized = _normalized(workflow_entry)

    assert "explicit workflow or multi-agent opt-in" in normalized
    assert "parallel sub-tasks" not in normalized
    assert "multi-step pipelines" not in normalized


def test_skill_keeps_verification_patterns_risk_scaled() -> None:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    paragraphs = _paragraphs(skill)

    _assert_terms_share_paragraph(
        paragraphs,
        "risk-scaled verifier selection",
        ("optional quality patterns", "task risk", "cost or latency"),
        ("optional pattern", "task risk", "cost or latency"),
    )
    normalized = _normalized(skill)
    assert "append the adversarial verifier" not in normalized
    assert "any reviewable agent-built result" not in normalized


def test_adaptation_preserves_source_repository_notice() -> None:
    reference = _AUTHORING_REFERENCE_PATH.read_text(encoding="utf-8")
    notice = _PIEBALD_NOTICE_PATH.read_bytes()

    assert "738bccbb279db7024b9a41f921b473d31ddc421a" in reference
    assert "source repository carries the MIT notice" in reference
    assert "underlying prompt text as extracted from Claude Code" in reference
    assert hashlib.sha256(notice).hexdigest() == "453afa8ddc35be35fa2dfd13762476bf058255d4af8b61b5acc3d9c20813e322"


def test_reference_defines_domain_neutral_dynamic_authoring_invariants() -> None:
    reference = _AUTHORING_REFERENCE_PATH.read_text(encoding="utf-8")
    paragraphs = _paragraphs(reference)

    _assert_terms_share_paragraph(
        paragraphs,
        "hybrid scouting",
        ("hybrid", "scout", "broad", "targeted"),
        ("hybrid", "scout", "breadth", "depth"),
        ("hybrid", "scout", "broad", "deep"),
    )
    _assert_terms_share_paragraph(
        paragraphs,
        "explicit Artifact dataflow",
        ("explicit", "artifact", "consume", "produce"),
        ("explicit", "artifact", "input", "output"),
    )
    _assert_terms_share_paragraph(
        paragraphs,
        "clean Step context",
        ("clean", "step", "context"),
        ("step", "context", "only", "needs"),
    )
    _assert_terms_share_paragraph(
        paragraphs,
        "branch-local pipelines",
        ("branch-local", "pipeline"),
        ("within each branch", "pipeline"),
    )
    _assert_terms_share_paragraph(
        paragraphs,
        "true cross-branch joins",
        ("only", "cross-branch", "join"),
        ("join", "branches", "actually needs"),
        ("join", "branches", "truly needs"),
    )
    _assert_terms_share_paragraph(
        paragraphs,
        "structured contracts",
        ("structured", "contract", "schema"),
        ("artifact contract", "schema"),
    )
    _assert_terms_share_paragraph(
        paragraphs,
        "explicit scale without silent caps",
        ("scale", "silent cap"),
        ("scale", "silently cap"),
        ("requested count", "arbitrary cap"),
    )
    _assert_terms_share_paragraph(
        paragraphs,
        "risk-scaled optional quality patterns",
        ("optional", "risk", "cost"),
        ("optional", "risk", "latency"),
    )
    _assert_terms_share_paragraph(
        paragraphs,
        "fixed-round cumulative deduplication",
        ("seen_candidates", "refuted", "rejected"),
        ("cumulative", "seen", "rejected"),
    )

    normalized = _normalized(reference)
    principles = {
        "adversarial checking": ("adversarial",),
        "different lenses": ("different lenses", "distinct lenses", "independent lenses"),
        "judging": ("judge", "judging"),
        "multiple modalities": ("multi-modal", "multimodal", "multiple modalities"),
        "completeness": ("completeness", "complete coverage"),
    }
    for principle, alternatives in principles.items():
        assert any(marker in normalized for marker in alternatives), f"missing authoring principle: {principle}"

    assert "uncertain returned verdict as `refuted`" in normalized
    assert "explicit majority" in normalized
    assert "does not become a missing value or a vote" in normalized


def test_reference_marks_external_runtime_features_outside_g4() -> None:
    reference = _AUTHORING_REFERENCE_PATH.read_text(encoding="utf-8")
    sections = _boundary_sections(reference)

    assert sections, "the reference must define an explicit capability boundary"
    boundary = " ".join(sections)
    assert "g4" in boundary
    for feature_terms in (
        ("claude", "javascript", "api"),
        ("ultracode",),
        ("background",),
        ("cached", "resume"),
    ):
        assert all(term in boundary for term in feature_terms)
    assert any(
        marker in boundary
        for marker in (
            "not g4 capabilities",
            "not supported by g4",
            "outside g4",
            "do not claim",
            "must not claim",
            "cannot claim",
            "unsupported in g4",
        )
    )


def test_software_migration_graph_keeps_branches_local_until_synthesis() -> None:
    source = r"""
-- @artifact migration_request [object]: Target state, constraints, and acceptance criteria.
-- @artifact repository_snapshot [object]: Application modules and dependency metadata.
-- @artifact runtime_inventory [object]: Runtime services, configuration, and deployment metadata.
-- @artifact application_findings [object]: Traceable application migration findings.
-- @artifact platform_findings [object]: Traceable runtime migration findings.
-- @artifact verified_application [object]: Checked application changes and unresolved risks.
-- @artifact verified_platform [object]: Checked platform changes and unresolved risks.
-- @artifact migration_plan [object]: Integrated migration sequence, dependencies, risks, and checks.

const migration_request: Artifact;
const repository_snapshot: Artifact;
const runtime_inventory: Artifact;
const application_findings: Artifact;
const platform_findings: Artifact;
const verified_application: Artifact;
const verified_platform: Artifact;
const migration_plan: Artifact;

const discover_application: Step;
const verify_application: Step;
const discover_platform: Step;
const verify_platform: Step;
const synthesize_plan: Step;

const application_scout: Agent, Executor;
const application_verifier: Agent, Executor;
const platform_scout: Agent, Executor;
const platform_verifier: Agent, Executor;
const migration_editor: Agent, Executor;

workflow software_migration {
  input_workflow(software_migration) ==
    [migration_request, repository_snapshot, runtime_inventory];

  consumes(discover_application) == [migration_request, repository_snapshot];
  produces(discover_application) == [application_findings];
  consumes(verify_application) ==
    [migration_request, repository_snapshot, application_findings];
  produces(verify_application) == [verified_application];

  consumes(discover_platform) == [migration_request, runtime_inventory];
  produces(discover_platform) == [platform_findings];
  consumes(verify_platform) ==
    [migration_request, runtime_inventory, platform_findings];
  produces(verify_platform) == [verified_platform];

  consumes(synthesize_plan) ==
    [migration_request, verified_application, verified_platform];
  produces(synthesize_plan) == [migration_plan];
  output_workflow(software_migration) == [migration_plan];

  step_executor(discover_application) == application_scout;
  step_executor(verify_application) == application_verifier;
  step_executor(discover_platform) == platform_scout;
  step_executor(verify_platform) == platform_verifier;
  step_executor(synthesize_plan) == migration_editor;

  step_name(discover_application) == "Discover Application Changes";
  step_instruction(discover_application) == "Inspect repository evidence. Return target changes and open questions.";
  step_name(verify_application) == "Verify Application Findings";
  step_instruction(verify_application) == "Check application findings against repository evidence; return risks.";
  step_name(discover_platform) == "Discover Platform Changes";
  step_instruction(discover_platform) == "Inspect runtime evidence. Return target changes and open questions.";
  step_name(verify_platform) == "Verify Platform Findings";
  step_instruction(verify_platform) == "Check platform findings against runtime evidence; return risks.";
  step_name(synthesize_plan) == "Synthesize Migration Plan";
  step_instruction(synthesize_plan) == "Integrate verified branches into a plan with dependencies and checks.";

  max_concurrency(software_migration) == 2;
}
"""

    graph = compile_workflow(source).graph
    consumed = {
        step.step_id: {
            edge.artifact_id for edge in graph.edges if isinstance(edge, ConsumesEdge) and edge.step_id == step.step_id
        }
        for step in graph.steps
    }
    produced = {
        step.step_id: {
            edge.artifact_id for edge in graph.edges if isinstance(edge, ProducesEdge) and edge.step_id == step.step_id
        }
        for step in graph.steps
    }

    assert consumed == {
        "discover_application": {"migration_request", "repository_snapshot"},
        "verify_application": {
            "migration_request",
            "repository_snapshot",
            "application_findings",
        },
        "discover_platform": {"migration_request", "runtime_inventory"},
        "verify_platform": {
            "migration_request",
            "runtime_inventory",
            "platform_findings",
        },
        "synthesize_plan": {
            "migration_request",
            "verified_application",
            "verified_platform",
        },
    }
    assert produced == {
        "discover_application": {"application_findings"},
        "verify_application": {"verified_application"},
        "discover_platform": {"platform_findings"},
        "verify_platform": {"verified_platform"},
        "synthesize_plan": {"migration_plan"},
    }

    producer_by_artifact = {edge.artifact_id: edge.step_id for edge in graph.edges if isinstance(edge, ProducesEdge)}
    branch_by_step = {
        "discover_application": "application",
        "verify_application": "application",
        "discover_platform": "platform",
        "verify_platform": "platform",
    }
    for edge in graph.edges:
        if not isinstance(edge, ConsumesEdge) or edge.step_id == "synthesize_plan":
            continue
        producer = producer_by_artifact.get(edge.artifact_id)
        if producer is not None:
            assert branch_by_step[producer] == branch_by_step[edge.step_id]

    synthesis_producers = {
        producer_by_artifact[artifact_id]
        for artifact_id in consumed["synthesize_plan"]
        if artifact_id in producer_by_artifact
    }
    assert synthesis_producers == {"verify_application", "verify_platform"}
    assert {artifact.artifact_id for artifact in graph.artifacts if artifact.is_output} == {"migration_plan"}
