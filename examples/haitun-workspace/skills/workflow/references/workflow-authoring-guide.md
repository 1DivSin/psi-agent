# Workflow Authoring Guide

Use this guide when a user has asked for coordinated work. A workflow makes
responsibilities, information flow, and checks explicit so independent work can
proceed without losing context or provenance.

## Authorization

Use a workflow only when the user explicitly asks for one, asks several agents
or roles to collaborate, requests parallel or staged work, or invokes a saved
workflow. A task that could benefit from extra calls does not by itself grant
permission to spend the additional time or tokens. When coordination would
materially change cost or latency, explain the proposed scale briefly and ask
first.

## Planning contract

Before writing the declaration, identify:

1. the user's goal and a concrete success condition;
2. every external input and the final output;
3. the complete scope, or how a first discovery step will establish it;
4. each step's single responsibility, inputs, executor, and outputs;
5. every information dependency and every genuine join between branches;
6. whether a constraint belongs to the graph, a deterministic program, an
   agent's judgment, or a person;
7. the structure expected at each input and output boundary; and
8. concurrency, timeout, retry, resource, scale, and cost limits.

The graph should own facts that can be decided mechanically. Use a program for
deterministic transformation, an agent for judgment or synthesis, and a human
step only when the user must make a decision during execution.

## Choose the shape from the work

These are composable designs, not fixed templates. Choose the smallest graph
that preserves the actual dependencies.

### Understand

When the subject has distinct parts, let several readers inspect their own
part using the same scope and evidence contract. Each returns observations,
evidence, uncertainty, and open questions. Add a synthesis step only when a
system-wide view is needed.

### Design

When alternatives matter, give independent candidate steps the same brief,
constraints, evidence, and decision criteria. A judge or panel can compare the
candidate artifacts, and a final step can preserve supported ideas and minority
concerns instead of reducing the decision to an unexplained vote.

For a candidate with repeated choices, create a visible decision ledger before
assigning values: map each decision dimension to the items it governs, group
alternatives by compatible family, and record the applicable exclusion,
coverage, capacity, aggregate-objective, and dependency relations. Compare
families globally when the contract or evidence requires one shared choice.
This ledger is domain-neutral and should be passed to both construction and
verification steps. Do not infer a mandatory global choice from hidden scoring
feedback; when the visible inputs do not establish whether alternatives may be
mixed, record the relation as undetermined and preserve the uncertainty.

### Review

Divide the review by independent dimensions. Each branch should inspect,
challenge, and record its own findings as soon as its evidence is ready. Join
the checked branch results only for deduplication, prioritization, or reporting.

### Research

Use multiple modalities and genuinely different discovery modes when the
question warrants them, such as structure-first, content-first,
chronology-first, primary-source-first, or contradiction-first. Record source identity, coverage, unavailable material,
and uncertainty. Finish with a completeness check when omissions matter.

### Migrate or transform

Discover and structure the complete set of sites before changing them. For a
small known set, give each disjoint site its own transform-and-check branch. For
a runtime-sized finite list, use one item-processing step with an explicit
aggregate contract. Parallel mutation is appropriate only when targets are
independent and the instructions make that independence clear.

### Per-item and composite work

Use a finite list expansion for homogeneous items and preserve source order in
the aggregate. Combine designs when a task genuinely contains discovery,
branch-local processing, synthesis, and final checking. Do not add stages only
because the request is large, and do not collapse separable responsibilities
just to make the graph look small.

## Discover scope before fan-out

If the work list is not known, first discover enough context to establish it.
Turn the result into a stable scope record with identities and the context each
worker needs. Pass that record as an explicit artifact. Do not guess a large
static branch list, and do not make every worker rediscover the same scope.
When completeness matters, carry the scope record through checking and final
synthesis so omissions can be distinguished from unavailable evidence.

## Keep contexts clean and data explicit

Each agent step receives a clean step context containing its instruction,
declared inputs, output contract, and allowed tools. It does not inherit a
parent conversation, hidden scratch state,
or an undeclared sibling result. State every required criterion, fact, and
evidence source in the input artifacts. Avoid phrases such as "as above".

Artifacts are the workflow's memory bus. Use structured contracts and schemas
at boundaries that need machine-checkable data, and require each step to produce exactly its
declared outputs. Pass source material as artifacts instead of embedding large
documents in instructions. Every input Artifact should be explicitly consumed,
and every output Artifact should be explicitly produced. Keep mutable shared
state out of parallel branches.

## Preserve branch locality

An independent branch may continue through a branch-local pipeline, from
discovery to its own transformation and check, without waiting for unrelated branches. Add a join only when the next
step needs all of the listed artifacts. A step that merely runs after another
through ordering does not receive the earlier result unless that result is an
explicit input.

## Scale deliberately and avoid silent caps

Use concurrency for a real user, service, memory, rate, mutation, or cost
constraint. Avoid a silent cap: make limits visible in the input, contract, instruction, or a
coverage record. Never silently sample, truncate, rank, or skip requested work.
If a bound is necessary, record both processed and omitted items and the reason.
Use a finite list for repeated work; use explicit branches for a few semantic
alternatives.

## Add checks according to risk

Quality steps are optional and should follow the task's risk, verifiability,
requested coverage, and user-stated cost or latency limits.

- An adversarial checker tries to refute a candidate with the same contract and
  evidence available to its builder. It records concrete counterevidence and
  uncertainty rather than merely confirming the result.
- When a candidate contains multiple related items, include a global relational
  lens: check applicable uniqueness, exclusions, temporal or spatial
  consistency, aggregate capacities or totals, cross-item dependencies,
  coverage, and provenance. Apply a relation only when the visible contract or
  evidence establishes it; otherwise record the check as undetermined rather
  than importing a hidden score rule.
- Distinct checking lenses may cover factual support, consistency, boundaries,
  reproducibility, safety, performance, or contract compliance. Use different
  lenses when the candidate has more than one independent way to fail. Each lens must
  state what would disprove the candidate.
- A candidate panel is useful when several approaches deserve independent
  comparison. Judges receive all candidates and the same explicit criteria.
- A completeness critic checks scope coverage, evidence, unresolved conflict,
  unavailable sources, and missing output fields. Any repair round must be
  finite and declared in the graph.

Only successful checker outputs enter an adjudication step. An executor failure
is a workflow failure, not a missing vote. If a verdict is uncertain, apply the
declared decision rule and preserve that uncertainty in the output.

## Failure and follow-up

Retries are for declared executor, transport, or timeout failures and reuse the
same inputs and instruction. They are not a semantic repair loop or a score
gate. A later workflow may consume an earlier result when the user explicitly
authorizes that next phase; do not hide a new graph round inside an agent step.

## Final review

Before running, confirm that the graph has one clear output, every step has a
bounded responsibility, all information is carried by declared artifacts, every
join is real, all requested scope is represented, limits are visible, and every
optional check is justified by risk or coverage. If the design depends on a
domain-specific shortcut, remove it and return to the general contract.
