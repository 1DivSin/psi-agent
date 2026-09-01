# Dynamic Workflow Authoring for FusionFlow G4

> Adapted from the Claude Code v2.1.248 prompts extracted in Piebald AI's
> `claude-code-system-prompts` repository: `Tool Description: Workflow` and
> `Skill: Workflow authoring reference`, at commit
> `738bccbb279db7024b9a41f921b473d31ddc421a`. This is a FusionFlow-specific
> adaptation, not a verbatim copy. The source repository carries the MIT notice
> reproduced in [PIEBALD_LICENSE.md](PIEBALD_LICENSE.md); that notice records the
> repository's licensing statement, while the repository describes the
> underlying prompt text as extracted from Claude Code.

## Purpose and authority

Author a deterministic Step-Artifact graph that holds the plan for coordinated
work. The graph, rather than a coordinator Agent's evolving conversation,
defines what fans out, what each branch receives, what may run concurrently,
what must wait, what verifies, and what synthesizes.

Deterministic means that the checked graph fixes dependency scheduling,
Artifact transport, foreach expansion and source-order collection, declared
retry limits, resource admission, and output boundaries. It does not mean that
an Agent's generated content is deterministic. Make model judgment inspectable
by giving it explicit inputs, bounded responsibilities, structured output
contracts, and independent checks.

This reference is authoring policy for FusionFlow G4. It does not add syntax,
operators, execution modes, or runner capabilities. Before emitting source,
read `../grammar/FusionFlow.g4` in full and use it as the sole surface-syntax
authority. The Workflow Skill and runner remain authoritative for executable
backend constraints and failure behavior.

## Explicit orchestration authorization

Apply this authoring reference only after the user has explicitly opted into a
Workflow or multi-agent orchestration. A task that could merely benefit from
parallelism, multiple perspectives, or several model calls does not authorize
the extra execution and token cost. Direct requests to use a workflow, fan out
agents, coordinate several agents or roles, author or run a G4 declaration, or
invoke a saved workflow do count. A user-invoked Skill may also provide that
authorization when its own instructions explicitly require Workflow.

Without explicit authorization, follow the parent system's ordinary task and
subagent path. If Workflow would materially change cost or scale, briefly
describe the proposed orchestration and ask before authoring or running it.

## Authoring contract

Before writing source, form an internal contract that names:

1. the user's goal and a concrete success condition;
2. all external input Artifacts and final output Artifacts;
3. the authoritative scope or work list, including how it is discovered when
   the user has not already supplied it;
4. each Step's one responsibility, executor, consumed Artifacts, and produced
   Artifacts;
5. every information dependency and every genuine cross-branch join;
6. the owner of each constraint: graph structure, deterministic Program logic,
   Agent judgment, or Human input;
7. structured contracts required at Agent, Program, Human, foreach, and final
   output boundaries; and
8. concurrency, timeout, retry, resource, scale, and user-stated cost limits.

Use the graph for mechanically decidable structure. Use a Program Step for
deterministic computation when an appropriate workspace-local program exists.
Use an Agent Step for judgment and synthesis, with the criteria named in its
instruction. Use a Human Step only when the workflow genuinely requires user
input or approval during execution.

## Scout first when the work list is not yet known

The right construction approach is often hybrid when the task's real scope is
not yet known: scout broadly enough to discover it, then orchestrate targeted
work over the resulting list. If the user already supplied a complete, finite
scope, use it directly; do not add a discovery Step or scope manifest merely to
fit this pattern.

1. Scout only enough context to discover the task's actual shape. Identify the
   relevant components, evidence channels, change surfaces, records, or other
   natural work units. Do not spend the whole task doing inline work that
   belongs in the graph.
2. Turn the discovered scope into an explicit work list or scope manifest. It
   must record stable identities and enough context for downstream Steps to
   know what is in scope. Do not rely on a prose promise that the scope was
   exhaustive.
3. Choose how that list enters the graph:
   - If the parent already has a finite work list, pass it as an input Artifact
     with an executable schema.
   - If discovery itself needs coordinated work, add a discovery Step that
     produces a structured List Artifact, then bind a downstream foreach Step
     with `foreach_item`.
   - If there are a few known semantic branches rather than a runtime-sized
     list, author explicit branch Steps. This preserves branch-local pipelines
     and makes each responsibility visible.
4. When completeness matters, preserve the scope manifest through verification
   and synthesis so a final critic can compare intended coverage with actual
   coverage.

Do not guess a large static branch list before inspecting the task. Conversely,
do not put discovery into every worker independently when one shared scope
Artifact can establish consistent coverage.

## Common workflow shapes

These are composable shapes, not templates that override the user's
dependencies.

### Understand

Use parallel readers or analysts over distinct subsystems, source groups, or
questions, each consuming the same scope contract plus only the evidence it
needs. Require structured maps that identify observations, evidence,
uncertainty, and unresolved questions. A synthesis Step joins the maps only if
it truly needs a system-wide view.

Typical graph:

```text
scope + evidence_a -> map_a ----> synthesis -> system_map
scope + evidence_b -> map_b ----/
scope + evidence_c -> map_c ---/
```

If `map_a` has its own verifier, connect `map_a -> verify_a` directly. Do not
wait for `map_b` or `map_c` merely because all maps belong to an Understand
phase.

### Design

Give several candidate Steps the same explicit brief, constraints, evidence,
and decision criteria. Keep their contexts independent so one proposal does
not anchor the others. Use one or more judge Steps with deliberately different
lenses, then synthesize a final design from the candidate and judgment
Artifacts. Preserve minority concerns and unsupported assumptions; a vote is
not evidence by itself.

Typical graph:

```text
brief + criteria -> candidate_a --\
brief + criteria -> candidate_b ----> judge panel -> synthesis -> final_design
brief + criteria -> candidate_c --/
```

The judge panel is a real join because comparison requires all candidates.

### Review

Fan out across independent review dimensions. Each branch should move from
discovery to adversarial verification as soon as its own candidate findings are
ready. Join only the verified branch outputs for deduplication, prioritization,
or final reporting.

Typical graph:

```text
subject + contract -> review_a -> refute_a --\
subject + contract -> review_b -> refute_b ----> synthesize -> critic -> final
subject + contract -> review_c -> refute_c --/
```

Do not create `all_reviews -> all_verifiers` when each verifier needs only one
review. That stage barrier wastes ready branches and weakens provenance.

### Research

Start from a question, scope manifest, source requirements, and evidence
contract. Run a multi-modal sweep in which branches use genuinely different
discovery modes, such as structure-first, content-first, entity-first,
chronology-first, primary-source-first, or contradiction-first. Deep-read and
validate results inside each branch before cross-branch synthesis. End with a
completeness critic that checks the scope manifest, source coverage,
unverified claims, conflicting evidence, and unread material.

Different modalities must differ in method or evidence surface, not only in
prompt wording. Record source identity and provenance in structured Artifacts.

### Migrate

Discover and structure the complete set of transformation sites first. For a
small, known set of disjoint sites, build one branch-local pipeline per site:

```text
site_a + contract -> transform_a -> verify_a --\
site_b + contract -> transform_b -> verify_b ----> integration_check -> result
site_c + contract -> transform_c -> verify_c --/
```

For a runtime-sized List, use `foreach_item`. Because one foreach Step
materializes its aggregate output only after all iterations finish, either:

- make each iteration perform one bounded transform-and-local-check operation;
  or
- accept the real aggregate boundary between a transformation foreach and a
  later verification foreach.

Never claim that separate foreach stages stream item-by-item when the runtime
does not provide that behavior. Parallel mutation is admissible only when
targets are disjoint and instructions prohibit cross-target edits. Otherwise
serialize with dependencies or resource requirements. FusionFlow G4 does not
provide the upstream workflow's per-Agent worktree-isolation option.

## Sequence separately authorized workflows at the parent boundary

For a large program of work whose next phase depends on judgment about the
current result, prefer several well-scoped top-level workflows across parent
turns. The parent Session reads each result, exposes it to the user, and decides
whether another explicitly authorized workflow is warranted. This keeps the
parent in the loop between understanding, design, implementation, or review.

Do not translate that pattern into a nested Workflow call: an Agent Step cannot
launch `run_flow`. For one Authoring Mode request, follow the Workflow Skill's
one-source, one-initial-run contract and encode all already-decided phases in
one acyclic graph. A later top-level run may receive an earlier result only
through its declared workflow inputs.

## Clean Agent Steps and explicit Artifact transport

Treat every Agent-backed Step as a clean invocation with a clean Step context.
It receives its resolved instruction, declared consumed Artifacts, output
contract, and allowed tool surface. It does not inherit the parent
conversation, hidden scratch state, undeclared sibling outputs, or a preceding
Agent's context.

For every Agent Step:

- State one bounded objective and the exact responsibility it owns.
- Explain how to interpret every consumed Artifact by its declared identity.
- Include every required requirement, criterion, candidate, prior result, and
  evidence source through `consumes`; never write "as discussed above" or rely
  on declaration order.
- Transport source material as Artifacts rather than embedding large content
  in `step_instruction` or `agent_system_prompt`.
- Produce all and only the declared output Artifact IDs. Downstream Steps must
  consume those outputs explicitly.
- Keep mutable cross-branch state out of Agent tools. Communicate through
  immutable, finite JSON-compatible Artifact values.
- Narrow tools with supported `allowed_tool` declarations when appropriate.
  Tool availability is not a substitute for declared inputs.

Artifact edges are the workflow's memory bus. Use explicit Artifact dataflow:
if Step B needs something Step A learned, Step A must produce it and Step B
must consume it. A Step that merely runs after another Step through
`depends_on` does not receive the predecessor's result.

### Structured contracts

For each structured Artifact contract, prefer an executable
`@artifact ... = {...}` JSON Schema directive at the machine-readable
boundary. A useful contract specifies:

- the top-level type and a non-empty description;
- required object properties and whether extra properties are allowed;
- array item structure and meaningful size constraints;
- stable identities and provenance fields;
- evidence, uncertainty, status, and omission fields when the task needs them;
  and
- exact enums or bounds only when they come from the task contract.

Use descriptions to tell an Agent what each field means; use supported schema
keywords to make the runner enforce structure. Do not ask downstream Agents to
recover a protocol from Markdown headings, acknowledgements, prose wrappers,
or delimiter conventions when a structured Artifact can carry it directly.

Contracts must be task-derived. Do not invent a fixed score, threshold,
category set, or acceptance rule merely to make an output look structured.

## Dependency-driven pipelines and true joins

FusionFlow has no `pipeline()` or `parallel()` authoring functions. Their useful
semantics arise from graph dependencies:

- A pipeline is an Artifact chain: `produces(step_a)` supplies an Artifact in
  `consumes(step_b)`.
- Fan-out is several ready Steps consuming the same input Artifact.
- A branch-local pipeline advances whenever that branch's required Artifact is
  ready, regardless of sibling progress.
- A join is a consumer that lists outputs from several branches because its
  task genuinely needs cross-branch context.
- Ordering without data transport uses `depends_on(step, predecessor)`.
  Declaration order never schedules work.

Default to branch-local pipelines. Add a cross-branch join only when the next
operation requires the entire prior result set, for example:

- deduplication across all findings;
- comparison or ranking across all candidates;
- an integration decision using all branch results;
- a completeness check against total coverage; or
- an explicit early decision based on a total count.

The following do not justify a barrier:

- the stages have different names;
- grouping by phase looks cleaner;
- a map, filter, or formatting operation could be done inside one branch;
- the author wants one large intermediate summary but no downstream Step
  consumes that summary; or
- every branch performs the same sequence independently.

`independent(step)` is only a scheduling hint. It does not erase Artifact or
`depends_on` dependencies. Named `if` selection is eager value selection: all
candidate producers run, and the selector waits for its candidate Artifacts.
It is not lazy branching and must not be used to pretend that an unselected
branch will be skipped.

## Concurrency, resources, and scale

Ready Steps and foreach iterations run concurrently subject to the workflow's
declared `max_concurrency`, resource availability, and host execution
conditions. Author operational policy deliberately:

- Use `max_concurrency(workflow)` only for a real user, service, memory, rate,
  mutation, or cost constraint. Do not copy an arbitrary cap from an unrelated
  runtime.
- Use `resource_requirement(step, resource)` for scarce named capacity. The G4
  source declares demand; the `run_flow` caller supplies capacities or concrete
  instance IDs. Never put host capacity or credentials into the source.
- Use `step_timeout` and `workflow_timeout` for actual latency requirements,
  not as guessed quality controls.
- A foreach source must be a finite JSON List. Iterations are parallel by
  default and the runtime has no separate per-foreach concurrency setting.
- Known bounded semantic branches should be explicit when branch-local
  pipelines matter. Runtime-sized homogeneous work belongs in foreach.

Scale without a silent cap to the user's requested coverage and the discovered
work list. Never silently sample, truncate, keep only a top-N subset, collapse
distinct items, or skip a modality. If a bound is required, make it visible in
an input, schema, instruction, or output coverage report. Record both what was
processed and what was omitted, with the reason. A schema `maxItems` rejects an
oversized input; it does not authorize silently taking the first items.

Do not transplant Claude Code's fixed concurrency formula, per-call item cap,
or total Agent-count backstop. FusionFlow's actual limits are its graph,
declared policy, supplied resources, contracts, and host runner. If those
cannot safely cover the requested scale, report the constraint instead of
claiming exhaustive coverage.

## Quality patterns

Compose these patterns from explicit Steps and Artifacts. They are optional,
general quality mechanisms, not domain checklists or hidden evaluation loops.
Select them according to the task's risk, verifiability, requested coverage,
and user-stated cost or latency limits. A quick, low-risk workflow may need no
extra verifier or only one; a comprehensive or high-stakes workflow may warrant
several independent checks and a final critic.

### Adversarial refutation

When adversarial verification is warranted, give an independent verifier each
claim, finding, or candidate selected for that pass, together with the original
task contract and the same source evidence available to the builder. Instruct
the verifier to try to **REFUTE** the candidate, not to confirm it. Require
concrete counterevidence, reproduced reasoning, and an explicit uncertainty
state.

For higher-stakes work, use several independent refuters with clean contexts.
The conservative upstream pattern treats an uncertain returned verdict as
`refuted` and lets a candidate survive only when an explicit majority of the
declared panel returns `not_refuted`. State that rule in the verdict Artifact
contract and adjudication instruction rather than silently changing it. Use a
deterministic Program tally when an appropriate workspace-local program exists;
otherwise make the threshold an explicit responsibility of an adjudication
Agent and report that its application is model-judged rather than mechanically
enforced. If the user's task contract selects another decision rule, state and
apply that rule instead.

Only successfully returned verdict Artifacts can be adjudicated. A verifier
Step that terminates with an executor or validation failure stops the G4
workflow under the failure policy below; it does not become a missing value or
a vote. Do not confuse that runtime failure with a valid verdict whose explicit
state is uncertain or refuted.

### Diverse verification lenses

When a candidate can fail in more than one independent way, assign distinct
lenses that follow from the task, such as factual support, internal consistency,
boundary conditions, reproducibility, safety, performance, or contract
compliance. Each lens must say what evidence would refute the candidate. Do not
clone the same prompt under different labels merely to create redundancy.

### Judge panel

Generate independent candidates from meaningfully different approaches. Give
judges the same explicit criteria and all candidate Artifacts. Separate
generation, judging, and final synthesis so the synthesizer can preserve the
best supported parts of losing candidates and surface unresolved disagreement.
When scoring is not mechanically defined, require rationale and evidence
rather than unexplained numbers.

### Multi-modal sweep

Partition discovery by genuinely different search modes or evidence surfaces.
Each branch records what it searched, what it could not access, and what it
found. Deep-read or validate branch findings before synthesis. The final
coverage Artifact must let a critic distinguish "not found" from "not
searched" and "source unavailable."

### Completeness critic

Add a fresh critic after the main synthesis when completeness matters. It
consumes the original scope manifest, task contract, evidence inventory,
branch coverage, and candidate result. Ask:

- Which declared work items or modalities were not processed?
- Which claims lack traceable evidence or independent verification?
- Which source was unavailable or unread?
- Which conflicts or uncertainty were hidden by synthesis?
- Which requested output element is missing or malformed?

The critic may feed one explicit repair Step or a predeclared foreach over a
structured `missing_items` Artifact. This is a fixed acyclic critic-to-repair
round. It must not be described as an unbounded "continue until complete"
loop.

### Fixed-point approximation without dynamic loops

FusionFlow cannot spawn a new graph round until no new findings appear. When a
task needs stronger convergence, author one or a finite number of explicit,
acyclic discovery -> deduplication -> refutation -> critic -> repair layers.
State the bound and residual risk. Do not claim loop-until-dry semantics.

Carry a cumulative `seen_candidates` Artifact through those explicit layers.
Each layer consumes the prior cumulative set and produces a new immutable set
for the next layer. Add every newly encountered candidate before adjudication,
including candidates later refuted or rejected, and deduplicate later discovery
against everything seen rather than only against confirmed results. Otherwise a
rejected candidate can recur in the next fixed round and consume the same
verification work again.

## Failure, retry, and resume semantics

Map policy to the runtime exactly:

- `max_attempts(step)` defaults to one attempt. A higher value creates a fresh
  dispatch after an ordinary executor, timeout, or output-validation failure,
  using the same declared instruction and inputs. It is not a workflow loop,
  semantic repair policy, post-hoc quality retry, or acceptance gate.
- After a Step exhausts its ordinary attempts, the workflow fails. Foreach
  siblings may finish before their failures are reported together, but failed
  Steps and iterations never become upstream-style `null` results that a later
  Step can filter out.
- Agent output correction occurs inside one dispatch. A normally completed
  invalid response may receive two output-only correction turns; after the
  third invalid response, only the runner's narrowly validated trailing-comma
  repair may be accepted. Every other malformed result raises without
  publishing an Artifact. This is not semantic repair or a Step rerun;
  graph-level `max_attempts` applies only after the dispatch raises.
- Only a declared Human wait is resumable. It suspends the run through the
  runner's control envelope and continues through `run_flow_resume`; it is not
  success, failure, or a retry. Exact Program fidelity, foreach aggregation,
  checkpoint, cancellation, and resource behavior remain defined in the
  Workflow Skill and runner rather than duplicated here.

## Non-portable upstream boundaries

The Piebald prompts describe a different Claude Code runtime. Preserve their
construction principles, but do not claim or emulate these unavailable
features:

### JavaScript workflow API

FusionFlow source is declarative G4, not JavaScript or TypeScript. Do not emit
`export const meta`, `agent()`, `pipeline()`, `parallel()`, `phase()`, `log()`,
`args`, `budget`, `workflow()`, promises, callbacks, imports, filesystem calls,
or Node APIs. There is no inline JS script, script-path reinvocation, saved JS
workflow registry, or nested workflow call. Agent Steps cannot launch
`run_flow`; only the parent Session starts the authored G4 workflow.

### Claude-specific permission modes

There is no `ultracode` mode, system-reminder, or automatic translation of a
token-spend directive into standing permission. Preserve the portable explicit
opt-in rule above, then follow this Workflow Skill's activation, authoring,
user-notice, and execution rules. Do not invent a Claude-specific permission
token or UI state.

### Background execution and progress UI

`run_flow` does not immediately return a background task ID, emit
`<task-notification>`, or provide `/workflows`, phases, progress groups, or a
live progress tree. A non-Human run completes inside its initial `run_flow`
call. A Human run returns only at a declared Human frontier. Do not invent
polling, background workers, task journals, or node-level progress claims.

### General resume and prefix caching

There is no `resumeFromRunId`, cached longest-unchanged-prefix resume,
script-edit resume, `journal.jsonl` recovery contract, or arbitrary
continuation of a completed or failed non-Human run. `run_flow_resume` is
exclusively for the exact active Human request returned by this runner, with
its exact run ID, request ID, unchanged workflow definition, and validated
checkpoint. Successful foreach iteration checkpoints may be reused only as
part of that supported Human wait/resume lifecycle.

### Shared token budget and dynamic scaling

There is no workflow-global `budget.total`, `spent()`, or `remaining()`, shared
hard ceiling derived from a token-spend directive, or runtime formula that
scales an Agent fleet from remaining tokens. `max_output_tokens` is an
individual Agent configuration, not a shared workflow budget. Translate
user-stated cost limits into an explicit static graph, input-size contract,
concurrency policy, and plain-language cost notice; do not claim exact
shared-token enforcement.

### Dynamic loops and dynamic agent creation

G4 has no `while`, `for`, mutable `Set`, runtime callback, dynamic Agent
spawning, recursive workflow, or loop-until-dry primitive. `foreach_item`
expands one statically declared Step over one finite runtime List. It cannot
create new Step definitions, nest another foreach dynamically, or feed a cycle;
the graph rejects dependency cycles. Named `if` is eager Artifact selection,
not conditional execution. Use an explicit acyclic graph and report any fixed
round bound.

### Isolation, model routing, tools, and terminal errors

There is no `isolation: "worktree"`, `agentType`, inherited MCP `ToolSearch`, or
upstream per-call model/effort option object. Use only the executor and Agent
operators actually accepted by the grammar and runner. The current workspace
socket rejects non-default model, engine, and API-base routing instead of
silently honoring it. Terminal Agent errors are failures, not `null` values to
filter from a result array.

### Upstream concurrency and backstops

Do not assume Claude Code's fixed concurrency formula, total Agent-count
backstop, or per-call item limit. Do not imitate those caps silently. Use
FusionFlow's declared `max_concurrency`, resource requirements, finite foreach
input, and actual runner diagnostics.

## Final author audit

Before finishing the G4 source, verify all of the following:

- The graph, not an Agent conversation, holds the complete plan.
- If the scope was not already explicit, it was scouted and represented by a
  work list or manifest.
- Every Agent Step is understandable from its instruction and consumed
  Artifacts alone.
- Every cross-Step fact travels through a named Artifact with an appropriate
  contract.
- Independent branches advance locally without an artificial phase barrier.
- Every fan-in exists because its consumer needs all listed branch results.
- Concurrency, resources, timeouts, attempts, and cost constraints come from
  real requirements and map to supported operators.
- Coverage is neither silently sampled nor overstated.
- When verification is warranted, it tries to refute and has no privileged
  evidence; distinct lenses are used only when the candidate has distinct
  task-derived failure modes.
- Any finite convergence approximation carries a cumulative seen set that
  includes rejected as well as accepted candidates.
- Open-ended alternatives use independent candidates and an explicit judging
  and synthesis boundary.
- Multi-modal discovery records searched, unsearched, and unavailable scope.
- A completeness critic compares the result with the original scope when
  completeness matters.
- Retry and Human resume behavior match the runner's actual semantics.
- No JavaScript, ultracode, background, general resume, shared budget, dynamic
  loop, nested workflow, worktree isolation, or null-failure behavior has been
  implied.
