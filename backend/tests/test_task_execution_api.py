import difflib

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import task_execution as task_endpoint
from app.main import app
from app.models.coder import (
    CoderDiffPreviewRequest,
    CoderDiffPreviewResponse,
    CoderDryRunOperation,
    CoderDryRunRequest,
    CoderDryRunResponse,
    CoderFileDiffPreview,
)
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.planning_workflow import FinalReviewedPlanSummary
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidatorResponse
from app.services.execution_handoff import ExecutionHandoffService
from app.services.execution_mutation import ExecutionMutationService
from app.services.execution_preflight import ExecutionPreflightService
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_store import ExecutionStore
from app.services.execution_verification import ExecutionVerificationRunner
from app.services.planning_approval import PlanningApprovalStore
from app.services.task_execution import ControlledTaskExecutionService
from app.services.task_execution_store import TaskExecutionStore
from app.services.task_execution_store import TaskExecutionStore
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


class FakeDryRunAgent:
    def __init__(self, operation="modify_text_file", fail=False):
        self.operation = operation
        self.fail = fail
        self.requests = []

    async def dry_run(self, request: CoderDryRunRequest) -> CoderDryRunResponse:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("dry-run failed")
        path = request.handoff.allowed_files[0]
        return CoderDryRunResponse(
            workflow_id=request.handoff.workflow_id,
            approved_plan_fingerprint=request.handoff.approved_plan_fingerprint,
            workspace_path=request.handoff.workspace_path,
            files_would_modify=[path] if self.operation == "modify_text_file" else [],
            files_would_create=[path] if self.operation == "create_text_file" else [],
            files_would_delete=[],
            intended_operations=[
                CoderDryRunOperation(
                    operation_type=self.operation,
                    relative_path=path,
                    description="Apply deterministic test content.",
                    rationale="Test orchestration.",
                )
            ],
            proposed_code_change_summary="Apply deterministic test content.",
            dependencies_required=[],
            tests_to_run=["python_compile"],
            rollback_backup_plan=["Use persisted snapshot."],
            warnings=[],
            blockers=[],
            model="fake",
            message="Dry run only.",
        )


class FakeDiffAgent:
    def __init__(self, execution_store, proposed_content="value = 2\n", fail=False):
        self.execution_store = execution_store
        self.proposed_content = proposed_content
        self.fail = fail

    async def preview_diff(self, request: CoderDiffPreviewRequest) -> CoderDiffPreviewResponse:
        if self.fail:
            raise RuntimeError("diff failed")
        operation = request.dry_run.intended_operations[0]
        current = None
        if operation.operation_type == "modify_text_file":
            with open(
                f"{request.dry_run.workspace_path}/{operation.relative_path}",
                "r",
                encoding="utf-8",
            ) as handle:
                current = handle.read()
        preview = CoderDiffPreviewResponse(
            workflow_id=request.dry_run.workflow_id,
            approved_plan_fingerprint=request.dry_run.approved_plan_fingerprint,
            workspace_path=request.dry_run.workspace_path,
            file_previews=[
                CoderFileDiffPreview(
                    relative_path=operation.relative_path,
                    operation_type=operation.operation_type,
                    current_content=current,
                    proposed_content=self.proposed_content,
                    unified_diff=make_diff(
                        operation.relative_path,
                        current,
                        self.proposed_content,
                    ),
                    warnings=[],
                )
            ],
            warnings=[],
            blockers=[],
            model="fake",
            message="Preview only.",
        )
        return self.execution_store.record_diff_review(preview)


@pytest.fixture
def task_context(tmp_path, monkeypatch):
    database = tmp_path / "runtime" / "devloopai.sqlite3"
    approval_store = PlanningApprovalStore(database)
    execution_store = ExecutionStore(database)
    workspace_service = WorkspaceService()
    preflight_service = ExecutionPreflightService(
        approval_store=approval_store,
        workspace_service=workspace_service,
    )
    handoff_service = ExecutionHandoffService(
        approval_store=approval_store,
        workspace_service=workspace_service,
        preflight_service=preflight_service,
    )
    service = ControlledTaskExecutionService(
        task_store=TaskExecutionStore(database),
        approval_store=approval_store,
        preflight_service=preflight_service,
        handoff_service=handoff_service,
        dry_run_agent=FakeDryRunAgent(),
        diff_preview_agent=FakeDiffAgent(execution_store),
        mutation_service=ExecutionMutationService(
            handoff_service=handoff_service,
            workspace_service=workspace_service,
            execution_store=execution_store,
        ),
        verification_runner=ExecutionVerificationRunner(
            execution_store=execution_store,
            approval_store=approval_store,
            workspace_service=workspace_service,
        ),
        quality_gate=ExecutionQualityGate(
            execution_store=execution_store,
            workspace_service=workspace_service,
        ),
    )
    monkeypatch.setattr(task_endpoint, "get_task_execution_service", lambda: service)
    return {
        "database": database,
        "approval_store": approval_store,
        "execution_store": execution_store,
        "service": service,
    }


def create_workspace(tmp_path, content="value = 1\n"):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace.joinpath("sample.py").write_text(content, encoding="utf-8", newline="\n")
    return workspace


def create_workflow(context, workspace, *, approve=True):
    planner = PlannerResponse(
        task_summary="Update sample.py.",
        assumptions=[],
        detected_project_context=PlannerProjectContext(
            workspace_name="sample", project_types=["Python"], frameworks=[], languages={"Python": 1}
        ),
        implementation_steps=["Update sample.py."],
        files_likely_to_change=["sample.py"],
        tests_verification_required=["Run python_compile."],
        risks=[],
        dependencies_or_user_input_needed=[],
        model="test",
    )
    reviewer = ReviewerResponse(
        overall_assessment="Scoped.", missing_steps=[], incorrect_assumptions=[],
        architecture_concerns=[], security_concerns=[], performance_concerns=[],
        testing_gaps=[], unnecessary_changes=[], recommended_improvements=[],
        approval_recommendation="APPROVE", model="test",
    )
    validator = ValidatorResponse(
        overall_validation_status="READY", plan_completeness=["Complete."],
        file_path_validity=[], dependency_concerns=[], environment_tool_requirements=[],
        security_concerns=[], destructive_operation_warnings=[],
        missing_user_information=[], test_verification_readiness=["Run python_compile."],
        blockers=[], final_execution_readiness="Ready.", model="test",
    )
    summary = FinalReviewedPlanSummary(
        final_recommendation="READY", final_execution_readiness="Ready.",
        execution_ready=False, required_changes_before_execution=[], blockers=[],
        warnings=[], risks=[], tests_expected=["python_compile"],
        user_approval_required=True, summary="Ready.",
    )
    gate = context["approval_store"].create_gate(
        task="Update sample.py.",
        workspace_path=str(workspace),
        planner_output=planner,
        reviewer_output=reviewer,
        validator_output=validator,
        final_reviewed_summary=summary,
        blockers=[],
    )
    if approve:
        context["approval_store"].approve(
            approval_id=gate.approval_id,
            approval_token=gate.approval_token,
            plan_fingerprint=gate.plan_fingerprint,
        )
    return gate


def prepare(workflow_id):
    return client.post("/api/v1/workflows/execution/task", json={"workflow_id": workflow_id})


def apply_task(task_id, expected_state=None):
    payload = {} if expected_state is None else {"expected_state": expected_state}
    return client.post(f"/api/v1/workflows/execution/task/{task_id}/apply", json=payload)


def verify_task(task_id, expected_state=None):
    payload = {} if expected_state is None else {"expected_state": expected_state}
    return client.post(f"/api/v1/workflows/execution/task/{task_id}/verify", json=payload)


def retry_task(task_id, expected_state=None):
    payload = {} if expected_state is None else {"expected_state": expected_state}
    return client.post(f"/api/v1/workflows/execution/task/{task_id}/retry", json=payload)


def make_diff(path, current, proposed):
    before = [] if current is None else current.splitlines(keepends=True)
    after = proposed.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="")
    )


def test_prepare_approved_workflow_stops_at_awaiting_execution_approval(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)

    response = prepare(gate.workflow_id)

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "AWAITING_EXECUTION_APPROVAL"
    assert body["diff_preview"]["review_id"]
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "value = 1\n"


def test_prepare_unapproved_workflow_is_blocked(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace, approve=False)

    body = prepare(gate.workflow_id).json()

    assert body["state"] in {"BLOCKED", "FAILED"}
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "value = 1\n"


def test_prepare_diff_failure_is_persisted_safely(tmp_path, task_context, monkeypatch):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], fail=True
    )

    body = prepare(gate.workflow_id).json()

    assert body["state"] == "FAILED"
    assert "diff failed" in body["blockers"][0]


def test_explicit_apply_succeeds_and_duplicate_apply_is_blocked(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task = prepare(gate.workflow_id).json()

    applied = client.post(
        f"/api/v1/workflows/execution/task/{task['task_execution_id']}/apply",
        json={"expected_state": "AWAITING_EXECUTION_APPROVAL"},
    ).json()
    duplicate = client.post(
        f"/api/v1/workflows/execution/task/{task['task_execution_id']}/apply",
        json={"expected_state": "APPLIED"},
    ).json()

    assert applied["state"] == "APPLIED"
    assert applied["mutation_execution_id"]
    assert duplicate["state"] == "APPLIED"
    assert duplicate["mutation_execution_id"] == applied["mutation_execution_id"]
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "value = 2\n"
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "value = 2\n"


def test_apply_without_preparation_or_wrong_state_is_blocked(task_context):
    response = client.post("/api/v1/workflows/execution/task/missing/apply", json={})

    assert response.status_code == 404


def test_stale_file_before_apply_blocks_without_overwrite(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task = prepare(gate.workflow_id).json()
    workspace.joinpath("sample.py").write_text("value = 99\n", encoding="utf-8", newline="\n")

    body = client.post(
        f"/api/v1/workflows/execution/task/{task['task_execution_id']}/apply",
        json={"expected_state": "AWAITING_EXECUTION_APPROVAL"},
    ).json()

    assert body["state"] == "BLOCKED"
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "value = 99\n"


def test_apply_verify_quality_passed(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task = prepare(gate.workflow_id).json()
    applied = client.post(
        f"/api/v1/workflows/execution/task/{task['task_execution_id']}/apply", json={}
    ).json()

    verified = client.post(
        f"/api/v1/workflows/execution/task/{task['task_execution_id']}/verify", json={}
    ).json()

    assert applied["state"] == "APPLIED"
    assert verified["state"] == "QUALITY_PASSED"
    assert verified["quality_result"]["quality_status"] == "QUALITY_PASSED"
    assert verified["verification_ids"]


def test_verification_failure_sets_quality_failed_and_rollback_is_explicit(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="def broken(:\n"
    )
    task = prepare(gate.workflow_id).json()
    client.post(f"/api/v1/workflows/execution/task/{task['task_execution_id']}/apply", json={})

    failed = client.post(
        f"/api/v1/workflows/execution/task/{task['task_execution_id']}/verify", json={}
    ).json()
    rolled_back = client.post(
        f"/api/v1/workflows/execution/task/{task['task_execution_id']}/rollback", json={}
    ).json()

    assert failed["state"] == "QUALITY_FAILED"
    assert failed["rollback_recommended"] is True
    assert rolled_back["state"] == "ROLLED_BACK"
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "value = 1\n"


def test_task_session_reconstructs_after_store_restart(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task = prepare(gate.workflow_id).json()

    restarted = TaskExecutionStore(task_context["database"])
    reloaded = restarted.get(task["task_execution_id"])

    assert reloaded.state == "AWAITING_EXECUTION_APPROVAL"
    assert reloaded.diff_preview is not None
    assert reloaded.diff_preview.review_id


def test_quality_failed_retry_prepares_new_diff_without_mutating_files(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    dry_run_agent = FakeDryRunAgent()
    task_context["service"].dry_run_agent = dry_run_agent
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="def broken(:\n"
    )
    task = prepare(gate.workflow_id).json()
    apply_task(task["task_execution_id"])
    failed = verify_task(task["task_execution_id"]).json()
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="value = 3\n"
    )

    retried = retry_task(failed["task_execution_id"], "QUALITY_FAILED").json()

    assert retried["state"] == "AWAITING_EXECUTION_APPROVAL"
    assert retried["current_attempt"] == 2
    assert retried["max_attempts"] == 3
    assert len(retried["attempts"]) == 2
    assert retried["attempts"][1]["parent_execution_id"] == failed["mutation_execution_id"]
    assert retried["attempts"][1]["parent_diff_review_id"] == failed["diff_review_id"]
    assert retried["attempts"][1]["failure_context_hash"]
    assert dry_run_agent.requests[-1].retry_context["next_attempt"] == 2
    assert dry_run_agent.requests[-1].retry_context["failed_required_verifications"][0]["status"] == "FAILED"
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "def broken(:\n"


def test_retry_apply_then_verify_can_recover_to_quality_passed(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="def broken(:\n"
    )
    task = prepare(gate.workflow_id).json()
    apply_task(task["task_execution_id"])
    failed = verify_task(task["task_execution_id"]).json()
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="value = 4\n"
    )
    retry = retry_task(failed["task_execution_id"]).json()

    applied = apply_task(retry["task_execution_id"], "AWAITING_EXECUTION_APPROVAL").json()
    verified = verify_task(retry["task_execution_id"], "APPLIED").json()

    assert applied["state"] == "APPLIED"
    assert verified["state"] == "QUALITY_PASSED"
    assert verified["current_attempt"] == 2
    assert verified["attempts"][1]["quality_status"] == "QUALITY_PASSED"
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "value = 4\n"


def test_retry_is_blocked_for_quality_passed_and_rolled_back(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task = prepare(gate.workflow_id).json()
    apply_task(task["task_execution_id"])
    passed = verify_task(task["task_execution_id"]).json()

    passed_retry = retry_task(passed["task_execution_id"], "QUALITY_PASSED")

    failed_workspace = tmp_path / "failed-workspace"
    failed_workspace.mkdir()
    failed_workspace.joinpath("sample.py").write_text("value = 1\n", encoding="utf-8", newline="\n")
    failed_gate = create_workflow(task_context, failed_workspace)
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="def broken(:\n"
    )
    failed_task = prepare(failed_gate.workflow_id).json()
    apply_task(failed_task["task_execution_id"])
    verify_task(failed_task["task_execution_id"])
    rolled_back = client.post(
        f"/api/v1/workflows/execution/task/{failed_task['task_execution_id']}/rollback",
        json={},
    ).json()
    rolled_back_retry = retry_task(rolled_back["task_execution_id"], "ROLLED_BACK")

    assert passed_retry.status_code == 409
    assert rolled_back_retry.status_code == 409


def test_retry_limit_blocks_fourth_attempt(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="def broken(:\n"
    )
    task = prepare(gate.workflow_id).json()
    apply_task(task["task_execution_id"])
    attempt1 = verify_task(task["task_execution_id"]).json()

    assert attempt1["state"] == "QUALITY_FAILED"

    for _ in range(2):
        retry = retry_task(task["task_execution_id"]).json()
        apply_task(task["task_execution_id"], "AWAITING_EXECUTION_APPROVAL")
        latest = verify_task(task["task_execution_id"], "APPLIED").json()

    blocked_retry = retry_task(task["task_execution_id"])

    assert latest["state"] == "RETRY_LIMIT_REACHED"
    assert latest["current_attempt"] == 3
    assert len(latest["attempts"]) == 3
    assert blocked_retry.status_code == 409
    assert len(task_context["service"].get(task["task_execution_id"]).attempts) == 3


def test_duplicate_retry_request_does_not_create_duplicate_attempt(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="def broken(:\n"
    )
    task = prepare(gate.workflow_id).json()
    apply_task(task["task_execution_id"])
    verify_task(task["task_execution_id"])
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="value = 5\n"
    )

    first = retry_task(task["task_execution_id"]).json()
    duplicate = retry_task(task["task_execution_id"], "AWAITING_EXECUTION_APPROVAL")

    assert first["current_attempt"] == 2
    assert duplicate.status_code == 409
    assert len(task_context["service"].get(task["task_execution_id"]).attempts) == 2


def test_retry_is_blocked_when_failed_execution_state_is_stale(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="def broken(:\n"
    )
    task = prepare(gate.workflow_id).json()
    apply_task(task["task_execution_id"])
    verify_task(task["task_execution_id"])
    workspace.joinpath("sample.py").write_text("value = 100\n", encoding="utf-8", newline="\n")

    retried = retry_task(task["task_execution_id"]).json()

    assert retried["state"] == "BLOCKED"
    assert retried["current_attempt"] == 1
    assert len(retried["attempts"]) == 1
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "value = 100\n"


def test_retry_model_failure_does_not_consume_attempt(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="def broken(:\n"
    )
    task = prepare(gate.workflow_id).json()
    apply_task(task["task_execution_id"])
    verify_task(task["task_execution_id"])
    task_context["service"].dry_run_agent = FakeDryRunAgent(fail=True)

    retried = retry_task(task["task_execution_id"]).json()

    assert retried["state"] == "QUALITY_FAILED"
    assert retried["current_attempt"] == 1
    assert len(retried["attempts"]) == 1
    assert "dry-run failed" in retried["blockers"][0]


def test_retry_attempt_lineage_survives_store_restart(tmp_path, task_context):
    workspace = create_workspace(tmp_path)
    gate = create_workflow(task_context, workspace)
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="def broken(:\n"
    )
    task = prepare(gate.workflow_id).json()
    apply_task(task["task_execution_id"])
    verify_task(task["task_execution_id"])
    task_context["service"].diff_preview_agent = FakeDiffAgent(
        task_context["execution_store"], proposed_content="value = 6\n"
    )
    retried = retry_task(task["task_execution_id"]).json()

    restarted = TaskExecutionStore(task_context["database"])
    reloaded = restarted.get(retried["task_execution_id"])

    assert reloaded.current_attempt == 2
    assert len(reloaded.attempts) == 2
    assert reloaded.attempts[1].parent_execution_id == retried["attempts"][1]["parent_execution_id"]
