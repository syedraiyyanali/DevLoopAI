import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.coder import CoderDiffPreviewResponse
from app.models.execution_history import (
    ExecutionHistoryDetail,
    ExecutionHistoryFile,
    ExecutionHistoryItem,
)
from app.models.execution_mutation import ExecutionApplyResponse, ExecutionFileResult
from app.models.execution_verification import ExecutionVerificationResult


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

    def list_execution_history(self) -> list[ExecutionHistoryItem]:
        """Return persisted execution history newest-first without sensitive payloads."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT execution_id, workflow_id, plan_fingerprint, diff_review_id,
                       diff_fingerprint, workspace_path, status, created_at,
                       completed_at, rolled_back_at, response_json
                FROM coding_executions
                ORDER BY rowid DESC
                """
            ).fetchall()

        return [self._history_item(row) for row in rows]

    def get_execution_history_detail(self, execution_id: str) -> ExecutionHistoryDetail:
        """Return one persisted execution audit record with verification history."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT execution_id, workflow_id, plan_fingerprint, diff_review_id,
                       diff_fingerprint, workspace_path, status, created_at,
                       completed_at, rolled_back_at, response_json
                FROM coding_executions
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()

        if row is None:
            raise ExecutionRecordNotFoundError("Execution ID is invalid.")

        item = self._history_item(row)
        response = self._execution_response(row)
        files = self._history_files(execution_id)
        verifications = self.list_verifications(execution_id)

        return ExecutionHistoryDetail(
            **item.model_dump(mode="json"),
            plan_fingerprint=row["plan_fingerprint"],
            diff_review_id=row["diff_review_id"],
            diff_fingerprint=row["diff_fingerprint"],
            files=files,
            verifications=verifications,
            message=response.message if response else self._state_message(row["status"]),
        )

    def get_execution_audit(self, execution_id: str) -> dict[str, str]:
        """Return immutable execution linkage fields used by verification checks."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT execution_id, workflow_id, plan_fingerprint, diff_review_id,
                       diff_fingerprint, workspace_path, status, created_at
                FROM coding_executions
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()

        if row is None:
            raise ExecutionRecordNotFoundError("Execution ID is invalid.")
        return dict(row)

    def get_execution_files(self, execution_id: str) -> list[ExecutionFileResult]:
        """Load persisted per-file audit rows in execution order."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT relative_path, operation_type, original_content_hash,
                       proposed_content_hash, final_content_hash, backup_location,
                       backup_status, mutation_status
                FROM coding_execution_files
                WHERE execution_id = ?
                ORDER BY ordinal ASC
                """,
                (execution_id,),
            ).fetchall()

        return [
            ExecutionFileResult(
                relative_path=row["relative_path"],
                operation_type=row["operation_type"],
                status=row["mutation_status"],
                original_content_hash=row["original_content_hash"],
                proposed_content_hash=row["proposed_content_hash"],
                final_content_hash=row["final_content_hash"],
                backup_location=row["backup_location"],
                backup_status=row["backup_status"],
            )
            for row in rows
        ]

    def _history_files(self, execution_id: str) -> list[ExecutionHistoryFile]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT relative_path, operation_type, original_content_hash,
                       proposed_content_hash, final_content_hash, backup_status,
                       mutation_status
                FROM coding_execution_files
                WHERE execution_id = ?
                ORDER BY ordinal ASC
                """,
                (execution_id,),
            ).fetchall()

        return [
            ExecutionHistoryFile(
                relative_path=row["relative_path"],
                operation_type=row["operation_type"],
                mutation_status=row["mutation_status"],
                original_content_hash=row["original_content_hash"],
                proposed_content_hash=row["proposed_content_hash"],
                final_content_hash=row["final_content_hash"],
                backup_status=row["backup_status"],
            )
            for row in rows
        ]

    def record_verification(self, result: ExecutionVerificationResult) -> None:
        """Persist one bounded verification result without environment data."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO execution_verifications (
                    verification_id, execution_id, workflow_id, verification_type,
                    command_identity, working_directory, status, exit_code,
                    duration_seconds, stdout_excerpt, stderr_excerpt,
                    output_truncated, timestamp, rollback_recommended,
                    changed_files_json, warnings_json, blockers_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.verification_id,
                    result.execution_id,
                    result.workflow_id,
                    result.verification_type,
                    result.command_identity,
                    result.working_directory,
                    result.status,
                    result.exit_code,
                    result.duration_seconds,
                    result.stdout_excerpt,
                    result.stderr_excerpt,
                    int(result.output_truncated),
                    result.timestamp,
                    int(result.rollback_recommended),
                    self._dump(result.changed_files),
                    self._dump(result.warnings),
                    self._dump(result.blockers),
                    self._dump(result.model_dump(mode="json")),
                ),
            )

    def list_verifications(self, execution_id: str) -> list[ExecutionVerificationResult]:
        """Return verification history in execution order."""
        self.get_execution_audit(execution_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT result_json
                FROM execution_verifications
                WHERE execution_id = ?
                ORDER BY rowid ASC
                """,
                (execution_id,),
            ).fetchall()
        return [
            ExecutionVerificationResult.model_validate(json.loads(row["result_json"]))
            for row in rows
        ]

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

    def _history_item(self, row: sqlite3.Row) -> ExecutionHistoryItem:
        response = self._execution_response(row)
        file_results = response.file_results if response else self.get_execution_files(row["execution_id"])
        verifications = self.list_verifications(row["execution_id"])
        latest_verification = verifications[-1] if verifications else None
        changed_files = response.files_changed if response else [
            result.relative_path
            for result in file_results
            if result.status in {"CHANGED", "CREATED", "ROLLED_BACK"}
        ]
        backup_status = response.backup_status if response else self._summarize_backup_status(file_results)
        rollback_available = bool(response.rollback_available) if response else False
        warnings = response.warnings if response else []
        blockers = response.blockers if response else []

        return ExecutionHistoryItem(
            execution_id=row["execution_id"],
            workflow_id=row["workflow_id"],
            workspace_path=row["workspace_path"],
            status=row["status"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            rolled_back_at=row["rolled_back_at"],
            changed_files=changed_files,
            operation_types=self._unique([result.operation_type for result in file_results]),
            backup_status=backup_status,
            rollback_available=rollback_available,
            verification_count=len(verifications),
            latest_verification_status=latest_verification.status if latest_verification else None,
            rollback_recommended=any(result.rollback_recommended for result in verifications),
            warnings=warnings,
            blockers=blockers,
            final_current_state=self._final_current_state(row["status"], verifications),
        )

    def _execution_response(self, row: sqlite3.Row) -> ExecutionApplyResponse | None:
        if row["response_json"] is None:
            return None
        return ExecutionApplyResponse.model_validate(json.loads(row["response_json"]))

    def _summarize_backup_status(self, file_results: list[ExecutionFileResult]) -> str:
        statuses = self._unique([result.backup_status for result in file_results])
        return ", ".join(statuses) if statuses else "UNKNOWN"

    def _final_current_state(
        self,
        status: str,
        verifications: list[ExecutionVerificationResult],
    ) -> str:
        if status == "ROLLED_BACK":
            return "Execution was rolled back from persisted snapshots."
        if status == "PARTIALLY_FAILED_AND_ROLLED_BACK":
            return "Execution partially failed and completed mutations were rolled back."
        if status == "EXECUTED" and any(result.rollback_recommended for result in verifications):
            return "Execution remains applied; verification recommends rollback."
        if status == "EXECUTED":
            return "Execution remains applied."
        return self._state_message(status)

    def _state_message(self, status: str) -> str:
        return f"Execution status is {status}."

    def _unique(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_verifications (
                    verification_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    verification_type TEXT NOT NULL,
                    command_identity TEXT NOT NULL,
                    working_directory TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exit_code INTEGER,
                    duration_seconds REAL NOT NULL,
                    stdout_excerpt TEXT NOT NULL,
                    stderr_excerpt TEXT NOT NULL,
                    output_truncated INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    rollback_recommended INTEGER NOT NULL,
                    changed_files_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    blockers_json TEXT NOT NULL,
                    result_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_verifications_execution
                ON execution_verifications (execution_id, timestamp ASC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _dump(self, payload) -> str:
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
