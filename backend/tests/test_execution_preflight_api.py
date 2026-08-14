import os
import shutil
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import execution_preflight as execution_preflight_endpoint
from app.main import app
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.planning_workflow import FinalReviewedPlanSummary
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidatorResponse
from app.services.execution_preflight import ExecutionPreflightService
from app.services.planning_approval import PlanningApprovalStore
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def preflight_store(tmp_path, monkeypatch):
    store = PlanningApprovalStore(tmp_path / "preflight-history.sqlite3")
    service = ExecutionPreflightService(
        approval_store=store,
        workspace_service=WorkspaceService(),
    )
    monkeypatch.setattr(
        execution_preflight_endpoint,
        "get_preflight_service",
        lambda: service,
    )
    return store


def create_workspace(tmp_path):
    workspace = tmp_path / "sample-project"
    source_dir = workspace / "src"
    source_dir.mkdir(parents=True)
    (workspace / "package.json").write_text(
        '{"dependencies":{"next":"16.2.10"},"devDependencies":{}}',
        encoding="utf-8",
    )
    (source_dir / "app.ts").write_text("export const status = 'ready';\n", encoding="utf-8")
    return workspace


def planner_response() -> PlannerResponse:
    return PlannerResponse(
        task_summary="Add a safe status label.",
        assumptions=["The source file exists."],
        detected_project_context=PlannerProjectContext(
            workspace_name="sample-project",
            project_types=["Node.js"],
            frameworks=["Next.js"],
            languages={"TypeScript": 1},
        ),
        implementation_steps=["Inspect src/app.ts.", "Add the status label."],
        files_likely_to_change=["src/app.ts"],
        tests_verification_required=["Run frontend lint."],
        risks=["Keep changes scoped."],
        dependencies_or_user_input_needed=[],
        model="qwen2.5-coder:7b",
    )


def reviewer_response(recommendation: str = "APPROVE") -> ReviewerResponse:
    return ReviewerResponse(
        overall_assessment="The plan is safe to prepare for execution.",
        missing_steps=[],
        incorrect_assumptions=[],
        architecture_concerns=[],
        security_concerns=[],
        performance_concerns=[],
        testing_gaps=[],
        unnecessary_changes=[],
        recommended_improvements=[],
        approval_recommendation=recommendation,
        model="qwen2.5-coder:7b",
    )


def validator_response(status: str = "READY") -> ValidatorResponse:
    return ValidatorResponse(
        overall_validation_status=status,
        plan_completeness=["Plan has implementation and verification steps."],
        file_path_validity=["src/app.ts: path exists."],
        dependency_concerns=[],
        environment_tool_requirements=["Run frontend lint."],
        security_concerns=[],
        destructive_operation_warnings=[],
        missing_user_information=[],
        test_verification_readiness=["Run frontend lint."],
        blockers=(["Execution is blocked."] if status == "BLOCKED" else []),
        final_execution_readiness=(
            "Reviewed plan is ready for future execution."
            if status == "READY"
            else "Reviewed plan is blocked."
        ),
        model="qwen2.5-coder:7b",
    )


def final_summary(status: str = "READY") -> FinalReviewedPlanSummary:
    return FinalReviewedPlanSummary(
        final_recommendation=status,
        final_execution_readiness="Reviewed plan is ready for future execution.",
        execution_ready=False,
        required_changes_before_execution=[],
        blockers=[],
        warnings=[],
        risks=[],
        tests_expected=["Run frontend lint."],
        user_approval_required=True,
        summary="Planner, reviewer, and validator completed.",
    )


def create_gate(store, workspace, *, reviewer="APPROVE", validator="READY"):
    return store.create_gate(
        task="Add a safe status label.",
        workspace_path=str(workspace) if workspace is not None else None,
        planner_output=planner_response(),
        reviewer_output=reviewer_response(reviewer),
        validator_output=validator_response(validator),
        final_reviewed_summary=final_summary(validator),
        blockers=(["Execution is blocked."] if validator == "BLOCKED" else []),
    )


def approve_gate(store, gate):
    return store.approve(
        approval_id=gate.approval_id,
        approval_token=gate.approval_token,
        plan_fingerprint=gate.plan_fingerprint,
    )


def test_execution_preflight_ready_for_approved_valid_workflow(tmp_path, preflight_store):
    workspace = create_workspace(tmp_path)
    gate = create_gate(preflight_store, workspace)
    approve_gate(preflight_store, gate)

    response = client.post(
        "/api/v1/workflows/execution/preflight",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY_FOR_EXECUTION"
    assert body["fingerprint"]["matches"] is True
    assert body["workspace"]["exists"] is True
    assert body["blockers"] == []
    assert body["file_checks"][0]["relative_path"] == "src/app.ts"
    assert body["file_checks"][0]["exists"] is True


def test_execution_preflight_blocks_unapproved_workflow(tmp_path, preflight_store):
    workspace = create_workspace(tmp_path)
    gate = create_gate(preflight_store, workspace)

    response = client.post(
        "/api/v1/workflows/execution/preflight",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "BLOCKED"
    assert response.json()["approval_status"] == "PENDING_APPROVAL"


def test_execution_preflight_blocks_rejected_workflow(tmp_path, preflight_store):
    workspace = create_workspace(tmp_path)
    gate = create_gate(preflight_store, workspace)
    preflight_store.reject(
        approval_id=gate.approval_id,
        approval_token=gate.approval_token,
        plan_fingerprint=gate.plan_fingerprint,
    )

    response = client.post(
        "/api/v1/workflows/execution/preflight",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "BLOCKED"
    assert response.json()["approval_status"] == "REJECTED"


def test_execution_preflight_requires_reapproval_for_stale_fingerprint(
    tmp_path,
    preflight_store,
):
    workspace = create_workspace(tmp_path)
    gate = create_gate(preflight_store, workspace)
    approve_gate(preflight_store, gate)

    with sqlite3.connect(preflight_store.database_path) as connection:
        connection.execute(
            "UPDATE planning_workflows SET plan_fingerprint = ? WHERE workflow_id = ?",
            ("0" * 64, gate.workflow_id),
        )

    response = client.post(
        "/api/v1/workflows/execution/preflight",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "REAPPROVAL_REQUIRED"
    assert response.json()["fingerprint"]["matches"] is False


def test_execution_preflight_blocks_missing_workspace(tmp_path, preflight_store):
    workspace = create_workspace(tmp_path)
    gate = create_gate(preflight_store, workspace)
    approve_gate(preflight_store, gate)
    shutil.rmtree(workspace)

    response = client.post(
        "/api/v1/workflows/execution/preflight",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "BLOCKED"
    assert response.json()["workspace"]["exists"] is False


def test_execution_preflight_requires_reapproval_when_relevant_file_changed(
    tmp_path,
    preflight_store,
):
    workspace = create_workspace(tmp_path)
    gate = create_gate(preflight_store, workspace)
    approve_gate(preflight_store, gate)
    target = workspace / "src" / "app.ts"
    target.write_text("export const status = 'changed';\n", encoding="utf-8")
    future_time = time.time() + 5
    os.utime(target, (future_time, future_time))

    response = client.post(
        "/api/v1/workflows/execution/preflight",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REAPPROVAL_REQUIRED"
    assert body["file_checks"][0]["modified_after_approval"] is True
    assert any("src/app.ts" in change for change in body["detected_changes"])


def test_execution_preflight_requires_reapproval_when_validated_file_is_missing(
    tmp_path,
    preflight_store,
):
    workspace = create_workspace(tmp_path)
    gate = create_gate(preflight_store, workspace)
    approve_gate(preflight_store, gate)
    (workspace / "src" / "app.ts").unlink()

    response = client.post(
        "/api/v1/workflows/execution/preflight",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "REAPPROVAL_REQUIRED"
    assert response.json()["file_checks"][0]["kind"] == "missing"


def test_execution_preflight_returns_404_for_invalid_workflow_id(preflight_store):
    response = client.post(
        "/api/v1/workflows/execution/preflight",
        json={"workflow_id": "missing-workflow"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Workflow id is invalid."


def test_execution_preflight_persisted_workflow_survives_store_restart(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "persistent-preflight.sqlite3"
    workspace = create_workspace(tmp_path)
    first_store = PlanningApprovalStore(database_path)
    gate = create_gate(first_store, workspace)
    approve_gate(first_store, gate)
    second_store = PlanningApprovalStore(database_path)
    service = ExecutionPreflightService(
        approval_store=second_store,
        workspace_service=WorkspaceService(),
    )
    monkeypatch.setattr(
        execution_preflight_endpoint,
        "get_preflight_service",
        lambda: service,
    )

    response = client.post(
        "/api/v1/workflows/execution/preflight",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "READY_FOR_EXECUTION"
