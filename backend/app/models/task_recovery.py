from typing import Literal

from pydantic import BaseModel, Field


RecoveryStatus = Literal["RECOVERABLE", "AWAITING_USER_ACTION", "BLOCKED", "COMPLETE"]


class TaskRecoveryResponse(BaseModel):
    """Read-only recovery view for a persisted controlled task session."""

    task_execution_id: str
    workflow_id: str
    current_task_state: str
    recovery_status: RecoveryStatus
    recoverable_next_action: str
    completed_stages: list[str] = Field(default_factory=list)
    interrupted_or_unknown_stages: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    approval_required: bool = False
    mutation_already_performed: bool = False
    rollback_available: bool = False
    commit_state: str | None = None
    commit_hash: str | None = None
    quality_status: str | None = None
    required_verification_types: list[str] = Field(default_factory=list)
    completed_verification_types: list[str] = Field(default_factory=list)
    missing_verification_types: list[str] = Field(default_factory=list)
    stale_or_corrupt_state_detected: bool = False
    message: str
