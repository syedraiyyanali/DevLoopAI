import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.coder import CoderDiffPreviewResponse
from app.models.execution_mutation import ExecutionApplyResponse, ExecutionFileResult


class ExecutionRecordNotFoundError(Exception):
    """Raised when a persisted review or execution record does not exist."""


class ExecutionStore:
    """SQLite audit store for reviewed diffs, executions, and snapshots."""

    def __init__(self, database_path: str | Path, backup_root: str | Path | None = None) -> None:
        self.database_path = Path(database_path)
        self.backup_root = Path(backup_root) if backup_root else self.database_path.parent / "snapshots"
        self._initialize_database()

    def record_diff_review(
        self,
        preview: CoderDiffPreviewResponse,
    ) -> CoderDiffPreviewResponse:
        review_id = str(uuid4())
        reviewed_at = self._now()
        fingerprint = self.diff_fingerprint(preview)
        reviewed_preview = preview.model_copy(
            update={
                "review_id": review_id,
                "review_fingerprint": fingerprint,
                "reviewed_at": reviewed_at,
            }
        )
        payload_json = self._dump(reviewed_preview.model_dump(mode="json"))

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO coder_diff_reviews (
                    review_id, workflow_id, plan_fingerprint, review_fingerprint,
                    workspace_path, preview_json, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    reviewed_preview.workflow_id,
                    reviewed_preview.approved_plan_fingerprint,
                    fingerprint,
                    reviewed_preview.workspace_path,
                    payload_json,
                    reviewed_at,
                ),
            )

        return reviewed_preview

    def get_diff_review(self, review_id: str) -> CoderDiffPreviewResponse:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT preview_json, review_fingerprint
                FROM coder_diff_reviews
                WHERE review_id = ?
                """,
                (review_id,),
            ).fetchone()

        if row is None:
            raise ExecutionRecordNotFoundError("Diff review ID is invalid.")

        preview = CoderDiffPreviewResponse.model_validate(json.loads(row["preview_json"]))
        if preview.review_fingerprint != row["review_fingerprint"]:
            raise ExecutionRecordNotFoundError("Persisted diff review fingerprint is invalid.")
        return preview

    def diff_fingerprint(self, preview: CoderDiffPreviewResponse) -> str:
        payload = preview.model_dump(
            mode="json",
            exclude={"review_id", "review_fingerprint", "reviewed_at"},
        )
        return hashlib.sha256(self._dump(payload).encode("utf-8")).hexdigest()

    def create_execution(
        self,
        *,
        execution_id: str,
        workflow_id: str,
        plan_fingerprint: str,
        diff_review_id: str,
        diff_fingerprint: str,
        workspace_path: str,
        created_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO coding_executions (
                    execution_id, workflow_id, plan_fingerprint, diff_review_id,
                    diff_fingerprint, workspace_path, status, created_at,
                    response_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'IN_PROGRESS', ?, NULL)
                """,
                (
                    execution_id,
                    workflow_id,
                    plan_fingerprint,
                    diff_review_id,
                    diff_fingerprint,
                    workspace_path,
                    created_at,
                ),
            )

    def record_file(
        self,
        *,
        execution_id: str,
        ordinal: int,
        result: ExecutionFileResult,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO coding_execution_files (
                    execution_id, ordinal, relative_path, operation_type,
                    original_content_hash, proposed_content_hash, final_content_hash,
                    backup_location, backup_status, mutation_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    ordinal,
                    result.relative_path,
                    result.operation_type,
                    result.original_content_hash,
                    result.proposed_content_hash,
                    result.final_content_hash,
                    result.backup_location,
                    result.backup_status,
                    result.status,
                ),
            )

    def complete_execution(self, response: ExecutionApplyResponse) -> None:
        completed_at = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE coding_executions
                SET status = ?, completed_at = ?, response_json = ?
                WHERE execution_id = ?
                """,
                (
                    response.status,
                    completed_at,
                    self._dump(response.model_dump(mode="json")),
                    response.execution_id,
                ),
            )

    def get_execution(self, execution_id: str) -> ExecutionApplyResponse:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM coding_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()

        if row is None or row["response_json"] is None:
            raise ExecutionRecordNotFoundError("Execution ID is invalid.")

        return ExecutionApplyResponse.model_validate(json.loads(row["response_json"]))

    def mark_rolled_back(self, response: ExecutionApplyResponse) -> str:
        rolled_back_at = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE coding_executions
                SET status = 'ROLLED_BACK', rolled_back_at = ?, response_json = ?
                WHERE execution_id = ?
                """,
                (
                    rolled_back_at,
                    self._dump(response.model_dump(mode="json")),
                    response.execution_id,
                ),
            )
        return rolled_back_at

    def _initialize_database(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS coder_diff_reviews (
                    review_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    plan_fingerprint TEXT NOT NULL,
                    review_fingerprint TEXT NOT NULL,
                    workspace_path TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_executions (
                    execution_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    plan_fingerprint TEXT NOT NULL,
                    diff_review_id TEXT NOT NULL,
                    diff_fingerprint TEXT NOT NULL,
                    workspace_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    rolled_back_at TEXT,
                    response_json TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS coding_execution_files (
                    execution_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    relative_path TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    original_content_hash TEXT,
                    proposed_content_hash TEXT NOT NULL,
                    final_content_hash TEXT,
                    backup_location TEXT,
                    backup_status TEXT NOT NULL,
                    mutation_status TEXT NOT NULL,
                    PRIMARY KEY (execution_id, ordinal)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_coding_executions_created_at
                ON coding_executions (created_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _dump(self, payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
