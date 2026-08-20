import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models.autonomous_task import AutonomousTaskSession


class AutonomousTaskNotFoundError(Exception):
    """Raised when an autonomous task session does not exist."""


class AutonomousTaskStore:
    """SQLite persistence for bounded autonomous task sessions."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._initialize_database()

    def create(self, session: AutonomousTaskSession) -> AutonomousTaskSession:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO autonomous_task_sessions (
                    autonomous_session_id, state, created_at, updated_at, session_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session.autonomous_session_id,
                    session.state,
                    session.created_at,
                    session.updated_at,
                    self._dump(session),
                ),
            )
        return session

    def update(self, session: AutonomousTaskSession) -> AutonomousTaskSession:
        session.updated_at = self._now()
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE autonomous_task_sessions
                SET state = ?, updated_at = ?, session_json = ?
                WHERE autonomous_session_id = ?
                """,
                (
                    session.state,
                    session.updated_at,
                    self._dump(session),
                    session.autonomous_session_id,
                ),
            )
        if result.rowcount == 0:
            raise AutonomousTaskNotFoundError("Autonomous task session ID is invalid.")
        return session

    def get(self, autonomous_session_id: str) -> AutonomousTaskSession:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT session_json
                FROM autonomous_task_sessions
                WHERE autonomous_session_id = ?
                """,
                (autonomous_session_id,),
            ).fetchone()
        if row is None:
            raise AutonomousTaskNotFoundError("Autonomous task session ID is invalid.")
        return AutonomousTaskSession.model_validate(json.loads(row["session_json"]))

    def _initialize_database(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS autonomous_task_sessions (
                    autonomous_session_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    session_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_autonomous_task_sessions_updated
                ON autonomous_task_sessions (updated_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _dump(self, session: AutonomousTaskSession) -> str:
        return json.dumps(
            session.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
