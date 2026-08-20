# Task

Independently review one `draft_assessment`. This is a substantive second read, not an approval form.

1. Resolve the exact `source_ref` from the draft and reread the complete original resume with `read_pdf`, `read_document`, or `read` as appropriate.
2. Recheck the draft against the raw scoring and role documents in `batch_context` and the normalized `evaluation_policy`.
3. Correct every error directly in the returned assessment. There is no later repair round.
4. If the resume cannot be read or a safe correction cannot be made, return `status=quality_blocked`; never mark a failed check as passed.

## Five mandatory checks

### factual_accuracy

- Verify every name, education entry, summary item, match/mismatch statement, score justification, and recommendation reason against the resume.
- Reject misreads, mixed-candidate facts, filename-derived facts, silent completion, and unlabelled inference.

### standard_compliance

- Verify one score for every policy dimension, the exact maximum, integer ranges, total arithmetic, grade range, active role identity, and requirement match.
- A score must be supported by `knowledge=known` evidence. Unknown or inferred content cannot earn points.

### evidence_traceability

- Verify each material statement has a concise quote and a page/section location.
- Positive matches must be `known`. Unknowns must use cautious wording. Inferences must be explicit and cannot become facts.

### business_completeness

- Verify all data needed for the 15-field talent row: 12 AI fields, one source attachment reference, empty new-row `备注`, and `初审状态=待审批`.
- Verify enums, field types, 1-5 summary lines, and 3-6 evidence-bound questions.

### human_boundary

- `面试建议` is advisory only.
- Remove any claim that a Human approved/rejected the candidate unless this workflow received an explicit Human decision, which it does not.
- Do not output or change `备注`, `初审状态`, `审批状态`, or a final hiring decision.

## Output

Return exactly one JSON object with `reviewed_assessments` as its only top-level key. The assessment fields are the same as the assessed draft, corrected as needed, plus exactly this object:

```json
{
  "quality_checks": {
    "factual_accuracy": {"passed": true, "notes": "what was checked or corrected"},
    "standard_compliance": {"passed": true, "notes": "what was checked or corrected"},
    "evidence_traceability": {"passed": true, "notes": "what was checked or corrected"},
    "business_completeness": {"passed": true, "notes": "what was checked or corrected"},
    "human_boundary": {"passed": true, "notes": "what was checked or corrected"}
  }
}
```

All five keys are required. `passed=true` is allowed only after the corrected output satisfies that check. Preserve `batch_id` and `source_ref` exactly. Return valid JSON with no Markdown or prose.
