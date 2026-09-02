---
name: workflow
description: Author, save, inspect, reuse, or run Workflow declarations after explicit Workflow or multi-agent opt-in. Use for coordinated agents or roles, program or human steps, parallel branches, and staged pipelines. Use the legacy flow skill only for explicit compatibility work.
---

# Workflow

Workflow is the workspace's declarative system for coordinating Agent, Human,
and Program Steps. A declaration is parsed, checked, compiled to a typed
Step--Artifact graph, and executed by `run_flow`.

Use the supported `.workflow`/`.g4` format only. Legacy `.flow.ts`, Fuclaw, and
`@agent-flow/core` requests belong to `skills/fusion-flow-legacy/`; do not
translate them implicitly. This Skill ships no runnable workflow examples.

## Activation and authorization

Activate this Skill only after explicit user opt-in, for example a request to
author, run, save, inspect, reuse, or list a Workflow, or to coordinate agents,
parallel branches, or staged work. A task that merely benefits from extra calls
does not authorize the additional cost. If orchestration would materially
change cost or latency, state the scale briefly and ask before authoring.

Saving, listing, loading, and inspecting activate the Skill for registry work;
they do not authorize execution. Call `run_flow` only when the user also asks
to run or invoke the declaration. Do not activate this Skill for `.prose` files.

## Runtime contract

The runtime has one supported Python API shape: `execute_workflow` requires
`inputs=`; Agent and Human callbacks receive `(prompt, CompletionContext)`;
`execute_plan` requires `dispatch=` with `(StepNode, inputs, DispatchContext)`.
These are contracts, not compatibility alternatives.

The Skill's job is to:

1. author valid Workflow source or resolve the concrete source named by the user;
2. save a self-contained reusable bundle when requested;
3. invoke `run_flow` when execution is authorized; and
4. return the final output Artifact mapping, or handle the declared Human wait.

## Workspace paths

One-off source belongs under `flows/`. A reusable declaration is a self-contained
bundle at `flows/workflows/<slug>/` containing `<slug>.workflow` (preferred) or
`<slug>.g4`, plus any referenced instruction files under the same bundle.
Resolve a saved workflow by slug only; never guess or execute a path outside
the workspace. Relative instruction paths resolve from the source file, and
the public adapter rejects bundle escapes.

Each run writes materialized Artifacts to
`<workflow-bundle>/runs/<run-id>/artifacts/` (text as Markdown, other strict
JSON values in a fenced `json` block). Human workflows also keep private
checkpoints in `.psi/fusion-flow/runs/`; `step-timings.json` and
`token-usage.json` are run-local observability files.

## Artifact contracts

Declare contracts with a standalone `@artifact` comment. The short form gives
a top-level type and description; the `=` form gives the supported executable
JSON Schema subset. Every schema needs a top-level `type` and non-empty
`description`. Supported types are `null`, `boolean`, `integer`, `number`,
`string`, `object`, and `array`. Supported keywords are `properties`, `required`,
`additionalProperties`, `items`, size and length limits, numeric bounds,
`pattern`, `enum`, and `const` (plus `type` and `description`).

For program-enforced parameter and output constraints, use for example:

```fusionflow
-- @artifact request = {"type":"object","description":"A lookup request.","properties":{"query":{"type":"string","description":"Non-empty text.","minLength":1}},"required":["query"],"additionalProperties":false}
```

Unsupported or malformed
schema keywords fail compilation. A contract may be repeated in a Step
instruction only for that Step's consumed or produced Artifacts; conflicting,
unknown, or unrelated declarations fail before dispatch. The runtime
recursively enforces declared object parameters, array items, required and
extra-property policy, sizes, bounds, patterns, enums, and constants at input,
Step, Program, downstream, and final boundaries. `foreach` contracts describe
the source-ordered aggregate; an `items` schema also validates each iteration.

Agent and Human outputs must match their declared Artifact IDs. A reserved
`$fusion_flow/program_error` value is deliverable only from the actual Program
producer. A single-output typed Program parses one strict JSON value; untyped
and string outputs preserve verbatim UTF-8 stdout.

## Intent routing

Use the user's wording to choose the narrowest action:

| Request | Action |
| --- | --- |
| Ask what Workflow can do | Explain capabilities in plain language and offer to build one. |
| Run a saved workflow by name | Resolve its canonical slug bundle, read `input_workflow`, collect every input, then call `run_flow` once. |
| List or inspect saved workflows | Use existing directory/file tools; do not execute. |
| Save the current declaration | Write one self-contained bundle under `flows/workflows/<slug>/`; saving never runs it. |
| Run or invoke a concrete declaration | Call `run_flow` and return its outputs, or follow the Human protocol below. |
| Continue a pending Human request | Call `run_flow_resume` with the exact returned identifiers. |
| Ask whether a declaration is runnable | Perform the Doctor checks below; do not run it. |

## Running and resuming

Before execution, ensure every Step uses exactly one supported executor. Every
Program needs an explicit workspace-relative `program_path`. Estimate the
number of Agent and Program Steps and give one short heads-up sentence; this is
notice, not an additional approval gate.

For a saved declaration, resolve all declared inputs before the initial call.
Do not call with an empty object merely to probe missing inputs. Initial calls
are fresh runs. Pass `resource_capacities_json` only when the declaration has a
resource requirement. Call `run_flow` once; do not manually dispatch Steps.

If the result is a sole `$fusion_flow/control` object with
`status == "waiting_for_human"`:

1. Pass its `request.question`, `options`, `recommended`, and `default` to the
   existing `clarify` tool and end the turn.
2. On the next user message, map a numbered choice to its label. Preserve free
   text; JSON-encode mapped labels, defaults, structured values, or text that
   is already JSON-like. For multiple outputs, encode exactly the declared
   Artifact mapping.
3. Call `run_flow_resume` with the exact `run_id` and `request_id`.
4. Repeat if another Human request is returned; otherwise report the final
   output mapping.

Never invent, reuse, or guess identifiers. A changed source, stale request, or
conflicting response is a stop-and-report error. A compilation or Step failure
is also stop-and-report: identify the diagnostic or Step and do not edit the
workflow, bypass the runner, create a mock, or silently retry. Retries are only
for predeclared executor, transport, or timeout failures, with identical input
and instruction.

The runner owns parsing, dependency scheduling, concurrency, resources,
timeouts, retries, process cleanup, and checkpoint validation. Do not invent
polling, PIDs, progress, or a second approval inbox. The tool exposes no
node-level progress; never claim that a branch has started or finished.

## Authoring Mode

Enter Authoring Mode when the user asks to build or revise a Workflow, or
explicitly asks for coordinated agents, fan-out/fan-in, debate, review, or a
multi-step pipeline. A request that is merely workflow-shaped without such
opt-in stays on the normal task path.

### Planning contract

Before writing source, identify:

- the intent and concrete success condition;
- every external input and final output Artifact;
- each Step's single responsibility and its consumed and produced Artifacts;
- information dependencies and the owner of every material constraint; and
- concurrency, timeout, retry, resource, and user-stated cost limits.

Assign mechanically decidable constraints to graph structure or a deterministic
Program Step; assign constraints that require judgment to an Agent Step. Let
dependencies determine execution: fan out independent work, keep dependent work
sequential, and join branches only when a consumer needs all their results.

### Authoring procedure

1. Restate the goal in one sentence; ask at most one clarifying question when
   genuinely necessary.
2. Read `references/workflow-authoring-guide.md` in full, then complete the
   planning contract. It is mandatory policy for scope discovery, clean
   contexts, explicit Artifact transport, true joins, visible limits, and
   risk-scaled verification.
3. Read `grammar/FusionFlow.g4` in full and write exactly one source file at
   the requested workspace path. Use only declarations, assertions, terms, and
   operators documented there.
4. Perform the Static self-check below. `run_flow` repeats it internally;
   there is no separate validator tool or CLI.
5. Say one plain-language heads-up and call `run_flow` once. Do not ask
   "要不要跑" or wait for another approval unless the user explicitly asked
   for source only.

Keep the authoring process silent. After any necessary clarification, do not narrate reasoning, alternative graph designs, syntax reconstruction, self-checks, edits, or retries. Still perform every authoring and static-check step in full.
Non-technical users receive the result, not implementation details; explain the
structure only when asked.

### Structural patterns

Choose the smallest graph that preserves real dependencies:

- **Fan-out/fan-in:** independent Steps consume shared input; a real join
  consumes their explicit results.
- **Pipeline:** each Step consumes the prior Artifact; use `max_attempts` only
  when rerunning that Step is safe.
- **Branch-local pipeline:** each independent branch discovers, transforms, and
  checks its own data before a final join.
- **Per-item map:** `foreach_item` expands a finite List; results preserve source
  order. Use workflow concurrency or resource capacity when a bound is needed.
- **Adversarial verifier:** an independent Agent consumes the visible contract,
  the builder's evidence, and the candidate; it records concrete checks and
  uncertainty, and returns either the unchanged or corrected result. It must
  not use hidden evaluator rules or privileged data.
- **Selection:** bind `selected == if(condition, candidate_a, candidate_b)` to a
  declared Artifact. Candidate producers are eager; chain named selections for
  more than two choices.

Do not add stages merely because a task is large, or collapse separable work
just to reduce node count. Discover an unknown work list before fan-out and pass
one stable scope Artifact to workers. Never silently sample, truncate, rank, or
skip requested work; make any bound and omissions visible.

### Adversarial verifier pattern

Use this optional pattern only when the task's risk, requested coverage, and
cost or latency limits justify an independent check. The verifier receives the
same visible task contract and evidence as the builder, plus the candidate; it
Do not call tools or use hidden evaluator rules. Build a checklist from the visible task contract
before judging the candidate. Report PASS or FAIL for each applicable check with concrete evidence.
Check each applicable requirement, factual claim, derivation,
cross-item relation, completeness condition, and output shape, and report
concrete evidence. Report PASS or FAIL for each applicable check with concrete
evidence; use UNDETERMINED when the visible basis is missing. Record all
violations before correction. If all checks pass, set the verdict to OK and
preserve the candidate; otherwise set the verdict to FIXED and return a fully
corrected result using only the supplied inputs. Never invent a check from
hidden scoring feedback or hidden evaluator rules.

### Source rules

The grammar covers declarations, assertions, Boolean formulas, comparisons,
arithmetic, Lists, quoted text, and value-producing `if` terms. Operator
registration, type compatibility, arity, workflow legality, and backend support
remain checker responsibilities; removed aliases are not compatibility forms.

Use explicit Artifact Lists for `input_workflow`, `consumes`, `produces`, and
`output_workflow`, including singleton lists. Use `depends_on(step,
predecessor) == True` when ordering is required without data transfer.
Declaration order does not define execution order. `independent` is a hint;
Artifact edges and `depends_on` decide readiness.

`foreach_item(step, source) == item` requires a finite JSON List at runtime;
iterations are parallel subject to workflow/resource limits. Normal iterations
produce an ordered aggregate only after all succeed. Ordinary iteration failures
are raised together after siblings finish; cancellation, timeout, Human
suspension, and invariant failures escape immediately.

Conditions use `=`, `!=`, `<`, `<=`, `>`, or `>=`; `==` is for assertions.
Combine conditions with `!`, `AND`, and `OR`. Both `if` branches and its result
must be declared Artifacts. Never put `if` inside dataflow Lists or another
`if`; do not invent `switch`, `choice`, `parallel`, `pipeline`, or imperative
blocks. Unknown or unsupported assertions remain residual and stop execution.

Every Step needs a supported executor, display name, actionable instruction,
and explicit data/control dependencies. Put long instructions in companion
Markdown files. Do not place shell commands, code, source documents, or secrets
in instruction text.

### Executor rules

Declare each executor as exactly `Agent, Executor`, `Human, Executor`, or
`Program, Executor`, then bind it with `step_executor`. Agent configuration may
set `agent_system_prompt`, `allowed_tool`, `max_output_tokens`, `temperature`,
`reasoning_effort`, and `max_turns`; the fixed safety/output protocol remains.
Non-default `model`, `engine`, or `api_base` is rejected because the workspace
AI socket fixes routing.

Agent completion must be a mapping keyed by the exact output Artifact IDs. A
normally completed turn may return one strict JSON object or one standalone
`json` fence; malformed output gets bounded output-only correction, not a Step
rerun. A zero-output Step may submit `{}`; invalid output fails when no declared
Artifact can carry it.

A Human Step's preparation Agent formats a question for `clarify`; it does not
ask the user or turn the question into an Artifact. A zero-output Human is a
gate. Human-backed `foreach` is rejected until iteration identity is supported.

A Program declares exactly one regular workspace file with `program_path`. The
host supplies newline-terminated JSON on stdin containing `instruction` and
`inputs`. Preparation may inspect the workspace and install a toolchain, but
authoritative execution uses structured `compile_program` or `execute_program`.
Fidelity-mode interpreted execution uses the host-built
`[interpreter, declared_script, *logical_argv[1:]]`; no extra flags, scripts, or
arguments are accepted. A launched Program is the sole attempt in fidelity
mode. Captured stdout, stderr, exit status, and launch errors remain
authoritative; the model never authors Program Artifact values.

Fidelity is the default. Only the exact standalone instruction line below
authorizes a pre-launch script or stdin adaptation; no paraphrase or input
content enables it:

```text
Program execution policy: successful completion outranks fidelity.
```

An authorized adaptation must state a concrete reason and must not mutate
consumed input Artifacts. After launch, the first captured attempt remains
authoritative even when it exits nonzero or produces invalid output.

Successful one-output Programs return exact UTF-8 stdout. Multiple outputs
require one strict finite JSON object with exactly the declared keys. Launch,
exit, UTF-8, and output-format failures become a
`$fusion_flow/program_error` value for each output; a failing zero-output
Program raises. A Program Step runs without a shell in a managed process group
or Job Object, with declared Step/workflow timeouts and bounded output.

### Static self-check

Before `run_flow`, confirm that:

- every identity has a supported concept (explicit graph values include
  `Artifact`);
- assertions use `==`, while formulas use comparison operators;
- every operator has its documented arity and supported shape;
- each Step has one supported executor, name, instruction, and explicit
  dependencies;
- the planning contract covers intent, success, interfaces, responsibilities,
  constraint ownership, dependencies, and operational limits;
- the authoring guide was applied: clean-context inputs are explicit,
  independent branches have no artificial barrier, joins have real consumers,
  structured boundaries have contracts, and coverage bounds are visible; and
- no residual or unsupported operator remains.

`check_workflow` performs the same checks before dispatch, including exactly
one workflow block, required instructions and Program paths, executor
validation, graph compilation, and residual rejection.

## Doctor checks

When asked whether a Workflow can run, verify that the source is a readable
workspace-relative `.workflow` or `.g4` file, perform the Static self-check,
and confirm any required resource capacities can be supplied. Report either:

```text
✓ Workflow source is ready for run_flow
```

or:

```text
✗ Workflow source is not ready to run
  Reason: <first source-contract issue>
```

## Capabilities

When asked what this Skill can do, explain that it can author, save, inspect,
reuse, and run user-requested multi-agent Workflows; coordinate Agent, Human,
and Program Steps; run independent branches concurrently; and preserve
intermediate and final Artifacts. State that saved declarations are reused by
slug and that the Skill ships no runnable examples.

## Security and approvals

Agent and Program Steps run in filtered, ephemeral Sessions. Nested workflow
launchers are unavailable to Steps. Human instructions use workspace-confined
read-only access; referenced files cannot escape through absolute paths, `..`,
or symlinks. Refuse remote URLs. Review user-supplied source before execution,
but do not add an approval gate unless the Workflow declares a Human Step.
Program environment preparation is trusted workspace execution, not a host
sandbox.
