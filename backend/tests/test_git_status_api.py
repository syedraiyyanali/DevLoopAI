import subprocess

from fastapi.testclient import TestClient

from app.api.v1.endpoints import git_status as git_endpoint
from app.main import app
from app.models.execution_mutation import ExecutionApplyResponse, ExecutionFileResult
from app.services.execution_store import ExecutionStore
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
    (workspace / "sample.py").write_text("value = 1\n", encoding="utf-8")
    run_git(workspace, ["add", "sample.py"])
    run_git(workspace, ["commit", "-m", "initial commit"])
    return workspace


def configure_service(tmp_path, monkeypatch):
    execution_store = ExecutionStore(tmp_path / "runtime" / "devloopai.sqlite3")
    service = GitStatusService(
        workspace_service=WorkspaceService(),
        execution_store=execution_store,
    )
    monkeypatch.setattr(git_endpoint, "get_git_status_service", lambda: service)
    return execution_store


def post_status(workspace, **extra):
    return client.post(
        "/api/v1/workflows/git/status",
        json={"workspace_path": str(workspace), **extra},
    )


def test_non_git_workspace_returns_skipped_status(tmp_path, monkeypatch):
    configure_service(tmp_path, monkeypatch)
    workspace = tmp_path / "plain"
    workspace.mkdir()

    body = post_status(workspace).json()

    assert body["is_git_repository"] is False
    assert body["warnings"] == ["Workspace is not a Git repository."]


def test_git_status_reports_branch_changed_files_and_diff(tmp_path, monkeypatch):
    configure_service(tmp_path, monkeypatch)
    workspace = make_repo(tmp_path)
    (workspace / "sample.py").write_text("value = 2\n", encoding="utf-8")
    (workspace / "new.txt").write_text("new\n", encoding="utf-8")

    response = post_status(workspace, max_diff_chars=1000)

    assert response.status_code == 200
    body = response.json()
    assert body["is_git_repository"] is True
    assert body["current_branch"] in {"main", "master"}
    assert body["changed_file_count"] == 2
    assert "sample.py" in body["unstaged_files"]
    assert "new.txt" in body["untracked_files"]
    assert "sample.py" in body["diff_excerpt"]
    assert body["recent_commits"][0]["subject"] == "initial commit"


def test_git_diff_is_bounded(tmp_path, monkeypatch):
    configure_service(tmp_path, monkeypatch)
    workspace = make_repo(tmp_path)
    (workspace / "sample.py").write_text("value = '" + ("x" * 5000) + "'\n", encoding="utf-8")

    body = post_status(workspace, max_diff_chars=1000).json()

    assert len(body["diff_excerpt"]) <= 1000
    assert body["diff_truncated"] is True


def test_execution_audit_comparison_surfaces_unexpected_changes(tmp_path, monkeypatch):
    execution_store = configure_service(tmp_path, monkeypatch)
    workspace = make_repo(tmp_path)
    execution_store.create_execution(
        execution_id="exec-1",
        workflow_id="workflow-1",
        plan_fingerprint="a" * 64,
        diff_review_id="review-1",
        diff_fingerprint="b" * 64,
        workspace_path=str(workspace),
        created_at="2026-08-20T00:00:00Z",
    )
    execution_store.complete_execution(
        ExecutionApplyResponse(
            execution_id="exec-1",
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
                    original_content_hash="a",
                    proposed_content_hash="b",
                    final_content_hash="b",
                    backup_status="CREATED",
                )
            ],
            backup_status="Backed up.",
            rollback_available=True,
            execution_timestamp="2026-08-20T00:00:00Z",
            message="Executed.",
        )
    )
    (workspace / "sample.py").write_text("value = 2\n", encoding="utf-8")
    (workspace / "other.py").write_text("value = 3\n", encoding="utf-8")

    body = post_status(workspace, execution_id="exec-1").json()

    assert body["execution_audit_files"] == ["sample.py"]
    assert body["unexpected_changed_files"] == ["other.py"]
