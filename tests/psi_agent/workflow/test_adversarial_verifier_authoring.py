from __future__ import annotations

from pathlib import Path

from fusion_flow.workflow_graph import ConsumesEdge, ProducesEdge
from fusion_flow.workflow_runner import compile_workflow

_ROOT = Path(__file__).parents[3]
_SKILL_PATH = _ROOT / "examples" / "haitun-workspace" / "skills" / "workflow" / "SKILL.md"


def _verifier_section() -> str:
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    return skill.split("### Adversarial verifier pattern", 1)[1].split(
        "#### Full-featured in-context example", 1
    )[0]


def test_authoring_prompt_builds_verifier_from_visible_contract_and_evidence() -> None:
    section = _verifier_section()
    normalized = " ".join(section.split())

    assert "Do not call tools or" in section
    assert "Build a checklist from the visible task contract" in section
    assert "Report PASS or FAIL for each applicable check with concrete evidence" in section
    assert "verdict to OK" in normalized
    assert "verdict to FIXED" in normalized
    assert "hidden scoring feedback" in section
    assert "same visible task contract and evidence" in section

    benchmark_terms = {
        "travelplanner",
        "flight number",
        "accommodation",
        "restaurant",
        "attraction",
        "itinerary",
    }
    lowered = section.lower()
    assert all(term not in lowered for term in benchmark_terms)


def test_non_travel_release_notes_can_compile_analyze_build_verify_shape() -> None:
    source = r'''
const task_contract: Artifact;
const change_evidence: Artifact;
const change_analysis: Artifact;
const candidate_notes: Artifact;
const verification_report: Artifact;
const final_notes: Artifact;

const analyze_changes: Step;
const build_notes: Step;
const verify_notes: Step;

const analyst: Agent, Executor;
const writer: Agent, Executor;
const verifier: Agent, Executor;

workflow release_notes {
  input_workflow(release_notes) == [task_contract, change_evidence];
  consumes(analyze_changes) == [task_contract, change_evidence];
  produces(analyze_changes) == [change_analysis];
  consumes(build_notes) == [task_contract, change_evidence, change_analysis];
  produces(build_notes) == [candidate_notes];
  consumes(verify_notes) == [task_contract, change_evidence, candidate_notes];
  produces(verify_notes) == [verification_report, final_notes];
  output_workflow(release_notes) == [final_notes];

  step_executor(analyze_changes) == analyst;
  step_executor(build_notes) == writer;
  step_executor(verify_notes) == verifier;

  step_name(analyze_changes) == "Analyze Changes";
  step_instruction(analyze_changes) == "Analyze the evidence against the contract and return traceable findings.";
  step_name(build_notes) == "Build Candidate Notes";
  step_instruction(build_notes) == "Build candidate notes from the inputs without unsupported claims.";
  step_name(verify_notes) == "Adversarially Verify Notes";
  step_instruction(verify_notes) == "Refute the candidate from the inputs; report checks and return corrected notes.";
}
'''

    compiled = compile_workflow(source)
    graph = compiled.graph

    assert [step.step_id for step in graph.steps] == ["analyze_changes", "build_notes", "verify_notes"]
    verifier_inputs = {
        edge.artifact_id
        for edge in graph.edges
        if isinstance(edge, ConsumesEdge) and edge.step_id == "verify_notes"
    }
    verifier_outputs = {
        edge.artifact_id
        for edge in graph.edges
        if isinstance(edge, ProducesEdge) and edge.step_id == "verify_notes"
    }
    assert verifier_inputs == {"task_contract", "change_evidence", "candidate_notes"}
    assert verifier_outputs == {"verification_report", "final_notes"}
    assert {artifact.artifact_id for artifact in graph.artifacts if artifact.is_output} == {"final_notes"}
