import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models.task_execution import TaskExecutionSession


class TaskExecutionNotFoundError(Exception):
    """Raised when a task execution session is missing."""


class TaskExecutionStore:
    """SQLite persistence for controlled single-task orchestration sessions."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._initialize_database()

    def create(self, session: TaskExecutionSession) -> TaskExecutionSession:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_execution_sessions (
                    task_execution_id, workflow_id, state, created_at, updated_at,
                    session_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session.task_execution_id,
                    session.workflow_id,
                    session.state,
                    session.created_at,
                    session.updated_at,
                    self._dump(session),
                ),
            )
        return session

    def update(self, session: TaskExecutionSession) -> TaskExecutionSession:
        session.updated_at = self._now()
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE task_execution_sessions
                SET state = ?, updated_at = ?, session_json = ?
                WHERE task_execution_id = ?
                """,
                (
                    session.state,
                    session.updated_at,
                    self._dump(session),
                    session.task_execution_id,
                ),
            )
        if result.rowcount == 0:
            raise TaskExecutionNotFoundError("Task execution ID is invalid.")
        return session

    def get(self, task_execution_id: str) -> TaskExecutionSession:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT session_json
                FROM task_execution_sessions
                WHERE task_execution_id = ?
                """,
                (task_execution_id,),
            ).fetchone()
        if row is None:
            raise TaskExecutionNotFoundError("Task execution ID is invalid.")
        return TaskExecutionSession.model_validate(json.loads(row["session_json"]))

    def _initialize_database(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_execution_sessions (
                    task_execution_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    session_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_execution_sessions_updated
                ON task_execution_sessions (updated_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _dump(self, session: TaskExecutionSession) -> str:
        return json.dumps(
            session.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

