from __future__ import annotations

import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

_REPOSITORY_ROOT = Path(__file__).parents[2]
_WORKFLOW_SKILL = _REPOSITORY_ROOT / "agents" / "feishu" / "skills" / "workflow"
_WORKFLOW_TOOLS = _REPOSITORY_ROOT / "agents" / "feishu" / "tools"
sys.path.insert(0, str(_WORKFLOW_SKILL))

fusion_flow = importlib.import_module("fusion_flow")
_execution = importlib.import_module("fusion_flow.execution")
_workflow_execution = importlib.import_module("fusion_flow.workflow_execution")
_workflow_runner = importlib.import_module("fusion_flow.workflow_runner")

AgentConfig = _execution.AgentConfig
flow = _execution.flow
DispatchContext = _workflow_execution.DispatchContext
create_execution_checkpoint = _workflow_execution.create_execution_checkpoint
generate_plan = _workflow_execution.generate_plan
ArtifactContract = _workflow_runner.ArtifactContract
CompletionContext = _workflow_runner.CompletionContext
ProgramInvocation = _workflow_runner.ProgramInvocation
compile_workflow = _workflow_runner.compile_workflow
execute_workflow = _workflow_runner.execute_workflow
validate_artifact_values = _workflow_runner.validate_artifact_values


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _section(markdown: str, heading: str, *, level: int) -> str:
    marker = f"{'#' * level} {heading}\n"
    start = markdown.index(marker) + len(marker)
    next_heading = f"\n{'#' * level} "
    end = markdown.find(next_heading, start)
    return markdown[start:] if end == -1 else markdown[start:end]


def _single_step_source(*, instruction: str, comments: str = "") -> str:
    encoded_instruction = json.dumps(instruction)
    return f"""{comments}
const source_document: Artifact;
const summary_sections: Artifact;
const summarize_step: Step;
const writer: Agent, Executor;

workflow document_summary {{
  input_workflow(document_summary) == [source_document];
  consumes(summarize_step) == [source_document];
  produces(summarize_step) == [summary_sections];
  output_workflow(document_summary) == [summary_sections];
  step_executor(summarize_step) == writer;
  step_name(summarize_step) == "Summarize";
  step_instruction(summarize_step) == {encoded_instruction};
}}
"""


def test_authoring_guidance_defines_domain_neutral_contracts() -> None:
    skill = (_WORKFLOW_SKILL / "SKILL.md").read_text(encoding="utf-8")
    planning = _section(skill, "Planning contract", level=3)

    for guidance in (
        "intent and concrete success condition",
        "every external input and final output Artifact",
        "each Step's single responsibility",
        "owner of every material constraint",
        "concurrency, timeout, retry, resource, and user-stated cost limits",
        "mechanically decidable constraints",
        "constraints that require judgment",
        "fan out independent work",
    ):
        assert guidance in planning
    assert "quality gate" not in planning.lower()
    assert "repair" not in planning.lower()

    artifact_contracts = _section(skill, "Artifact Contracts", level=2)
    assert "top-level JSON type" in artifact_contracts
    assert "deterministic Program validation Step" in artifact_contracts
    assert "Keep the authoring process silent." in skill
    assert "perform every authoring and static-check step in full" in skill


def test_generic_agent_operator_arguments_and_bool_shorthand_parse() -> None:
    source = """
const review_agent: Agent, Executor;
const model: Model;
const engine: Engine;
const api_base: ApiBase;
const read: Tool;

workflow code_review {
  agent_config(review_agent, model, engine, api_base);
  allowed_tool(review_agent, read);
}
"""
    concepts = {
        name: fusion_flow.Concept(name) for name in ("Agent", "ApiBase", "Bool", "Engine", "Executor", "Model", "Tool")
    }
    context = fusion_flow.ParseContext(
        concepts=concepts,
        operators={
            "agent_config": fusion_flow.Operator(
                name="agent_config",
                input_concepts=tuple(concepts[name] for name in ("Agent", "Model", "Engine", "ApiBase")),
                output_concept=concepts["Bool"],
            ),
            "allowed_tool": fusion_flow.Operator(
                name="allowed_tool",
                input_concepts=(concepts["Agent"], concepts["Tool"]),
                output_concept=concepts["Bool"],
            ),
        },
    )

    parsed = fusion_flow.parse_workflow(source, context=context)

    assert parsed.diagnostics == ()
    assert parsed.core_ir is not None
    calls = []
    for assertion in parsed.core_ir.workflows[0].assertions:
        assert isinstance(assertion.lhs, fusion_flow.CompoundTerm)
        assert isinstance(assertion.rhs, fusion_flow.Constant)
        assert assertion.rhs.symbol == "True"
        calls.append(assertion.lhs)
    assert [call.operator.name for call in calls] == ["agent_config", "allowed_tool"]
    assert [term.symbol for term in calls[0].arguments if isinstance(term, fusion_flow.Constant)] == [
        "review_agent",
        "model",
        "engine",
        "api_base",
    ]


@pytest.mark.anyio
async def test_artifact_contracts_reach_prompt_context_and_runtime_validation() -> None:
    source = _single_step_source(
        comments="-- @artifact source_document [object]: Required keys are title and body.",
        instruction=(
            "Summarize the supplied document.\n"
            "@artifact summary_sections [array]: Ordered objects with heading and body keys."
        ),
    )
    observed_prompt = ""
    observed_context: CompletionContext | None = None

    async def complete(prompt: str, context: CompletionContext) -> object:
        nonlocal observed_context, observed_prompt
        observed_prompt = prompt
        observed_context = context
        return {"summary_sections": [{"heading": "Overview", "body": "Short summary"}]}

    outputs = await execute_workflow(
        source,
        inputs={"source_document": {"title": "Example", "body": "Text"}},
        complete=complete,
    )

    assert outputs == {"summary_sections": [{"heading": "Overview", "body": "Short summary"}]}
    assert observed_context is not None
    assert observed_context.input_contracts["source_document"].json_type == "object"
    assert observed_context.output_contracts["summary_sections"].json_type == "array"
    assert "Input Artifact contracts" in observed_prompt
    assert "Ordered objects with heading and body keys" in observed_prompt

    called = False

    async def should_not_run(prompt: str, context: CompletionContext) -> object:
        nonlocal called
        del prompt, context
        called = True
        return {"summary_sections": []}

    with pytest.raises(ValueError, match="workflow inputs Artifact 'source_document' must be JSON object"):
        await execute_workflow(source, inputs={"source_document": []}, complete=should_not_run)
    assert called is False


@pytest.mark.parametrize(
    ("comments", "error"),
    (
        (
            "-- @artifact missing_document [object]: This identifier is not declared.",
            "unknown Artifacts",
        ),
        (
            "-- @artifact summary_sections [dictionary]: Unsupported type spelling.",
            "malformed Artifact contract",
        ),
    ),
)
def test_compile_rejects_invalid_artifact_contracts(comments: str, error: str) -> None:
    source = _single_step_source(
        comments=comments,
        instruction="Summarize source_document into summary_sections.",
    )

    with pytest.raises(ValueError, match=error):
        compile_workflow(source)


@pytest.mark.anyio
async def test_conflicting_and_wrong_step_outputs_fail() -> None:
    conflicting = _single_step_source(
        comments="-- @artifact summary_sections [object]: A keyed summary.",
        instruction=("Summarize the document.\n@artifact summary_sections [array]: Ordered summary sections."),
    )
    called = False

    async def complete(prompt: str, context: CompletionContext) -> object:
        nonlocal called
        del prompt, context
        called = True
        return {"summary_sections": []}

    with pytest.raises(ValueError, match="conflicting Artifact contracts"):
        await execute_workflow(conflicting, inputs={"source_document": {}}, complete=complete)
    assert called is False

    wrong_output = _single_step_source(
        instruction=("Summarize the document.\n@artifact summary_sections [array]: Ordered summary sections.")
    )

    async def return_wrong_type(prompt: str, context: CompletionContext) -> object:
        del prompt, context
        return {"summary_sections": "not-an-array"}

    with pytest.raises(ExceptionGroup) as caught:
        await execute_workflow(wrong_output, inputs={"source_document": {}}, complete=return_wrong_type)
    assert len(caught.value.exceptions) == 1
    assert "must be JSON array" in str(caught.value.exceptions[0])


@pytest.mark.anyio
async def test_checkpoint_values_still_obey_artifact_contracts() -> None:
    source = _single_step_source(
        instruction=("Summarize the document.\n@artifact summary_sections [array]: Ordered summary sections.")
    )
    compiled = compile_workflow(source)
    checkpoint = create_execution_checkpoint(
        generate_plan(compiled.graph),
        compiled.graph,
        values={"source_document": {}, "summary_sections": "not-an-array"},
        completed_step_ids=("summarize_step",),
    )
    called = False

    async def should_not_run(prompt: str, context: CompletionContext) -> object:
        nonlocal called
        del prompt, context
        called = True
        return {"summary_sections": []}

    with pytest.raises(ValueError, match="checkpoint values Artifact 'summary_sections' must be JSON array"):
        await execute_workflow(
            source,
            inputs={"source_document": {}},
            complete=should_not_run,
            checkpoint=checkpoint,
        )
    assert called is False


@pytest.mark.anyio
async def test_foreach_contract_applies_to_the_collected_artifact() -> None:
    source = """-- @artifact documents [array]: Source document strings.
-- @artifact summaries [array]: Source-ordered summary objects.
const documents: Artifact;
const document: Artifact;
const summaries: Artifact;
const summarize_step: Step;
const writer: Agent, Executor;

workflow summarize_documents {
  input_workflow(summarize_documents) == [documents];
  foreach_item(summarize_step, documents) == document;
  produces(summarize_step) == [summaries];
  output_workflow(summarize_documents) == [summaries];
  step_executor(summarize_step) == writer;
  step_name(summarize_step) == "Summarize";
  step_instruction(summarize_step) == "Return one summary object.";
}
"""
    contexts: list[CompletionContext] = []

    async def complete(prompt: str, context: CompletionContext) -> object:
        contexts.append(context)
        assert "one foreach iteration" in prompt
        return {"summaries": {"text": context.inputs["document"]}}

    outputs = await execute_workflow(source, inputs={"documents": ["first", "second"]}, complete=complete)

    assert outputs == {"summaries": [{"text": "first"}, {"text": "second"}]}
    assert sorted(context.dispatch.iteration_index for context in contexts) == [0, 1]


def test_typed_program_output_and_program_error_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(_WORKFLOW_TOOLS))
    sys.modules.pop("run_flow", None)
    run_flow = importlib.import_module("run_flow")
    contract = ArtifactContract(
        description="Ordered summary objects.",
        json_type="array",
    )
    invocation = ProgramInvocation(
        name="program",
        argv=("./summarize.py",),
        stdin="{}\n",
        cwd=".",
        binding_name="summarize_step",
        dispatch=DispatchContext(),
        output_ids=("summary_sections",),
        output_contracts={"summary_sections": contract},
    )
    attempt = run_flow._ProgramProcessResult(
        argv=("python", "summarize.py"),
        exit_code=0,
        stdout=b'[{"heading":"Overview"}]',
        stderr=b"",
    )

    assert run_flow._program_result_outputs(invocation, [attempt]) == {"summary_sections": [{"heading": "Overview"}]}
    assert run_flow._program_output_mode(invocation.output_ids, invocation.output_contracts) == "strict_json_value"

    wrong_type_attempt = run_flow._ProgramProcessResult(
        argv=("python", "summarize.py"),
        exit_code=0,
        stdout=b"{}",
        stderr=b"",
    )
    wrong_type = run_flow._program_result_outputs(invocation, [wrong_type_attempt])
    assert wrong_type["summary_sections"]["$fusion_flow/program_error"]["kind"] == "invalid_output_contract"

    foreach_invocation = replace(
        invocation,
        dispatch=DispatchContext(
            invocation_id="summarize_step[0]",
            iteration_index=0,
        ),
    )
    assert run_flow._program_result_outputs(foreach_invocation, [wrong_type_attempt]) == {"summary_sections": {}}
    foreach_contract = run_flow._program_output_contract_payload(foreach_invocation)["summary_sections"]
    assert "type" not in foreach_contract
    assert "One element contributed by this foreach iteration" in foreach_contract["description"]

    error_value = {"summary_sections": {"$fusion_flow/program_error": {"kind": "nonzero_exit"}}}
    with pytest.raises(ValueError, match="must be JSON array"):
        validate_artifact_values(error_value, {"summary_sections": contract}, context="Agent output")
    validate_artifact_values(
        error_value,
        {"summary_sections": contract},
        context="Program output",
        program_error_artifact_ids={"summary_sections"},
    )


@pytest.mark.anyio
async def test_agent_submission_schema_and_correction_use_output_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(_WORKFLOW_TOOLS))
    sys.modules.pop("run_flow", None)
    run_flow = importlib.import_module("run_flow")
    captured_schema: dict[str, object] = {}
    responses = iter(
        (
            '{"summary_sections":"wrong type"}',
            '{"summary_sections":[{"heading":"Overview"}]}',
        )
    )

    async def fake_create_step_agent(ai_socket, tool_registry, **kwargs):
        del ai_socket, kwargs
        captured_schema.update(tool_registry.tools["submit_step_result"].parameters)
        return object(), SimpleNamespace(messages=[])

    async def fake_complete_step_agent(agent, conversation, message, **kwargs):
        del agent, conversation, message, kwargs
        return next(responses)

    monkeypatch.setattr(run_flow, "_create_step_agent", fake_create_step_agent)
    monkeypatch.setattr(run_flow, "_complete_step_agent", fake_complete_step_agent)
    context = CompletionContext(
        step_id="summarize_step",
        executor_id="writer",
        executor_kind="Agent",
        inputs={"source_document": {}},
        output_ids=("summary_sections",),
        dispatch=DispatchContext(),
        output_contracts={
            "summary_sections": ArtifactContract(
                description="Ordered objects with a required heading.",
                json_type="array",
            )
        },
    )

    result = await run_flow._complete_agent_step(
        "Summarize the document.",
        context,
        ai_socket="unix:///unused.sock",
        tool_registry=SimpleNamespace(tools={}, get=lambda name: None),
    )

    assert result == {"summary_sections": [{"heading": "Overview"}]}
    assert captured_schema["properties"] == {
        "summary_sections": {
            "description": "Ordered objects with a required heading.",
            "type": "array",
        }
    }

    responses = iter(('{"summary_sections":"wrong type",}',) * 3)
    with pytest.raises(ValueError, match="result remained invalid after 3 attempts"):
        await run_flow._complete_agent_step(
            "Summarize the document.",
            context,
            ai_socket="unix:///unused.sock",
            tool_registry=SimpleNamespace(tools={}, get=lambda name: None),
        )


@pytest.mark.anyio
@pytest.mark.parametrize("declared_limit", (None, 2048))
async def test_session_output_limit_is_unset_unless_explicit(
    monkeypatch: pytest.MonkeyPatch,
    declared_limit: int | None,
) -> None:
    flow_module = importlib.import_module("fusion_flow.execution.flow")
    captured_payload: dict[str, object] = {}

    class PayloadCapturedError(Exception):
        pass

    def capture_payload(payload: dict[str, object]) -> str:
        captured_payload.update(payload)
        raise PayloadCapturedError

    monkeypatch.setattr(flow_module, "current_run_context", lambda: SimpleNamespace(runner=object()))
    monkeypatch.setattr(flow_module, "stable_payload_hash", capture_payload)
    agent = flow.agent(
        AgentConfig(
            name="summary_writer",
            system_prompt="Write a concise summary.",
            max_tokens=declared_limit,
        )
    )

    with pytest.raises(PayloadCapturedError):
        await flow.session(agent, "Summarize the document.")

    config = cast(dict[str, object], captured_payload["config"])
    assert config["max_tokens"] is declared_limit
