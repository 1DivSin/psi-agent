# Task

Create or reuse one 13-field initial-review row in the configured `候选人才库` table for every table-writeable assessment in the finalized validation bundle.

## Guard and live contract

- Before any Feishu call, require `validated_candidate_assessments.status=complete`, a non-empty `assessments` list, the validator-generated `assessment_revision`, and a non-empty runtime `feishu_config.talent_pool_table_id`. `constraint_warnings` describe unresolved business content and do not block a row whose mapped fields remain writeable. Otherwise perform no Feishu read or write.
- The verified table has exactly these fields in live order: `姓名`, `评级`, `学历`, `毕业院校/背景`, `总分`, `备注`, `匹配岗位`, `匹配点`, `不匹配点`, `面试建议`, `面试建议理由`, `初审状态`, `简历摘要`.
- `评级` must be A-F; `面试建议` must be `建议面试` or `不建议面试`; `初审状态` is `待审批`, `通过`, or `不通过`.
- Use the real view name `候选人看板` in the manifest and Human handoff.
- Create rows only for `validated_candidate_assessments.assessments`. Copy `failed_candidates` to the manifest as skipped extraction failures; never create guessed rows for them.

## Exact row mapping

Build all 13 visible fields deterministically:

- `姓名`: `candidate_name`;
- `评级`: `grade`;
- `学历`: `education`;
- `毕业院校/背景`: `education_background`;
- `简历摘要`: `resume_summary` 必须是 JSON 字符串数组；写入文本字段前确定性转换为 `"\n".join(resume_summary)`，不得把 JSON 数组文本本身写入表格；
- `总分`: numeric `total_score`;
- `备注`: 新记录留空；
- `匹配岗位`: `matched_role_name`;
- `匹配点`: convert the required non-empty `match_points` list to concise Simplified-Chinese bullet lines in source order, exactly one line per point as `- 要求：…；证据：…`;
- `不匹配点`: convert the required non-empty `mismatch_points` list to concise Simplified-Chinese bullet lines in source order, exactly one line per point as `- 风险：…；依据：…`; preserve cautious evidence-gap wording and never turn an unknown into a definite negative claim;
- `面试建议`: exact `interview_recommendation` enum;
- `面试建议理由`: `interview_recommendation_reason` as concise Chinese text;
- `初审状态`: 新记录固定为 `待审批`.

Do not write hashes, IDs, JSON, raw resume text, contact information, internal keys, or English enum tokens to visible fields.

## 11-field idempotency

The row fingerprint is the canonical ordered object of 11 个 AI 所有字段: `姓名`, `评级`, `学历`, `毕业院校/背景`, `简历摘要`, `总分`, `匹配岗位`, `匹配点`, `不匹配点`, `面试建议`, `面试建议理由`. `备注` 和 `初审状态` 不进入指纹 because Human may change them.

1. Query the configured table by exact `姓名`, follow pagination, normalize the 11 AI fields to visible scalar text/number values, and compare the complete fingerprint locally. Never use name alone as identity.
2. More than one exact fingerprint match blocks the whole batch. One exact match is reused without any update or status reset. Zero exact matches creates exactly one 13-field row.
3. Another row with the same name but a different 11-field fingerprint is a separate assessment revision and must not be overwritten.
4. After every create attempt, query the exact name again and require exactly one matching 11-field fingerprint before reporting success. This recheck is mandatory even when the create response is missing or times out.
5. The current toolset is append-only. Never overwrite `备注`, `初审状态`, or any reused row.

## Output

```json
{
  "talent_pool_manifest": {
    "schema_version": "4.0",
    "status": "complete|blocked",
    "batch_id": "...",
    "base_url": "...",
    "table_id": "exact feishu_config.talent_pool_table_id",
    "view_name": "候选人看板",
    "expected_count": 0,
    "failed_candidates": [],
    "records": [
      {
        "record_id": "...",
        "candidate_id": "...",
        "assessment_revision": "...",
        "row_fingerprint": {
          "姓名": "...",
          "评级": "...",
          "学历": "...",
          "毕业院校/背景": "...",
          "简历摘要": "- ...\n- ...",
          "总分": 0,
          "匹配岗位": "...",
          "匹配点": "...",
          "不匹配点": "...",
          "面试建议": "...",
          "面试建议理由": "..."
        },
        "created": true
      }
    ],
    "errors": []
  }
}
```
