"""One consolidated deterministic gate for the Lite resume workflow."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

_GRADES = tuple("ABCDEF")
_EDUCATION = {"博士", "硕士", "本科", "专科", "高中及以下", "unknown"}
_RECOMMENDATIONS = {"建议面试", "不建议面试"}
_QUESTION_CATEGORIES = {"真实性核验", "岗位匹配", "风险澄清"}
_QUALITY_CHECKS = (
    "factual_accuracy",
    "standard_compliance",
    "evidence_traceability",
    "business_completeness",
    "human_boundary",
)
_AI_FIELDS = (
    "姓名",
    "评级",
    "学历",
    "毕业院校/背景",
    "总分",
    "匹配岗位",
    "匹配点",
    "不匹配点",
    "面试建议",
    "面试建议理由",
    "问题库",
    "简历摘要",
)
_ALL_FIELDS = (
    "姓名",
    "简历附件",
    "评级",
    "学历",
    "毕业院校/背景",
    "总分",
    "备注",
    "匹配岗位",
    "匹配点",
    "不匹配点",
    "面试建议",
    "面试建议理由",
    "问题库",
    "初审状态",
    "简历摘要",
)
_FORBIDDEN_DECISION_KEYS = {"初审状态", "审批状态", "审核结果", "human_decision", "final_decision"}
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_IDENTITY = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
_PROTECTED = re.compile(
    r"(?:年龄|出生日期|生日|性别|婚姻|已婚|未婚|生育|怀孕|民族|宗教|信仰|"
    r"健康状况|病史|残疾|残障|家庭住址|户籍|籍贯)",
    re.IGNORECASE,
)
_UNKNOWN_WORDING = re.compile(r"(?:未体现|未提及|未说明|未知|unknown|证据不足)", re.IGNORECASE)
_CAUTIOUS_WORDING = re.compile(r"(?:需核实|需确认|待核实|待确认|需要核实|需要确认)")


def _decode(value: Any, wrapper: str | None = None) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        try:
            value = json.loads(text)
        except TypeError, ValueError:
            return value
    if wrapper and isinstance(value, dict) and set(value) == {wrapper}:
        return value[wrapper]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be non-empty text")
    return value.strip()


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{path} must be an integer")
    return value


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(_FORBIDDEN_DECISION_KEYS.intersection(value)) or any(
            _contains_forbidden_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _private_text(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in (_EMAIL, _PHONE, _IDENTITY, _PROTECTED))
    if isinstance(value, Mapping):
        return any(_private_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_private_text(item) for item in value)
    return False


def _validate_policy(value: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, str]]:
    policy = _decode(value, "evaluation_policy")
    if not isinstance(policy, dict) or policy.get("schema_version") != "1.0":
        raise ValueError("evaluation_policy must use schema 1.0")
    if policy.get("total_max") != 100:
        raise ValueError("evaluation_policy.total_max must equal 100")

    dimensions = policy.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ValueError("evaluation_policy.dimensions must be a non-empty list")
    dimension_map: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(dimensions):
        path = f"evaluation_policy.dimensions[{index}]"
        if not isinstance(item, dict):
            raise TypeError(f"{path} must be an object")
        name = _text(item.get("name"), f"{path}.name")
        maximum = _integer(item.get("max_score"), f"{path}.max_score")
        if maximum <= 0 or name in dimension_map:
            raise ValueError(f"{path} has an invalid name or maximum")
        rules = item.get("rules")
        if (
            not isinstance(rules, list)
            or not rules
            or not all(isinstance(rule, str) and rule.strip() for rule in rules)
        ):
            raise ValueError(f"{path}.rules must contain source-grounded text")
        dimension_map[name] = item
    if sum(item["max_score"] for item in dimension_map.values()) != 100:
        raise ValueError("policy dimension maxima must sum to 100")

    ranges = policy.get("grade_ranges")
    if not isinstance(ranges, list) or len(ranges) != 6:
        raise ValueError("evaluation_policy must define six grade ranges")
    grade_for_score: dict[str, str] = {}
    seen_grades: set[str] = set()
    for index, item in enumerate(ranges):
        path = f"evaluation_policy.grade_ranges[{index}]"
        if not isinstance(item, dict) or item.get("grade") not in _GRADES:
            raise ValueError(f"{path} is invalid")
        grade = item["grade"]
        if grade in seen_grades:
            raise ValueError("evaluation_policy contains a duplicate grade")
        seen_grades.add(grade)
        low = _integer(item.get("min_score"), f"{path}.min_score")
        high = _integer(item.get("max_score"), f"{path}.max_score")
        if low < 0 or high > 100 or low > high:
            raise ValueError(f"{path} has an invalid interval")
        for score in range(low, high + 1):
            key = str(score)
            if key in grade_for_score:
                raise ValueError("grade ranges overlap")
            grade_for_score[key] = grade
    if set(grade_for_score) != {str(score) for score in range(101)} or seen_grades != set(_GRADES):
        raise ValueError("grade ranges must cover 0 through 100 exactly once")

    roles = policy.get("roles")
    if not isinstance(roles, list) or not roles:
        raise ValueError("evaluation_policy.roles must be a non-empty list")
    role_map: dict[str, dict[str, Any]] = {}
    for index, role in enumerate(roles):
        path = f"evaluation_policy.roles[{index}]"
        if not isinstance(role, dict) or role.get("status") != "active":
            raise ValueError(f"{path} must be an active role")
        key = _text(role.get("role_key"), f"{path}.role_key")
        _text(role.get("name"), f"{path}.name")
        if key in role_map:
            raise ValueError("evaluation_policy contains a duplicate role key")
        for field in ("responsibilities", "hard_requirements", "preferences"):
            items = role.get(field)
            if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
                raise ValueError(f"{path}.{field} must be a text list")
        role_map[key] = role

    boundary = policy.get("human_boundary")
    expected_boundary = {
        "ai_is_advisory": True,
        "new_row_initial_status": "待审批",
        "agent_may_approve_or_reject": False,
        "existing_human_fields_immutable": ["备注", "初审状态"],
    }
    if boundary != expected_boundary:
        raise ValueError("evaluation_policy.human_boundary is invalid")
    return policy, role_map, grade_for_score


def _validate_evidence(item: Any, path: str, *, allow_unknown: bool) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TypeError(f"{path} must be an object")
    knowledge = item.get("knowledge")
    allowed = {"known", "unknown"} if allow_unknown else {"known"}
    if knowledge not in allowed:
        raise ValueError(f"{path}.knowledge must be one of {sorted(allowed)}")
    _text(item.get("requirement"), f"{path}.requirement")
    evidence = _text(item.get("evidence"), f"{path}.evidence")
    _text(item.get("location"), f"{path}.location")
    if knowledge == "unknown" and not (_UNKNOWN_WORDING.search(evidence) and _CAUTIOUS_WORDING.search(evidence)):
        raise ValueError(f"{path} must phrase unknown evidence cautiously")
    return item


def _validate_assessment(
    value: Any,
    *,
    index: int,
    batch_id: str,
    source_ref: Any,
    dimension_map: dict[str, dict[str, Any]],
    role_map: dict[str, dict[str, Any]],
    grade_for_score: dict[str, str],
) -> dict[str, Any]:
    path = f"reviewed_assessments[{index}]"
    assessment = _decode(value, "reviewed_assessments")
    if not isinstance(assessment, dict) or assessment.get("status") != "assessed":
        raise ValueError(f"{path} must contain one assessed candidate")
    if assessment.get("schema_version") != "1.0" or assessment.get("batch_id") != batch_id:
        raise ValueError(f"{path} has invalid schema or batch identity")
    if _canonical(assessment.get("source_ref")) != _canonical(source_ref):
        raise ValueError(f"{path}.source_ref does not match its exact input")
    if _contains_forbidden_key(assessment):
        raise ValueError(f"{path} contains a Human decision field")
    privacy_view = {key: value for key, value in assessment.items() if key not in {"source_ref", "quality_checks"}}
    if _private_text(privacy_view):
        raise ValueError(f"{path} contains private or protected candidate data")

    candidate_name = _text(assessment.get("candidate_name"), f"{path}.candidate_name")
    scores = assessment.get("dimension_scores")
    if not isinstance(scores, list) or len(scores) != len(dimension_map):
        raise ValueError(f"{path}.dimension_scores must exactly cover the policy")
    seen_dimensions: set[str] = set()
    total = 0
    for score_index, score_item in enumerate(scores):
        score_path = f"{path}.dimension_scores[{score_index}]"
        if not isinstance(score_item, dict):
            raise TypeError(f"{score_path} must be an object")
        name = score_item.get("dimension")
        if name not in dimension_map or name in seen_dimensions:
            raise ValueError(f"{score_path}.dimension is invalid or duplicated")
        seen_dimensions.add(name)
        maximum = _integer(score_item.get("max_score"), f"{score_path}.max_score")
        score = _integer(score_item.get("score"), f"{score_path}.score")
        if maximum != dimension_map[name]["max_score"] or not 0 <= score <= maximum:
            raise ValueError(f"{score_path} violates the policy range")
        evidence = score_item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"{score_path}.evidence must be non-empty")
        known_count = 0
        for evidence_index, evidence_item in enumerate(evidence):
            evidence_path = f"{score_path}.evidence[{evidence_index}]"
            if not isinstance(evidence_item, dict):
                raise TypeError(f"{evidence_path} must be an object")
            _text(evidence_item.get("claim"), f"{evidence_path}.claim")
            _text(evidence_item.get("resume_quote"), f"{evidence_path}.resume_quote")
            _text(evidence_item.get("location"), f"{evidence_path}.location")
            if evidence_item.get("knowledge") not in {"known", "unknown", "inference"}:
                raise ValueError(f"{evidence_path}.knowledge is invalid")
            known_count += evidence_item.get("knowledge") == "known"
        if score > 0 and known_count == 0:
            raise ValueError(f"{score_path} awards points without known resume evidence")
        total += score
    if seen_dimensions != set(dimension_map):
        raise ValueError(f"{path}.dimension_scores does not match the policy")
    declared_total = _integer(assessment.get("total_score"), f"{path}.total_score")
    if declared_total != total or not 0 <= total <= 100:
        raise ValueError(f"{path}.total_score is inconsistent")
    grade = assessment.get("grade")
    if grade != grade_for_score[str(total)]:
        raise ValueError(f"{path}.grade does not match total_score")

    education = assessment.get("education")
    if education not in _EDUCATION:
        raise ValueError(f"{path}.education is invalid")
    education_background = _text(assessment.get("education_background"), f"{path}.education_background")
    summaries = assessment.get("resume_summary")
    if (
        not isinstance(summaries, list)
        or not 1 <= len(summaries) <= 5
        or not all(isinstance(item, str) and item.startswith("- ") and len(item.strip()) > 2 for item in summaries)
    ):
        raise ValueError(f"{path}.resume_summary must contain 1-5 bullet strings")

    role_key = assessment.get("matched_role_key")
    role = role_map.get(role_key)
    if role is None or assessment.get("matched_role_name") != role["name"]:
        raise ValueError(f"{path} does not reference one exact active role")
    role_requirements = set(role["responsibilities"] + role["hard_requirements"] + role["preferences"])
    match_points = assessment.get("match_points")
    mismatch_points = assessment.get("mismatch_points")
    if not isinstance(match_points, list) or not match_points:
        raise ValueError(f"{path}.match_points must be non-empty")
    if not isinstance(mismatch_points, list) or not mismatch_points:
        raise ValueError(f"{path}.mismatch_points must be non-empty")
    for point_index, point in enumerate(match_points):
        checked = _validate_evidence(point, f"{path}.match_points[{point_index}]", allow_unknown=False)
        if checked["requirement"] not in role_requirements:
            raise ValueError(f"{path}.match_points[{point_index}] uses an unknown role requirement")
    for point_index, point in enumerate(mismatch_points):
        checked = _validate_evidence(point, f"{path}.mismatch_points[{point_index}]", allow_unknown=True)
        if checked["requirement"] not in role_requirements:
            raise ValueError(f"{path}.mismatch_points[{point_index}] uses an unknown role requirement")

    recommendation = assessment.get("interview_recommendation")
    if recommendation not in _RECOMMENDATIONS:
        raise ValueError(f"{path}.interview_recommendation is invalid")
    reason = _text(assessment.get("interview_recommendation_reason"), f"{path}.interview_recommendation_reason")
    questions = assessment.get("verification_questions")
    if not isinstance(questions, list) or not 3 <= len(questions) <= 6:
        raise ValueError(f"{path}.verification_questions must contain 3-6 items")
    categories: set[str] = set()
    for question_index, question in enumerate(questions):
        question_path = f"{path}.verification_questions[{question_index}]"
        if not isinstance(question, dict) or question.get("category") not in _QUESTION_CATEGORIES:
            raise ValueError(f"{question_path}.category is invalid")
        categories.add(question["category"])
        _text(question.get("question"), f"{question_path}.question")
        _text(question.get("evidence_anchor"), f"{question_path}.evidence_anchor")
    if not {"真实性核验", "岗位匹配"}.issubset(categories):
        raise ValueError(f"{path}.verification_questions lacks required categories")
    if any(point.get("knowledge") == "unknown" for point in mismatch_points) and "风险澄清" not in categories:
        raise ValueError(f"{path}.verification_questions must clarify unknown risks")

    checks = assessment.get("quality_checks")
    if not isinstance(checks, dict) or set(checks) != set(_QUALITY_CHECKS):
        raise ValueError(f"{path}.quality_checks must contain all five checks")
    for check in _QUALITY_CHECKS:
        result = checks[check]
        if not isinstance(result, dict) or result.get("passed") is not True:
            raise ValueError(f"{path}.quality_checks.{check} did not pass")
        _text(result.get("notes"), f"{path}.quality_checks.{check}.notes")

    rendered_matches = "\n".join(
        f"- 要求: {point['requirement']}; 证据: {point['evidence']} ({point['location']})" for point in match_points
    )
    rendered_mismatches = "\n".join(
        f"- 风险: {point['requirement']}; 依据: {point['evidence']} ({point['location']})" for point in mismatch_points
    )
    rendered_questions = "\n".join(
        f"{question_index}. [{question['category']}] {question['question']}"
        for question_index, question in enumerate(questions, start=1)
    )
    fields = {
        "姓名": candidate_name,
        "简历附件": {"source_ref": deepcopy(source_ref)},
        "评级": grade,
        "学历": education,
        "毕业院校/背景": education_background,
        "总分": total,
        "备注": "",
        "匹配岗位": role["name"],
        "匹配点": rendered_matches,
        "不匹配点": rendered_mismatches,
        "面试建议": recommendation,
        "面试建议理由": reason,
        "问题库": rendered_questions,
        "初审状态": "待审批",
        "简历摘要": "\n".join(summaries),
    }
    if tuple(fields) != _ALL_FIELDS or tuple(field for field in fields if field in _AI_FIELDS) != _AI_FIELDS:
        raise AssertionError("internal 15-field order is inconsistent")

    result = deepcopy(assessment)
    result["candidate_id"] = f"resume-{index + 1:03d}"
    result["table_fields"] = fields
    return result


def run(inputs: Mapping[str, Any]) -> dict[str, Any]:
    policy, role_map, grade_for_score = _validate_policy(inputs.get("evaluation_policy"))
    dimension_map = {item["name"]: item for item in policy["dimensions"]}
    resume_files = inputs.get("resume_files")
    if not isinstance(resume_files, list) or not resume_files:
        raise ValueError("resume_files must be a non-empty list")
    refs = [_canonical(item) for item in resume_files]
    if len(refs) != len(set(refs)):
        raise ValueError("resume_files contains duplicate source references")

    batch_context = _decode(inputs.get("batch_context"), "batch_context")
    if not isinstance(batch_context, dict):
        raise TypeError("batch_context must be an object")
    batch_id = _text(batch_context.get("batch_id"), "batch_context.batch_id")
    if batch_context.get("resume_count") != len(resume_files):
        raise ValueError("batch_context.resume_count does not match resume_files")

    reviewed = inputs.get("reviewed_assessments")
    if not isinstance(reviewed, list) or len(reviewed) != len(resume_files):
        raise ValueError("reviewed_assessments must exactly cover resume_files")
    by_ref: dict[str, Any] = {}
    for item in reviewed:
        decoded = _decode(item, "reviewed_assessments")
        if not isinstance(decoded, dict):
            raise TypeError("each reviewed assessment must be an object")
        source_key = _canonical(decoded.get("source_ref"))
        if source_key in by_ref:
            raise ValueError("reviewed_assessments contains duplicate source references")
        by_ref[source_key] = decoded
    if set(by_ref) != set(refs):
        raise ValueError("reviewed_assessments does not exactly cover resume_files")

    assessments = [
        _validate_assessment(
            by_ref[source_key],
            index=index,
            batch_id=batch_id,
            source_ref=resume_files[index],
            dimension_map=dimension_map,
            role_map=role_map,
            grade_for_score=grade_for_score,
        )
        for index, source_key in enumerate(refs)
    ]
    return {
        "validated_candidate_assessments": {
            "schema_version": "lite-1.0",
            "status": "complete",
            "batch_id": batch_id,
            "assessments": assessments,
        },
        "validation_manifest": {
            "schema_version": "lite-1.0",
            "status": "complete",
            "candidate_count": len(assessments),
            "quality_guarantees": list(_QUALITY_CHECKS),
            "field_count": len(_ALL_FIELDS),
            "errors": [],
        },
    }


def _load_inputs() -> dict[str, Any]:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict) or not isinstance(payload.get("inputs"), dict):
        raise TypeError("Program stdin must contain an inputs object")
    return payload["inputs"]


def main() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    result = run(_load_inputs())
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
