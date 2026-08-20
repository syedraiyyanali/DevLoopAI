import hashlib
import subprocess

from fastapi.testclient import TestClient

from app.api.v1.endpoints import git_commit as git_commit_endpoint
from app.main import app
from app.models.execution_mutation import ExecutionApplyResponse, ExecutionFileResult
from app.models.execution_verification import ExecutionVerificationResult
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_store import ExecutionStore
from app.services.git_commit import ControlledGitCommitService, GitCommitStore
from app.services.git_status import GitStatusService
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


def run_git(workspace, args):
    return subprocess.run(
        ["git", *args],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        shell=False,
        check=True,
    )


def make_repo(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    run_git(workspace, ["init"])
    run_git(workspace, ["config", "user.email", "devloopai@example.test"])
    run_git(workspace, ["config", "user.name", "DevLoopAI Test"])
    (workspace / "sample.py").write_text("value = 1\n", encoding="utf-8", newline="\n")
    run_git(workspace, ["add", "sample.py"])
    run_git(workspace, ["commit", "-m", "initial commit"])
    return workspace


def configure_service(tmp_path, monkeypatch):
    database = tmp_path / "runtime" / "devloopai.sqlite3"
    execution_store = ExecutionStore(database)
    workspace_service = WorkspaceService()
    service = ControlledGitCommitService(
        execution_store=execution_store,
        quality_gate=ExecutionQualityGate(
            execution_store=execution_store,
            workspace_service=workspace_service,
        ),
        git_status_service=GitStatusService(
            workspace_service=workspace_service,
            execution_store=execution_store,
        ),
        commit_store=GitCommitStore(database),
        workspace_service=workspace_service,
    )
    monkeypatch.setattr(git_commit_endpoint, "get_git_commit_service", lambda: service)
    return execution_store


def create_quality_passed_execution(store, workspace, *, execution_id="exec-1"):
    original = "value = 1\n"
    proposed = "value = 2\n"
    (workspace / "sample.py").write_text(proposed, encoding="utf-8", newline="\n")
    original_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
    proposed_hash = hashlib.sha256(proposed.encode("utf-8")).hexdigest()
    store.create_execution(
        execution_id=execution_id,
        workflow_id="workflow-1",
        plan_fingerprint="a" * 64,
        diff_review_id="review-1",
        diff_fingerprint="b" * 64,
        workspace_path=str(workspace),
        created_at="2026-08-20T00:00:00Z",
    )
    file_result = ExecutionFileResult(
        relative_path="sample.py",
        operation_type="modify_text_file",
        status="CHANGED",
        original_content_hash=original_hash,
        proposed_content_hash=proposed_hash,
        final_content_hash=proposed_hash,
        backup_status="CREATED",
    )
    store.record_file(execution_id=execution_id, ordinal=0, result=file_result)
    store.complete_execution(
        ExecutionApplyResponse(
            execution_id=execution_id,
            workflow_id="workflow-1",
            workspace_path=str(workspace),
            status="EXECUTED",
            files_attempted=["sample.py"],
            files_changed=["sample.py"],
            file_results=[file_result],
            backup_status="Backed up.",
            rollback_available=True,
            execution_timestamp="2026-08-20T00:00:00Z",
            message="Executed.",
        )
    )
    store.record_verification(
        ExecutionVerificationResult(
            verification_id=f"verify-{execution_id}",
            execution_id=execution_id,
            workflow_id="workflow-1",
            verification_type="python_compile",
            command_identity="python_compile",
            working_directory=str(workspace),
            status="PASSED",
            exit_code=0,
            duration_seconds=0.01,
            timestamp="2026-08-20T00:00:01Z",
            changed_files=["sample.py"],
        )
    )


def post_commit(execution_id, message=None):
    return client.post(
        "/api/v1/workflows/git/commit",
        json={"execution_id": execution_id, "message": message},
    )


def test_quality_passed_execution_commits_only_audited_files(tmp_path, monkeypatch):
    store = configure_service(tmp_path, monkeypatch)
    workspace = make_repo(tmp_path)
    create_quality_passed_execution(store, workspace)

    response = post_commit("exec-1", "feat: update sample")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMMITTED"
    assert body["files_committed"] == ["sample.py"]
    assert body["commit_hash"]
    assert run_git(workspace, ["log", "-1", "--pretty=%s"]).stdout.strip() == "feat: update sample"


def test_commit_blocks_when_quality_is_incomplete(tmp_path, monkeypatch):
    store = configure_service(tmp_path, monkeypatch)
    workspace = make_repo(tmp_path)
    create_quality_passed_execution(store, workspace, execution_id="exec-2")
    # Remove verification history by using an execution that has not passed required checks.
    store.create_execution(
        execution_id="exec-missing",
        workflow_id="workflow-1",
        plan_fingerprint="a" * 64,
        diff_review_id="review-1",
        diff_fingerprint="b" * 64,
        workspace_path=str(workspace),
        created_at="2026-08-20T00:00:00Z",
    )
    store.complete_execution(
        ExecutionApplyResponse(
            execution_id="exec-missing",
            workflow_id="workflow-1",
            workspace_path=str(workspace),
            status="EXECUTED",
            files_attempted=["sample.py"],
            files_changed=["sample.py"],
            file_results=[
                ExecutionFileResult(
                    relative_path="sample.py",
                    operation_type="modify_text_file",
                    status="CHANGED",
                    proposed_content_hash="new",
                    final_content_hash="new",
                    backup_status="CREATED",
                )
            ],
            backup_status="Backed up.",
            rollback_available=True,
            execution_timestamp="2026-08-20T00:00:00Z",
            message="Executed.",
        )
    )

    body = post_commit("exec-missing").json()

    assert body["status"] == "BLOCKED"
    assert "Quality must be QUALITY_PASSED" in body["blockers"][0]


def test_commit_blocks_unexpected_changed_files(tmp_path, monkeypatch):
    store = configure_service(tmp_path, monkeypatch)
    workspace = make_repo(tmp_path)
    create_quality_passed_execution(store, workspace)
    (workspace / "other.py").write_text("value = 3\n", encoding="utf-8")

    body = post_commit("exec-1").json()

    assert body["status"] == "BLOCKED"
    assert "Unexpected changed files" in body["blockers"][0]


def test_commit_message_is_sanitized(tmp_path, monkeypatch):
    store = configure_service(tmp_path, monkeypatch)
    workspace = make_repo(tmp_path)
    create_quality_passed_execution(store, workspace)

    body = post_commit("exec-1", "feat: update\n\nmalicious").json()

    assert body["status"] == "COMMITTED"
    assert body["message"] == "feat: update malicious"
