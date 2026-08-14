from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import execution_history as history_endpoint
from app.main import app
from app.models.execution_mutation import ExecutionApplyResponse, ExecutionFileResult
from app.models.execution_verification import ExecutionVerificationResult
from app.services.execution_store import ExecutionStore


client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def history_context(tmp_path, monkeypatch):
    database = tmp_path / "runtime" / "devloopai.sqlite3"
    store = ExecutionStore(database)
    monkeypatch.setattr(history_endpoint, "get_execution_store", lambda: store)
    return {"database": database, "store": store}


def create_execution(
    store: ExecutionStore,
    *,
    execution_id: str,
    workflow_id: str = "workflow-1",
    created_at: str = "2026-08-15T00:00:00Z",
    status: str = "EXECUTED",
    rollback_available: bool = True,
    backup_location: str | None = "D:/runtime/snapshots/secret-backup.txt",
):
    file_result = ExecutionFileResult(
        relative_path="sample.py",
        operation_type="modify_text_file",
        status="CHANGED",
        original_content_hash="before-hash",
        proposed_content_hash="after-hash",
        final_content_hash="after-hash",
        backup_location=backup_location,
        backup_status="CREATED",
    )
    response = ExecutionApplyResponse(
        execution_id=execution_id,
        workflow_id=workflow_id,
        workspace_path="D:/tmp/devloopai-history",
        status=status,
        files_attempted=["sample.py"],
        files_changed=["sample.py"],
        file_results=[file_result],
        backup_status="CREATED",
        rollback_available=rollback_available,
        warnings=[],
        blockers=[],
        execution_timestamp=created_at,
        message="Execution audit record.",
    )
    store.create_execution(
        execution_id=execution_id,
        workflow_id=workflow_id,
        plan_fingerprint="f" * 64,
        diff_review_id="review-1",
        diff_fingerprint="d" * 64,
        workspace_path=response.workspace_path,
        created_at=created_at,
    )
    store.record_file(execution_id=execution_id, ordinal=0, result=file_result)
    store.complete_execution(response)
    return response


def create_verification(
    store: ExecutionStore,
    *,
    execution_id: str,
    workflow_id: str = "workflow-1",
    status: str = "PASSED",
    rollback_recommended: bool = False,
):
    result = ExecutionVerificationResult(
        verification_id=f"verification-{execution_id}-{status}",
        execution_id=execution_id,
        workflow_id=workflow_id,
        verification_type="python_compile",
        command_identity="python_compile",
        working_directory="D:/tmp/devloopai-history",
        status=status,
        exit_code=0 if status == "PASSED" else 1,
        duration_seconds=0.1,
        stdout_excerpt="ok",
        stderr_excerpt="",
        output_truncated=False,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        rollback_recommended=rollback_recommended,
        changed_files=["sample.py"],
        warnings=[],
        blockers=[],
    )
    store.record_verification(result)
    return result


def test_execution_history_is_newest_first(history_context):
    store = history_context["store"]
    create_execution(
        store,
        execution_id="older",
        created_at=(datetime.now(timezone.utc) - timedelta(minutes=1))
        .isoformat()
        .replace("+00:00", "Z"),
    )
    create_execution(store, execution_id="newer")

    response = client.get("/api/v1/workflows/execution")

    assert response.status_code == 200
    body = response.json()
    assert [item["execution_id"] for item in body["executions"][:2]] == [
        "newer",
        "older",
    ]


def test_execution_detail_includes_files_hashes_and_verifications(history_context):
    store = history_context["store"]
    create_execution(store, execution_id="execution-1")
    create_verification(store, execution_id="execution-1")

    response = client.get("/api/v1/workflows/execution/execution-1")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_id"] == "execution-1"
    assert body["changed_files"] == ["sample.py"]
    assert body["files"][0]["original_content_hash"] == "before-hash"
    assert body["files"][0]["final_content_hash"] == "after-hash"
    assert body["files"][0]["backup_status"] == "CREATED"
    assert body["verifications"][0]["status"] == "PASSED"
    assert body["verification_count"] == 1
    assert body["latest_verification_status"] == "PASSED"


def test_rolled_back_execution_history(history_context):
    store = history_context["store"]
    execution = create_execution(store, execution_id="rolled-back")
    execution.status = "ROLLED_BACK"
    execution.rollback_available = False
    store.mark_rolled_back(execution)

    response = client.get("/api/v1/workflows/execution/rolled-back")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ROLLED_BACK"
    assert body["rollback_available"] is False
    assert body["rolled_back_at"] is not None
    assert "rolled back" in body["final_current_state"].lower()


def test_invalid_execution_id_returns_not_found(history_context):
    response = client.get("/api/v1/workflows/execution/missing")

    assert response.status_code == 404


def test_execution_history_persists_after_store_restart(history_context):
    store = history_context["store"]
    create_execution(store, execution_id="persisted")
    create_verification(store, execution_id="persisted")

    restarted = ExecutionStore(history_context["database"])
    detail = restarted.get_execution_history_detail("persisted")

    assert detail.execution_id == "persisted"
    assert detail.verification_count == 1
    assert detail.verifications[0].status == "PASSED"


def test_history_omits_approval_tokens_and_snapshot_contents(history_context):
    store = history_context["store"]
    create_execution(
        store,
        execution_id="no-leak",
        backup_location="D:/runtime/snapshots/secret-token-backup.txt",
    )
    create_verification(
        store,
        execution_id="no-leak",
        status="FAILED",
        rollback_recommended=True,
    )

    response = client.get("/api/v1/workflows/execution/no-leak")

    assert response.status_code == 200
    payload = response.text
    assert "approval_token" not in payload
    assert "secret-token" not in payload
    assert "backup_location" not in payload
    assert "snapshot contents" not in payload
    body = response.json()
    assert body["rollback_recommended"] is True
    assert body["final_current_state"] == (
        "Execution remains applied; verification recommends rollback."
    )

