from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PROGRAM_PATH = Path(__file__).resolve().parents[1] / "programs" / "load_initial_review_handoff.py"
BATCH_ID = "resume-20260810-120000-123456"
CANDIDATE_ID = "a" * 16
ASSESSMENT_REVISION = "d" * 64
ROLE_REVISION = "c" * 64
ROLE_KEY = "role-0123456789abcdef01234567"


def _row_fingerprint() -> dict:
    return {
        "姓名": "测试候选人",
        "评级": "B",
        "学历": "硕士",
        "毕业院校/背景": "硕士\uff1a测试大学",
        "简历摘要": '["- 有相关项目经验"]',
        "总分": 82,
        "匹配岗位": "AI应用开发工程师",
        "匹配点": '["- 要求\uff1aPython\uff1b证据\uff1a项目使用 Python"]',
        "不匹配点": '["- 要求\uff1a生产经验\uff1b证据\uff1a简历未体现"]',
        "面试建议": "建议面试",
        "面试建议理由": "核心技能基本匹配。",
    }


def _load_module():
    spec = importlib.util.spec_from_file_location("load_initial_review_handoff", PROGRAM_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assessment() -> dict:
    return {
        "schema_version": "3.0",
        "status": "assessed",
        "batch_id": BATCH_ID,
        "candidate_id": CANDIDATE_ID,
        "candidate_name": "测试候选人",
        "matched_role_key": ROLE_KEY,
        "matched_role_name": "AI应用开发工程师",
        "document_revisions": {
            "resume_scoring_sha256": "b" * 64,
            "role_information_sha256": ROLE_REVISION,
        },
        "assessment_revision": ASSESSMENT_REVISION,
    }


def _document() -> dict:
    assessment = _assessment()
    return {
        "schema_version": "1.0",
        "status": "ready_for_review",
        "batch_id": BATCH_ID,
        "destination": {
            "app_token": "app-token",
            "base_url": "https://example.feishu.cn/base/app-token",
            "talent_pool_table_id": "tblTalent",
            "interview_table_id": "tblInterview",
        },
        "role_catalog": {
            "schema_version": "1.0",
            "source_document_sha256": ROLE_REVISION,
            "roles": [
                {
                    "role_key": ROLE_KEY,
                    "name": "AI应用开发工程师",
                    "status": "active",
                }
            ],
        },
        "validated_candidate_assessments": {
            "schema_version": "3.0",
            "status": "complete",
            "batch_id": BATCH_ID,
            "document_revisions": copy.deepcopy(assessment["document_revisions"]),
            "assessments": [assessment],
            "failed_candidates": [],
            "constraint_warnings": [],
        },
        "talent_pool_manifest": {
            "schema_version": "4.0",
            "status": "complete",
            "batch_id": BATCH_ID,
            "base_url": "https://example.feishu.cn/base/app-token",
            "table_id": "tblTalent",
            "view_name": "候选人看板",
            "expected_count": 1,
            "failed_candidates": [],
            "records": [
                {
                    "record_id": "recTalent00001",
                    "candidate_id": CANDIDATE_ID,
                    "assessment_revision": ASSESSMENT_REVISION,
                    "row_fingerprint": _row_fingerprint(),
                    "created": True,
                }
            ],
            "errors": [],
        },
    }


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _write_case(workspace: Path, document: dict | None = None) -> tuple[dict, Path]:
    payload = copy.deepcopy(document if document is not None else _document())
    relative = Path(".psi/resume-approval/initial-review-handoffs") / f"{BATCH_ID}.json"
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _canonical_bytes(payload)
    path.write_bytes(content)
    descriptor = {
        "schema_version": "1.0",
        "status": "ready_for_review",
        "batch_id": BATCH_ID,
        "expected_count": len(payload["talent_pool_manifest"]["records"]),
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "next_workflow": "resume-interview-preparation",
        "next_input": "initial_review_handoff",
    }
    defaults = workspace / "flows/workflows/resume-approval/resume-approval.defaults.json"
    defaults.parent.mkdir(parents=True, exist_ok=True)
    defaults.write_text(
        json.dumps(
            {
                "schema_version": "3.0",
                "feishu_config": payload["destination"] | {"user_key": "local-only"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return descriptor, path


def test_loads_verified_review_source_for_live_decision_collection(tmp_path: Path) -> None:
    module = _load_module()
    descriptor, _ = _write_case(tmp_path)

    result = module.run({"initial_review_handoff": descriptor}, str(tmp_path))

    assert set(result) == {
        "initial_review_stage_bundle",
        "validated_candidate_assessments",
        "talent_pool_manifest",
        "role_catalog",
        "initial_review_batch_id",
        "initial_review_feishu_config",
        "initial_review_load_manifest",
    }
    assert result["initial_review_batch_id"] == BATCH_ID
    assert result["validated_candidate_assessments"] == _document()["validated_candidate_assessments"]
    assert result["talent_pool_manifest"] == _document()["talent_pool_manifest"]
    assert result["initial_review_feishu_config"]["user_key"] == "local-only"
    assert result["initial_review_load_manifest"] == {
        "schema_version": "1.0",
        "status": "complete",
        "expected_count": 1,
        "errors": [],
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda descriptor, _path: descriptor.update(status="complete"), "ready_for_review"),
        (lambda descriptor, _path: descriptor.update(expected_count=2), "expected_count"),
        (lambda descriptor, _path: descriptor.update(sha256="0" * 64), "hash"),
        (lambda descriptor, _path: descriptor.update(path="../escape.json"), "path"),
    ],
)
def test_rejects_invalid_descriptor(tmp_path: Path, mutation, message: str) -> None:
    module = _load_module()
    descriptor, path = _write_case(tmp_path)
    mutation(descriptor, path)

    with pytest.raises((TypeError, ValueError), match=message):
        module.run({"initial_review_handoff": descriptor}, str(tmp_path))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda doc: doc["talent_pool_manifest"]["records"][0].update(candidate_id="e" * 16),
            "cover",
        ),
        (
            lambda doc: doc["talent_pool_manifest"]["records"][0].update(assessment_revision="f" * 64),
            "revision",
        ),
        (
            lambda doc: doc["talent_pool_manifest"]["records"][0]["row_fingerprint"].pop("面试建议理由"),
            "row_fingerprint",
        ),
        (
            lambda doc: doc["validated_candidate_assessments"].update(assessments=[]),
            "non-empty",
        ),
    ],
)
def test_rejects_forged_private_review_source(tmp_path: Path, mutation, message: str) -> None:
    module = _load_module()
    document = _document()
    mutation(document)
    descriptor, _ = _write_case(tmp_path, document)

    with pytest.raises((TypeError, ValueError), match=message):
        module.run({"initial_review_handoff": descriptor}, str(tmp_path))


def test_rejects_changed_local_destination(tmp_path: Path) -> None:
    module = _load_module()
    descriptor, _ = _write_case(tmp_path)
    defaults = tmp_path / "flows/workflows/resume-approval/resume-approval.defaults.json"
    current = json.loads(defaults.read_text(encoding="utf-8"))
    current["feishu_config"]["talent_pool_table_id"] = "tblChanged"
    defaults.write_text(json.dumps(current), encoding="utf-8")

    with pytest.raises(ValueError, match="destination"):
        module.run({"initial_review_handoff": descriptor}, str(tmp_path))
