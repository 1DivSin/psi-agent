-- Workflow A Lite: six steps, one semantic review, one deterministic gate.

const resume_approval_lite:Workflow;

const prepare_context_step:Step;
const build_evaluation_policy_step:Step;
const analyze_resume_step:Step;
const review_assessment_step:Step;
const validate_batch_step:Step;
const write_initial_review_step:Step;

const context_preparer:Program,Executor;
const batch_validator:Program,Executor;
const policy_agent:Agent,Executor;
const resume_analyzer:Agent,Executor;
const quality_reviewer:Agent,Executor;
const talent_pool_agent:Agent,Executor;

const read:Tool;
const read_document:Tool;
const read_pdf:Tool;
const feishu_bitable_search_records:Tool;
const feishu_bitable_create_records:Tool;
const feishu_bitable_update_record:Tool;
const feishu_drive_upload:Tool;
const high:ReasoningEffort;

const resume_files:Artifact,List;
const resume_file:Artifact;
const batch_context:Artifact;
const feishu_config:Artifact;
const evaluation_policy:Artifact;
const draft_assessments:Artifact,List;
const draft_assessment:Artifact;
const reviewed_assessments:Artifact,List;
const validated_candidate_assessments:Artifact;
const validation_manifest:Artifact;
const talent_pool_manifest:Artifact;
const initial_review_handoff:Artifact;
const initial_review_request:Artifact;
const user_facing_summary:Artifact;

workflow resume_approval_lite {
    input_workflow(resume_approval_lite) == [resume_files];
    output_workflow(resume_approval_lite) == [
        validated_candidate_assessments,
        talent_pool_manifest,
        initial_review_handoff,
        initial_review_request,
        user_facing_summary
    ];
    max_concurrency(resume_approval_lite) == 4;
    workflow_timeout(resume_approval_lite) == 2400;

    program_path(context_preparer) == "./flows/experiments/resume-approval-lite/programs/prepare_context.py";
    program_path(batch_validator) == "./flows/experiments/resume-approval-lite/programs/validate_batch.py";

    step_name(prepare_context_step) == "Load configuration and current recruitment standards";
    step_instruction(prepare_context_step) == "Load the current scoring and role documents plus the Feishu destination once. Fail the step on missing input or source data; do not calculate or propagate content hashes.";
    step_executor(prepare_context_step) == context_preparer;
    consumes(prepare_context_step) == [resume_files];
    produces(prepare_context_step) == [batch_context, feishu_config];
    step_timeout(prepare_context_step) == 180;

    step_name(build_evaluation_policy_step) == "Build one batch-wide scoring and role policy";
    step_instruction(build_evaluation_policy_step) == "./instructions/build-evaluation-policy.md";
    step_executor(build_evaluation_policy_step) == policy_agent;
    consumes(build_evaluation_policy_step) == [batch_context];
    produces(build_evaluation_policy_step) == [evaluation_policy];
    step_timeout(build_evaluation_policy_step) == 600;
    max_attempts(build_evaluation_policy_step) == 2;

    step_name(analyze_resume_step) == "Assess one resume against the fixed batch policy";
    step_instruction(analyze_resume_step) == "./instructions/analyze-resume.md";
    step_executor(analyze_resume_step) == resume_analyzer;
    foreach_item(analyze_resume_step, resume_files) == resume_file;
    consumes(analyze_resume_step) == [resume_file, batch_context, evaluation_policy];
    produces(analyze_resume_step) == [draft_assessments];
    step_timeout(analyze_resume_step) == 600;
    max_attempts(analyze_resume_step) == 2;

    step_name(review_assessment_step) == "Independently review and correct one assessment";
    step_instruction(review_assessment_step) == "./instructions/review-assessment.md";
    step_executor(review_assessment_step) == quality_reviewer;
    foreach_item(review_assessment_step, draft_assessments) == draft_assessment;
    consumes(review_assessment_step) == [draft_assessment, batch_context, evaluation_policy];
    produces(review_assessment_step) == [reviewed_assessments];
    step_timeout(review_assessment_step) == 600;
    max_attempts(review_assessment_step) == 2;

    step_name(validate_batch_step) == "Apply one consolidated deterministic quality gate";
    step_instruction(validate_batch_step) == "Validate source identity, score arithmetic, grade, role identity, evidence shape, all five quality checks, the complete 15-field plan, privacy, and the Human-owned field boundary. Fail atomically on any violation.";
    step_executor(validate_batch_step) == batch_validator;
    consumes(validate_batch_step) == [reviewed_assessments, evaluation_policy, resume_files, batch_context];
    produces(validate_batch_step) == [validated_candidate_assessments, validation_manifest];
    step_timeout(validate_batch_step) == 180;

    step_name(write_initial_review_step) == "Write validated rows and hand off to Human review";
    step_instruction(write_initial_review_step) == "./instructions/write-initial-review.md";
    step_executor(write_initial_review_step) == talent_pool_agent;
    consumes(write_initial_review_step) == [validated_candidate_assessments, validation_manifest, resume_files, batch_context, feishu_config];
    produces(write_initial_review_step) == [talent_pool_manifest, initial_review_handoff, initial_review_request, user_facing_summary];
    step_timeout(write_initial_review_step) == 600;
    max_attempts(write_initial_review_step) == 2;

    allowed_tool(resume_analyzer, read);
    allowed_tool(resume_analyzer, read_document);
    allowed_tool(resume_analyzer, read_pdf);
    agent_system_prompt(resume_analyzer) == "Assess exactly one supplied resume against only the fixed batch policy. Every factual statement must have resume evidence or be marked unknown; never infer protected or missing facts. Return exactly one JSON object whose sole key is draft_assessments.";
    reasoning_effort(resume_analyzer) == high;
    max_output_tokens(resume_analyzer) == 32768;
    max_turns(resume_analyzer) == 10;

    allowed_tool(quality_reviewer, read);
    allowed_tool(quality_reviewer, read_document);
    allowed_tool(quality_reviewer, read_pdf);
    agent_system_prompt(quality_reviewer) == "Independently reread the same resume, audit the draft against the five required quality dimensions, and return one corrected final assessment. Do not merely endorse the draft. Return exactly one JSON object whose sole key is reviewed_assessments.";
    reasoning_effort(quality_reviewer) == high;
    max_output_tokens(quality_reviewer) == 32768;
    max_turns(quality_reviewer) == 10;

    agent_system_prompt(policy_agent) == "Extract one exact batch-wide evaluation policy from the supplied scoring and role documents. Preserve stated dimensions, maxima, grade ranges, active role names, and requirements; do not add recruiting knowledge. Return exactly one JSON object whose sole key is evaluation_policy.";
    reasoning_effort(policy_agent) == high;
    max_output_tokens(policy_agent) == 32768;
    max_turns(policy_agent) == 6;

    allowed_tool(talent_pool_agent, feishu_bitable_search_records);
    allowed_tool(talent_pool_agent, feishu_bitable_create_records);
    allowed_tool(talent_pool_agent, feishu_bitable_update_record);
    allowed_tool(talent_pool_agent, feishu_drive_upload);
    agent_system_prompt(talent_pool_agent) == "Persist only the Program-validated 15-field row plans. Existing Human-owned 备注 and 初审状态 are immutable; a new row may initialize them only to empty text and 待审批. Never approve, reject, or infer a Human decision. Return exactly the four named output artifacts as one JSON object.";
    reasoning_effort(talent_pool_agent) == high;
    max_output_tokens(talent_pool_agent) == 32768;
    max_turns(talent_pool_agent) == 24;
}
