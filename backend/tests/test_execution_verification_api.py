import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import execution_verification as verification_endpoint
from app.main import app
from app.models.execution_mutation import ExecutionApplyResponse, ExecutionFileResult
from app.models.execution_verification import ExecutionVerificationRequest
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.planning_workflow import FinalReviewedPlanSummary
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidatorResponse
from app.services.execution_store import ExecutionStore
from app.services.execution_verification import (
    ExecutionVerificationRunner,
    VerificationCommand,
    VerificationDefinition,
)
from app.services.planning_approval import PlanningApprovalStore
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def verification_context(tmp_path, monkeypatch):
    database = tmp_path / "runtime" / "devloopai.sqlite3"
    execution_store = ExecutionStore(database)
    approval_store = PlanningApprovalStore(database)
    runner = ExecutionVerificationRunner(
        execution_store=execution_store,
        approval_store=approval_store,
        workspace_service=WorkspaceService(),
    )
    runner.registry = dict(runner.registry)
    monkeypatch.setattr(
        verification_endpoint,
        "get_execution_verification_runner",
        lambda: runner,
    )
    return {
        "database": database,
        "execution_store": execution_store,
        "approval_store": approval_store,
        "runner": runner,
    }


def create_workspace(tmp_path, files):
    workspace = tmp_path / f"workspace-{uuid4().hex[:8]}"
    workspace.mkdir()
    for relative_path, content in files.items():
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    return workspace


def create_execution(context, workspace, *, status="EXECUTED", audit_workspace=None):
    paths = [
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(workspace).parts)
    ]
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
        files_likely_to_change=paths,
        tests_verification_required=["Run allowlisted verification."],
        risks=[],
        dependencies_or_user_input_needed=[],
        model="test-model",
    )
    reviewer = ReviewerResponse(
        overall_assessment="Scoped disposable change.",
        missing_steps=[], incorrect_assumptions=[], architecture_concerns=[],
        security_concerns=[], performance_concerns=[], testing_gaps=[],
        unnecessary_changes=[], recommended_improvements=[],
        approval_recommendation="APPROVE", model="test-model",
    )
    validator = ValidatorResponse(
        overall_validation_status="READY", plan_completeness=["Complete."],
        file_path_validity=[], dependency_concerns=[], environment_tool_requirements=[],
        security_concerns=[], destructive_operation_warnings=[], missing_user_information=[],
        test_verification_readiness=["Run allowlisted verification."], blockers=[],
        final_execution_readiness="Ready.", model="test-model",
    )
    summary = FinalReviewedPlanSummary(
        final_recommendation="READY", final_execution_readiness="Ready.",
        execution_ready=False, required_changes_before_execution=[], blockers=[], warnings=[],
        risks=[], tests_expected=["Run allowlisted verification."],
        user_approval_required=True, summary="Reviewed disposable change.",
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

    execution_id = str(uuid4())
    recorded_workspace = str((audit_workspace or workspace).resolve())
    context["execution_store"].create_execution(
        execution_id=execution_id,
        workflow_id=gate.workflow_id,
        plan_fingerprint=gate.plan_fingerprint,
        diff_review_id="test-review",
        diff_fingerprint="f" * 64,
        workspace_path=recorded_workspace,
        created_at="2026-08-15T00:00:00Z",
    )
    file_results = []
    for ordinal, path in enumerate(paths):
        content = (workspace / path).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        result = ExecutionFileResult(
            relative_path=path,
            operation_type="modify_text_file",
            status="CHANGED" if status == "EXECUTED" else "ROLLED_BACK",
            original_content_hash="0" * 64,
            proposed_content_hash=digest,
            final_content_hash=digest,
            backup_location=str(context["execution_store"].backup_root / execution_id / path),
            backup_status="CREATED",
        )
        context["execution_store"].record_file(
            execution_id=execution_id,
            ordinal=ordinal,
            result=result,
        )
        file_results.append(result)

    response = ExecutionApplyResponse(
        execution_id=execution_id,
        workflow_id=gate.workflow_id,
        workspace_path=recorded_workspace,
        status=status,
        files_attempted=paths,
        files_changed=paths if status == "EXECUTED" else [],
        file_results=file_results,
        backup_status="Test audit.",
        rollback_available=status == "EXECUTED",
        execution_timestamp="2026-08-15T00:00:00Z",
        message="Disposable execution audit.",
    )
    context["execution_store"].complete_execution(response)
    return response


def post_verify(execution_id, verification_types):
    return client.post(
        f"/api/v1/workflows/execution/{execution_id}/verify",
        json={"verification_types": verification_types},
    )


def test_successful_python_compile_verification(tmp_path, verification_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(verification_context, workspace)
    response = post_verify(execution.execution_id, ["python_compile"])
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "PASSED"
    assert result["command_identity"] == "python_compile:v1"
    assert "Checked 1 Python files." in result["stdout_excerpt"]
    assert result["rollback_recommended"] is False


def test_failed_verification_recommends_rollback(tmp_path, verification_context):
    workspace = create_workspace(tmp_path, {"sample.py": "def broken(:\n"})
    execution = create_execution(verification_context, workspace)
    result = post_verify(execution.execution_id, ["python_compile"]).json()["results"][0]
    assert result["status"] == "FAILED"
    assert result["exit_code"] == 1
    assert "invalid syntax" in result["stderr_excerpt"]
    assert result["rollback_recommended"] is True


def test_timeout_terminates_verification(tmp_path, verification_context, monkeypatch):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(verification_context, workspace)
    runner = verification_context["runner"]
    runner.registry["python_compile"] = VerificationDefinition(
        command_identity="python_compile:v1",
        timeout_seconds=0.05,
        resolver_name="_resolve_python_compile",
    )
    monkeypatch.setattr(
        runner,
        "_resolve_python_compile",
        lambda root: (
            VerificationCommand(
                arguments=[sys.executable, "-I", "-c", "import time; time.sleep(10)"],
                working_directory=root,
            ),
            None,
        ),
    )
    result = post_verify(execution.execution_id, ["python_compile"]).json()["results"][0]
    assert result["status"] == "TIMED_OUT"
    assert result["rollback_recommended"] is True
    assert result["duration_seconds"] < 3


@pytest.mark.parametrize(
    "verification_type",
    ["unknown", "python_compile; Remove-Item sample.py", "pytest && whoami"],
)
def test_unsupported_or_injected_command_identifier_is_blocked(
    tmp_path, verification_context, verification_type
):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(verification_context, workspace)
    result = post_verify(execution.execution_id, [verification_type]).json()["results"][0]
    assert result["status"] == "BLOCKED"
    assert result["command_identity"] == "unrecognized"
    assert "allowlist" in result["blockers"][0]


def test_invalid_execution_id_returns_not_found(verification_context):
    response = post_verify("missing", ["python_compile"])
    assert response.status_code == 404


@pytest.mark.parametrize("status", ["BLOCKED", "ROLLED_BACK"])
def test_non_executed_or_rolled_back_execution_is_blocked(
    tmp_path, verification_context, status
):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(verification_context, workspace, status=status)
    result = post_verify(execution.execution_id, ["python_compile"]).json()["results"][0]
    assert result["status"] == "BLOCKED"
    assert "EXECUTED" in result["blockers"][0]


def test_workspace_outside_approved_root_is_blocked(tmp_path, verification_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    outside = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(
        verification_context,
        workspace,
        audit_workspace=outside,
    )
    result = post_verify(execution.execution_id, ["python_compile"]).json()["results"][0]
    assert result["status"] == "BLOCKED"
    assert any("approved workspace" in blocker for blocker in result["blockers"])


def test_registry_working_directory_escape_is_blocked(
    tmp_path, verification_context, monkeypatch
):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    outside = create_workspace(tmp_path, {})
    execution = create_execution(verification_context, workspace)
    monkeypatch.setattr(
        verification_context["runner"],
        "_resolve_python_compile",
        lambda root: (
            VerificationCommand(
                arguments=[sys.executable, "-I", "-c", "print('must not run')"],
                working_directory=outside,
            ),
            None,
        ),
    )
    result = post_verify(execution.execution_id, ["python_compile"]).json()["results"][0]
    assert result["status"] == "BLOCKED"
    assert "outside the approved workspace" in result["blockers"][0]


def test_changed_file_hash_mismatch_is_blocked(tmp_path, verification_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(verification_context, workspace)
    workspace.joinpath("sample.py").write_bytes(b"value = 2\n")
    result = post_verify(execution.execution_id, ["python_compile"]).json()["results"][0]
    assert result["status"] == "BLOCKED"
    assert result["rollback_recommended"] is True
    assert "execution audit" in result["blockers"][0]


def test_stale_workflow_fingerprint_is_blocked(tmp_path, verification_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(verification_context, workspace)
    with sqlite3.connect(verification_context["database"]) as connection:
        connection.execute(
            "UPDATE planning_workflows SET plan_fingerprint = ? WHERE workflow_id = ?",
            ("0" * 64, execution.workflow_id),
        )
    result = post_verify(execution.execution_id, ["python_compile"]).json()["results"][0]
    assert result["status"] == "BLOCKED"
    assert any("fingerprint" in blocker for blocker in result["blockers"])


def test_missing_tool_is_skipped(tmp_path, verification_context, monkeypatch):
    workspace = create_workspace(
        tmp_path,
        {"package.json": '{"scripts":{"lint":"eslint ."}}'},
    )
    execution = create_execution(verification_context, workspace)
    monkeypatch.setattr("app.services.execution_verification.shutil.which", lambda name: None)
    result = post_verify(execution.execution_id, ["frontend_lint"]).json()["results"][0]
    assert result["status"] == "SKIPPED"
    assert "Node.js" in result["warnings"][0]


def test_missing_package_script_is_skipped(tmp_path, verification_context):
    workspace = create_workspace(tmp_path, {"package.json": '{"scripts":{}}'})
    execution = create_execution(verification_context, workspace)
    result = post_verify(execution.execution_id, ["frontend_build"]).json()["results"][0]
    assert result["status"] == "SKIPPED"
    assert "build script" in result["warnings"][0]


def test_stdout_and_stderr_are_truncated(tmp_path, verification_context, monkeypatch):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(verification_context, workspace)
    runner = verification_context["runner"]
    runner.output_limit_bytes = 64
    monkeypatch.setattr(
        runner,
        "_resolve_python_compile",
        lambda root: (
            VerificationCommand(
                arguments=[
                    sys.executable,
                    "-I",
                    "-c",
                    "import sys; print('o' * 200); print('e' * 200, file=sys.stderr)",
                ],
                working_directory=root,
            ),
            None,
        ),
    )
    result = post_verify(execution.execution_id, ["python_compile"]).json()["results"][0]
    assert result["status"] == "PASSED"
    assert result["output_truncated"] is True
    assert len(result["stdout_excerpt"].encode()) <= 64
    assert len(result["stderr_excerpt"].encode()) <= 64


def test_potential_credentials_are_redacted_from_output(
    tmp_path, verification_context, monkeypatch
):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(verification_context, workspace)
    monkeypatch.setattr(
        verification_context["runner"],
        "_resolve_python_compile",
        lambda root: (
            VerificationCommand(
                arguments=[
                    sys.executable,
                    "-I",
                    "-c",
                    "print('API_KEY=super-secret-value')",
                ],
                working_directory=root,
            ),
            None,
        ),
    )
    result = post_verify(execution.execution_id, ["python_compile"]).json()["results"][0]
    assert "super-secret-value" not in result["stdout_excerpt"]
    assert "[REDACTED]" in result["stdout_excerpt"]
    assert any("redacted" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    ("verification_type", "script_name", "cli_path", "message"),
    [
        ("frontend_lint", "lint", "eslint/bin/eslint.js", "lint passed"),
        ("frontend_build", "build", "next/dist/bin/next", "build passed"),
    ],
)
def test_frontend_verification_uses_fixed_local_cli(
    tmp_path,
    verification_context,
    verification_type,
    script_name,
    cli_path,
    message,
):
    if shutil.which("node") is None:
        pytest.skip("Node.js is not installed")
    workspace = create_workspace(
        tmp_path,
        {
            "package.json": (
                '{"scripts":{"%s":"malicious user command must not execute"}}'
                % script_name
            ),
        },
    )
    execution = create_execution(verification_context, workspace)
    cli = workspace / "node_modules" / cli_path
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text(f"console.log('{message}');\n", encoding="utf-8")
    result = post_verify(execution.execution_id, [verification_type]).json()["results"][0]
    assert result["status"] == "PASSED"
    assert message in result["stdout_excerpt"]


def test_pytest_verification_passes_for_minimal_project(tmp_path, verification_context):
    workspace = create_workspace(
        tmp_path,
        {
            "sample.py": "def add(a, b):\n    return a + b\n",
            "tests/test_sample.py": "from sample import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        },
    )
    execution = create_execution(verification_context, workspace)
    result = post_verify(execution.execution_id, ["pytest"]).json()["results"][0]
    assert result["status"] == "PASSED"
    assert "1 passed" in result["stdout_excerpt"]


def test_multiple_runs_and_history_persist_across_store_restart(
    tmp_path, verification_context
):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(verification_context, workspace)
    post_verify(execution.execution_id, ["python_compile", "pytest"])
    restarted = ExecutionStore(verification_context["database"])
    history = restarted.list_verifications(execution.execution_id)
    assert [result.verification_type for result in history] == ["python_compile", "pytest"]
    assert [result.status for result in history] == ["PASSED", "SKIPPED"]

    response = client.get(
        f"/api/v1/workflows/execution/{execution.execution_id}/verifications"
    )
    assert response.status_code == 200
    assert len(response.json()["verifications"]) == 2
