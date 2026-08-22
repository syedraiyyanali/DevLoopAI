import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.git_commit import GitCommitRequest, GitCommitResponse
from app.models.git_status import GitStatusRequest
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_store import ExecutionRecordNotFoundError, ExecutionStore
from app.services.git_status import GitStatusService
from app.services.workspace import WorkspaceService


class GitCommitBlockedError(Exception):
    """Raised when controlled Git commit preconditions are not met."""


class GitCommitStore:
    """SQLite audit persistence for controlled Git commits."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._initialize_database()

    def record(self, response: GitCommitResponse) -> GitCommitResponse:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO git_commit_audits (
                    commit_audit_id, execution_id, status, created_at, response_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    response.commit_audit_id,
                    response.execution_id,
                    response.status,
                    response.timestamp,
                    self._dump(response),
                ),
            )
        return response

    def latest_for_execution(self, execution_id: str) -> GitCommitResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT response_json
                FROM git_commit_audits
                WHERE execution_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (execution_id,),
            ).fetchone()
        if row is None:
            return None
        return GitCommitResponse.model_validate(json.loads(row["response_json"]))

    def _initialize_database(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS git_commit_audits (
                    commit_audit_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    response_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _dump(self, response: GitCommitResponse) -> str:
        return json.dumps(
            response.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )


class ControlledGitCommitService:
    """Stages only audited execution paths and creates one explicit local commit."""

    timeout_seconds = 10

    def __init__(
        self,
        *,
        execution_store: ExecutionStore,
        quality_gate: ExecutionQualityGate,
        git_status_service: GitStatusService,
        commit_store: GitCommitStore,
        workspace_service: WorkspaceService,
    ) -> None:
        self.execution_store = execution_store
        self.quality_gate = quality_gate
        self.git_status_service = git_status_service
        self.commit_store = commit_store
        self.workspace_service = workspace_service

    def commit(self, request: GitCommitRequest) -> GitCommitResponse:
        latest_commit = self.commit_store.latest_for_execution(request.execution_id)
        if latest_commit and latest_commit.status == "COMMITTED":
            return latest_commit

        try:
            execution = self.execution_store.get_execution(request.execution_id)
        except ExecutionRecordNotFoundError as exc:
            raise GitCommitBlockedError("Execution ID is invalid.") from exc

        quality = self.quality_gate.evaluate(request.execution_id)
        if quality.quality_status != "QUALITY_PASSED":
            return self._blocked(request, execution, [f"Quality must be QUALITY_PASSED; got {quality.quality_status}."])

        workspace = self.workspace_service.open_workspace(execution.workspace_path)
        root = Path(workspace.root_path)
        audited_files = sorted({item.relative_path for item in execution.file_results})
        if not audited_files:
            return self._blocked(request, execution, ["Execution audit has no files to commit."])

        git_status = self.git_status_service.status(
            GitStatusRequest(
                workspace_path=str(root),
                execution_id=request.execution_id,
            )
        )
        if not git_status.is_git_repository:
            return self._blocked(request, execution, ["Workspace is not a Git repository."])
        if git_status.unexpected_changed_files:
            return self._blocked(
                request,
                execution,
                ["Unexpected changed files are present: " + ", ".join(git_status.unexpected_changed_files)],
            )
        if git_status.restricted_changed_file_count:
            return self._blocked(
                request,
                execution,
                ["Restricted changed files are present and must be resolved before commit."],
            )

        for relative_path in audited_files:
            self.workspace_service._resolve_child_path(root, relative_path)

        add_result = self._run(root, ["add", "--", *audited_files])
        if add_result.returncode != 0:
            return self._failed(request, execution, audited_files, "Git add failed.")

        message = self._commit_message(request.message, execution.workflow_id)
        commit_result = self._run(root, ["commit", "--no-verify", "-m", message])
        if commit_result.returncode != 0:
            return self._failed(
                request,
                execution,
                audited_files,
                "Git commit failed or no audited changes were available to commit.",
            )

        commit_hash = self._run(root, ["rev-parse", "--short", "HEAD"]).stdout.strip()
        return self.commit_store.record(
            GitCommitResponse(
                commit_audit_id=str(uuid4()),
                execution_id=request.execution_id,
                workflow_id=execution.workflow_id,
                workspace_path=str(root),
                status="COMMITTED",
                commit_hash=commit_hash,
                message=message,
                files_committed=audited_files,
                timestamp=self._now(),
                warnings=[],
                blockers=[],
            )
        )

    def _blocked(self, request, execution, blockers: list[str]) -> GitCommitResponse:
        return self.commit_store.record(
            GitCommitResponse(
                commit_audit_id=str(uuid4()),
                execution_id=request.execution_id,
                workflow_id=getattr(execution, "workflow_id", None),
                workspace_path=getattr(execution, "workspace_path", None),
                status="BLOCKED",
                message="Controlled Git commit was blocked.",
                timestamp=self._now(),
                blockers=blockers,
            )
        )

    def _failed(self, request, execution, files: list[str], message: str) -> GitCommitResponse:
        return self.commit_store.record(
            GitCommitResponse(
                commit_audit_id=str(uuid4()),
                execution_id=request.execution_id,
                workflow_id=execution.workflow_id,
                workspace_path=execution.workspace_path,
                status="FAILED",
                message=message,
                files_committed=files,
                timestamp=self._now(),
                blockers=[message],
            )
        )

    def _run(self, root: Path, args: list[str]):
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            shell=False,
            check=False,
        )

    def _commit_message(self, requested: str | None, workflow_id: str) -> str:
        message = requested.strip() if requested else f"chore: apply DevLoopAI execution {workflow_id[:8]}"
        message = re.sub(r"[\r\n\t]+", " ", message)
        message = re.sub(r"\s{2,}", " ", message).strip()
        if not message or len(message) > 120:
            return f"chore: apply DevLoopAI execution {workflow_id[:8]}"
        return message

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
