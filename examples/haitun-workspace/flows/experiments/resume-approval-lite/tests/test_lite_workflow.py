from __future__ import annotations

import json
import subprocess
import sys
from builtins import BaseExceptionGroup
from copy import deepcopy
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any

import anyio
import pytest
from fusion_flow.workflow_runner import (
    CompletionContext,
    ProgramInvocation,
    compile_workflow,
    execute_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "resume-approval-lite.workflow"
WORKSPACE_ROOT = ROOT.parents[2]


def _load(module_name: str, path: Path) -> ModuleType:
    module = ModuleType(module_name)
    module.__file__ = str(path)
    source = path.read_text(encoding="utf-8")
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


validator = _load("resume_approval_lite_validator", ROOT / "programs" / "validate_batch.py")
context_preparer = _load("resume_approval_lite_context", ROOT / "programs" / "prepare_context.py")


def _policy() -> dict:
    return {
        "schema_version": "1.0",
        "total_max": 100,
        "dimensions": [
            {"name": "专业能力", "max_score": 60, "rules": ["按可验证项目证据评分"]},
            {"name": "学习行动", "max_score": 40, "rules": ["按主动学习成果评分"]},
        ],
        "grade_ranges": [
            {"grade": "A", "min_score": 90, "max_score": 100},
            {"grade": "B", "min_score": 80, "max_score": 89},
            {"grade": "C", "min_score": 70, "max_score": 79},
            {"grade": "D", "min_score": 60, "max_score": 69},
            {"grade": "E", "min_score": 50, "max_score": 59},
            {"grade": "F", "min_score": 0, "max_score": 49},
        ],
        "roles": [
            {
                "role_key": "agent-engineer",
                "name": "Agent 工程师",
                "status": "active",
                "responsibilities": ["交付 Agent 应用"],
                "hard_requirements": ["Python 工程能力"],
                "preferences": ["具有 RAG 经验"],
            }
        ],
        "human_boundary": {
            "ai_is_advisory": True,
            "new_row_initial_status": "待审批",
            "agent_may_approve_or_reject": False,
            "existing_human_fields_immutable": ["备注", "初审状态"],
        },
    }


def _assessment(source_ref: object = "resumes/candidate.pdf") -> dict:
    checks = {name: {"passed": True, "notes": "已重新读取原简历并完成核对"} for name in validator._QUALITY_CHECKS}
    return {
        "schema_version": "1.0",
        "status": "assessed",
        "batch_id": "batch-lite-001",
        "source_ref": source_ref,
        "candidate_name": "张某",
        "dimension_scores": [
            {
                "dimension": "专业能力",
                "score": 50,
                "max_score": 60,
                "evidence": [
                    {
                        "claim": "完成 Agent 应用交付",
                        "resume_quote": "负责 Agent 应用的开发与上线",
                        "location": "项目经历第一项",
                        "knowledge": "known",
                    }
                ],
            },
            {
                "dimension": "学习行动",
                "score": 35,
                "max_score": 40,
                "evidence": [
                    {
                        "claim": "主动学习并应用检索技术",
                        "resume_quote": "自学 RAG 并用于知识库项目",
                        "location": "项目经历第二项",
                        "knowledge": "known",
                    }
                ],
            },
        ],
        "total_score": 85,
        "grade": "B",
        "education": "本科",
        "education_background": "本科: 示例大学",
        "resume_summary": ["- 完成 Agent 应用开发与上线"],
        "matched_role_key": "agent-engineer",
        "matched_role_name": "Agent 工程师",
        "match_points": [
            {
                "requirement": "Python 工程能力",
                "evidence": "使用 Python 完成 Agent 应用开发与上线",
                "location": "项目经历第一项",
                "knowledge": "known",
            }
        ],
        "mismatch_points": [
            {
                "requirement": "具有 RAG 经验",
                "evidence": "简历未体现线上 RAG 指标, 需核实",
                "location": "简历全篇",
                "knowledge": "unknown",
            }
        ],
        "interview_recommendation": "建议面试",
        "interview_recommendation_reason": "有明确工程交付证据, 线上检索效果仍需核实。",
        "verification_questions": [
            {
                "category": "真实性核验",
                "question": "请说明 Agent 应用中你个人负责的开发和上线工作。",
                "evidence_anchor": "负责 Agent 应用的开发与上线",
            },
            {
                "category": "岗位匹配",
                "question": "请说明 Python 工程实现中的关键取舍。",
                "evidence_anchor": "Python 工程能力",
            },
            {
                "category": "风险澄清",
                "question": "请补充线上 RAG 指标和验证方法。",
                "evidence_anchor": "简历未体现线上 RAG 指标, 需核实",
            },
        ],
        "quality_checks": checks,
    }


def _inputs() -> dict:
    source = "resumes/candidate.pdf"
    return {
        "evaluation_policy": _policy(),
        "resume_files": [source],
        "batch_context": {"batch_id": "batch-lite-001", "resume_count": 1},
        "reviewed_assessments": [_assessment(source)],
    }


def _write_isolated_defaults(tmp_path: Path) -> None:
    defaults_dir = tmp_path / "flows" / "workflows" / "resume-approval"
    defaults_dir.mkdir(parents=True)
    defaults = {
        "batch_prefix": "resume",
        "resume_scoring_document_token": "score-token",
        "role_information_document_token": "role-token",
        "feishu_config": {
            "app_token": "app-token",
            "base_url": "https://example.feishu.cn/base/example",
            "talent_pool_table_id": "table-id",
            "user_key": "user-key",
            "identity": "bot",
        },
    }
    (defaults_dir / "resume-approval.defaults.json").write_text(
        json.dumps(defaults, ensure_ascii=False), encoding="utf-8"
    )


def _isolated_request_json(method: str, url: str, headers, payload) -> dict[str, Any]:
    del method, headers, payload
    if url.endswith("tenant_access_token/internal"):
        return {"code": 0, "tenant_access_token": "tenant-token"}
    if "score-token" in url:
        return {"code": 0, "data": {"content": "满分100分, 专业能力60分, 学习行动40分。"}}
    if "role-token" in url:
        return {"code": 0, "data": {"content": "启用岗位: Agent 工程师。要求 Python 工程能力。"}}
    raise AssertionError(f"unexpected isolated request: {url}")


def _writer_outputs(batch_id: str, candidate_count: int) -> dict[str, Any]:
    fingerprint = {
        "姓名": "脱敏候选人",
        "评级": "B",
        "学历": "本科",
        "毕业院校/背景": "本科: 示例大学",
        "总分": 85,
        "匹配岗位": "Agent 工程师",
        "匹配点": "有可追溯工程证据",
        "不匹配点": "部分信息需核实",
        "面试建议": "建议面试",
        "面试建议理由": "存在可核验的岗位相关证据",
        "问题库": "请核实项目职责",
        "简历摘要": "- 完成工程项目",
    }
    records = [
        {
            "candidate_id": f"resume-{index + 1:03d}",
            "record_id": f"isolated-record-{index + 1:03d}",
            "created": True,
            "attachment_persisted": True,
            "row_fingerprint": deepcopy(fingerprint),
        }
        for index in range(candidate_count)
    ]
    return {
        "talent_pool_manifest": {
            "schema_version": "lite-1.0",
            "status": "complete",
            "batch_id": batch_id,
            "base_url": "https://example.feishu.cn/base/example",
            "records": records,
            "errors": [],
        },
        "initial_review_handoff": {
            "schema_version": "lite-1.0",
            "status": "ready",
            "batch_id": batch_id,
            "records": [{"candidate_id": item["candidate_id"], "record_id": item["record_id"]} for item in records],
            "human_owned_fields": ["备注", "初审状态"],
            "allowed_human_decisions": ["通过", "不通过"],
        },
        "initial_review_request": {
            "status": "waiting_for_external_human_review",
            "instruction": "请在候选人才库逐行核对, 并仅由审核人设置初审状态。",
        },
        "user_facing_summary": {
            "schema_version": "1.0",
            "status": "complete",
            "text": f"已完成 {candidate_count} 份简历初评, 等待人工审核。",
        },
    }


def _runtime_callbacks(
    tmp_path: Path,
    *,
    fail_first_analysis_for: str | None = None,
    always_fail_analysis_for: str | None = None,
    invalid_writer_contract: bool = False,
) -> tuple[Any, Any, Any, dict[str, list[Any]]]:
    _write_isolated_defaults(tmp_path)
    events: dict[str, list[Any]] = {
        "instructions": [],
        "programs": [],
        "completions": [],
    }

    async def resolve_instruction(reference: str) -> str:
        events["instructions"].append(reference)
        path = ROOT / reference.removeprefix("./")
        return path.read_text(encoding="utf-8")

    async def run_program(invocation: ProgramInvocation) -> str:
        payload = json.loads(invocation.stdin)
        assert payload == {
            "instruction": invocation.instruction,
            "inputs": dict(invocation.inputs),
        }
        assert invocation.cwd == str(WORKSPACE_ROOT)
        events["programs"].append(invocation)
        if invocation.name == "context_preparer":
            result = context_preparer.run(
                payload["inputs"],
                str(tmp_path),
                environment={
                    "PSI_FEISHU_APP_ID": "isolated-id",
                    "PSI_FEISHU_APP_SECRET": "isolated-secret",
                },
                request_json=_isolated_request_json,
                batch_id="batch-lite-runtime",
            )
            return json.dumps(result, ensure_ascii=False, allow_nan=False)

        assert invocation.name == "batch_validator"
        completed = await anyio.run_process(
            [sys.executable, invocation.argv[0]],
            cwd=invocation.cwd,
            input=invocation.stdin.encode(),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.decode().strip())
        assert completed.stderr == b""
        return completed.stdout.decode()

    analysis_attempts: dict[str, int] = {}

    async def complete(prompt: str, context: CompletionContext) -> dict[str, Any]:
        assert context.executor_kind == "Agent"
        assert "Instruction:\n" in prompt and "Inputs:" in prompt
        events["completions"].append(context)
        if context.step_id == "build_evaluation_policy_step":
            assert "# Task" in prompt and "Human boundary" in prompt
            return {"evaluation_policy": _policy()}
        if context.step_id == "analyze_resume_step":
            source = context.inputs["resume_file"]
            assert isinstance(source, str)
            analysis_attempts[source] = analysis_attempts.get(source, 0) + 1
            if source == always_fail_analysis_for:
                raise RuntimeError("terminal isolated analysis failure")
            if source == fail_first_analysis_for and context.dispatch.attempt == 1:
                raise RuntimeError("transient isolated analysis failure")
            if source.endswith("02.docx"):
                await anyio.sleep(0.01)
            assessment = _assessment(source)
            assessment["batch_id"] = "batch-lite-runtime"
            assessment["candidate_name"] = f"候选人{source[-6:-5]}"
            return {"draft_assessments": assessment}
        if context.step_id == "review_assessment_step":
            reviewed = deepcopy(context.inputs["draft_assessment"])
            return {"reviewed_assessments": reviewed}
        if context.step_id == "write_initial_review_step":
            if invalid_writer_contract:
                return {"user_facing_summary": {"text": "invalid contract"}}
            assessments = context.inputs["validated_candidate_assessments"]["assessments"]
            return _writer_outputs("batch-lite-runtime", len(assessments))
        raise AssertionError(f"unexpected Agent step: {context.step_id}")

    return complete, run_program, resolve_instruction, events


def test_workflow_is_six_steps_with_two_programs_and_no_assert_or_hash_chain() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert source.count(":Step;") == 6
    assert source.count(":Program,Executor;") == 2
    assert source.count(":Agent,Executor;") == 4
    assert "assert_" not in source
    assert "sha256" not in source.casefold()
    assert source.count("foreach_item(") == 2


def test_validator_builds_exact_15_field_plan_and_keeps_human_defaults() -> None:
    result = validator.run(_inputs())

    assert result["validation_manifest"]["quality_guarantees"] == list(validator._QUALITY_CHECKS)
    fields = result["validated_candidate_assessments"]["assessments"][0]["table_fields"]
    assert tuple(fields) == validator._ALL_FIELDS
    assert fields["备注"] == ""
    assert fields["初审状态"] == "待审批"
    assert fields["简历附件"] == {"source_ref": "resumes/candidate.pdf"}
    assert fields["总分"] == 85
    assert fields["评级"] == "B"


def test_validator_rejects_score_arithmetic_or_grade_drift() -> None:
    inputs = _inputs()
    inputs["reviewed_assessments"][0]["total_score"] = 84

    with pytest.raises(ValueError, match="total_score is inconsistent"):
        validator.run(inputs)


@pytest.mark.parametrize("check_name", validator._QUALITY_CHECKS)
def test_validator_rejects_each_failed_five_point_quality_signoff(check_name: str) -> None:
    inputs = _inputs()
    inputs["reviewed_assessments"][0]["quality_checks"][check_name]["passed"] = False

    with pytest.raises(ValueError, match=rf"{check_name} did not pass"):
        validator.run(inputs)


def test_validator_rejects_agent_owned_human_decision() -> None:
    inputs = _inputs()
    inputs["reviewed_assessments"][0]["初审状态"] = "通过"

    with pytest.raises(ValueError, match="Human decision field"):
        validator.run(inputs)


def test_validator_rejects_unknown_claim_without_cautious_wording() -> None:
    inputs = _inputs()
    inputs["reviewed_assessments"][0]["mismatch_points"][0]["evidence"] = "候选人不具备线上经验"

    with pytest.raises(ValueError, match="phrase unknown evidence cautiously"):
        validator.run(inputs)


def test_validator_rejects_score_without_known_resume_evidence() -> None:
    inputs = _inputs()
    evidence = inputs["reviewed_assessments"][0]["dimension_scores"][0]["evidence"]
    evidence[0]["knowledge"] = "inference"

    with pytest.raises(ValueError, match="awards points without known resume evidence"):
        validator.run(inputs)


def test_validator_rejects_source_identity_drift() -> None:
    inputs = _inputs()
    inputs["reviewed_assessments"][0]["source_ref"] = "resumes/another-candidate.pdf"

    with pytest.raises(ValueError, match="does not exactly cover resume_files"):
        validator.run(inputs)


def test_validator_rejects_private_or_protected_candidate_data() -> None:
    inputs = _inputs()
    inputs["reviewed_assessments"][0]["interview_recommendation_reason"] = "候选人手机号 13800138000, 建议面试。"

    with pytest.raises(ValueError, match="contains private or protected candidate data"):
        validator.run(inputs)


def test_validator_rejects_role_or_requirement_not_in_current_policy() -> None:
    inputs = _inputs()
    inputs["reviewed_assessments"][0]["match_points"][0]["requirement"] = "未定义岗位要求"

    with pytest.raises(ValueError, match="uses an unknown role requirement"):
        validator.run(inputs)


def test_context_preparer_fetches_sources_once_without_revision_fields(tmp_path: Path) -> None:
    defaults_dir = tmp_path / "flows" / "workflows" / "resume-approval"
    defaults_dir.mkdir(parents=True)
    defaults = {
        "batch_prefix": "resume",
        "resume_scoring_document_token": "score-token",
        "role_information_document_token": "role-token",
        "feishu_config": {
            "app_token": "app-token",
            "base_url": "https://example.feishu.cn/base/example",
            "talent_pool_table_id": "table-id",
            "user_key": "user-key",
            "identity": "bot",
        },
    }
    (defaults_dir / "resume-approval.defaults.json").write_text(
        json.dumps(defaults, ensure_ascii=False), encoding="utf-8"
    )
    calls: list[str] = []

    def request_json(method: str, url: str, headers, payload):
        del method, headers, payload
        calls.append(url)
        if url.endswith("tenant_access_token/internal"):
            return {"code": 0, "tenant_access_token": "tenant-token"}
        if "score-token" in url:
            return {"code": 0, "data": {"content": "满分100分的评分标准"}}
        return {"code": 0, "data": {"content": "启用岗位信息"}}

    result = context_preparer.run(
        {"resume_files": ["resumes/candidate.pdf"]},
        str(tmp_path),
        environment={"PSI_FEISHU_APP_ID": "id", "PSI_FEISHU_APP_SECRET": "secret"},
        request_json=request_json,
        batch_id="batch-lite-001",
    )

    assert len(calls) == 3
    assert result["batch_context"]["batch_id"] == "batch-lite-001"
    assert "sha256" not in json.dumps(result, ensure_ascii=False).casefold()


def test_real_workflow_runtime_runs_all_six_steps_and_preserves_foreach_order(tmp_path: Path) -> None:
    resumes = ["resumes/candidate-01.pdf", "resumes/candidate-02.docx"]
    complete, run_program, resolve_instruction, events = _runtime_callbacks(tmp_path)

    result = anyio.run(
        partial(
            execute_workflow,
            WORKFLOW.read_text(encoding="utf-8"),
            inputs={"resume_files": resumes},
            complete=complete,
            resolve_instruction=resolve_instruction,
            work_dir=str(WORKSPACE_ROOT),
            run_program=run_program,
        )
    )

    assessments = result["validated_candidate_assessments"]["assessments"]
    assert [item["source_ref"] for item in assessments] == resumes
    assert [item["candidate_id"] for item in assessments] == ["resume-001", "resume-002"]
    assert result["talent_pool_manifest"]["status"] == "complete"
    assert all(len(item["row_fingerprint"]) == 12 for item in result["talent_pool_manifest"]["records"])
    assert result["initial_review_handoff"]["human_owned_fields"] == ["备注", "初审状态"]
    assert result["initial_review_request"]["status"] == "waiting_for_external_human_review"
    assert result["user_facing_summary"]["schema_version"] == "1.0"
    assert {item.name for item in events["programs"]} == {"context_preparer", "batch_validator"}
    assert {item.step_id for item in events["completions"]} == {
        "build_evaluation_policy_step",
        "analyze_resume_step",
        "review_assessment_step",
        "write_initial_review_step",
    }
    assert set(events["instructions"]) == {
        "./instructions/build-evaluation-policy.md",
        "./instructions/analyze-resume.md",
        "./instructions/review-assessment.md",
        "./instructions/write-initial-review.md",
    }


def test_real_runtime_retries_one_foreach_iteration_without_reordering(tmp_path: Path) -> None:
    resumes = ["resumes/candidate-01.pdf", "resumes/candidate-02.docx"]
    complete, run_program, resolve_instruction, events = _runtime_callbacks(
        tmp_path,
        fail_first_analysis_for=resumes[0],
    )

    result = anyio.run(
        partial(
            execute_workflow,
            WORKFLOW.read_text(encoding="utf-8"),
            inputs={"resume_files": resumes},
            complete=complete,
            resolve_instruction=resolve_instruction,
            work_dir=str(WORKSPACE_ROOT),
            run_program=run_program,
        )
    )

    analysis_contexts = [item for item in events["completions"] if item.step_id == "analyze_resume_step"]
    attempts_by_source: dict[str, list[int]] = {}
    for context in analysis_contexts:
        attempts_by_source.setdefault(context.inputs["resume_file"], []).append(context.dispatch.attempt)
    assert attempts_by_source == {resumes[0]: [1, 2], resumes[1]: [1]}
    assert [item["source_ref"] for item in result["validated_candidate_assessments"]["assessments"]] == resumes


def test_foreach_terminal_failure_is_atomic_and_blocks_all_downstream_steps(tmp_path: Path) -> None:
    resumes = ["resumes/candidate-01.pdf", "resumes/candidate-02.docx"]
    complete, run_program, resolve_instruction, events = _runtime_callbacks(
        tmp_path,
        always_fail_analysis_for=resumes[0],
    )

    with pytest.raises(BaseExceptionGroup):
        anyio.run(
            partial(
                execute_workflow,
                WORKFLOW.read_text(encoding="utf-8"),
                inputs={"resume_files": resumes},
                complete=complete,
                resolve_instruction=resolve_instruction,
                work_dir=str(WORKSPACE_ROOT),
                run_program=run_program,
            )
        )

    completion_steps = [item.step_id for item in events["completions"]]
    assert completion_steps.count("analyze_resume_step") == 3
    assert "review_assessment_step" not in completion_steps
    assert "write_initial_review_step" not in completion_steps
    assert [item.name for item in events["programs"]] == ["context_preparer"]


def test_writer_must_return_the_exact_four_artifact_contract(tmp_path: Path) -> None:
    complete, run_program, resolve_instruction, events = _runtime_callbacks(
        tmp_path,
        invalid_writer_contract=True,
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        anyio.run(
            partial(
                execute_workflow,
                WORKFLOW.read_text(encoding="utf-8"),
                inputs={"resume_files": ["resumes/candidate-01.pdf"]},
                complete=complete,
                resolve_instruction=resolve_instruction,
                work_dir=str(WORKSPACE_ROOT),
                run_program=run_program,
            )
        )

    assert "must match exactly" in repr(raised.value)
    writer_calls = [item for item in events["completions"] if item.step_id == "write_initial_review_step"]
    assert [item.dispatch.attempt for item in writer_calls] == [1, 2]


def test_validator_program_real_subprocess_rejects_contract_violation() -> None:
    program = ROOT / "programs" / "validate_batch.py"
    invalid_payload = json.dumps(
        {
            "instruction": "validate",
            "inputs": {**_inputs(), "reviewed_assessments": []},
        },
        ensure_ascii=False,
    )

    completed = subprocess.run(
        [sys.executable, str(program)],
        cwd=str(WORKSPACE_ROOT),
        input=invalid_payload,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "reviewed_assessments must exactly cover resume_files" in completed.stderr


def test_workflow_compiles_with_expected_executor_and_tool_contracts() -> None:
    compiled = compile_workflow(WORKFLOW.read_text(encoding="utf-8"))

    assert len(compiled.graph.steps) == 6
    assert sorted(compiled.executor_kinds.values()) == [
        "Agent",
        "Agent",
        "Agent",
        "Agent",
        "Program",
        "Program",
    ]
    assert compiled.program_paths == {
        "batch_validator": "./flows/experiments/resume-approval-lite/programs/validate_batch.py",
        "context_preparer": "./flows/experiments/resume-approval-lite/programs/prepare_context.py",
    }
    assert compiled.agent_configs["resume_analyzer"].tools == (
        "read",
        "read_document",
        "read_pdf",
    )
    assert compiled.agent_configs["quality_reviewer"].tools == (
        "read",
        "read_document",
        "read_pdf",
    )
    assert set(compiled.agent_configs["talent_pool_agent"].tools) == {
        "feishu_bitable_search_records",
        "feishu_bitable_create_records",
        "feishu_bitable_update_record",
        "feishu_drive_upload",
    }
