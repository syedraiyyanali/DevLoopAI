import hashlib
import json
from dataclasses import dataclass
from secrets import token_urlsafe

from app.models.planning_workflow import (
    ApprovalStatus,
    PlanningApprovalActionResponse,
    PlanningApprovalGate,
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
    Raised when an approval session does not exist or the token is invalid.
    """


class PlanningApprovalStaleError(PlanningApprovalError):
    """
    Raised when approval is attempted for a changed plan fingerprint.
    """


class PlanningApprovalBlockedError(PlanningApprovalError):
    """
    Raised when approval is not allowed for the reviewed plan.
    """


@dataclass
class PlanningApprovalRecord:
    approval_id: str
    approval_token: str
    plan_fingerprint: str
    status: ApprovalStatus
    approval_allowed: bool
    reason: str


class PlanningApprovalStore:
    """
    Process-local store for read-only planning approval state.
    """

    def __init__(self) -> None:
        self._records: dict[str, PlanningApprovalRecord] = {}

    def create_gate(
        self,
        *,
        planner_output: PlannerResponse,
        reviewer_output: ReviewerResponse,
        validator_output: ValidatorResponse,
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
        status: ApprovalStatus = "PENDING_APPROVAL" if approval_allowed else "BLOCKED"
        record = PlanningApprovalRecord(
            approval_id=token_urlsafe(18),
            approval_token=token_urlsafe(32),
            plan_fingerprint=fingerprint,
            status=status,
            approval_allowed=approval_allowed,
            reason=reason,
        )
        self._records[record.approval_id] = record

        return self._to_gate(record)

    def approve(
        self,
        *,
        approval_id: str,
        approval_token: str,
        plan_fingerprint: str,
    ) -> PlanningApprovalActionResponse:
        record = self._get_matching_record(
            approval_id=approval_id,
            approval_token=approval_token,
        )
        self._ensure_current_plan(record, plan_fingerprint)

        if record.status == "APPROVED":
            return self._to_response(record, "Plan is already approved.")

        if record.status == "REJECTED":
            raise PlanningApprovalBlockedError("Rejected plans cannot be approved.")

        if record.status == "BLOCKED" or not record.approval_allowed:
            raise PlanningApprovalBlockedError(record.reason)

        record.status = "APPROVED"
        record.reason = "User explicitly approved this exact reviewed plan."

        return self._to_response(record, "Plan approved. No code was executed.")

    def reject(
        self,
        *,
        approval_id: str,
        approval_token: str,
        plan_fingerprint: str,
    ) -> PlanningApprovalActionResponse:
        record = self._get_matching_record(
            approval_id=approval_id,
            approval_token=approval_token,
        )
        self._ensure_current_plan(record, plan_fingerprint)

        if record.status == "REJECTED":
            return self._to_response(record, "Plan is already rejected.")

        if record.status == "APPROVED":
            raise PlanningApprovalBlockedError("Approved plans cannot be rejected here.")

        record.status = "REJECTED"
        record.approval_allowed = False
        record.reason = "User explicitly rejected this exact reviewed plan."

        return self._to_response(record, "Plan rejected. No code was executed.")

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

    def _get_matching_record(
        self,
        *,
        approval_id: str,
        approval_token: str,
    ) -> PlanningApprovalRecord:
        record = self._records.get(approval_id)

        if record is None or record.approval_token != approval_token:
            raise PlanningApprovalNotFoundError("Approval id or token is invalid.")

        return record

    def _ensure_current_plan(
        self,
        record: PlanningApprovalRecord,
        plan_fingerprint: str,
    ) -> None:
        if record.plan_fingerprint != plan_fingerprint:
            raise PlanningApprovalStaleError(
                "Approval does not match the current reviewed plan."
            )

    def _to_gate(self, record: PlanningApprovalRecord) -> PlanningApprovalGate:
        return PlanningApprovalGate(
            approval_id=record.approval_id,
            approval_token=record.approval_token,
            plan_fingerprint=record.plan_fingerprint,
            status=record.status,
            approval_allowed=record.approval_allowed,
            reason=record.reason,
        )

    def _to_response(
        self,
        record: PlanningApprovalRecord,
        message: str,
    ) -> PlanningApprovalActionResponse:
        return PlanningApprovalActionResponse(
            approval_id=record.approval_id,
            plan_fingerprint=record.plan_fingerprint,
            status=record.status,
            approval_allowed=record.approval_allowed,
            message=message,
        )


planning_approval_store = PlanningApprovalStore()
