import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import execution_quality as quality_endpoint
from app.main import app
from app.models.execution_mutation import ExecutionApplyResponse, ExecutionFileResult
from app.models.execution_verification import ExecutionVerificationResult
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_store import ExecutionStore
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def quality_context(tmp_path, monkeypatch):
    database = tmp_path / "runtime" / "devloopai.sqlite3"
    store = ExecutionStore(database)
    gate = ExecutionQualityGate(
        execution_store=store,
        workspace_service=WorkspaceService(),
    )
    monkeypatch.setattr(quality_endpoint, "get_execution_quality_gate", lambda: gate)
    return {"database": database, "store": store}


def create_workspace(tmp_path, files, *, with_pytest=False, with_frontend=False):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for relative_path, content in files.items():
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    if with_pytest:
        (workspace / "tests").mkdir(exist_ok=True)
        (workspace / "tests" / "test_sample.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8", newline="\n"
        )
    if with_frontend:
        (workspace / "package.json").write_text(
            json.dumps({"scripts": {"lint": "eslint .", "build": "next build"}}),
            encoding="utf-8",
        )
    return workspace


def create_execution(
    store,
    workspace,
    *,
    execution_id="execution-1",
    workflow_id="workflow-1",
    relative_path="sample.py",
    operation_type="modify_text_file",
    status="EXECUTED",
    final_content="value = 2\n",
    rollback_available=True,
):
    target = workspace / relative_path
    original_hash = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    if operation_type == "create_text_file":
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(final_content, encoding="utf-8", newline="\n")
    final_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    file_result = ExecutionFileResult(
        relative_path=relative_path,
        operation_type=operation_type,
        status="CREATED" if operation_type == "create_text_file" else "CHANGED",
        original_content_hash=original_hash,
        proposed_content_hash=final_hash,
        final_content_hash=final_hash,
        backup_location="D:/runtime/snapshots/private.txt",
        backup_status="NOT_REQUIRED" if operation_type == "create_text_file" else "CREATED",
    )
    response = ExecutionApplyResponse(
        execution_id=execution_id,
        workflow_id=workflow_id,
        workspace_path=str(workspace),
        status=status,
        files_attempted=[relative_path],
        files_changed=[relative_path],
        file_results=[file_result],
        backup_status=file_result.backup_status,
        rollback_available=rollback_available,
        warnings=[],
        blockers=[],
        execution_timestamp="2026-08-15T00:00:00Z",
        message="Synthetic execution.",
    )
    store.create_execution(
        execution_id=execution_id,
        workflow_id=workflow_id,
        plan_fingerprint="f" * 64,
        diff_review_id="review-1",
        diff_fingerprint="d" * 64,
        workspace_path=str(workspace),
        created_at=response.execution_timestamp,
    )
    store.record_file(execution_id=execution_id, ordinal=0, result=file_result)
    store.complete_execution(response)
    return response


def record_verification(store, execution, verification_type, status, *, rollback_recommended=False):
    result = ExecutionVerificationResult(
        verification_id=f"{execution.execution_id}-{verification_type}-{status}",
        execution_id=execution.execution_id,
        workflow_id=execution.workflow_id,
        verification_type=verification_type,
        command_identity=f"{verification_type}:v1",
        working_directory=execution.workspace_path,
        status=status,
        exit_code=0 if status == "PASSED" else 1,
        duration_seconds=0.1,
        stdout_excerpt="",
        stderr_excerpt="",
        output_truncated=False,
        timestamp="2026-08-15T00:00:01Z",
        rollback_recommended=rollback_recommended,
        changed_files=list(execution.files_changed),
        warnings=[],
        blockers=[],
    )
    store.record_verification(result)
    return result


def get_quality(execution_id):
    return client.get(f"/api/v1/workflows/execution/{execution_id}/quality")


def test_executed_all_required_checks_passed_returns_quality_passed(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(quality_context["store"], workspace)
    record_verification(quality_context["store"], execution, "python_compile", "PASSED")

    response = get_quality(execution.execution_id)

    assert response.status_code == 200
    body = response.json()
    assert body["quality_status"] == "QUALITY_PASSED"
    assert body["required_verification_types"] == ["python_compile"]
    assert body["passed_checks"] == ["python_compile"]
    assert body["rollback_recommended"] is False


@pytest.mark.parametrize("verification_status", ["FAILED", "TIMED_OUT"])
def test_required_check_failed_or_timed_out_returns_quality_failed(
    tmp_path, quality_context, verification_status
):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(quality_context["store"], workspace)
    record_verification(
        quality_context["store"],
        execution,
        "python_compile",
        verification_status,
        rollback_recommended=True,
    )

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "QUALITY_FAILED"
    assert body["failed_checks"] == ["python_compile"]
    assert body["rollback_recommended"] is True


def test_missing_required_check_returns_quality_incomplete(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(quality_context["store"], workspace)

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "QUALITY_INCOMPLETE"
    assert body["missing_checks"] == ["python_compile"]
    assert body["rollback_recommended"] is False


def test_skipped_required_check_returns_quality_incomplete(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(quality_context["store"], workspace)
    record_verification(quality_context["store"], execution, "python_compile", "SKIPPED")

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "QUALITY_INCOMPLETE"
    assert body["skipped_checks"] == ["python_compile"]


def test_successful_rollback_returns_rolled_back(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(quality_context["store"], workspace)
    execution.status = "ROLLED_BACK"
    execution.rollback_available = False
    quality_context["store"].mark_rolled_back(execution)

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "ROLLED_BACK"
    assert body["rollback_status"] == "ROLLED_BACK"
    assert body["rollback_recommended"] is False


def test_post_execution_file_change_blocks_quality(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(quality_context["store"], workspace)
    record_verification(quality_context["store"], execution, "python_compile", "PASSED")
    workspace.joinpath("sample.py").write_text("value = 99\n", encoding="utf-8", newline="\n")

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "BLOCKED"
    assert body["rollback_recommended"] is True
    assert any("no longer matches" in blocker for blocker in body["blockers"])


def test_missing_created_file_blocks_quality(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {})
    execution = create_execution(
        quality_context["store"],
        workspace,
        operation_type="create_text_file",
        relative_path="created.py",
    )
    record_verification(quality_context["store"], execution, "python_compile", "PASSED")
    workspace.joinpath("created.py").unlink()

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "BLOCKED"
    assert any("Created file is missing" in blocker for blocker in body["blockers"])


def test_verification_from_wrong_execution_is_ignored(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(quality_context["store"], workspace, execution_id="target")
    other = create_execution(
        quality_context["store"],
        workspace,
        execution_id="other",
        final_content="value = 3\n",
    )
    record_verification(quality_context["store"], other, "python_compile", "PASSED")

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "BLOCKED"
    assert body["missing_checks"] == ["python_compile"]


def test_optional_failed_check_does_not_fail_required_policy(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(quality_context["store"], workspace)
    record_verification(quality_context["store"], execution, "python_compile", "PASSED")
    record_verification(
        quality_context["store"],
        execution,
        "frontend_build",
        "FAILED",
        rollback_recommended=True,
    )

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "QUALITY_PASSED"
    assert body["failed_checks"] == []
    assert any(item["verification_type"] == "frontend_build" for item in body["verification_summary"])


def test_frontend_policy_requires_lint_and_build_when_scripts_exist(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"src/app.tsx": "export const value = 1;\n"}, with_frontend=True)
    execution = create_execution(
        quality_context["store"],
        workspace,
        relative_path="src/app.tsx",
        final_content="export const value = 2;\n",
    )
    record_verification(quality_context["store"], execution, "frontend_lint", "PASSED")
    record_verification(quality_context["store"], execution, "frontend_build", "PASSED")

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "QUALITY_PASSED"
    assert body["required_verification_types"] == ["frontend_lint", "frontend_build"]


def test_pytest_required_when_pytest_project_present(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"}, with_pytest=True)
    execution = create_execution(quality_context["store"], workspace)
    record_verification(quality_context["store"], execution, "python_compile", "PASSED")

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "QUALITY_INCOMPLETE"
    assert body["missing_checks"] == ["pytest"]
    assert body["required_verification_types"] == ["python_compile", "pytest"]


def test_invalid_execution_id_returns_not_found(quality_context):
    response = get_quality("missing")

    assert response.status_code == 404


def test_quality_survives_store_restart(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(quality_context["store"], workspace)
    record_verification(quality_context["store"], execution, "python_compile", "PASSED")

    restarted = ExecutionQualityGate(
        execution_store=ExecutionStore(quality_context["database"]),
        workspace_service=WorkspaceService(),
    )
    quality = restarted.evaluate(execution.execution_id)

    assert quality.quality_status == "QUALITY_PASSED"


def test_corrupt_file_audit_blocks_quality(tmp_path, quality_context):
    workspace = create_workspace(tmp_path, {"sample.py": "value = 1\n"})
    execution = create_execution(quality_context["store"], workspace)
    with sqlite3.connect(quality_context["database"]) as connection:
        connection.execute(
            "UPDATE coding_execution_files SET final_content_hash = ? WHERE execution_id = ?",
            ("0" * 64, execution.execution_id),
        )

    body = get_quality(execution.execution_id).json()

    assert body["quality_status"] == "BLOCKED"
    assert any("file audit" in blocker for blocker in body["blockers"])

