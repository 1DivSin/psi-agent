from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fusion_flow.workflow_execution import DispatchContext
from fusion_flow.workflow_runner import (
    ArtifactContract,
    CompletionContext,
    ProgramInvocation,
    compile_workflow,
    execute_workflow,
    validate_artifact_values,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _single_step_source(*, instruction: str, comments: str = "") -> str:
    encoded_instruction = json.dumps(instruction)
    return f"""{comments}
const source_data: Artifact;
const result_data: Artifact;
const transform_step: Step;
const worker: Agent, Executor;

workflow contracted_flow {{
  input_workflow(contracted_flow) == [source_data];
  consumes(transform_step) == [source_data];
  produces(transform_step) == [result_data];
  output_workflow(contracted_flow) == [result_data];
  step_executor(transform_step) == worker;
  step_name(transform_step) == "Transform";
  step_instruction(transform_step) == {encoded_instruction};
}}
"""


def test_compile_reads_contracts_from_line_and_block_comments() -> None:
    source = _single_step_source(
        comments="""-- @artifact source_data [object]: Required key: query (string).
/*
 * @artifact result_data [array]: Ordered result objects; [] means no matches.
 */""",
        instruction='Keep this text literal unchanged: "-- @artifact result_data [string]: not a comment".',
    )

    compiled = compile_workflow(source)

    assert compiled.artifact_contracts["source_data"].to_dict() == {
        "description": "Required key: query (string).",
        "type": "object",
    }
    assert compiled.artifact_contracts["result_data"].to_dict() == {
        "description": "Ordered result objects; [] means no matches.",
        "type": "array",
    }


def test_compile_rejects_contract_for_unknown_artifact() -> None:
    source = _single_step_source(
        comments="-- @artifact misspelled_result [array]: This name is not declared.",
        instruction="Transform source_data into result_data.",
    )

    with pytest.raises(ValueError, match=r"unknown Artifacts.*misspelled_result"):
        compile_workflow(source)


def test_compile_rejects_malformed_contract_instead_of_ignoring_it() -> None:
    source = _single_step_source(
        comments="-- @artifact result_data [dict]: Unsupported type spelling.",
        instruction="Transform source_data into result_data.",
    )

    with pytest.raises(ValueError, match=r"malformed Artifact contract.*\[dict\]"):
        compile_workflow(source)


def test_only_program_outputs_may_preserve_program_error_envelope() -> None:
    values = {"result_data": {"$fusion_flow/program_error": {"kind": "nonzero_exit"}}}
    contracts = {
        "result_data": ArtifactContract(
            description="Successful results are arrays.",
            json_type="array",
        )
    }

    with pytest.raises(ValueError, match="must be JSON array"):
        validate_artifact_values(values, contracts, context="Agent output")
    validate_artifact_values(
        values,
        contracts,
        context="Program output",
        program_error_artifact_ids={"result_data"},
    )


@pytest.mark.anyio
async def test_instruction_contract_reaches_prompt_and_completion_context() -> None:
    source = _single_step_source(
        comments="-- @artifact source_data [object]: Required key: query (string).",
        instruction=(
            "Transform source_data into result_data.\n"
            "@artifact result_data [array]: Ordered objects with exact keys id and score."
        ),
    )
    observed_prompt = ""
    observed_context: CompletionContext | None = None

    async def complete(prompt: str, context: CompletionContext) -> object:
        nonlocal observed_context, observed_prompt
        observed_prompt = prompt
        observed_context = context
        return {"result_data": [{"id": "candidate-1", "score": 1}]}

    outputs = await execute_workflow(
        source,
        inputs={"source_data": {"query": "example"}},
        complete=complete,
    )

    assert outputs == {"result_data": [{"id": "candidate-1", "score": 1}]}
    assert observed_context is not None
    assert observed_context.input_contracts["source_data"].json_type == "object"
    assert observed_context.output_contracts["result_data"].json_type == "array"
    assert "Input Artifact contracts" in observed_prompt
    assert "Ordered objects with exact keys id and score" in observed_prompt


@pytest.mark.anyio
async def test_resolved_instruction_file_can_declare_contract() -> None:
    source = _single_step_source(
        instruction="./transform.md",
        comments="-- @artifact source_data [object]: Required key: query.",
    )

    async def resolve_instruction(reference: str) -> str:
        assert reference == "./transform.md"
        return (
            "Transform the supplied object.\n"
            "@artifact result_data [array]: Ordered result objects from this transformation."
        )

    async def complete(prompt: str, context: CompletionContext) -> object:
        assert context.output_contracts["result_data"].json_type == "array"
        assert "Ordered result objects" in prompt
        return {"result_data": []}

    outputs = await execute_workflow(
        source,
        inputs={"source_data": {"query": "example"}},
        complete=complete,
        resolve_instruction=resolve_instruction,
    )

    assert outputs == {"result_data": []}


@pytest.mark.anyio
async def test_workflow_input_type_is_validated_before_dispatch() -> None:
    source = _single_step_source(
        comments="-- @artifact source_data [object]: A JSON object.",
        instruction="Transform source_data into result_data.",
    )
    called = False

    async def complete(prompt: str, context: CompletionContext) -> object:
        nonlocal called
        del prompt, context
        called = True
        return {"result_data": None}

    with pytest.raises(ValueError, match="workflow inputs Artifact 'source_data' must be JSON object"):
        await execute_workflow(source, inputs={"source_data": []}, complete=complete)
    assert called is False


@pytest.mark.anyio
async def test_step_output_type_is_validated() -> None:
    source = _single_step_source(
        instruction=(
            "Transform source_data into result_data.\n"
            "@artifact result_data [array]: A JSON array, never prose."
        )
    )

    async def complete(prompt: str, context: CompletionContext) -> object:
        del prompt, context
        return {"result_data": "not-an-array"}

    with pytest.raises(ExceptionGroup) as caught:
        await execute_workflow(source, inputs={"source_data": {}}, complete=complete)
    assert len(caught.value.exceptions) == 1
    assert isinstance(caught.value.exceptions[0], ValueError)
    assert "outputs for step 'transform_step' Artifact 'result_data' must be JSON array" in str(
        caught.value.exceptions[0]
    )


@pytest.mark.anyio
async def test_conflicting_comment_and_instruction_contracts_fail_before_dispatch() -> None:
    source = _single_step_source(
        comments="-- @artifact result_data [object]: One result object.",
        instruction=(
            "Transform source_data into result_data.\n"
            "@artifact result_data [array]: A list of result objects."
        ),
    )
    called = False

    async def complete(prompt: str, context: CompletionContext) -> object:
        nonlocal called
        del prompt, context
        called = True
        return {"result_data": []}

    with pytest.raises(ValueError, match="conflicting Artifact contracts for 'result_data'"):
        await execute_workflow(source, inputs={"source_data": {}}, complete=complete)
    assert called is False


@pytest.mark.anyio
async def test_same_type_comment_and_instruction_guidance_is_combined() -> None:
    source = _single_step_source(
        comments="-- @artifact result_data [object]: Keys are idx, query, and plan.",
        instruction=(
            "Transform source_data into result_data.\n"
            "@artifact result_data [object]: The plan contains exactly seven ordered day objects."
        ),
    )

    async def complete(prompt: str, context: CompletionContext) -> object:
        contract = context.output_contracts["result_data"]
        assert contract.json_type == "object"
        assert "Keys are idx, query, and plan." in contract.description
        assert "exactly seven ordered day objects" in contract.description
        assert "Keys are idx, query, and plan." in prompt
        assert "exactly seven ordered day objects" in prompt
        return {"result_data": {"idx": 1, "query": "trip", "plan": []}}

    outputs = await execute_workflow(source, inputs={"source_data": {}}, complete=complete)

    assert outputs == {"result_data": {"idx": 1, "query": "trip", "plan": []}}


@pytest.mark.anyio
async def test_foreach_contract_describes_and_validates_aggregate() -> None:
    source = """-- @artifact items [array]: Source strings.
-- @artifact enriched_items [array]: Source-ordered enriched objects.
const items: Artifact;
const item: Artifact;
const enriched_items: Artifact;
const enrich_step: Step;
const worker: Agent, Executor;

workflow enrich_flow {
  input_workflow(enrich_flow) == [items];
  foreach_item(enrich_step, items) == item;
  produces(enrich_step) == [enriched_items];
  output_workflow(enrich_flow) == [enriched_items];
  step_executor(enrich_step) == worker;
  step_name(enrich_step) == "Enrich";
  step_instruction(enrich_step) == "Enrich item as one object for enriched_items.";
}
"""
    contexts: list[CompletionContext] = []

    async def complete(prompt: str, context: CompletionContext) -> object:
        contexts.append(context)
        assert "one foreach iteration" in prompt
        return {"enriched_items": {"value": context.inputs["item"]}}

    outputs = await execute_workflow(source, inputs={"items": ["a", "b"]}, complete=complete)

    assert outputs == {"enriched_items": [{"value": "a"}, {"value": "b"}]}
    assert sorted(context.dispatch.iteration_index for context in contexts) == [0, 1]


@pytest.mark.anyio
async def test_run_flow_uses_contract_in_submit_schema_and_correction_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools_dir = Path(__file__).parents[3] / "examples" / "haitun-workspace" / "tools"
    monkeypatch.syspath_prepend(str(tools_dir))
    sys.modules.pop("run_flow", None)
    module = importlib.import_module("run_flow")
    captured_schema: dict[str, object] = {}
    responses = iter(
        (
            '{"result_data":"wrong type"}',
            '{"result_data":[{"id":"candidate-1"}]}',
        )
    )

    async def fake_create_step_agent(ai_socket, tool_registry, **kwargs):
        del ai_socket, kwargs
        captured_schema.update(tool_registry.tools["submit_step_result"].parameters)
        return object(), SimpleNamespace(messages=[])

    async def fake_complete_step_agent(agent, conversation, message, **kwargs):
        del agent, conversation, message, kwargs
        return next(responses)

    monkeypatch.setattr(module, "_create_step_agent", fake_create_step_agent)
    monkeypatch.setattr(module, "_complete_step_agent", fake_complete_step_agent)
    context = CompletionContext(
        step_id="transform_step",
        executor_id="worker",
        executor_kind="Agent",
        inputs={"source_data": {}},
        output_ids=("result_data",),
        dispatch=DispatchContext(),
        output_contracts={
            "result_data": ArtifactContract(
                description="Ordered objects with required id.",
                json_type="array",
            )
        },
    )

    result = await module._complete_agent_step(
        "Execute the step.",
        context,
        ai_socket="unix:///unused.sock",
        tool_registry=SimpleNamespace(tools={}, get=lambda name: None),
    )

    assert result == {"result_data": [{"id": "candidate-1"}]}
    assert captured_schema["properties"] == {
        "result_data": {
            "description": "Ordered objects with required id.",
            "type": "array",
        }
    }


def test_run_flow_parses_typed_single_program_output() -> None:
    tools_dir = Path(__file__).parents[3] / "examples" / "haitun-workspace" / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    module = importlib.import_module("run_flow")
    contract = ArtifactContract(
        description="Ordered result objects.",
        json_type="array",
    )
    invocation = ProgramInvocation(
        name="program",
        argv=("./program.py",),
        stdin="{}\n",
        cwd=".",
        binding_name="program_step",
        dispatch=DispatchContext(),
        output_ids=("result_data",),
        output_contracts={"result_data": contract},
    )
    attempt = module._ProgramProcessResult(
        argv=("python", "program.py"),
        exit_code=0,
        stdout=b'[{"id":"candidate-1"}]',
        stderr=b"",
    )

    result = module._program_result_outputs(invocation, [attempt])

    assert result == {"result_data": [{"id": "candidate-1"}]}
    assert module._program_output_mode(invocation.output_ids, invocation.output_contracts) == "strict_json_value"
