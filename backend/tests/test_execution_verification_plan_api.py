import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import execution_verification as verification_endpoint
from app.main import app
from app.models.execution_mutation import ExecutionApplyResponse, ExecutionFileResult
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.planning_workflow import FinalReviewedPlanSummary
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidatorResponse
from app.services.execution_store import ExecutionStore
from app.services.execution_verification import ExecutionVerificationRunner
from app.services.planning_approval import PlanningApprovalStore
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def plan_context(tmp_path, monkeypatch):
    database = tmp_path / "runtime" / "devloopai.sqlite3"
    execution_store = ExecutionStore(database)
    approval_store = PlanningApprovalStore(database)
    runner = ExecutionVerificationRunner(
        execution_store=execution_store,
        approval_store=approval_store,
        workspace_service=WorkspaceService(),
    )
    monkeypatch.setattr(
        verification_endpoint,
        "get_execution_verification_runner",
        lambda: runner,
    )
    return {"execution_store": execution_store, "approval_store": approval_store}


def create_workspace(tmp_path, files, *, with_pytest=False, with_frontend=False):
    workspace = tmp_path / f"workspace-{uuid4().hex[:8]}"
    workspace.mkdir()
    for relative_path, content in files.items():
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    if with_pytest:
        (workspace / "tests").mkdir(exist_ok=True)
        (workspace / "tests" / "test_sample.py").write_text(
            "def test_ok():\n    assert True\n",
            encoding="utf-8",
            newline="\n",
        )
    if with_frontend:
        (workspace / "package.json").write_text(
            json.dumps({"scripts": {"lint": "eslint .", "build": "next build"}}),
            encoding="utf-8",
        )
    return workspace


def create_execution(context, workspace: Path, relative_path: str, content: str):
    planner = PlannerResponse(
        task_summary="Apply a disposable verified change.",
        assumptions=[],
        detected_project_context=PlannerProjectContext(
            workspace_name=workspace.name,
            project_types=[],
            frameworks=[],
            languages={},
        ),
        implementation_steps=["Modify approved disposable files."],
        files_likely_to_change=[relative_path],
        tests_verification_required=["Run allowlisted verification."],
        risks=[],
        dependencies_or_user_input_needed=[],
        model="test-model",
    )
    reviewer = ReviewerResponse(
        overall_assessment="Scoped disposable change.",
        missing_steps=[],
        incorrect_assumptions=[],
        architecture_concerns=[],
        security_concerns=[],
        performance_concerns=[],
        testing_gaps=[],
        unnecessary_changes=[],
        recommended_improvements=[],
        approval_recommendation="APPROVE",
        model="test-model",
    )
    validator = ValidatorResponse(
        overall_validation_status="READY",
        plan_completeness=["Complete."],
        file_path_validity=[],
        dependency_concerns=[],
        environment_tool_requirements=[],
        security_concerns=[],
        destructive_operation_warnings=[],
        missing_user_information=[],
        test_verification_readiness=["Run allowlisted verification."],
        blockers=[],
        final_execution_readiness="Ready.",
        model="test-model",
    )
    summary = FinalReviewedPlanSummary(
        final_recommendation="READY",
        final_execution_readiness="Ready.",
        execution_ready=False,
        required_changes_before_execution=[],
        blockers=[],
        warnings=[],
        risks=[],
        tests_expected=["Run allowlisted verification."],
        user_approval_required=True,
        summary="Reviewed disposable change.",
    )
    gate = context["approval_store"].create_gate(
        task="Apply a disposable verified change.",
        workspace_path=str(workspace),
        planner_output=planner,
        reviewer_output=reviewer,
        validator_output=validator,
        final_reviewed_summary=summary,
        blockers=[],
    )
    context["approval_store"].approve(
        approval_id=gate.approval_id,
        approval_token=gate.approval_token,
        plan_fingerprint=gate.plan_fingerprint,
    )

    target = workspace / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    file_result = ExecutionFileResult(
        relative_path=relative_path,
        operation_type="modify_text_file",
        status="CHANGED",
        original_content_hash="0" * 64,
        proposed_content_hash=digest,
        final_content_hash=digest,
        backup_location=str(context["execution_store"].backup_root / "backup.txt"),
        backup_status="CREATED",
    )
    execution_id = str(uuid4())
    context["execution_store"].create_execution(
        execution_id=execution_id,
        workflow_id=gate.workflow_id,
        plan_fingerprint=gate.plan_fingerprint,
        diff_review_id="review-1",
        diff_fingerprint="f" * 64,
        workspace_path=str(workspace),
        created_at="2026-08-20T00:00:00Z",
    )
    context["execution_store"].record_file(
        execution_id=execution_id,
        ordinal=0,
        result=file_result,
    )
    response = ExecutionApplyResponse(
        execution_id=execution_id,
        workflow_id=gate.workflow_id,
        workspace_path=str(workspace),
        status="EXECUTED",
        files_attempted=[relative_path],
        files_changed=[relative_path],
        file_results=[file_result],
        backup_status="CREATED",
        rollback_available=True,
        execution_timestamp="2026-08-20T00:00:00Z",
        message="Synthetic execution.",
    )
    context["execution_store"].complete_execution(response)
    return response


def get_plan(execution_id: str):
    return client.get(f"/api/v1/workflows/execution/{execution_id}/verification-plan")


def test_python_change_selects_compile_only_without_pytest_project(tmp_path, plan_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(plan_context, workspace, "sample.py", "value = 2\n")

    body = get_plan(execution.execution_id).json()

    assert body["required_verification_types"] == ["python_compile"]
    assert body["skipped_verification_types"] == ["pytest", "frontend_lint", "frontend_build"]
    compile_check = next(item for item in body["checks"] if item["verification_type"] == "python_compile")
    assert compile_check["tier"] == "required"
    assert "syntax compilation" in compile_check["reason"]


def test_python_change_selects_pytest_when_project_has_tests(tmp_path, plan_context):
    workspace = create_workspace(
        tmp_path,
        {"sample.py": "value = 1\n"},
        with_pytest=True,
    )
    execution = create_execution(plan_context, workspace, "sample.py", "value = 2\n")

    body = get_plan(execution.execution_id).json()

    assert body["required_verification_types"] == ["python_compile", "pytest"]
    pytest_check = next(item for item in body["checks"] if item["verification_type"] == "pytest")
    assert pytest_check["selected_by_default"] is True


def test_frontend_change_selects_lint_and_build_when_scripts_exist(tmp_path, plan_context):
    workspace = create_workspace(
        tmp_path,
        {"src/app.tsx": "export const value = 1;\n"},
        with_frontend=True,
    )
    execution = create_execution(plan_context, workspace, "src/app.tsx", "export const value = 2;\n")

    body = get_plan(execution.execution_id).json()

    assert body["required_verification_types"] == ["frontend_lint", "frontend_build"]
    assert body["skipped_verification_types"] == ["python_compile", "pytest"]


def test_generic_change_returns_no_required_checks_with_warning(tmp_path, plan_context):
    workspace = create_workspace(tmp_path, {"README.md": "# Demo\n"})
    execution = create_execution(plan_context, workspace, "README.md", "# Demo 2\n")

    body = get_plan(execution.execution_id).json()

    assert body["required_verification_types"] == []
    assert body["warnings"] == [
        "No required allowlisted verification was selected for the changed file types."
    ]


def test_invalid_execution_id_returns_not_found(plan_context):
    response = get_plan("missing")

    assert response.status_code == 404
