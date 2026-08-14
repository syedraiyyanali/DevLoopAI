import difflib

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import execution_mutation as mutation_endpoint
from app.main import app
from app.models.coder import (
    CoderDiffPreviewResponse,
    CoderDryRunOperation,
    CoderDryRunResponse,
    CoderFileDiffPreview,
)
from app.models.execution_handoff import ExecutionHandoffRequest
from app.models.execution_mutation import ExecutionApplyRequest, ExecutionRollbackRequest
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.planning_workflow import FinalReviewedPlanSummary
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidatorResponse
from app.services.execution_handoff import ExecutionHandoffBlockedError, ExecutionHandoffService
from app.services.execution_mutation import ExecutionMutationBlockedError, ExecutionMutationService
from app.services.execution_preflight import ExecutionPreflightService
from app.services.execution_store import ExecutionRecordNotFoundError, ExecutionStore
from app.services.planning_approval import PlanningApprovalStore
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


def planner(paths, *, delete=False):
    return PlannerResponse(
        task_summary="Delete files." if delete else "Update approved text files.",
        assumptions=[],
        detected_project_context=PlannerProjectContext(
            workspace_name="sample", project_types=[], frameworks=[], languages={}
        ),
        implementation_steps=[
            ("Delete " if delete else "Update ") + path for path in paths
        ],
        files_likely_to_change=paths,
        tests_verification_required=["Inspect changed text."],
        risks=[],
        dependencies_or_user_input_needed=[],
        model="test-model",
    )


def reviewer():
    return ReviewerResponse(
        overall_assessment="Scoped change.", missing_steps=[], incorrect_assumptions=[],
        architecture_concerns=[], security_concerns=[], performance_concerns=[],
        testing_gaps=[], unnecessary_changes=[], recommended_improvements=[],
        approval_recommendation="APPROVE", model="test-model",
    )


def validator():
    return ValidatorResponse(
        overall_validation_status="READY", plan_completeness=["Complete."],
        file_path_validity=[], dependency_concerns=[], environment_tool_requirements=[],
        security_concerns=[], destructive_operation_warnings=[], missing_user_information=[],
        test_verification_readiness=["Inspect changed text."], blockers=[],
        final_execution_readiness="Ready.", model="test-model",
    )


def summary():
    return FinalReviewedPlanSummary(
        final_recommendation="READY", final_execution_readiness="Ready.",
        execution_ready=False, required_changes_before_execution=[], blockers=[], warnings=[],
        risks=[], tests_expected=["Inspect changed text."], user_approval_required=True,
        summary="Reviewed and ready.",
    )


@pytest.fixture
def mutation_context(tmp_path, monkeypatch):
    database = tmp_path / "runtime" / "devloopai.sqlite3"
    approval_store = PlanningApprovalStore(database)
    execution_store = ExecutionStore(database)
    workspace_service = WorkspaceService()
    preflight = ExecutionPreflightService(
        approval_store=approval_store, workspace_service=workspace_service
    )
    handoff_service = ExecutionHandoffService(
        approval_store=approval_store,
        workspace_service=workspace_service,
        preflight_service=preflight,
    )
    service = ExecutionMutationService(
        handoff_service=handoff_service,
        workspace_service=workspace_service,
        execution_store=execution_store,
    )
    monkeypatch.setattr(mutation_endpoint, "get_execution_mutation_service", lambda: service)
    return {
        "approval_store": approval_store,
        "execution_store": execution_store,
        "handoff_service": handoff_service,
        "service": service,
    }


def create_workspace(tmp_path, files):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for path, content in files.items():
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return workspace


def create_pipeline(context, workspace, changes, *, approve=True, delete=False):
    paths = list(changes)
    gate = context["approval_store"].create_gate(
        task="Update approved text files.", workspace_path=str(workspace),
        planner_output=planner(paths, delete=delete), reviewer_output=reviewer(),
        validator_output=validator(), final_reviewed_summary=summary(), blockers=[],
    )
    if approve:
        context["approval_store"].approve(
            approval_id=gate.approval_id,
            approval_token=gate.approval_token,
            plan_fingerprint=gate.plan_fingerprint,
        )
    if not approve:
        return gate, None

    handoff = context["handoff_service"].create_handoff(
        ExecutionHandoffRequest(workflow_id=gate.workflow_id)
    )
    operations = []
    previews = []
    for path, proposed in changes.items():
        target = workspace / path
        operation = "modify_text_file" if target.exists() else "create_text_file"
        if delete:
            operation = "delete_text_file"
        current = target.read_bytes().decode("utf-8") if target.exists() else None
        operations.append(
            CoderDryRunOperation(
                operation_type=operation,
                relative_path=path,
                description="Apply reviewed text.",
            )
        )
        previews.append(
            CoderFileDiffPreview(
                relative_path=path,
                operation_type=operation,
                current_content=current,
                proposed_content=None if delete else proposed,
                unified_diff=make_diff(path, current, None if delete else proposed),
            )
        )
    dry_run = CoderDryRunResponse(
        workflow_id=gate.workflow_id,
        approved_plan_fingerprint=gate.plan_fingerprint,
        workspace_path=str(workspace.resolve()),
        files_would_modify=[p for p in paths if (workspace / p).exists() and not delete],
        files_would_create=[p for p in paths if not (workspace / p).exists() and not delete],
        files_would_delete=paths if delete else [],
        intended_operations=operations,
        proposed_code_change_summary="Apply exact reviewed content.",
        dependencies_required=[], tests_to_run=[], rollback_backup_plan=[], warnings=[], blockers=[],
        model="test-model", message="Dry run only.",
    )
    preview = CoderDiffPreviewResponse(
        workflow_id=gate.workflow_id,
        approved_plan_fingerprint=gate.plan_fingerprint,
        workspace_path=str(workspace.resolve()),
        file_previews=previews,
        warnings=[], blockers=[], model="test-model", message="Preview only.",
    )
    preview = context["execution_store"].record_diff_review(preview)
    return gate, ExecutionApplyRequest(handoff=handoff, dry_run=dry_run, diff_preview=preview)


def make_diff(path, current, proposed):
    before = [] if current is None else current.splitlines(keepends=True)
    after = [] if proposed is None else proposed.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="")
    )


def test_valid_modify_creates_backup_writes_and_persists(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {"sample.txt": "before\n"})
    _, request = create_pipeline(mutation_context, workspace, {"sample.txt": "after\n"})
    response = client.post("/api/v1/workflows/execution/apply", json=request.model_dump(mode="json"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "EXECUTED"
    assert workspace.joinpath("sample.txt").read_text(encoding="utf-8") == "after\n"
    assert body["file_results"][0]["backup_status"] == "CREATED"
    assert body["file_results"][0]["backup_location"]
    assert mutation_context["execution_store"].get_execution(body["execution_id"]).status == "EXECUTED"


def test_valid_create_records_previous_absence(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {})
    _, request = create_pipeline(mutation_context, workspace, {"sample.txt": "created\n"})
    result = mutation_context["service"].apply(request)
    assert result.status == "EXECUTED"
    assert workspace.joinpath("sample.txt").read_text(encoding="utf-8") == "created\n"
    assert result.file_results[0].backup_status == "NOT_REQUIRED"
    assert result.file_results[0].original_content_hash is None


def test_unapproved_workflow_is_blocked(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {"sample.txt": "before\n"})
    gate, _ = create_pipeline(mutation_context, workspace, {"sample.txt": "after\n"}, approve=False)
    with pytest.raises(ExecutionHandoffBlockedError):
        mutation_context["handoff_service"].create_handoff(
            ExecutionHandoffRequest(workflow_id=gate.workflow_id)
        )


def test_invalid_fingerprint_is_blocked(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {"sample.txt": "before\n"})
    _, request = create_pipeline(mutation_context, workspace, {"sample.txt": "after\n"})
    request.dry_run.approved_plan_fingerprint = "0" * 64
    with pytest.raises(ExecutionMutationBlockedError, match="fingerprint"):
        mutation_context["service"].apply(request)


def test_tampered_reviewed_content_is_blocked(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {"sample.txt": "before\n"})
    _, request = create_pipeline(mutation_context, workspace, {"sample.txt": "after\n"})
    request.diff_preview.file_previews[0].proposed_content = "unreviewed\n"
    with pytest.raises(ExecutionMutationBlockedError, match="diff preview differs"):
        mutation_context["service"].apply(request)


def test_preflight_failure_is_blocked(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {"sample.txt": "before\n"})
    _, request = create_pipeline(mutation_context, workspace, {"sample.txt": "after\n"})
    workspace.joinpath("sample.txt").write_text("changed\n", encoding="utf-8")
    result = mutation_context["service"].apply(request)
    assert result.status == "REVIEW_STALE"
    assert result.files_changed == []


def test_stale_file_since_review_is_not_overwritten(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {"sample.txt": "before\n"})
    _, request = create_pipeline(mutation_context, workspace, {"sample.txt": "after\n"})
    workspace.joinpath("sample.txt").write_text("newer\n", encoding="utf-8")
    result = mutation_context["service"].apply(request)
    assert result.status == "REVIEW_STALE"
    assert workspace.joinpath("sample.txt").read_text(encoding="utf-8") == "newer\n"


@pytest.mark.parametrize("path", ["../outside.txt", ".env", "node_modules/file.txt"])
def test_unsafe_paths_are_blocked(tmp_path, mutation_context, path):
    workspace = create_workspace(tmp_path, {})
    gate = mutation_context["approval_store"].create_gate(
        task="Unsafe", workspace_path=str(workspace), planner_output=planner([path]),
        reviewer_output=reviewer(), validator_output=validator(),
        final_reviewed_summary=summary(), blockers=[],
    )
    mutation_context["approval_store"].approve(
        approval_id=gate.approval_id, approval_token=gate.approval_token,
        plan_fingerprint=gate.plan_fingerprint,
    )
    with pytest.raises(ExecutionHandoffBlockedError):
        mutation_context["handoff_service"].create_handoff(
            ExecutionHandoffRequest(workflow_id=gate.workflow_id)
        )


def test_delete_operation_remains_blocked(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {"sample.txt": "before\n"})
    _, request = create_pipeline(
        mutation_context, workspace, {"sample.txt": ""}, delete=True
    )
    with pytest.raises(ExecutionMutationBlockedError, match="disabled"):
        mutation_context["service"].apply(request)


def test_backup_failure_causes_no_mutation(tmp_path, mutation_context, monkeypatch):
    workspace = create_workspace(tmp_path, {"sample.txt": "before\n"})
    _, request = create_pipeline(mutation_context, workspace, {"sample.txt": "after\n"})
    monkeypatch.setattr(
        mutation_context["service"], "_create_snapshot",
        lambda *args: (_ for _ in ()).throw(OSError("backup failed")),
    )
    result = mutation_context["service"].apply(request)
    assert result.status == "BLOCKED"
    assert workspace.joinpath("sample.txt").read_text(encoding="utf-8") == "before\n"


def test_multi_file_write_failure_rolls_back_prior_mutation(tmp_path, mutation_context, monkeypatch):
    workspace = create_workspace(tmp_path, {"a.txt": "a-before\n", "b.txt": "b-before\n"})
    _, request = create_pipeline(
        mutation_context, workspace, {"a.txt": "a-after\n", "b.txt": "b-after\n"}
    )
    original_write = mutation_context["service"]._atomic_write

    def fail_second_target(target, content):
        if target == workspace / "b.txt":
            raise OSError("write failed")
        original_write(target, content)

    monkeypatch.setattr(mutation_context["service"], "_atomic_write", fail_second_target)
    result = mutation_context["service"].apply(request)
    assert result.status == "PARTIALLY_FAILED_AND_ROLLED_BACK"
    assert workspace.joinpath("a.txt").read_text(encoding="utf-8") == "a-before\n"
    assert workspace.joinpath("b.txt").read_text(encoding="utf-8") == "b-before\n"


def test_rollback_restores_modified_file_and_is_idempotent(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {"sample.txt": "before\n"})
    _, request = create_pipeline(mutation_context, workspace, {"sample.txt": "after\n"})
    execution = mutation_context["service"].apply(request)
    first = mutation_context["service"].rollback(
        ExecutionRollbackRequest(execution_id=execution.execution_id)
    )
    second = mutation_context["service"].rollback(
        ExecutionRollbackRequest(execution_id=execution.execution_id)
    )
    assert first.status == second.status == "ROLLED_BACK"
    assert workspace.joinpath("sample.txt").read_text(encoding="utf-8") == "before\n"


def test_rollback_removes_created_file(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {})
    _, request = create_pipeline(mutation_context, workspace, {"sample.txt": "created\n"})
    execution = mutation_context["service"].apply(request)
    rollback = mutation_context["service"].rollback(
        ExecutionRollbackRequest(execution_id=execution.execution_id)
    )
    assert rollback.status == "ROLLED_BACK"
    assert not workspace.joinpath("sample.txt").exists()


def test_invalid_execution_id_is_not_found(mutation_context):
    response = client.post(
        "/api/v1/workflows/execution/rollback", json={"execution_id": "missing"}
    )
    assert response.status_code == 404


def test_execution_persists_across_store_restart(tmp_path, mutation_context):
    workspace = create_workspace(tmp_path, {"sample.txt": "before\n"})
    _, request = create_pipeline(mutation_context, workspace, {"sample.txt": "after\n"})
    execution = mutation_context["service"].apply(request)
    restarted = ExecutionStore(mutation_context["execution_store"].database_path)
    assert restarted.get_execution(execution.execution_id).status == "EXECUTED"
