from __future__ import annotations

import importlib
import sys
from pathlib import Path

_WORKFLOW_SKILL = Path(__file__).parents[3] / "examples" / "haitun-workspace" / "skills" / "workflow"
sys.path.insert(0, str(_WORKFLOW_SKILL))
fusion_flow = importlib.import_module("fusion_flow")


def test_generic_agent_operator_signatures_and_bool_shorthand_parse() -> None:
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
    assertions = parsed.core_ir.workflows[0].assertions
    calls = []
    for assertion in assertions:
        assert isinstance(assertion.lhs, fusion_flow.CompoundTerm)
        assert isinstance(assertion.rhs, fusion_flow.Constant)
        assert assertion.rhs.symbol == "True"
        calls.append(assertion.lhs)

    assert [call.operator.name for call in calls] == ["agent_config", "allowed_tool"]
    assert all(isinstance(term, fusion_flow.Constant) for term in calls[0].arguments)
    assert [term.symbol for term in calls[0].arguments if isinstance(term, fusion_flow.Constant)] == [
        "review_agent",
        "model",
        "engine",
        "api_base",
    ]
    assert all(isinstance(term, fusion_flow.Constant) for term in calls[1].arguments)
    assert [term.symbol for term in calls[1].arguments if isinstance(term, fusion_flow.Constant)] == [
        "review_agent",
        "read",
    ]
