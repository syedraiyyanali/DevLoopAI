from typing import Literal

from pydantic import BaseModel, Field

from app.models.coder import CoderDiffPreviewResponse, CoderDryRunResponse
from app.models.execution_handoff import ExecutionHandoffResponse
from app.models.execution_mutation import ExecutionApplyResponse, ExecutionRollbackResponse
from app.models.execution_preflight import ExecutionPreflightResponse
from app.models.execution_quality import ExecutionQualityResponse
from app.models.execution_verification import ExecutionVerificationResult


TaskExecutionState = Literal[
    "PREPARING",
    "READY_FOR_REVIEW",
    "AWAITING_EXECUTION_APPROVAL",
    "APPLYING",
    "APPLIED",
    "VERIFYING",
    "QUALITY_PASSED",
    "QUALITY_FAILED",
    "QUALITY_INCOMPLETE",
    "RETRY_PREPARING",
    "RETRY_LIMIT_REACHED",
    "BLOCKED",
    "ROLLED_BACK",
    "FAILED",
]


class TaskExecutionPrepareRequest(BaseModel):
    """Prepare one approved workflow through reviewed diff without mutation."""

    workflow_id: str = Field(..., min_length=1)
    model: str | None = None


class TaskExecutionActionRequest(BaseModel):
    """Optional state guard for explicit task actions."""

    expected_state: TaskExecutionState | None = None


class TaskExecutionAttempt(BaseModel):
    """Immutable-ish audit summary for one reviewed execution attempt."""

    attempt_number: int = Field(..., ge=1)
    state: TaskExecutionState
    parent_execution_id: str | None = None
    parent_diff_review_id: str | None = None
    diff_review_id: str | None = None
    mutation_execution_id: str | None = None
    verification_ids: list[str] = Field(default_factory=list)
    quality_status: str | None = None
    failure_context_hash: str | None = None
    created_at: str
    updated_at: str
    message: str = ""


class TaskExecutionSession(BaseModel):
    """Persisted controlled single-task orchestration session."""

    task_execution_id: str
    workflow_id: str
    plan_fingerprint: str | None = None
    workspace_path: str | None = None
    state: TaskExecutionState
    created_at: str
    updated_at: str
    current_attempt: int = 1
    max_attempts: int = 3
    attempts: list[TaskExecutionAttempt] = Field(default_factory=list)
    diff_review_id: str | None = None
    mutation_execution_id: str | None = None
    verification_ids: list[str] = Field(default_factory=list)
    rollback_status: str | None = None
    rollback_recommended: bool = False
    preflight: ExecutionPreflightResponse | None = None
    handoff: ExecutionHandoffResponse | None = None
    dry_run: CoderDryRunResponse | None = None
    diff_preview: CoderDiffPreviewResponse | None = None
    apply_result: ExecutionApplyResponse | None = None
    verification_results: list[ExecutionVerificationResult] = Field(default_factory=list)
    quality_result: ExecutionQualityResponse | None = None
    rollback_result: ExecutionRollbackResponse | None = None
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    message: str
