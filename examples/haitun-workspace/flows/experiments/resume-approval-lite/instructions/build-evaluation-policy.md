# Task

Read `batch_context.scoring_document.content` and `batch_context.role_document.content` and build one evaluation policy used by every candidate in this batch.

The two supplied documents are the only authorities. Do not use general recruiting knowledge, an older local role profile, a resume, or another batch. Do not calculate or invent document hashes.

## Scoring contract

- Extract every stated scoring dimension, its exact maximum, and concise scoring rules grounded in the scoring document.
- Require the dimension maxima to sum to exactly 100. If they do not, return no guessed policy.
- Extract all A-F score ranges. They must cover every integer from 0 through 100 exactly once without gaps or overlap.
- Preserve the meaning of missing evidence: absence is `unknown`, not proof of a negative fact and not permission to award unsupported points.

## Role contract

- Extract every active concrete opening from the role document.
- Copy role name, responsibilities, hard requirements, and preferences faithfully. Do not turn headings, departments, historical candidates, examples, or inactive openings into roles.
- Create a stable `role_key` only from an explicit source ID when present; otherwise use a normalized key derived from the exact role name. Never merge two roles.

## Human boundary

The policy must state all of the following:

- AI scoring and `面试建议` are advisory inputs, not Human approval decisions.
- A new row may initialize `初审状态` only to `待审批`.
- Agents may never set `初审状态` to `通过` or `不通过`.
- Existing `备注` and `初审状态` are Human-owned and must never be overwritten.

## Output

Return exactly one JSON object with `evaluation_policy` as its only top-level key:

```json
{
  "evaluation_policy": {
    "schema_version": "1.0",
    "total_max": 100,
    "dimensions": [
      {
        "name": "exact dimension name",
        "max_score": 20,
        "rules": ["source-grounded scoring rule"]
      }
    ],
    "grade_ranges": [
      {"grade": "A", "min_score": 90, "max_score": 100},
      {"grade": "B", "min_score": 80, "max_score": 89},
      {"grade": "C", "min_score": 70, "max_score": 79},
      {"grade": "D", "min_score": 60, "max_score": 69},
      {"grade": "E", "min_score": 50, "max_score": 59},
      {"grade": "F", "min_score": 0, "max_score": 49}
    ],
    "roles": [
      {
        "role_key": "source role id or normalized exact-name key",
        "name": "exact active role name",
        "status": "active",
        "responsibilities": ["exact or faithful source item"],
        "hard_requirements": ["exact or faithful source item"],
        "preferences": ["exact or faithful source item"]
      }
    ],
    "human_boundary": {
      "ai_is_advisory": true,
      "new_row_initial_status": "待审批",
      "agent_may_approve_or_reject": false,
      "existing_human_fields_immutable": ["备注", "初审状态"]
    }
  }
}
```

The example grade ranges illustrate shape only. Copy the actual ranges from the supplied scoring document. Return valid JSON with no Markdown or prose.
