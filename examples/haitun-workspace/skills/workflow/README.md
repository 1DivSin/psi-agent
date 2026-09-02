# Workflow

Workflow is the workspace-local declarative system for coordinating Agent,
Human, and Program Steps. `grammar/FusionFlow.g4` defines the source language;
the Python parser, checker, graph compiler, and runner validate and execute it.
The workspace entry point is `run_flow`; `run_flow_resume` continues a pending
Human request.

This Skill uses only `.workflow` and `.g4` declarations. Legacy `.flow.ts`,
Fuclaw, and `@agent-flow/core` requests belong to the legacy flow Skill. The
Skill ships no runnable workflow examples.

## Workspace integration

One-off declarations live under `flows/`. Reusable declarations use one
self-contained bundle:

```text
flows/workflows/<slug>/<slug>.workflow
flows/workflows/<slug>/instructions/*.md   # optional
```

If `<slug>.workflow` is absent, `<slug>.g4` is used. Saving, listing, and
loading are upper-layer file operations; this Skill adds no registry operator.
An initial run is always fresh. Inputs are collected before `run_flow`, and only
the exact active Human request may continue through `run_flow_resume`.

Every materialized Artifact is persisted under the bundle's
`runs/<run-id>/artifacts/` directory. Human checkpoints are private under
`.psi/fusion-flow/runs/`; timing and token-usage sidecars are run-local
observability data.

## Components

| Component | Responsibility |
| --- | --- |
| `grammar/FusionFlow.g4` and parser | Source syntax and Core IR. |
| `fusion_flow/checker.py` | Static semantics and diagnostics. |
| `fusion_flow/workflow_graph/` | Immutable Step--Artifact graph and validation. |
| `fusion_flow/graph_compiler.py` | Core IR to graph backend. |
| `fusion_flow/workflow_runner.py` | Compile, plan, validate, and dispatch entry point. |
| `fusion_flow/workflow_execution.py` | Dependencies, concurrency, resources, timeouts, retries, and checkpoints. |
| `fusion_flow/execution/` | Shared `flow.*` runtime used by Agent Steps. |
| `fusion_flow/artifact_store.py` | Atomic Markdown persistence for materialized Artifacts. |
| `fusion_flow/job_store.py` | Strict Human wait/resume state and leases. |
| `run_flow` / `run_flow_resume` | Workspace file/JSON boundary and execution calls. |
| `clarify` | Existing user-facing Human question formatter. |

The runtime API has one supported shape: `execute_workflow(inputs=...)`, Agent
and Human callbacks `(prompt, CompletionContext)`, and
`execute_plan(dispatch=...)` with `(StepNode, inputs, DispatchContext)`.

## Contracts and execution boundaries

Artifact declarations support a documented executable JSON Schema subset. The
runner carries contracts into Step prompts and validates workflow inputs, Step
outputs, Program output, downstream inputs, and final outputs. A reserved
`$fusion_flow/program_error` value is valid only from its actual Program
producer.

Agent, Human, and Program Steps have distinct execution boundaries. Agent
outputs must use exact declared Artifact IDs. Human Steps pause through
`clarify` and resume with the exact run/request identifiers. Programs declare
one workspace-local file; structured compilation/execution captures the real
process result, and fidelity-mode execution does not retry a launched Program.

The runner validates the complete graph before dispatch, owns scheduling and
checkpoint integrity, and rejects residual or unsupported assertions. It does
not expose node-level progress. A compile or Step failure is reported rather
than repaired by editing the source or bypassing the runner.

## Authoring

Use the Skill only after explicit Workflow or multi-agent opt-in. Before
authoring, read `references/workflow-authoring-guide.md` and
`grammar/FusionFlow.g4`. Keep responsibilities, dependencies, limits, and
Artifact contracts explicit. Discover unknown scope before fan-out; preserve
branch locality; join only for a real consumer; and make any coverage bound
visible. Choose optional verification according to risk and user cost/latency
limits. Do not add domain-specific solver rules, hidden evaluator checks, or
imperative runtime code.

The authoring reference is the concise policy for clean Step contexts, explicit
Artifact transport, branch-local pipelines, genuine joins, finite work, and
risk-scaled checks. `SKILL.md` contains the operational protocol, source rules,
executor boundaries, Human resume handling, and Doctor checks.

## Regenerating the parser

The committed Python lexer/parser under `fusion_flow/generated/` must match the
grammar. Regenerate only when changing `grammar/FusionFlow.g4`, then run the
Workflow tests and the repository's normal lint/format checks.

## Out of scope

This directory defines orchestration mechanics, not domain content. It does
not add benchmark inputs, evaluator logic, task-specific prompts or heuristics,
privileged data paths, or acceptance policies. Domain-specific instructions
belong in the user's Workflow Artifacts and Step instructions.
