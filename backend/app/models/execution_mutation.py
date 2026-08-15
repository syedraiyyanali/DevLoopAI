from typing import Literal

from pydantic import BaseModel, Field

from app.models.coder import CoderDiffPreviewResponse, CoderDryRunResponse
from app.models.execution_handoff import ExecutionHandoffResponse


ExecutionStatus = Literal[
    "EXECUTED",
    "BLOCKED",
    "REVIEW_STALE",
    "ROLLED_BACK",
    "PARTIALLY_FAILED_AND_ROLLED_BACK",
]


class ExecutionApplyRequest(BaseModel):
    """Exact reviewed pipeline artifacts submitted for controlled mutation."""

    handoff: ExecutionHandoffResponse
    dry_run: CoderDryRunResponse
    diff_preview: CoderDiffPreviewResponse
    allow_audited_retry_state: bool = False


class ExecutionFileResult(BaseModel):
    """Audit result for one attempted file mutation."""

    relative_path: str
    operation_type: Literal["modify_text_file", "create_text_file"]
    status: Literal["CHANGED", "CREATED", "ROLLED_BACK", "NOT_ATTEMPTED", "FAILED"]
    original_content_hash: str | None = None
    proposed_content_hash: str
    final_content_hash: str | None = None
    backup_location: str | None = None
    backup_status: Literal["CREATED", "NOT_REQUIRED", "FAILED"]


class ExecutionApplyResponse(BaseModel):
    """Structured controlled-mutation result and rollback availability."""

    execution_id: str
    workflow_id: str
    workspace_path: str
    status: ExecutionStatus
    files_attempted: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    file_results: list[ExecutionFileResult] = Field(default_factory=list)
    backup_status: str
    rollback_available: bool
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    execution_timestamp: str
    message: str


class ExecutionRollbackRequest(BaseModel):
    """Request rollback for one persisted execution record."""

    execution_id: str = Field(..., min_length=1)


class ExecutionRollbackResponse(BaseModel):
    """Result of restoring all files changed by one execution."""

    execution_id: str
    workflow_id: str
    status: Literal["ROLLED_BACK", "BLOCKED"]
    files_restored: list[str] = Field(default_factory=list)
    files_removed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    rolled_back_at: str | None = None
    message: str
