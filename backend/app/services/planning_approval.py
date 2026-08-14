import hashlib
import json
import sqlite3
from pathlib import Path
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4

from app.models.planning_workflow import (
    ApprovalStatus,
    FinalReviewedPlanSummary,
    PlanningApprovalActionResponse,
    PlanningApprovalGate,
    PlanningWorkflowHistoryItem,
    PlanningWorkflowHistoryRecord,
)
from app.models.planner import PlannerResponse
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidatorResponse


class PlanningApprovalError(Exception):
    """
    Raised when a planning approval action cannot be accepted.
    """


class PlanningApprovalNotFoundError(PlanningApprovalError):
    """
    Raised when an approval/workflow record does not exist or the token is invalid.
    """


class PlanningApprovalStaleError(PlanningApprovalError):
    """
    Raised when approval is attempted for a changed plan fingerprint.
    """


class PlanningApprovalBlockedError(PlanningApprovalError):
    """
    Raised when approval is not allowed for the reviewed plan.
    """


class PlanningApprovalStore:
    """
    SQLite-backed store for read-only planning workflow history and approvals.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._initialize_database()

    def create_gate(
        self,
        *,
        task: str,
        planner_output: PlannerResponse,
        reviewer_output: ReviewerResponse,
        validator_output: ValidatorResponse,
        final_reviewed_summary: FinalReviewedPlanSummary,
        blockers: list[str],
    ) -> PlanningApprovalGate:
        fingerprint = self.plan_fingerprint(
            planner_output=planner_output,
            reviewer_output=reviewer_output,
            validator_output=validator_output,
        )
        approval_allowed, reason = self._approval_policy(
            reviewer_output=reviewer_output,
            validator_output=validator_output,
            blockers=blockers,
        )
        approval_status: ApprovalStatus = (
            "PENDING_APPROVAL" if approval_allowed else "BLOCKED"
        )
        workflow_id = str(uuid4())
        approval_token = token_urlsafe(32)
        now = self._now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO planning_workflows (
                    workflow_id,
                    user_task,
                    planner_output_json,
                    reviewer_output_json,
                    validator_output_json,
                    final_summary_json,
                    plan_fingerprint,
                    approval_status,
                    approval_allowed,
                    approval_reason,
                    approval_token,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    task,
                    self._dump_model(planner_output),
                    self._dump_model(reviewer_output),
                    self._dump_model(validator_output),
                    self._dump_model(final_reviewed_summary),
                    fingerprint,
                    approval_status,
                    int(approval_allowed),
                    reason,
                    approval_token,
                    now,
                    now,
                ),
            )

        return PlanningApprovalGate(
            workflow_id=workflow_id,
            approval_id=workflow_id,
            approval_token=approval_token,
            plan_fingerprint=fingerprint,
            status=approval_status,
            approval_allowed=approval_allowed,
            reason=reason,
        )

    def approve(
        self,
        *,
        approval_id: str,
        approval_token: str,
        plan_fingerprint: str,
    ) -> PlanningApprovalActionResponse:
        record = self._get_matching_row(
            approval_id=approval_id,
            approval_token=approval_token,
        )
        self._ensure_current_plan(record, plan_fingerprint)
        status = record["approval_status"]

        if status == "APPROVED":
            return self._action_response(record, "Plan is already approved.")

        if status == "REJECTED":
            raise PlanningApprovalBlockedError("Rejected plans cannot be approved.")

        if status == "BLOCKED" or not bool(record["approval_allowed"]):
            raise PlanningApprovalBlockedError(record["approval_reason"])

        now = self._now()
        message = "Plan approved. No code was executed."
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE planning_workflows
                SET approval_status = ?,
                    approval_reason = ?,
                    approval_decided_at = ?,
                    updated_at = ?
                WHERE workflow_id = ?
                """,
                (
                    "APPROVED",
                    "User explicitly approved this exact reviewed plan.",
                    now,
                    now,
                    record["workflow_id"],
                ),
            )

        updated_record = self._get_row(record["workflow_id"])
        return self._action_response(updated_record, message)

    def reject(
        self,
        *,
        approval_id: str,
        approval_token: str,
        plan_fingerprint: str,
    ) -> PlanningApprovalActionResponse:
        record = self._get_matching_row(
            approval_id=approval_id,
            approval_token=approval_token,
        )
        self._ensure_current_plan(record, plan_fingerprint)
        status = record["approval_status"]

        if status == "REJECTED":
            return self._action_response(record, "Plan is already rejected.")

        if status == "APPROVED":
            raise PlanningApprovalBlockedError("Approved plans cannot be rejected here.")

        now = self._now()
        message = "Plan rejected. No code was executed."
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE planning_workflows
                SET approval_status = ?,
                    approval_allowed = ?,
                    approval_reason = ?,
                    approval_decided_at = ?,
                    updated_at = ?
                WHERE workflow_id = ?
                """,
                (
                    "REJECTED",
                    0,
                    "User explicitly rejected this exact reviewed plan.",
                    now,
                    now,
                    record["workflow_id"],
                ),
            )

        updated_record = self._get_row(record["workflow_id"])
        return self._action_response(updated_record, message)

    def list_workflows(self) -> list[PlanningWorkflowHistoryItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT workflow_id,
                       user_task,
                       plan_fingerprint,
                       approval_status,
                       approval_allowed,
                       approval_reason,
                       created_at,
                       updated_at,
                       approval_decided_at
                FROM planning_workflows
                ORDER BY rowid DESC
                """
            ).fetchall()

        return [self._history_item(row) for row in rows]

    def get_workflow(self, workflow_id: str) -> PlanningWorkflowHistoryRecord:
        return self._history_record(self._get_row(workflow_id))

    def plan_fingerprint(
        self,
        *,
        planner_output: PlannerResponse,
        reviewer_output: ReviewerResponse,
        validator_output: ValidatorResponse,
    ) -> str:
        payload = {
            "planner_output": planner_output.model_dump(exclude={"raw_model_response"}),
            "reviewer_output": reviewer_output.model_dump(exclude={"raw_model_response"}),
            "validator_output": validator_output.model_dump(exclude={"raw_model_response"}),
        }
        encoded_payload = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return hashlib.sha256(encoded_payload).hexdigest()

    def clear_all_for_tests(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM planning_workflows")

    def _initialize_database(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS planning_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    user_task TEXT NOT NULL,
                    planner_output_json TEXT NOT NULL,
                    reviewer_output_json TEXT NOT NULL,
                    validator_output_json TEXT NOT NULL,
                    final_summary_json TEXT NOT NULL,
                    plan_fingerprint TEXT NOT NULL,
                    approval_status TEXT NOT NULL,
                    approval_allowed INTEGER NOT NULL,
                    approval_reason TEXT NOT NULL,
                    approval_token TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approval_decided_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_planning_workflows_created_at
                ON planning_workflows (created_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _approval_policy(
        self,
        *,
        reviewer_output: ReviewerResponse,
        validator_output: ValidatorResponse,
        blockers: list[str],
    ) -> tuple[bool, str]:
        if reviewer_output.approval_recommendation == "REJECT":
            return False, "Reviewer rejected the planner output."

        if validator_output.overall_validation_status == "BLOCKED":
            return False, "Validator blocked the reviewed plan."

        if blockers:
            return False, "Workflow blockers must be resolved before approval."

        return True, "Plan is awaiting explicit user approval."

    def _get_matching_row(
        self,
        *,
        approval_id: str,
        approval_token: str,
    ) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM planning_workflows
                WHERE workflow_id = ?
                """,
                (approval_id,),
            ).fetchone()

        if row is None or row["approval_token"] != approval_token:
            raise PlanningApprovalNotFoundError("Approval id or token is invalid.")

        return row

    def _get_row(self, workflow_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM planning_workflows
                WHERE workflow_id = ?
                """,
                (workflow_id,),
            ).fetchone()

        if row is None:
            raise PlanningApprovalNotFoundError("Workflow id is invalid.")

        return row

    def _ensure_current_plan(
        self,
        row: sqlite3.Row,
        plan_fingerprint: str,
    ) -> None:
        if row["plan_fingerprint"] != plan_fingerprint:
            raise PlanningApprovalStaleError(
                "Approval does not match the current reviewed plan."
            )

    def _action_response(
        self,
        row: sqlite3.Row,
        message: str,
    ) -> PlanningApprovalActionResponse:
        return PlanningApprovalActionResponse(
            workflow_id=row["workflow_id"],
            approval_id=row["workflow_id"],
            plan_fingerprint=row["plan_fingerprint"],
            status=row["approval_status"],
            approval_allowed=bool(row["approval_allowed"]),
            message=message,
        )

    def _history_item(self, row: sqlite3.Row) -> PlanningWorkflowHistoryItem:
        return PlanningWorkflowHistoryItem(
            workflow_id=row["workflow_id"],
            user_task=row["user_task"],
            plan_fingerprint=row["plan_fingerprint"],
            approval_status=row["approval_status"],
            approval_allowed=bool(row["approval_allowed"]),
            approval_reason=row["approval_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            approval_decided_at=row["approval_decided_at"],
        )

    def _history_record(self, row: sqlite3.Row) -> PlanningWorkflowHistoryRecord:
        return PlanningWorkflowHistoryRecord(
            workflow_id=row["workflow_id"],
            user_task=row["user_task"],
            planner_output=PlannerResponse.model_validate(
                self._load_json(row["planner_output_json"])
            ),
            reviewer_output=ReviewerResponse.model_validate(
                self._load_json(row["reviewer_output_json"])
            ),
            validator_output=ValidatorResponse.model_validate(
                self._load_json(row["validator_output_json"])
            ),
            final_reviewed_summary=FinalReviewedPlanSummary.model_validate(
                self._load_json(row["final_summary_json"])
            ),
            plan_fingerprint=row["plan_fingerprint"],
            approval_status=row["approval_status"],
            approval_allowed=bool(row["approval_allowed"]),
            approval_reason=row["approval_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            approval_decided_at=row["approval_decided_at"],
        )

    def _dump_model(self, model) -> str:
        return json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _load_json(self, value: str) -> dict[str, Any]:
        return json.loads(value)

    def _now(self) -> str:
        with self._connect() as connection:
            return connection.execute(
                "SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
            ).fetchone()[0]
