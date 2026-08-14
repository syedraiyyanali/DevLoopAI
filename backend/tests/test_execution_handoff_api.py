import os
import shutil
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import execution_preflight as execution_endpoint
from app.main import app
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.planning_workflow import FinalReviewedPlanSummary
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidatorResponse
from app.services.execution_handoff import ExecutionHandoffService
from app.services.execution_preflight import ExecutionPreflightService
from app.services.planning_approval import PlanningApprovalStore
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def handoff_store(tmp_path, monkeypatch):
    store = PlanningApprovalStore(tmp_path / "handoff-history.sqlite3")
    workspace_service = WorkspaceService()
    preflight_service = ExecutionPreflightService(
        approval_store=store,
        workspace_service=workspace_service,
    )
    handoff_service = ExecutionHandoffService(
        approval_store=store,
        workspace_service=workspace_service,
        preflight_service=preflight_service,
    )
    monkeypatch.setattr(
        execution_endpoint,
        "get_handoff_service",
        lambda: handoff_service,
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


def planner_response(paths=None) -> PlannerResponse:
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
        files_likely_to_change=paths if paths is not None else ["src/app.ts"],
        tests_verification_required=["Run frontend lint."],
        risks=["Keep changes scoped."],
        dependencies_or_user_input_needed=[],
        model="qwen2.5-coder:7b",
    )


def reviewer_response(recommendation="APPROVE") -> ReviewerResponse:
    return ReviewerResponse(
        overall_assessment="The plan is safe to prepare for execution.",
        missing_steps=[],
        incorrect_assumptions=[],
        architecture_concerns=[],
        security_concerns=[],
        performance_concerns=[],
        testing_gaps=["Run frontend build."],
        unnecessary_changes=[],
        recommended_improvements=[],
        approval_recommendation=recommendation,
        model="qwen2.5-coder:7b",
    )


def validator_response(status="READY") -> ValidatorResponse:
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


def final_summary(status="READY") -> FinalReviewedPlanSummary:
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


def create_gate(store, workspace, *, paths=None, reviewer="APPROVE", validator="READY"):
    return store.create_gate(
        task="Add a safe status label.",
        workspace_path=str(workspace),
        planner_output=planner_response(paths),
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


def test_execution_handoff_created_for_approved_ready_preflight(
    tmp_path,
    handoff_store,
):
    workspace = create_workspace(tmp_path)
    gate = create_gate(handoff_store, workspace)
    approve_gate(handoff_store, gate)

    response = client.post(
        "/api/v1/workflows/execution/handoff",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == gate.workflow_id
    assert body["approved_plan_fingerprint"] == gate.plan_fingerprint
    assert body["workspace_path"] == str(workspace.resolve())
    assert body["preflight_result"]["status"] == "READY_FOR_EXECUTION"
    assert body["allowed_files"] == ["src/app.ts"]
    assert body["allowed_operation_types"] == [
        "read_file",
        "create_text_file",
        "modify_text_file",
    ]
    assert "Run frontend lint." in body["expected_tests"]
    assert "Run frontend build." in body["expected_tests"]
    assert body["rollback_backup_requirements"]["backup_required"] is True
    assert body["user_approval_metadata"]["approval_status"] == "APPROVED"
    assert body["execution_allowed"] is False


def test_execution_handoff_blocks_unapproved_workflow(tmp_path, handoff_store):
    workspace = create_workspace(tmp_path)
    gate = create_gate(handoff_store, workspace)

    response = client.post(
        "/api/v1/workflows/execution/handoff",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 409
    assert "Workflow must be APPROVED" in response.json()["error"]["message"]


def test_execution_handoff_blocks_stale_fingerprint(tmp_path, handoff_store):
    workspace = create_workspace(tmp_path)
    gate = create_gate(handoff_store, workspace)
    approve_gate(handoff_store, gate)

    with sqlite3.connect(handoff_store.database_path) as connection:
        connection.execute(
            "UPDATE planning_workflows SET plan_fingerprint = ? WHERE workflow_id = ?",
            ("0" * 64, gate.workflow_id),
        )

    response = client.post(
        "/api/v1/workflows/execution/handoff",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 409
    assert "Plan fingerprint does not match" in response.json()["error"]["message"]


def test_execution_handoff_blocks_failed_preflight(tmp_path, handoff_store):
    workspace = create_workspace(tmp_path)
    gate = create_gate(handoff_store, workspace)
    approve_gate(handoff_store, gate)
    target = workspace / "src" / "app.ts"
    target.write_text("export const status = 'changed';\n", encoding="utf-8")
    future_time = time.time() + 5
    os.utime(target, (future_time, future_time))

    response = client.post(
        "/api/v1/workflows/execution/handoff",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 409
    assert "Preflight must be READY_FOR_EXECUTION" in response.json()["error"]["message"]


def test_execution_handoff_blocks_path_outside_workspace(tmp_path, handoff_store):
    workspace = create_workspace(tmp_path)
    gate = create_gate(handoff_store, workspace, paths=["../outside.ts"])
    approve_gate(handoff_store, gate)

    response = client.post(
        "/api/v1/workflows/execution/handoff",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 409
    assert "Preflight must be READY_FOR_EXECUTION" in response.json()["error"]["message"]


def test_execution_handoff_blocks_ignored_secret_path(tmp_path, handoff_store):
    workspace = create_workspace(tmp_path)
    (workspace / ".env").write_text("SECRET=value\n", encoding="utf-8")
    gate = create_gate(handoff_store, workspace, paths=[".env"])
    approve_gate(handoff_store, gate)

    response = client.post(
        "/api/v1/workflows/execution/handoff",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 409
    assert "Preflight must be READY_FOR_EXECUTION" in response.json()["error"]["message"]


def test_execution_handoff_blocks_missing_workspace(tmp_path, handoff_store):
    workspace = create_workspace(tmp_path)
    gate = create_gate(handoff_store, workspace)
    approve_gate(handoff_store, gate)
    shutil.rmtree(workspace)

    response = client.post(
        "/api/v1/workflows/execution/handoff",
        json={"workflow_id": gate.workflow_id},
    )

    assert response.status_code == 409
    assert "Preflight must be READY_FOR_EXECUTION" in response.json()["error"]["message"]


def test_execution_handoff_returns_404_for_invalid_workflow_id(handoff_store):
    response = client.post(
        "/api/v1/workflows/execution/handoff",
        json={"workflow_id": "missing-workflow"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Workflow id is invalid."
