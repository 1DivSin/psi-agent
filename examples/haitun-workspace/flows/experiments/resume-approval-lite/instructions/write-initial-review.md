# Task

Write only a batch whose `validation_manifest.status` is `complete` and whose count exactly matches `validated_candidate_assessments.assessments`. Otherwise make no Feishu write and return a blocked result.

The Program-generated `table_fields` object is authoritative. It contains exactly 15 fields. Do not rescore, rewrite evidence, rename a role, or invent missing values.

## Source attachment

- Match each assessment to exactly one `resume_files` item by exact structural equality with `source_ref`, never by candidate name or fuzzy filename.
- Upload that exact source using `feishu_drive_upload` with a neutral remote name `resume.<extension>`.
- Replace the internal `简历附件.source_ref` placeholder with exactly `[{"file_token": "<returned token>"}]` for a new row. Never write a local path or token into a text field or output Artifact.

## Row identity and Human boundary

The AI fingerprint consists of exactly these 12 fields:

`姓名`, `评级`, `学历`, `毕业院校/背景`, `总分`, `匹配岗位`, `匹配点`, `不匹配点`, `面试建议`, `面试建议理由`, `问题库`, `简历摘要`.

For each candidate:

1. Query all exact-name rows and compare all 12 fields locally.
2. If exactly one full fingerprint match exists, reuse it. Do not update any AI field, `备注`, or `初审状态`. If its attachment is missing, update only `简历附件`.
3. If no full fingerprint match exists, upload the source and create one row with all 15 fields. For a new row only, `备注` must be empty and `初审状态` must be `待审批`.
4. Multiple full matches, upload failure, or ambiguous create/update blocks the batch. Do not guess.

Never set `初审状态` to `通过` or `不通过`; never write an approval result, interview result, or hiring decision. Human reviewers make those decisions outside this workflow.

## Outputs

Return one JSON object with exactly these four top-level keys:

```json
{
  "talent_pool_manifest": {
    "schema_version": "lite-1.0",
    "status": "complete|blocked",
    "batch_id": "...",
    "base_url": "safe Feishu base URL",
    "records": [
      {
        "candidate_id": "resume-001",
        "record_id": "exact Feishu record id",
        "created": true,
        "attachment_persisted": true,
        "row_fingerprint": {"姓名": "...", "评级": "..."}
      }
    ],
    "errors": []
  },
  "initial_review_handoff": {
    "schema_version": "lite-1.0",
    "status": "ready|blocked",
    "batch_id": "...",
    "records": [
      {"candidate_id": "resume-001", "record_id": "exact Feishu record id"}
    ],
    "human_owned_fields": ["备注", "初审状态"],
    "allowed_human_decisions": ["通过", "不通过"]
  },
  "initial_review_request": {
    "status": "waiting_for_external_human_review|blocked",
    "instruction": "请在候选人才库逐行核对，并仅由审核人设置初审状态。"
  },
  "user_facing_summary": {
    "schema_version": "1.0",
    "status": "complete|blocked",
    "text": "privacy-safe Chinese summary without ids, paths, tokens, hashes, or raw resume text"
  }
}
```

`row_fingerprint` must contain all 12 AI fields, not only the abbreviated example. Never include credentials, attachment tokens, local paths, source references, raw resume text, or technical IDs in `user_facing_summary.text`.

This Lite handoff is intentionally not the production immutable-file handoff. Do not claim compatibility with `resume-interview-preparation`.
