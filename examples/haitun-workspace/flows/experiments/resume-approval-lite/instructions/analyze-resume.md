# Task

Assess exactly one `resume_file` against the fixed `evaluation_policy`. `batch_context` supplies the batch ID and source documents only; the policy is the scoring and role contract for this step.

## Read the source

`resume_file` is either a path string or an object containing a path. Preserve the complete input value exactly as `source_ref`.

- PDF: call `read_pdf` with all pages and `max_pages=100`.
- DOCX: call `read_document` with a sufficiently large character limit.
- Markdown or text: call `read` without truncation.
- If the file cannot be fully read, return `status=extraction_failed`; do not invent an assessment.

Do not use the filename as evidence about the candidate. Exclude phone, email, exact address, ID number, age, gender, marital/family status, ethnicity, religion, health, or disability from every output field.

## Facts and evidence

- Every candidate statement must be supported by the resume. Copy a concise evidence excerpt and identify its page or section in `location`.
- `knowledge=known` means the cited resume evidence directly supports the statement.
- `knowledge=unknown` means the resume is silent or insufficient; phrase it as “简历未体现……，需核实”.
- `knowledge=inference` is allowed only for an explicitly labelled tentative observation. It cannot support a positive match, a score, or a definitive negative claim.
- Never silently complete dates, employers, degrees, institutions, skills, results, responsibility scope, or location willingness.

## Score and role match

- Emit exactly one `dimension_scores` item for every policy dimension, in policy order. Copy each dimension name and maximum exactly.
- Award points only for resume-supported evidence. `score` must be an integer from 0 through `max_score`.
- `total_score` is the exact sum. `grade` comes from the policy range containing that total.
- Evaluate every active role, then select exactly one policy role with the strongest supported match. Copy its key and name exactly.
- Every positive `match_points` item must use `knowledge=known` and concrete resume evidence.
- `mismatch_points` may contain direct contrary evidence (`known`) or a material evidence gap (`unknown`). Missing evidence must not be written as “不具备”.
- `面试建议` remains an AI recommendation. It is not `初审状态` and cannot approve or reject a candidate.

## Business fields

- `education` is exactly one of `博士|硕士|本科|专科|高中及以下|unknown`.
- `education_background` contains only stage and institution, such as `本科：合肥工业大学；硕士：中国科学技术大学`; otherwise `unknown`.
- `resume_summary` contains 1-5 evidence-backed highlight strings, each starting with `- `.
- Produce 3-6 `verification_questions` covering at least `真实性核验` and `岗位匹配`; include `风险澄清` when there is an unknown or risk. Each question must cite one exact evidence anchor.

## Output

Return exactly one JSON object with `draft_assessments` as its only top-level key:

```json
{
  "draft_assessments": {
    "schema_version": "1.0",
    "status": "assessed",
    "batch_id": "exact batch_context.batch_id",
    "source_ref": "exact resume_file value; an object remains an object",
    "candidate_name": "resume-supported name or unknown",
    "dimension_scores": [
      {
        "dimension": "exact policy dimension",
        "score": 0,
        "max_score": 20,
        "evidence": [
          {
            "claim": "fact used for this score",
            "resume_quote": "concise source text",
            "location": "page or section",
            "knowledge": "known"
          }
        ]
      }
    ],
    "total_score": 0,
    "grade": "A|B|C|D|E|F",
    "education": "博士|硕士|本科|专科|高中及以下|unknown",
    "education_background": "stage and institution only, or unknown",
    "resume_summary": ["- evidence-backed highlight"],
    "matched_role_key": "exact policy role key",
    "matched_role_name": "exact policy role name",
    "match_points": [
      {
        "requirement": "exact selected-role requirement",
        "evidence": "concise resume evidence",
        "location": "page or section",
        "knowledge": "known"
      }
    ],
    "mismatch_points": [
      {
        "requirement": "exact selected-role requirement",
        "evidence": "direct evidence or cautious evidence gap",
        "location": "page, section, or resume-wide",
        "knowledge": "known|unknown"
      }
    ],
    "interview_recommendation": "建议面试|不建议面试",
    "interview_recommendation_reason": "evidence-based advisory reason",
    "verification_questions": [
      {
        "category": "真实性核验|岗位匹配|风险澄清",
        "question": "complete evidence-bound question",
        "evidence_anchor": "exact evidence or requirement text"
      }
    ]
  }
}
```

For `extraction_failed`, preserve `batch_id` and `source_ref`, set `candidate_name=unknown`, and add a concise `failure` object. Do not emit scores or table fields. Return valid JSON with no Markdown or prose.
