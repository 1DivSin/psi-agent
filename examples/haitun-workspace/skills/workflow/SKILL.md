---
name: workflow
description: Author, save, inspect, reuse, or run workflow declarations after explicit Workflow or multi-agent opt-in. Use for coordinated agents or roles, program or human steps, parallel branches, and staged pipelines. Use the legacy flow skill only for explicit compatibility work.
---

# Workflow

Workflow is the workspace's declarative system for coordinating agents,
programs, and human checkpoints. This skill turns a user's intent into a
checked graph, executes independent work concurrently when appropriate, and
returns the final declared artifacts.

> **Workspace boundary.** Store one-off authored G4 files under the workspace-managed `flows/` directory. Reusable declarations have one canonical bundle: `flows/workflows/<slug>/`, containing `<slug>.workflow` or `<slug>.g4` (`.workflow` takes precedence if both exist). The skill ships no runnable example workflows. Every run persists all materialized Artifacts as Markdown under its workflow bundle's `runs/<run-id>/artifacts/` directory. Human Steps additionally persist private checkpoints under the ignored workspace `.psi/fusion-flow/runs/` directory; non-Human runs remain non-resumable.

> **Legacy handoff.** An explicit `.flow.ts`, Fuclaw, or `@agent-flow/core`
> request belongs to the `flow` skill under `skills/fusion-flow-legacy/`.
> Do not silently translate between the two runtimes.

## When to Activate

Author or run a Workflow only after the user explicitly opts into Workflow or
multi-agent orchestration. Explicit opt-in includes the user's own request to:

- author, run, save, list, load, or reuse a G4 workflow declaration;
- use a workflow, coordinated agents, parallel agents, fan-out/fan-in, or a
  multi-agent review or debate; or
- run a concrete `.workflow` or `.g4` file, or work with FusionFlow while asking
  for an operation that requires this Skill.

A save, list, load, or inspect request activates this Skill for registry
management but does not by itself authorize execution. Call `run_flow` only
when the user also asks to run, invoke, or reuse the declaration for a task.

A task that would merely benefit from parallelism, multiple perspectives, or
two or more model calls does **not** authorize the extra execution and token
cost. For an ordinary task without opt-in, use the normal task path and any
available individual-subagent tools. When Workflow would materially improve the
result, briefly describe its proposed scale and approximate cost or latency,
then ask whether the user wants it before authoring or running anything.

An explicit request to simulate several agents or roles is already opt-in. In
that case, enter Authoring Mode and build a G4 workflow whose Agent Steps hold
the distinct roles; do not role-play all of them in one parent response. Once
the user has opted in, building and running the graph is the default delivery
path unless they explicitly ask to inspect or save it without execution.

Do **not** activate this skill for `.prose` files — those belong to OpenProse.

## Architecture

| Layer | Responsibility |
| --- | --- |
| `grammar/FusionFlow.g4` + parser | G4 source to Core IR |
| `fusion_flow.workflow_graph` | immutable Step–Artifact structure and validation |
| `fusion_flow.workflow_runner` | Core IR to graph, plan, and checked dispatch |
| `fusion_flow.workflow_execution` | graph interpretation, dependencies, concurrency, timeouts, resources, and validated checkpoints |
| `fusion_flow.execution` | shared `flow.*` runtime; G4 Agent leaves reuse `run`/`agent`/`session` |
| `fusion_flow.job_store` | private, strict state-v3 Human wait/checkpoint state |
| workspace `run_flow` / `run_flow_resume` tools | file/JSON boundary, ephemeral Session-backed Agent/Program dispatch, and Human preparation/resume |
| workspace `clarify` tool | existing user-facing choice or free-text question formatter |

The Python runtime has one contract: `execute_workflow` requires `inputs=`;
Agent and Human callbacks receive `(prompt, CompletionContext)`;
`execute_plan` requires a `dispatch=` callback with the exact
`(StepNode, inputs, DispatchContext)` signature. These are the supported forms,
not compatibility alternatives.

The skill's job is to:

1. Turn the user's intent into valid Workflow G4 source, or resolve the concrete G4 workflow they pointed to.
2. Save reusable source at the fixed path with existing file tools when requested.
3. Start it through `run_flow`.
4. If it reaches a Human Step, pass the nested `$fusion_flow/control.request` fields to the existing `clarify` tool, end the turn, and resume from the next user message.
5. Return only the final workflow output Artifact mapping.

## Artifact Contracts

Artifacts may declare an executable JSON Schema subset, including descriptions
for the Artifact and its parameters. The G4 lexer retains comment tokens for the
runner, which parses these declarations before dispatch. The runner carries one
compiled contract into every related Agent, Human, and Program Step. Agent
output contracts become the JSON Schema properties of `submit_step_result`, and
the runtime validates the same schema on workflow inputs, ordinary Step outputs,
downstream Step inputs, Program stdout, and final outputs.

Write each contract as a standalone directive line. A workflow comment makes
the contract global:

```fusionflow
-- @artifact source_document [object]: Required keys are content, language, and metadata.
/*
 * @artifact summary_sections [array]: Ordered section objects; each object contains heading, body, and source_refs.
 */
```

The legacy form above remains useful for a top-level type and advisory
description. For program-enforced parameter and output constraints, declare a
single-line JSON Schema object with `=`:

```fusionflow
-- @artifact request = {"type":"object","description":"One lookup request.","properties":{"query":{"type":"string","description":"Non-empty lookup text.","minLength":1},"limit":{"type":"integer","description":"Maximum result count.","minimum":1,"maximum":100}},"required":["query"],"additionalProperties":false}
-- @artifact results = {"type":"array","description":"Ordered matching records.","maxItems":100,"items":{"type":"object","description":"One match.","properties":{"id":{"type":"string","description":"Stable identifier.","minLength":1},"score":{"type":"number","description":"Normalized score.","minimum":0,"maximum":1}},"required":["id","score"],"additionalProperties":false}}
```

Every schema directive requires a top-level `type` and non-empty `description`.
Supported types are `null`, `boolean`, `integer`, `number`, `string`, `object`,
and `array`. The executable keyword subset is `properties`, `required`,
`additionalProperties`, `items`, `minItems`, `maxItems`, `minProperties`,
`maxProperties`, `minLength`, `maxLength`, `minimum`, `maximum`, `pattern`,
`enum`, and `const`, plus `type` and `description`. Unsupported or malformed
schema keywords fail compilation rather than becoming advisory text. Parameter
`description` values are preserved in prompts, Program contracts, and Agent
tool schemas; the other keywords are enforced by the runtime.

A contract can instead live in a Step instruction. This works both in an
inline JSON-escaped newline and in a companion instruction Markdown file:

```fusionflow
step_instruction(normalize_step) == "Normalize only the supplied records.\n@artifact normalized_records [array]: Preserve every id, timestamp, source, and payload; [] means the input contained no records.";
```

An instruction may declare contracts only for Artifacts consumed or produced
by that Step. Repeating the same contract is allowed; conflicting declarations,
unknown Artifact IDs, and unrelated instruction declarations fail before Step
dispatch. Ordinary instruction prose is still passed through unchanged, but
only exact `@artifact` directive lines become structured runtime contracts.

The built-in validator recursively enforces declared object parameters, array
items, required and extra-property policies, sizes, numeric bounds, patterns,
enums, and constants. For a `foreach` output, the declared contract describes
the collected aggregate Artifact; when it has an `items` schema, each iteration
also submits against that item schema, and the aggregate is validated downstream
or at workflow output. A reserved `$fusion_flow/program_error` value from the
actual Program producer remains deliverable even when its success-value type
differs; Agent and Human outputs cannot use that envelope to bypass validation.
For a single-output Program Step, a non-`string` contract changes stdout from
verbatim text to one strict JSON value of the declared type; untyped and
`string` outputs retain the existing verbatim-stdout behavior.

## Intent Routing

Natural-language workflow requests map to these actions:

| What the user says (examples) | Action |
| --- | --- |
| "我能用这个干嘛 / 你能帮我做什么" | Describe capabilities in plain language (see "Capabilities" at the bottom) + offer to build a flow |
| "调用 daily-brief 的 workflow / 运行已保存的 daily-brief / reuse saved daily-brief" | Resolve `flows/workflows/daily-brief/daily-brief.workflow`, falling back to `daily-brief.g4`, collect its declared inputs, and start one fresh run with `run_flow(flow_path=...)`. |
| "有哪些保存的工作流 / list workflows" | List the fixed `flows/workflows/` directory with existing file tools. |
| "加载 X / 看看保存的 X" | Read the saved `.workflow` or `.g4` file with existing file tools, preferring `.workflow` if both exist. |
| "把刚生成的这个保存为 X" | After self-check, save the self-contained bundle at `flows/workflows/<slug>/`: one `.workflow` or `.g4` source file plus every referenced instruction Markdown file, preserving relative paths. |
| "跑一下这个 / 帮我跑 X / 执行这个 workflow" | Start the concrete workspace G4 source with `run_flow`; return outputs, or handle its Human request with `clarify`. |
| "接着上次那个跑 / 只重跑改动的部分" | Use `run_flow_resume` only for the active Human request already returned in this conversation. Arbitrary cache/resume is unsupported; otherwise offer a fresh run. |
| "看看结果 / 刚才那个跑完了吗" | Use the result already returned. A Human wait is not completion; wait for the user's answer rather than polling. |
| "环境齐不齐 / 能不能跑 / 帮我检查下" | Confirm that the G4 source parses and that all Steps use supported Agent, Human, or Program executors. |
| **"帮我写个工作流做 X / 帮我编排 / 我想让几个 agent ..."** | **Author a new G4 workflow from natural language. See "Authoring Mode" below.** |
| Any other explicitly opted-in Workflow operation | Interpret intent against this table; an ordinary task that is merely workflow-shaped stays on the normal task path. |

## Running a Workflow

Use the workspace `run_flow` tool for Workflow G4 source. It validates the workflow and returns either the final output Artifacts or one persisted Human request under the reserved `$fusion_flow/control` key.

### Saved workflow reuse

When the user asks to run a saved workflow by name, resolve only an existing
slug directory under `flows/workflows/`; never treat the name as an arbitrary
path. Prefer `<slug>.workflow` and fall back to `<slug>.g4`. If the name is
ambiguous or neither source exists, ask the user to choose an existing saved
workflow.

Read the declaration and inspect `input_workflow(...)` before execution.
Resolve every declared input from the conversation; if any value is missing,
ask for it and end the turn without calling `run_flow`. Do not guess values or
call once with the default empty input object merely to discover missing
inputs. Once all inputs are available, invoke `run_flow` exactly once with the
resolved `flow_path` and complete `inputs_json`. Use an empty input object only
when the declaration has no inputs. Every initial invocation is a fresh run;
only a returned active Human request may continue through `run_flow_resume`.

### Fixed-path reuse

- **Save:** use the existing file-writing capability to write one declaration
  at `flows/workflows/<slug>/<slug>.workflow` or
  `flows/workflows/<slug>/<slug>.g4`. If it references companion
  instruction Markdown, copy those files into the same canonical bundle while
  preserving every relative path; never leave a saved declaration pointing
  back to its one-off directory. This is an upper-layer instruction,
  not a new save/list/load operator. A parent Session or Agent Step may save a
  self-contained bundle generated within its assigned hierarchy. Saving never
  executes it.
- **List/read:** use existing directory and file tools.
- **Execute:** only the parent Session invokes `run_flow(flow_path=...)`.

### Supported workflow source

Only author and run the supported workflow declaration format. If the user
points to another format, do not execute or translate it implicitly. If they
explicitly ask for a migration, enter Authoring Mode and author one new
workflow from its intent.

Use a workspace-relative `.workflow` or `.g4` path under `flows/`. Never guess, scan for, or execute a path outside the workspace.

One runnable file must contain exactly one `workflow ... {}` block and use
supported Agent, Human, or Program executors.

Pass named workflow inputs through `inputs_json`. Do not rewrite the G4 source just to inject one run's values.

Pass run-local resource pools through `resource_capacities_json` only when the workflow declares `resource_requirement`.

Call `run_flow` once. If it returns output Artifacts, use them as the result. If it returns a `$fusion_flow/control` object with `status == "waiting_for_human"`, follow the Human protocol below. This reserved key cannot be a G4 Artifact ID, so an ordinary output Artifact named `status` is never control state.

### Human wait and resume

`run_flow_resume` is only for a pending Human request; it is not a general cache or arbitrary-step resume API.

When `run_flow` or `run_flow_resume` returns a sole top-level `$fusion_flow/control` object whose `status == "waiting_for_human"`:

1. Call the existing `clarify` tool with `$fusion_flow/control.request.question`, `.options`, `.recommended`, and `.default`.
2. Show the formatted text verbatim and **END THE TURN**. Do not call another tool and do not treat the question as an output Artifact.
3. On the next user message, map a numbered choice to its option label. If the user selected the generated `Other` line without supplying text, ask for that text first. For an open-ended request with a non-empty `default`, map an affirmative acceptance such as “可以” or “ok” to that exact default. Preserve other free text or structured content.
4. For a single-output Human Step, JSON-encode every mapped option label or default as a JSON string. Pass other ordinary non-empty free text directly, except JSON-encode it as a JSON string when its trimmed spelling is valid JSON, starts with `{`, `[`, or `"`, or equals `NaN`, `Infinity`, or `-Infinity`. JSON-encode non-string structured content. Multiple output Artifacts require a JSON object keyed exactly by those Artifact IDs; JSON-encode that object without dropping or adding keys.
5. Call `run_flow_resume` with the exact `$fusion_flow/control.run_id` and `.request.request_id`.
6. If another Human request is returned, repeat this protocol. Otherwise report the final output Artifact mapping.

Never invent, reuse, or guess a run/request ID. A changed workflow source, stale request, or conflicting duplicate response is a stop-and-report error.

## Agent-, Human-, and Program-backed execution

Before executing a G4 workflow:

1. Ensure every Step executor is declared as exactly one of `Agent`, `Human`, or `Program`. Every Program must declare an explicit workspace-relative `program_path`.
2. Internally estimate cost and latency from the number of Agent and Program Steps. Fold that into one plain-language heads-up line.
3. Say the heads-up line, then run without adding another approval gate unless the user explicitly said "只生成别跑".

### Running is the runtime's job, not yours

Resolve the workspace-relative G4 path, submit it to `run_flow`, and report the returned output mapping. Do not reproduce parsing, dependency scheduling, resource leasing, or Step execution in the parent Session.

Agent-backed Steps must never invoke `run_flow` or start another workflow. A
Step may save a self-contained child declaration to the fixed reusable folder;
the parent Session remains the only launcher. Relative paths passed by a Step
to `read`, `write`, or `edit` resolve against the invoking psi workspace root,
independent of the launcher process working directory.

### Staged execution

Workflows without Human Steps finish in the initial `run_flow` call. A Human workflow executes to the next Human frontier, persists a checkpoint, releases the current Session turn, and continues only through `run_flow_resume`. Do not call the legacy `.flow.ts` `flow_run(start/status/result)` tool for G4 source, and do not invent polling, PIDs, workers, or a separate approval inbox.

### Checkpoint integrity and resume safety

An `ExecutionCheckpoint` is valid only for its exact non-empty `workflow_id` and `plan_digest`. The digest is SHA-256 over a canonical serialization of the current graph semantics and explicit execution-plan fibers; matching Step and Artifact IDs from another workflow or graph version are not enough. Values must be strict, finite JSON values, and resume compares them recursively with type identity, so JSON `true` never matches JSON `1`. The executor also validates unique known operation IDs, dependency closure, and the exact set of materialized values before it skips any work.

The public `run_flow_resume` boundary additionally validates the current workflow definition against the `definition_digest` recorded when the run was created; that definition includes the `.workflow` or `.g4` source and every referenced Markdown instruction. Persisted Human runs use the strict state-v3 schema; state-v2 and all other older versions are rejected rather than resumed through a compatibility path. Each resume is protected by an OS-released advisory file lock plus an in-process reservation guard; a leftover lock file is not ownership, and an abrupt process exit releases the live advisory lease. Do not copy checkpoints between workflows, edit persisted state, or bypass the matching `run_id` / `request_id` protocol.

### When a run fails

A compilation or Step exception is a **STOP-and-report point**. Report the failing Step or diagnostic exposed by `run_flow`, state one best hypothesis, and hand back to the user.

These actions are forbidden when a run fails:

- editing the workflow or creating a modified copy to work around the failure;
- bypassing `run_flow` and manually executing individual Steps;
- silently retrying or approximating an unsupported operator or executor.

Do not create a mock or offline twin with baked-in output.

### Don't fake or guess progress

The tool does not expose intermediate progress. Do not invent node status while the call is in flight.

## Reading a Run

When a call returns output Artifacts, summarize them. The runtime has already
persisted every materialized input, intermediate, selected, and final Artifact
as one Markdown file under the workflow bundle's
`runs/<run-id>/artifacts/` directory. String values are written verbatim;
non-string strict JSON values use a fenced `json` block. These user-visible
files are separate from the private Human checkpoint. When a call returns a
Human request, ask it through `clarify`; the request text is control state, not
an Artifact or completed result.

## File Locations

Paths are relative to the workspace:

| File | Location | Purpose |
| --- | --- | --- |
| `flows/<task-slug>/` | one-off authored Workflow G4 source |
| `flows/<task-slug>/instructions/*.md` | optional long-form instructions for that one-off source |
| `flows/workflows/<slug>/<slug>.workflow` or `<slug>.g4` | reusable G4 source (`.workflow` preferred when both exist) |
| `flows/workflows/<slug>/instructions/*.md` | optional long-form instructions for that reusable source |
| `<workflow-bundle>/runs/<run-id>/artifacts/*.md` | one Markdown file for every materialized Artifact in one run |
| `<workflow-bundle>/runs/<run-id>/step-timings.json` | resumable Agent/Program step timing report with attempts and foreach iterations |
| `<workflow-bundle>/runs/<run-id>/token-usage.json` | private per-Step model-call and token-usage observability for that run |
| `.psi/fusion-flow/runs/<run-id>.json` | private resumable state for workflows containing Human Steps |

## Authoring Mode

This is the authoring path for turning a plain-language request into one
reusable workflow. Running a saved workflow is a reuse request, not a new
authoring request.

Author one real workflow for the requested work. Do not create an offline twin,
sample result, or substitute executor to make a demonstration appear to pass.
Examples in this document explain structure only; they are not extra workflow
files.

### When to enter Authoring Mode

- User describes a workflow they want built: "帮我写个工作流 ..." / "make a flow that ..." / "帮我编排 ..." / similar.
- User asks "帮我写一个 flow ..." / "make a flow that ..." / similar in any LLM client.
- User edits existing Workflow G4 source and asks you to "rewrite" or "扩展".
- User explicitly asks several agents or roles to collaborate, fan out, debate,
  review independently, or run a multi-step pipeline. The word "workflow" is
  not required when the user's requested orchestration is itself explicit.

### Planning contract

Before writing Workflow G4 source, make an internal planning contract for the
requested workflow. It must identify:

- the user's intent and concrete success condition;
- every external input and final output Artifact;
- each Step's single responsibility and its consumed and produced Artifacts;
- information dependencies and the owner of every material constraint;
- concurrency, timeout, retry, resource, and user-stated cost limits.

Assign mechanically decidable constraints to graph structure or a deterministic
Program Step. Assign constraints that require judgment to an Agent Step whose
instruction names that responsibility. Let dependencies determine execution:
fan out independent work, keep dependent work sequential, and join branches
only when a consumer needs all of their results. Keep this contract in the
authoring context; do not expose framework planning detail to a non-technical
user.

### Workflow authoring guide

Before modeling any new workflow or revising an existing one, read
`references/workflow-authoring-guide.md` in full. Resolve that path relative
to the exact `SKILL.md` file supplied by the system prompt, not relative to a
generated flow bundle or a user-workspace mirror. The guide is mandatory
authoring policy: it covers discovery before fan-out, clean step contexts,
explicit Artifact transport, branch-local pipelines, genuine joins, scale, and
independent verification patterns.

### The 5-step author loop

1. **Understand intent** — restate the user's goal in 1 sentence. If genuinely ambiguous, ask **one** clarifying question (don't grill them). Note whether the user looks like a *developer* (asked to edit Workflow G4 source or mentioned operators) — that's the only case where you show technical detail later. Everyone else gets the minimal plain-language summary.
2. **Model the workflow** — read and apply the Workflow authoring guide, complete the planning contract, and choose among the executable patterns below. Let information dependencies determine graph depth: add an intermediate aggregation layer only when downstream work needs a coherent result from a distinct group of upstream Artifacts. Select optional quality patterns according to task risk, requested coverage, and the user's cost or latency limits.
3. **Author one Workflow G4 source** — before writing, read `grammar/FusionFlow.g4` completely and treat it as the sole source of truth for FusionFlow syntax and preset operators. Use only declarations, assertions, terms, and operators documented there. Use the workspace-provided target path; never invent a second copy.
4. **Static self-check** — compare the source against `grammar/FusionFlow.g4` and the executable guardrails in this Skill. `run_flow` repeats this with its built-in `check_workflow` pass before dispatch; there is no separate validation tool or CLI.
5. **Start it once** — the user asked you to do a task, not to receive an implementation artifact. After the static self-check, say ONE friendly heads-up line ("🚀 方案定了，正在帮你跑，预计几分钟…" — a notice, NOT a question), then call `run_flow` once. A declared Human Step may later ask its own task-specific question through the Human protocol; that is part of execution, not an extra pre-run gate. **Do NOT ask "要不要跑 / 跑不跑" and do NOT wait for `跑`.** The only exception is when the user explicitly says "只生成别跑 / 先给我看看别执行".

Never mention the source file, its path, G4, operator names, static-check stages, or internal runnable artifacts to a non-technical user. From their side you are just doing the task they asked for. If they ask "你在干嘛 / 怎么做的", answer in plain business language ("我让几个分析分头跑、再汇总").

### Talking to the user while you work

Before calling `run_flow`, send one short heads-up such as "🚀 方案定了，正在帮你跑，预计几分钟…". The tools expose no node-level progress, so do not claim that an individual Step or branch has started or completed. When a call returns final outputs, lead with the result; when it returns a Human request, follow the Human protocol. Do not add an approval question between authoring and execution.

Keep the authoring process silent. After any necessary clarification, use the
workspace tools directly; do not narrate reasoning, alternative graph designs,
syntax reconstruction, self-checks, edits, or retries. The only user-visible
text before execution is the single heads-up line above. This changes
presentation only: perform every authoring and static-check step in full.

### Authoring safeguards

Apply these safeguards while authoring and running:

1. Run the real workflow after the static self-check; do not replace it with a
   made-up answer or an offline copy.
2. Write one workflow source for the request. Companion instruction files are
   part of that source; do not create a second version or test harness.
3. Report only values returned by the real run. If it fails, report the failure.
4. Keep generated files under the workspace-managed `flows/` directory.
5. An agent step cannot start another workflow. Only the parent session may do
   so.

### Heads-up before execution

Give one short, plain-language sentence describing the expected result and an
approximate wait. This is a notice, not a permission gate. Then run the
workflow without asking the user to repeat approval.

Use one plain-language sentence for everyone. Do not expose implementation
names, paths, per-step details, or token calculations unless the user asks.

```
我来帮你完成这项工作并整理好结果，预计几分钟，这就开始。
```

That's it: one line, then run. Do not add separate planning fields, list every
step, show a path, or ask for approval again. Show technical detail only when
the user explicitly asks for the structure:

```
3 个审查步骤共用输入，1 个汇总步骤整理三个结果。
```

Show a structural summary only when the user explicitly asks for it.

### Reference patterns

Read `grammar/FusionFlow.g4` completely before using these patterns. The grammar is authoritative; these patterns illustrate artifact dependencies and do not add syntax or operators.

| Pattern | Workflow shape | When to use |
| --- | --- | --- |
| **Fan-out + fan-in** | Several Steps each use `consumes(step) == [shared_artifact]`; one final Step uses `consumes(final_step) == [result_a, result_b]`. Set `max_concurrency` on the workflow when needed. | PR review, multi-perspective audit, content moderation. |
| **Artifact pipeline** | Each Step produces the Artifact consumed by the next Step. Use `max_attempts` only when rerunning that individual Step is safe. | Writing, ETL, and refine-and-check work. |
| **Branch-local pipelines** | Independent branches each advance from discovery or construction to their own check as soon as that branch's Artifact is ready. Only a consumer that needs every branch result performs the final fan-in. | Multi-surface inspection, independent research channels, and partitioned migrations. |
| **Adversarial verifier** | An independent final Agent Step consumes the task contract, the same evidence available to the builder, and its candidate. It tries to refute the candidate, records evidence for each check, and emits either the unchanged candidate or a corrected final Artifact. | When task risk, requested coverage, and user cost or latency limits warrant an independent check that can be performed from visible inputs. |
| **Independent candidate panel** | Several candidate Steps consume the same task contract; judging or synthesis Steps consume explicit candidate Artifacts and the same decision criteria. | Open-ended design where genuinely different approaches should be compared before synthesis. |
| **Per-item map** | Bind one List-valued source Artifact with `foreach_item`; use workflow `max_concurrency` or resources when a limit is needed. | Parallel processing with ordered results; ordinary failures are raised together after siblings finish. |
| **Named Artifact selection** | Keep every candidate result explicit, then bind `selected_artifact == if(formula, artifact_a, artifact_b)` and use `selected_artifact` in ordinary dataflow. For priority selection, chain named intermediate Artifacts. | Eagerly run all candidate producers, then choose one value for downstream Steps. |
| **Composite workflow** | Combine artifact chains, fan-out/fan-in, explicit bounded Agent Steps, and named Artifact selections. | When one simple pattern does not cover the task. |

Before reporting a missing capability for a conditional request, first check whether eager value selection is sufficient. Named Artifact selection runs every candidate producer and only selects the value passed downstream. If the request requires lazy branch activation or guarantees that an unselected producer will not run, report that limitation instead of emitting an approximation. Never invent a keyword or operator to make the source look complete.

### Adversarial verifier pattern

Use this optional pattern as an authoring prompt, not as a fixed domain
checklist. Add it only when task risk, requested coverage, and user-stated cost
or latency limits warrant the extra check, a builder produces a reviewable
candidate, and the verifier can perform a meaningful independent check from the
same visible task contract and evidence. Do not add it to a side-effect-only
Step or when correction would require facts that are absent from the consumed
Artifacts.

Author a final Agent-backed verifier Step that consumes:

- the original task contract or requirements Artifact;
- the same source evidence used to build the candidate; and
- the candidate Artifact itself.

Adapt the following prompt to the actual Artifact IDs and declared output
contract. Put it in a companion instruction Markdown file when it is too long
for one `step_instruction` string:

```text
You are an adversarial verifier for a candidate result. Do not call tools or
introduce external facts. Treat the consumed task contract and source evidence
as the complete ground truth, and treat the consumed candidate as untrusted.

Build a checklist from the visible task contract. At minimum, try to refute:
1. every explicit requirement and constraint;
2. every factual claim that should be traceable to the supplied evidence;
3. every derived value or calculation that can be recomputed;
4. internal consistency across the whole candidate; and
5. the requested output structure and completeness.

Report PASS or FAIL for each applicable check with concrete evidence. Do not
invent a check from hidden scoring feedback or task-specific knowledge that is
absent from the consumed inputs. If every check passes, set the verdict to OK
and preserve the candidate exactly. If any check fails, set the verdict to
FIXED and produce a fully corrected final result using only the same inputs.
Never leave placeholders. Return exactly the verifier Step's declared Artifact
mapping: the verification report and the final result.
```

The verifier is one independent check-and-correct Step, not an evaluator-driven
retry loop. It receives no privileged source and does not call the builder
again. Declare a report Artifact and a final Artifact; expose only the final
Artifact through `output_workflow` unless the user explicitly asks to receive
the report too. For example, a release-note workflow can analyze a change set,
build draft notes, then have the verifier check every statement against that
same change evidence and correct unsupported or inconsistent claims.

#### Full-featured in-context example

This is the canonical review shape from the activation example: three independent review Steps consume the same source, then one final Step consumes their outputs.

```fusionflow
-- SCENARIO: security, performance, and readability review followed by one report

const source_code: Artifact;
const security_findings: Artifact;
const performance_findings: Artifact;
const readability_findings: Artifact;
const final_report: Artifact;

const security_review: Step;
const performance_review: Step;
const readability_review: Step;
const synthesize_report: Step;

const security_agent: Agent, Executor;
const performance_agent: Agent, Executor;
const readability_agent: Agent, Executor;
const editor_agent: Agent, Executor;


workflow code_review {
  -- DATA FLOW
  input_workflow(code_review) == [source_code];
  consumes(security_review) == [source_code];
  produces(security_review) == [security_findings];
  consumes(performance_review) == [source_code];
  produces(performance_review) == [performance_findings];
  consumes(readability_review) == [source_code];
  produces(readability_review) == [readability_findings];
  consumes(synthesize_report) ==
    [security_findings, performance_findings, readability_findings];
  produces(synthesize_report) == [final_report];
  output_workflow(code_review) == [final_report];

  -- EXECUTOR ASSIGNMENT
  step_executor(security_review) == security_agent;
  step_executor(performance_review) == performance_agent;
  step_executor(readability_review) == readability_agent;
  step_executor(synthesize_report) == editor_agent;

  -- STEP CONFIGURATION
  step_name(security_review) == "Security Review";
  step_instruction(security_review) == "Inspect the source for exploitable behavior and unsafe trust boundaries. Return prioritized findings with concrete evidence and remediation.";
  step_timeout(security_review) == 300;
  step_name(performance_review) == "Performance Review";
  step_instruction(performance_review) == "Identify material performance risks in the source. Explain the triggering workload, likely impact, evidence, and practical fixes.";
  step_timeout(performance_review) == 300;
  step_name(readability_review) == "Readability Review";
  step_instruction(readability_review) == "Review maintainability and clarity. Return specific high-impact issues, why they matter, and focused improvements.";
  step_timeout(readability_review) == 300;
  step_name(synthesize_report) == "Synthesize Report";
  step_instruction(synthesize_report) == "Combine the three reviews into one deduplicated report. Preserve evidence, resolve conflicts explicitly, prioritize actions, and separate findings from inference.";

  -- WORKFLOW CONFIGURATION
  max_concurrency(code_review) == 3;
  workflow_timeout(code_review) == 900;

}
```

### G4 source of truth

Before authoring, read `grammar/FusionFlow.g4` completely. It is the sole authority for surface syntax, declarations, assertions, formulas, terms, and preset operator signatures. This skill additionally defines which grammar-valid shapes the executable graph backend accepts.
Runner-specific typed catalog extensions use the grammar's generic operator-call syntax without changing its preset catalog. In particular, `depends_on(Step, Step) -> Bool` is registered by `fusion_flow/workflow_runner.py` and is executable there, but is not one of the grammar's 21 canonical preset operators.

### Executable graph backend guardrails

- Every dataflow operator has one owner and an explicit Artifact List RHS.
- Every executable `if` has the top-level shape `selected_artifact == if(condition, artifact_a, artifact_b);`. Never put `if` inside a dataflow List or another `if`; chain named intermediate Artifacts instead.
- Selection is eager: every candidate producer runs before the selected value is published.
- A Step instruction is either short JSON-style quoted text or a `"./..."` UTF-8 text-file path relative to the `.workflow` or `.g4` source file. Use a companion Markdown file when the instruction needs multiple sections.

### Modeling rules

- Group assertions by concern in this exact order: `DATA FLOW`, `EXECUTOR ASSIGNMENT`, `STEP CONFIGURATION`, `SCHEDULING CONFIGURATION`, `WORKFLOW CONFIGURATION`. Omit empty groups.
- In `DATA FLOW`, declare the complete external input List once, then every Step's `consumes`/`produces` edges and named Artifact selections in dependency order, then the complete external output List once.
- Use exactly one symmetric Artifact dataflow contract: `input_workflow(workflow) == [artifact_a, artifact_b];`, `consumes(step) == [artifact_a, artifact_b];`, `produces(step) == [artifact_a, artifact_b];`, and `output_workflow(workflow) == [artifact_a, artifact_b];`. All four operators return `List`; even one Artifact requires an explicit List literal such as `[artifact]`. Never use these calls as standalone assertions, with `== True`, with an Artifact as a second argument, or through alternate multi variants.
- Bool shorthand is only for supported non-dataflow Bool operators such as `independent(step)` and `depends_on(step, predecessor)`. Keep `== False` explicit. Retain the right-hand value for every non-Bool operator.
- Write each Step display name directly as a JSON string, for example `step_name(security_review) == "Security Review";`. Do not declare an intermediate `StepName` constant or emit a symbolic display name ending in `_name`; symbolic StepName values are rejected before compilation.
- When the user supplies a grammar-valid literal as a typed constant name, including a restricted quoted ID or `"./..."` path, preserve that literal and use it directly as the required preset value; do not hide it behind an alias constant and an extra equality.
- Write every `step_instruction` as an executable task specification, not a label. State the objective, how to interpret consumed Artifacts, important constraints or evidence requirements, and the expected result. A name such as `"task_name"` is not an instruction.
- Treat every Agent Step as a clean, isolated context. It sees its instruction
  and consumed Artifacts, not the parent conversation or undeclared sibling
  results. Pass every required fact, criterion, candidate, and prior result
  through explicit Artifact edges; never rely on phrases such as "as above".
- Keep independent pipelines branch-local. A verifier or transformer that
  needs only one branch result consumes that result directly and may become
  ready before sibling branches finish. Add a fan-in consumer only when its
  task genuinely requires cross-branch context from all listed Artifacts.
- Use executable `@artifact ... = {...}` contracts at boundaries that need
  machine-checkable structure. Do not ask a downstream Agent to recover a
  protocol by parsing acknowledgements, prose wrappers, or an undeclared text
  convention.
- Keep each Step independently understandable and bounded. Let information dependencies determine the hierarchy: synthesize a distinct group of upstream Artifacts before combining it with other groups only when that intermediate result is genuinely consumed downstream. Do not add layers merely because a request is large, and do not collapse separable work into coarse Steps merely to minimize node count.
- Model data sequencing through Artifact edges: a Step that produces an Artifact precedes a Step that consumes it. When ordering is required without passing data, use `depends_on(step, predecessor) == True`; repeat it for multiple predecessors. Declaration order never defines execution order.
- Preserve the external data boundary from the user's intent. Fan-out Steps that analyze the same subject reuse one shared input Artifact; do not split it into synthetic per-branch workflow inputs.
- Emit every explicitly requested relation. Every operand must be a declared grammar term: `_` and `...` are not wildcards. Declare typed constants for required operands, or omit an optional configuration instead of inserting placeholders.
- Model fan-out by making several steps consume the same artifact.
- Model fan-in with `consumes(step) == [artifact_a, artifact_b];`.
- Use `foreach_item(step, source_artifact) == item_binding` when a source Artifact contains a finite JSON List. The item binding is local to the expanded Step and is added to that iteration's inputs; do not also declare it as a workflow input.
- Foreach iterations run in parallel by default. Only workflow `max_concurrency` and resource capacity bound them; there is no per-foreach limit.
- Normal foreach outputs become source-ordered Lists only after every iteration succeeds; an empty source produces empty Lists. Iteration failures are raised, never declared or returned as G4 Artifacts.
- Bind each step to its executor with `step_executor`.
- Configure concurrency, timeouts, retries, and resources with the corresponding supported operators. Resources, `step_timeout`, `max_attempts`, and checkpoint progress apply independently to each foreach iteration.
- Treat `independent(step)` only as a hint. Artifact dependencies and `depends_on` still decide when the Step is ready.
- Declare resource demand with `resource_requirement(step, resource)`. Resource capacities or concrete IDs come from runner configuration, never from `.workflow` source.
- Agent- and Program-backed foreach Steps are executable. Human-backed foreach is rejected before dispatch until Human requests and responses carry iteration identity.
- A Program failure inside foreach participates in that Step's `max_attempts` and then joins the aggregate exception. Outside foreach, preserve the existing `$fusion_flow/program_error` error-valued Artifact behavior.
- Ordinary terminal foreach failures do not cancel siblings; after all ordinary iterations finish, the runner raises them together. Successful iteration checkpoints are reused on resume. Cancellation, workflow timeout, Human suspension, and graph/checkpoint/allocator invariant failures still escape immediately.
- Unknown or unsupported assertions remain residual and stop execution. Never delete them, comment them out, or bypass residual validation to make a run start.
- Lower executable `if` as a named Artifact selection: `selected_artifact == if(formula, artifact_a, artifact_b);`, followed by ordinary list dataflow such as `consumes(final_step) == [selected_artifact];`.
- Variables, quantifiers, rules, implications, biconditionals, query/SAT/optimization requests, local concept declarations, local operator declarations, and imperative blocks are outside this language.
- Never emit imports, imperative runtime calls, `run(...)`, or invented `parallel`/`pipeline`/`for` blocks.

#### Foreach example

```fusionflow
const enrich_batch: Workflow;
const enrich_item: Step;
const worker: Agent, Executor;
const items: Artifact;
const item: Artifact;
const enriched_items: Artifact;

workflow enrich_batch {
  -- DATA FLOW
  input_workflow(enrich_batch) == [items];
  foreach_item(enrich_item, items) == item;
  produces(enrich_item) == [enriched_items];
  output_workflow(enrich_batch) == [enriched_items];

  -- EXECUTOR ASSIGNMENT
  step_executor(enrich_item) == worker;

  -- STEP CONFIGURATION
  step_name(enrich_item) == "Enrich Item";
  step_instruction(enrich_item) == "Enrich the local item input and return the enriched_items value.";
  step_timeout(enrich_item) == 120;
  max_attempts(enrich_item) == 2;

  -- WORKFLOW CONFIGURATION
  max_concurrency(enrich_batch) == 8;
}
```

At runtime `items` must be a JSON List. Iterations run in parallel and
`enriched_items` preserves source order. If ordinary iterations fail, siblings
finish and the failures are raised together; successful iteration checkpoints
can be reused on resume.

#### Executor configuration

Declare every executor as exactly one of `Agent, Executor`, `Human, Executor`, or `Program, Executor`, bind it with `step_executor`, and give each Step a `step_instruction`.

Agent configuration may use `agent_config`, `agent_system_prompt`,
`allowed_tool`, `max_output_tokens`, `temperature`, `reasoning_effort`, and
`max_turns`. The declared system prompt augments the fixed Step safety/output
protocol; it cannot replace it. `allowed_tool` narrows the host-safe tool
registry and cannot re-enable a denied workflow launcher. The current workspace
AI socket fixes provider routing, so a non-default `model`, `engine`, or
`api_base` is rejected explicitly instead of being ignored.

Agent-backed Steps execute through the shared `flow.agent()` and
`flow.session()` primitives inside `fusion_flow.execution.run()`. Their
completion callback must return a mapping keyed exactly by the declared output
Artifact IDs. A normally completed Agent turn may return either one strict JSON
object or one standalone `json` fence. Malformed JSON is returned to the model
for output-only correction without rerunning the Step. If the third ordinary
text response is still invalid, the runtime may remove only unambiguous trailing
commas by trying `json-repair` once. The repaired result is accepted only when it
is canonically identical, including JSON value types, to a string-aware pass that
removes trailing commas and nothing else; strict parsing and exact-key validation
then run again. Every other malformed result fails without publishing any
Artifact, regardless of output cardinality; invalid raw text is never bound or
broadcast.

A Human Step may request an approval, choose among up to four options, or accept open-ended/structured input. Its dedicated preparation Agent receives the resolved instruction text, consumed Artifacts, and output contract, then emits the arguments for the existing `clarify` tool. It never asks the user itself, and its question text never becomes a produced Artifact. The next user response becomes the Human Step result after `run_flow_resume`. Multiple output Artifacts require a JSON object keyed exactly by those Artifact IDs; a zero-output Human Step acts as a pure gate.

Every Program must declare one explicit workspace-relative script or source path:

```text
const worker: Program, Executor;

program_path(worker) == "./bin/worker";
```

The public workspace runner has no catalog path resolver, so do not use a bare Path identity. `program_path` names one workspace-local regular file, not a shell command: do not append arguments, operators, pipes, or environment assignments. It does not need an executable bit, a shebang, or `chmod`. A specialized Program Agent may inspect the workspace, prepare or install the required language runtime, dependencies, compiler, or toolchain, and interpret or compile the declared file. The runtime supplies one newline-terminated JSON object as the authoritative stdin:

```json
{
  "instruction": "<resolved step_instruction text>",
  "inputs": {
    "<consumed Artifact ID>": "<runtime value>"
  }
}
```

Fidelity-mode interpreted execution does not accept an arbitrary argv from the Program Agent. The Agent selects one interpreter executable, and the host constructs exactly `[interpreter, declared_script, *logical_argv[1:]]`; do not add interpreter flags, inline code, another script, extra arguments, or reorder/drop the declared logical arguments. Compiled languages must use structured `compile_program`, which binds the compiler argv, declared source hash, artifact hashes, and one exact launch argv. `execute_program` may launch that compiled argv only after the host revalidates the registered source and artifacts. Preparation shells must not substitute for either structured operation.

The structured tools capture the actual argv, stdout and stderr bytes, exit code, and launch error separately. Once the real Program launches in fidelity mode, it is the sole attempt: never call `execute_program` again, even after a nonzero exit, invalid-input/domain error, or invalid output. Preserve that first result or error and let `submit_program_result` commit it deterministically; the model never authors the Artifact values itself. Before launch, the Program Agent may install missing environment or toolchain components and retry preparation failures, but it must not patch/replace the declared script, alter consumed input Artifact values or stdin, or reinterpret output. Only include the following exact standalone line in the resolved `step_instruction` when the user deliberately authorizes successful completion to outrank fidelity:

```text
Program execution policy: successful completion outranks fidelity.
```

No paraphrase enables adaptation. An authorized script or stdin adaptation must state a concrete `adaptation_reason`, and the consumed input Artifact values remain immutable.

For one produced Artifact, valid UTF-8 stdout is that Artifact's exact string value, including trailing newlines. For multiple produced Artifacts, stdout must be exactly one strict, finite JSON object keyed by all and only those Artifact IDs; `NaN`, `Infinity`, numeric overflow to infinity, nested non-finite values, and duplicate object keys are rejected. A Program that produces no Artifacts must not write stdout. Launch errors, nonzero exits, invalid UTF-8, and output-format errors become the same `{"$fusion_flow/program_error": {...}}` value on every declared output Artifact, preserving captured attempts; a failing zero-output Program raises because it has no Artifact for the diagnostic. Never reinterpret an error-valued Artifact as success.

`execute_program` runs without a shell in a separate POSIX process group or Windows Job Object. Shielded cleanup terminates members of that boundary on failure, declared Step/workflow timeout, cancellation, output overflow, and after a direct child exits with managed descendants still present. There is no internal 300-second Program timeout. Stdout and stderr are streamed with retained-output defaults of 4 MiB and 1 MiB respectively; set `PSI_FUSION_FLOW_PROGRAM_STDOUT_LIMIT_BYTES` or `PSI_FUSION_FLOW_PROGRAM_STDERR_LIMIT_BYTES` to a positive integer to override them. Exceeding either limit terminates the process boundary. Environment preparation can use shell tools, so this remains a trusted-workspace lifecycle boundary rather than a host sandbox; on POSIX, code that deliberately creates a new session/process group leaves the managed group.

#### Named Artifact selection with `if`

Keep every candidate result explicit and produced by a Step. Bind each `if` result to a declared Artifact before downstream dataflow:

```fusionflow
const incoming_case: Artifact;
const primary_criterion: Artifact;
const block_criterion: Artifact;
const review_criterion: Artifact;
const exception_criterion: Artifact;
const primary_observation: Artifact;
const block_observation: Artifact;
const review_observation: Artifact;
const exception_observation: Artifact;
const primary_result: Artifact;
const review_result: Artifact;
const fallback_result: Artifact;
const review_or_fallback: Artifact;
const selected_result: Artifact;
const final_result: Artifact;

const triage_step: Step;
const primary_handler_step: Step;
const review_handler_step: Step;
const fallback_handler_step: Step;
const final_step: Step;

const triage_agent: Agent, Executor;
const primary_handler: Agent, Executor;
const review_handler: Agent, Executor;
const fallback_handler: Agent, Executor;
const final_consumer: Agent, Executor;

workflow priority_routing {
  -- DATA FLOW
  input_workflow(priority_routing) ==
    [incoming_case, primary_criterion, block_criterion, review_criterion, exception_criterion];
  consumes(triage_step) == [incoming_case];
  produces(triage_step) ==
    [primary_observation, block_observation, review_observation, exception_observation];
  consumes(primary_handler_step) == [incoming_case];
  produces(primary_handler_step) == [primary_result];
  consumes(review_handler_step) == [incoming_case];
  produces(review_handler_step) == [review_result];
  consumes(fallback_handler_step) == [incoming_case];
  produces(fallback_handler_step) == [fallback_result];
  review_or_fallback == if(
    (review_observation = review_criterion) OR (exception_observation = exception_criterion),
    review_result,
    fallback_result
  );
  selected_result == if(
    (primary_observation = primary_criterion) AND !(block_observation = block_criterion),
    primary_result,
    review_or_fallback
  );
  consumes(final_step) == [selected_result];
  produces(final_step) == [final_result];
  output_workflow(priority_routing) == [final_result];

  -- EXECUTOR ASSIGNMENT
  step_executor(triage_step) == triage_agent;
  step_executor(primary_handler_step) == primary_handler;
  step_executor(review_handler_step) == review_handler;
  step_executor(fallback_handler_step) == fallback_handler;
  step_executor(final_step) == final_consumer;

  -- STEP CONFIGURATION
  step_name(triage_step) == "Triage";
  step_instruction(triage_step) == "Evaluate incoming_case against each supplied criterion. Produce one observation Artifact per criterion, citing the relevant evidence and marking uncertainty.";
  step_name(primary_handler_step) == "Primary Handler";
  step_instruction(primary_handler_step) == "Produce the primary handling result for incoming_case. Explain the decision, preserve material constraints, and return a result suitable for downstream selection.";
  step_name(review_handler_step) == "Review Handler";
  step_instruction(review_handler_step) == "Produce a reviewed handling result for incoming_case. Identify risks or ambiguities, resolve what the available evidence supports, and state any remaining uncertainty.";
  step_name(fallback_handler_step) == "Fallback Handler";
  step_instruction(fallback_handler_step) == "Produce a safe fallback result for incoming_case when stronger handling criteria are not met. Explain limitations and preserve enough context for finalization.";
  step_name(final_step) == "Finalize Result";
  step_instruction(final_step) == "Turn the selected_result into the final response. Preserve its supported conclusions, remove routing metadata, and make unresolved uncertainty explicit.";
}
```

- Build conditions with `=`, `!=`, `<`, `<=`, `>`, or `>=`; reserve `==` for the surrounding assertion.
- Combine comparisons with `!`, `AND`, and `OR`.
- Both branches must be declared Artifacts. The selection result must also be a declared Artifact.
- Every candidate producer runs. Selection is eager value routing, not lazy control flow.
- For more choices, chain named intermediate Artifacts in priority order; do not nest an `if` directly inside another `if`.
- Never place `if(...)` inline inside `input_workflow`, `consumes`, `produces`, or `output_workflow`; those operators still take explicit Artifact Lists.
- Do not replace candidate Artifacts with Boolean Step payloads or invent `switch`, `choice`, or conditional blocks.

Use free-form quoted text only where the typed catalog expects an `Instruction` or `StepName`. Do not encode shell commands, code, large source documents, or secrets as instruction text. Put a long instruction in a companion Markdown file; pass source material through input Artifacts.

### Anti-patterns to refuse

1. **Hand-writing imports or imperative runtime calls.** The authored program is Workflow G4 source.
2. **Inventing a keyword or operator.** Flexible call syntax does not make unknown names valid.
3. **Using `==` inside a condition or `=` for a workflow assertion.** These have different grammar roles.
4. **Using a symbolic instruction label as the task.** A Step needs actionable instruction text or a companion instruction file, not only a name such as `"task_label"`.
5. **Treating `max_attempts` as a workflow loop or score gate.** It only sets the attempt limit for one Step.
6. **Expanding a large item list without a cost check.** Every explicit Agent Step may consume a model call; keep the bounded expansion intentional.
7. **Inlining a large source document as an instruction.** Keep the task specification in the instruction and pass source material through an input Artifact.
8. **Relaying an external tool's secret through workflow source.** Let the tool read its own configuration; never encode credentials in constants.
9. **Sharing mutable state between parallel branches.** Use artifacts and explicit producer/consumer relations.

### Code template

Every authored workflow follows this shape:

```fusionflow
-- SCENARIO: <one-line user-facing description>
-- AUTHORED: <YYYY-MM-DD HH:mm:ss> from intent: "<original user intent>"

const input_artifact: Artifact;
const output_artifact: Artifact;
const work_step: Step;
const worker: Agent, Executor;

workflow workflow_name {
  -- DATA FLOW
  input_workflow(workflow_name) == [input_artifact];
  consumes(work_step) == [input_artifact];
  produces(work_step) == [output_artifact];
  output_workflow(workflow_name) == [output_artifact];

  -- EXECUTOR ASSIGNMENT
  step_executor(work_step) == worker;

  -- STEP CONFIGURATION
  step_name(work_step) == "Work";
  step_instruction(work_step) == "Complete the requested transformation using input_artifact, follow the user's stated constraints, and return the concrete result as output_artifact.";
}
```

Extend this skeleton only with syntax and preset operators documented in `grammar/FusionFlow.g4`.

### Static self-check

Before the initial `run_flow` call, inspect the source in order:

- graph values may be untyped; when explicitly typed, their concepts include `Artifact`;
- every other identity is declared with a supported concept;
- assertions use `==`, while formulas use comparison operators;
- each operator uses the documented arity and supported shape;
- each Step has a supported Agent, Human, or Program executor, name, instruction, and explicit data/control dependencies;
- the planning contract covers intent, success, interfaces, responsibilities, constraint ownership, dependencies, and operational limits;
- the Workflow authoring guide was applied: clean-context inputs are
  explicit, independent branches have no artificial stage barrier, joins have
  real cross-branch consumers, structured boundaries have Artifact contracts,
  and any deliberate coverage bound is visible rather than silently dropped;
- no residual or unsupported operator is emitted.

This manual source review is not a second tool or CLI invocation. Inside `run_flow`, `check_workflow` requires exactly one workflow, delegates graph semantics to `WorkflowGraphCompiler`, rejects unsupported residual assertions and graph values with explicit concepts that omit `Artifact`, requires every Step instruction and Program path, and rejects untyped or ambiguous executor declarations. Parsing, checking, and compilation all occur before dispatch.

### Running it (automatic, right after the self-check)

1. Call `run_flow(flow_path=..., inputs_json=..., resource_capacities_json=...)` once. Omit resource capacities when the graph declares no resource requirement.
2. If it returns a `$fusion_flow/control` Human-wait envelope, follow the Human wait/resume protocol exactly. Do not present that envelope as the workflow result.
3. When a call returns output Artifacts, summarize them in plain language.
4. On error, report the compiler diagnostic or failed Step without creating a second workflow or bypassing the runner.

The workflow controls structure and execution, not the truth of domain content.
The user can request a later revision after reading the result. Keep
implementation details out of the response unless the user asks for them.

## Doctor Checks

When the user asks whether a workflow can run:

1. Confirm the source is a readable workspace-relative `.workflow` or `.g4` file.
2. Perform the static self-check above. The same checks run inside `run_flow`; there is no separate validator tool or CLI.
3. Confirm that required resource capacities can be supplied.

If the static check finds an issue, report:

```
✗ Workflow source is not ready to run
  Reason: <first source-contract issue>
```

Otherwise:

```
✓ Workflow source is ready for run_flow
```

## Capabilities

When the user asks what this skill can do ("你能帮我做什么 / 我能用这个干嘛"), lead with natural-language examples and mention saved-workflow reuse:

```
🐾 Workflow
用自然语言驱动多 Agent 工作流，也可以保存后按名称复用：

  • "帮我写个工作流做 X / 帮我编排 ..."           → 用大白话描述需求，我帮你搭好并运行
  • "把这个保存为 daily-brief"                   → 保存到固定的 workflow 文件夹
  • "调用 daily-brief 的 workflow"               → 按名称加载并全新运行一次
  • "跑一下刚才那个 / 帮我跑这个 workflow"        → 执行 G4 workflow；需要你审批或输入时直接在对话里问
  • "环境齐不齐 / 能不能跑"                        → 检查 G4、Agent/Human/Program executor 和资源声明

不附带现成可运行示例；你想要什么工作流，直接描述，我会写入 workspace 的 flows/ 目录。
```

## Security + Approvals

Agent Steps run through ephemeral psi Sessions with a filtered workspace tool snapshot; nested workflow launchers and `clarify` are unavailable to them. Program Steps run through separate specialized Sessions with workspace-inspection/environment-preparation tools plus structured `compile_program` and `execute_program`; their declared regular script/source file and working directory must resolve inside the workspace, but the script needs no executable permission. Fidelity-mode interpreted argv is host-built, compiled provenance is hash-bound, and a launched Program is never retried. Human instruction preparers receive only a workspace-confined, read-only `read` tool, so a referenced file cannot escape the workspace through `..`, an absolute path, or a symbolic link. Review user-supplied G4 source before execution, but do not add an approval gate unless the workflow itself declares a Human Step. Human interaction reuses the parent Session's existing `clarify` flow and never creates a separate approval UI. Refuse remote URLs: `run_flow` accepts workspace-local `.workflow` or `.g4` files only. Treat the Program Agent's shell-enabled environment preparation as trusted workspace execution, not as a host sandbox.
